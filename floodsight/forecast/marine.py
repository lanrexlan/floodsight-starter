"""
Coastal / tidal signal — Open-Meteo Marine API (free, no key).

Why: FloodSight's alert engine is rainfall-driven, but two of the eight
back-tested misses (see floodsight/config.py thresholds comment) were
non-rainfall floods. One of the two real labeled events (lekki_2021_07_12)
was a tidal surge. This module adds the cheapest available coastal signal:
hourly sea level height (MSL) for the Lagos coast, next 72 h.

What it is NOT: a storm-surge model or a dam-release monitor. Dam-release
floods (Oyan dam on the Ogun river) still need NiHSA / Ogun-Osun RBDA data
or GloFAS discharge on the Ogun reach — tracked as the remaining half of
IMPROVEMENTS.md item 8.

Usage:
    from floodsight.forecast.marine import get_coastal_summary
    get_coastal_summary()  ->
        {
          "max_sea_level_m": 1.12,        # max hourly MSL height, next 72 h
          "peak_time": "2026-07-05T04:00",
          "current_sea_level_m": 0.61,
          "advisory": True,               # max >= COASTAL_ADVISORY_M
          "threshold_m": 1.0,
          "source": "open-meteo-marine",
          "fetched_at": "...",
        }

Results cached in-process for 30 minutes (same policy as openmeteo.py).
Failures raise RuntimeError — callers treat the signal as optional.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Point just off the Lagos coast (Bar Beach / Victoria Island shoreline).
COAST_LAT = 6.40
COAST_LON = 3.40

# Advisory threshold for hourly sea level height above mean sea level.
# PLACEHOLDER calibration: chosen so normal semi-diurnal tide (~0.9 m range
# at Lagos Bar) stays below it and anomalous surge/spring-tide stacking
# crosses it. Calibrate against NiHSA tide gauge records + the 2021-07
# surge event before treating this as operational.
COASTAL_ADVISORY_M = 1.0

_CACHE_TTL_S = 1800
_cache: tuple[float, dict] | None = None


def summarize_sea_level(times: list[str], heights: list[float | None]) -> dict:
    """Pure summariser — separated from the fetch so it can be unit-tested."""
    pairs = [(t, h) for t, h in zip(times, heights) if h is not None]
    if not pairs:
        raise RuntimeError("Marine API returned no sea level data")
    peak_time, peak = max(pairs, key=lambda p: p[1])
    return {
        "max_sea_level_m": round(float(peak), 3),
        "peak_time": peak_time,
        "current_sea_level_m": round(float(pairs[0][1]), 3),
        "advisory": bool(peak >= COASTAL_ADVISORY_M),
        "threshold_m": COASTAL_ADVISORY_M,
        "source": "open-meteo-marine",
    }


def get_coastal_summary(force: bool = False) -> dict:
    """Sea level summary for the Lagos coast, next 72 h (30-min cache)."""
    global _cache
    now = time.time()
    if _cache is not None and not force and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]

    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={COAST_LAT}&longitude={COAST_LON}"
        "&hourly=sea_level_height_msl&forecast_days=3&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(f"Marine API fetch failed: {exc}") from exc

    hourly = data.get("hourly", {})
    summary = summarize_sea_level(
        hourly.get("time", []), hourly.get("sea_level_height_msl", [])
    )
    summary["fetched_at"] = datetime.now(timezone.utc).isoformat()

    if summary["advisory"]:
        log.warning(
            "COASTAL ADVISORY: sea level peaks at %.2f m (>= %.2f m) at %s",
            summary["max_sea_level_m"], COASTAL_ADVISORY_M, summary["peak_time"],
        )

    _cache = (now, summary)
    return summary


def try_coastal_summary() -> dict | None:
    """Non-raising wrapper — coastal data is an optional signal."""
    try:
        return get_coastal_summary()
    except Exception as exc:
        log.warning("Coastal signal unavailable: %s", exc)
        return None
