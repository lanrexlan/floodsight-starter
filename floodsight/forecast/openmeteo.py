"""
Open-Meteo forecast fetcher — free API, no key required.
https://open-meteo.com/

Returns 24h and 72h accumulated precipitation forecasts for any lat/lon.
Results are cached in-process for 30 minutes to avoid hammering the API.
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


def fetch_forecast(lat: float, lon: float) -> dict:
    """
    Fetch next-24h and next-72h accumulated precipitation from Open-Meteo.

    Returns::
        {
            "rain_24h_mm": float,
            "rain_72h_mm": float,
            "forecast_source": str,
            "fetched_at": ISO-8601 str,
            "lat": float,
            "lon": float,
        }

    Raises ``RuntimeError`` if the fetch or parse fails (caller should
    catch and return a 503).
    """
    key = (_round_coord(lat), _round_coord(lon))
    now_ts = time.time()

    # Return cached result if still fresh
    if key in _CACHE:
        expires, data = _CACHE[key]
        if now_ts < expires:
            log.debug("Forecast cache hit for %s", key)
            return data

    # Build request — 4 days so we always have ≥72 h ahead of current hour
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=precipitation"
        "&forecast_days=4"
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
        times = payload["hourly"]["time"]        # ["2026-06-24T00:00", ...]
        precip = payload["hourly"]["precipitation"]  # mm/h values
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Open-Meteo response format: {exc}") from exc

    # Find the index that matches the current UTC hour
    now_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    current_hour_str = now_dt.strftime("%Y-%m-%dT%H:00")

    if current_hour_str in times:
        start_idx = times.index(current_hour_str)
    else:
        # Fallback: start from the first available hour
        log.warning(
            "Current hour %s not found in Open-Meteo response; defaulting to index 0",
            current_hour_str,
        )
        start_idx = 0

    rain_24h = sum(precip[start_idx : start_idx + 24])
    rain_72h = sum(precip[start_idx : start_idx + 72])

    data: dict = {
        "rain_24h_mm": round(rain_24h, 1),
        "rain_72h_mm": round(rain_72h, 1),
        "forecast_source": "Open-Meteo (GFS/ECMWF ensemble)",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "valid_from": current_hour_str,
        "lat": lat,
        "lon": lon,
    }
    _CACHE[key] = (now_ts + CACHE_TTL_S, data)
    log.info(
        "Forecast fetched for (%.2f, %.2f): 24h=%.1f mm, 72h=%.1f mm",
        lat, lon, rain_24h, rain_72h,
    )
    return data
