"""
Open-Meteo forecast fetcher — free API, no key required.
https://open-meteo.com/

Phase 11: Dual-stream observed + forecast rainfall.

Uses Open-Meteo's ``past_hours=24`` parameter to fetch both:
  - Observed rainfall: actual precipitation recorded in the last 24 h
    (near-real-time ERA5-based analysis, updated hourly)
  - Forecast rainfall: next 72 h from the GFS/ECMWF ensemble

This matters because:
  - Heavy rain that already fell saturates the soil and overwhelmed
    drainage — even moderate forecast rain can then cause flooding.
  - The combined 72 h risk window (observed 24 h + forecast 48 h)
    is more accurate than a pure forecast for flood alerting.

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
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple in-memory cache: (lat_r, lon_r) → (expires_ts, data_dict)
# ---------------------------------------------------------------------------
_CACHE: dict[tuple[float, float], tuple[float, dict]] = {}
CACHE_TTL_S = 1800  # 30 minutes


def _round_coord(v: float) -> float:
    """Round to 2 decimal places so nearby points share a cache entry."""
    return round(v, 2)


def fetch_combined(lat: float, lon: float) -> dict:
    """
    Fetch observed (past 24 h) + forecast (next 72 h) in a single API call.

    Returns::
        {
            "observed_24h_mm":  float,   # actual rain in the past 24 h
            "forecast_24h_mm":  float,   # forecast for the next 24 h
            "forecast_48h_mm":  float,   # forecast for the next 48 h
            "forecast_72h_mm":  float,   # forecast for the next 72 h
            "rain_24h_mm":      float,   # = forecast_24h_mm  (alert engine compat)
            "rain_72h_mm":      float,   # = observed + fc48  (true 72 h window)
            "data_mode":        str,     # "observed+forecast"
            "forecast_source":  str,
            "fetched_at":       str,     # ISO-8601
            "valid_from":       str,     # current UTC hour
            "lat":              float,
            "lon":              float,
        }

    Raises ``RuntimeError`` on fetch or parse failure (caller should return 503).
    """
    key = (_round_coord(lat), _round_coord(lon))
    now_ts = time.time()

    # Return cached result if still fresh
    if key in _CACHE:
        expires, data = _CACHE[key]
        if now_ts < expires:
            log.debug("Forecast cache hit for %s", key)
            return data

    # past_hours=24 + forecast_days=3 → 24 observed + 72 forecast = 96 h total
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=precipitation"
        "&past_hours=24"
        "&forecast_days=3"
        "&timezone=UTC"
    )

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "FloodSight/1.0 (flood-early-warning, Lagos)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(f"Open-Meteo request failed: {exc}") from exc

    try:
        times  = payload["hourly"]["time"]        # ["2026-06-24T00:00", ...]
        precip = payload["hourly"]["precipitation"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Open-Meteo response format: {exc}") from exc

    # Replace None values (missing data gaps) with 0.0
    precip = [p if p is not None else 0.0 for p in precip]

    # Locate the current UTC hour in the time array
    now_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    current_hour_str = now_dt.strftime("%Y-%m-%dT%H:00")

    if current_hour_str in times:
        now_idx = times.index(current_hour_str)
    else:
        # With past_hours=24, current hour is typically at index 24
        now_idx = min(24, len(times) - 1)
        log.warning(
            "Current hour %s not found in Open-Meteo response; using index %d",
            current_hour_str, now_idx,
        )

    # ── Observed: actual rainfall in the past 24 h ────────────────────────
    observed_24h = sum(precip[max(0, now_idx - 24) : now_idx])

    # ── Forecast: future rainfall windows from current hour ───────────────
    forecast_24h = sum(precip[now_idx : now_idx + 24])
    forecast_48h = sum(precip[now_idx : now_idx + 48])
    forecast_72h = sum(precip[now_idx : now_idx + 72])

    # ── Combined 72 h risk window ─────────────────────────────────────────
    # Antecedent soil saturation (observed 24 h) + upcoming rain (forecast 48 h)
    # = the full 72 h rainfall burden on Lagos drainage.
    rain_72h_combined = observed_24h + forecast_48h

    data: dict = {
        # Phase 11 observed + forecast fields
        "observed_24h_mm":  round(observed_24h, 1),
        "forecast_24h_mm":  round(forecast_24h, 1),
        "forecast_48h_mm":  round(forecast_48h, 1),
        "forecast_72h_mm":  round(forecast_72h, 1),
        # Alert engine compatibility (used by /forecast/alerts and /forecast/summary)
        # rain_24h_mm = what's COMING → determines next-24h alert level
        # rain_72h_mm = combined 72h burden → determines sustained-rain alert level
        "rain_24h_mm":      round(forecast_24h, 1),
        "rain_72h_mm":      round(rain_72h_combined, 1),
        # Metadata
        "forecast_source":  "Open-Meteo — ERA5-RT observed + ECMWF/GFS forecast",
        "data_mode":        "observed+forecast",
        "fetched_at":       datetime.now(timezone.utc).isoformat(),
        "valid_from":       current_hour_str,
        "lat":              lat,
        "lon":              lon,
    }
    _CACHE[key] = (now_ts + CACHE_TTL_S, data)
    log.info(
        "Dual-stream fetch (%.2f, %.2f): observed=%.1f mm | fc24=%.1f mm, fc48=%.1f mm → alert72=%.1f mm",
        lat, lon, observed_24h, forecast_24h, forecast_48h, rain_72h_combined,
    )
    return data


def fetch_forecast(lat: float, lon: float) -> dict:
    """
    Backward-compatible wrapper — now delegates to fetch_combined().

    Returns all original fields (rain_24h_mm, rain_72h_mm, forecast_source,
    fetched_at, valid_from, lat, lon) plus the new Phase 11 fields
    (observed_24h_mm, forecast_24h_mm, forecast_48h_mm, forecast_72h_mm,
    data_mode).
    """
    return fetch_combined(lat, lon)
