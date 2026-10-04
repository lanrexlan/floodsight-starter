"""
Open-Meteo forecast fetcher — free API, no key required.
https://open-meteo.com/

Phase 11:   Dual-stream observed + forecast rainfall.
Phase 11b:  Switched from ERA5 reanalysis to GFS seamless model.
Phase 18T2: GFS + ICON ensemble (per-hour max) for better convective coverage.

Architecture
------------
Two NWP models are fetched in parallel for every grid point:

  GFS seamless  — NOAA GFS, 0.25° (~28 km), updated every 6 h.
                  Good global coverage; tends to smooth out intense
                  localised convective cells.

  ICON seamless — DWD ICON (German Weather Service), 13 km global
                  (ICON-Global), blended with 7 km (ICON-EU) where
                  available.  Better representation of mesoscale
                  convective systems (MCS) — the dominant rainfall
                  mode in coastal West Africa during the wet season.

Ensemble strategy: per-hour MAXIMUM
  precip[t] = max(gfs_precip[t], icon_precip[t])

"Max" is deliberately conservative for flood alerting:
  - False alarm cost  : nuisance (residents stay home one day)
  - Missed event cost : catastrophic (no warning → people in flooded roads)

If either model fails, the other is used alone.
Both fail → fallback to Open-Meteo best_match (single call, any model).

Alert engine mapping
--------------------
  rain_24h_mm = forecast_24h_mm   (what is COMING — actionable signal)
  rain_72h_mm = observed_24h_mm + forecast_48h_mm  (true 72 h risk window)

Results are cached in-process for 30 minutes.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensemble model list
# ---------------------------------------------------------------------------
# ICON-Global (~13 km) is the effective resolution for Nigeria — ICON-EU
# (7 km) only covers Europe and northern Mediterranean.
# "icon_seamless" lets Open-Meteo pick the best-resolution ICON domain
# available for the requested lat/lon; for Lagos it uses icon_global.
_ENSEMBLE_MODELS: list[str] = ["gfs_seamless", "icon_seamless"]
_FALLBACK_MODEL: str = ""  # empty string → Open-Meteo best_match (any model)

# ---------------------------------------------------------------------------
# Simple in-memory cache: (lat_r, lon_r) → (expires_ts, data_dict)
# ---------------------------------------------------------------------------
_CACHE: dict[tuple[float, float], tuple[float, dict]] = {}
CACHE_TTL_S = 1800  # 30 minutes


def _round_coord(v: float) -> float:
    """Round to 2 decimal places so nearby points share a cache entry."""
    return round(v, 2)


# ---------------------------------------------------------------------------
# Single-model fetch (called in parallel for each ensemble member)
# ---------------------------------------------------------------------------

def _fetch_model_hourly(
    lat: float,
    lon: float,
    model: str,
) -> tuple[list[str], list[float]]:
    """
    Fetch hourly precipitation for one Open-Meteo model.

    Returns (times, precip_mm_per_hour) where times are ISO strings like
    "2026-07-03T14:00" and precip is hourly mm with None replaced by 0.0.

    Raises on any network or parse error.
    """
    model_param = f"&models={model}" if model else ""
    from floodsight.forecast.provider import endpoint, credential_query
    url = (
        endpoint("forecast", "forecast")
        + f"?latitude={lat}&longitude={lon}"
        "&hourly=precipitation"
        "&past_hours=24"
        "&forecast_days=3"
        "&timezone=UTC"
        + model_param + credential_query()
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "FloodSight/1.0 (flood-early-warning, Lagos)"}
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        payload = json.loads(resp.read())
    times  = payload["hourly"]["time"]
    precip = [p if p is not None else 0.0 for p in payload["hourly"]["precipitation"]]
    return times, precip


# ---------------------------------------------------------------------------
# Ensemble fetch — parallel GFS + ICON, per-hour max merge
# ---------------------------------------------------------------------------

def fetch_combined(lat: float, lon: float) -> dict:
    """
    Fetch observed (past 24 h) + forecast (next 72 h) using a GFS + ICON
    ensemble.  Returns the per-hour maximum precipitation across both models.

    Returns::

        {
            "observed_24h_mm":  float,   # past 24 h (ensemble max)
            "forecast_24h_mm":  float,   # next 24 h (ensemble max)
            "forecast_48h_mm":  float,   # next 48 h (ensemble max)
            "forecast_72h_mm":  float,   # next 72 h (ensemble max)
            "rain_24h_mm":      float,   # = forecast_24h_mm  (alert engine)
            "rain_72h_mm":      float,   # = observed + fc48  (72 h window)
            "data_mode":        str,     # "observed+forecast"
            "forecast_source":  str,     # e.g. "GFS+ICON ensemble (max)"
            "ensemble_models":  list,    # which models succeeded
            "fetched_at":       str,     # ISO-8601
            "valid_from":       str,     # current UTC hour string
            "lat":              float,
            "lon":              float,
        }

    Raises ``RuntimeError`` if every model (including fallback) fails.
    """
    key = (_round_coord(lat), _round_coord(lon))
    now_ts = time.time()

    if key in _CACHE:
        expires, data = _CACHE[key]
        if now_ts < expires:
            log.debug("Forecast cache hit for %s", key)
            return data

    # ── Step 1: fetch ensemble models in parallel ─────────────────────────
    model_results: dict[str, tuple[list[str], list[float]]] = {}

    with ThreadPoolExecutor(max_workers=len(_ENSEMBLE_MODELS)) as pool:
        future_to_model = {
            pool.submit(_fetch_model_hourly, lat, lon, m): m
            for m in _ENSEMBLE_MODELS
        }
        for future in as_completed(future_to_model):
            m = future_to_model[future]
            try:
                model_results[m] = future.result()
                log.debug("Ensemble model %s OK for (%.2f, %.2f)", m, lat, lon)
            except Exception as exc:
                log.warning("Ensemble model %s failed for (%.2f, %.2f): %s", m, lat, lon, exc)

    # ── Step 2: fallback if all ensemble models failed ────────────────────
    if not model_results:
        log.warning(
            "All ensemble models failed for (%.2f, %.2f) — trying best_match fallback",
            lat, lon,
        )
        try:
            times, precip = _fetch_model_hourly(lat, lon, _FALLBACK_MODEL)
            model_results["best_match"] = (times, precip)
        except Exception as exc:
            raise RuntimeError(
                f"All Open-Meteo models (ensemble + fallback) failed for "
                f"({lat:.2f}, {lon:.2f}): {exc}"
            ) from exc

    # ── Step 3: per-hour maximum across successful models ─────────────────
    # Use the time array from the first successful model as the reference.
    ref_times   = next(iter(model_results.values()))[0]
    n_hours     = len(ref_times)
    merged_precip: list[float] = []
    for i in range(n_hours):
        hourly_vals = [
            model_results[m][1][i]
            for m in model_results
            if i < len(model_results[m][1])
        ]
        merged_precip.append(max(hourly_vals) if hourly_vals else 0.0)

    # ── Step 4: accumulate windows from merged hourly precipitation ───────
    now_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    current_hour_str = now_dt.strftime("%Y-%m-%dT%H:00")

    if current_hour_str in ref_times:
        now_idx = ref_times.index(current_hour_str)
    else:
        now_idx = min(24, n_hours - 1)
        log.warning(
            "Current hour %s not found in Open-Meteo response; using index %d",
            current_hour_str, now_idx,
        )

    observed_24h = sum(merged_precip[max(0, now_idx - 24) : now_idx])
    forecast_24h = sum(merged_precip[now_idx : now_idx + 24])
    forecast_48h = sum(merged_precip[now_idx : now_idx + 48])
    forecast_72h = sum(merged_precip[now_idx : now_idx + 72])
    rain_72h_combined = observed_24h + forecast_48h

    # ── Step 5: build result dict ─────────────────────────────────────────
    succeeded = list(model_results.keys())
    if set(succeeded) == {"gfs_seamless", "icon_seamless"}:
        source_label = "GFS + ICON ensemble (max)"
    elif "gfs_seamless" in succeeded:
        source_label = "GFS seamless (ICON unavailable)"
    elif "icon_seamless" in succeeded:
        source_label = "ICON seamless (GFS unavailable)"
    else:
        source_label = "Open-Meteo best_match (ensemble fallback)"

    data: dict = {
        "observed_24h_mm":  round(observed_24h, 1),
        "forecast_24h_mm":  round(forecast_24h, 1),
        "forecast_48h_mm":  round(forecast_48h, 1),
        "forecast_72h_mm":  round(forecast_72h, 1),
        "rain_24h_mm":      round(forecast_24h, 1),
        "rain_72h_mm":      round(rain_72h_combined, 1),
        "forecast_source":  f"Open-Meteo — {source_label}",
        "ensemble_models":  succeeded,
        "model":            "+".join(succeeded),
        "data_mode":        "observed+forecast",
        "fetched_at":       datetime.now(timezone.utc).isoformat(),
        "valid_from":       current_hour_str,
        "lat":              lat,
        "lon":              lon,
    }
    _CACHE[key] = (now_ts + CACHE_TTL_S, data)
    log.info(
        "Ensemble fetch (%.2f, %.2f) [%s]: obs=%.1f mm | fc24=%.1f mm | fc48=%.1f mm → r72=%.1f mm",
        lat, lon, source_label,
        observed_24h, forecast_24h, forecast_48h, rain_72h_combined,
    )
    return data


def fetch_forecast(lat: float, lon: float) -> dict:
    """
    Backward-compatible wrapper — delegates to fetch_combined().

    Preserves the original return shape (rain_24h_mm, rain_72h_mm,
    forecast_source, fetched_at, valid_from, lat, lon) plus all Phase 11
    and Phase 18T2 fields.
    """
    return fetch_combined(lat, lon)
