"""
Coastal / tidal signal — Open-Meteo Marine API (free, no key).

Why: FloodSight's alert engine is rainfall-driven, but some of the
validated misses are non-rainfall coastal floods — specifically the
July 2021 tidal-rain surge (sea level 122 cm above normal) and the
October 2022 Niger/Benue coastal backwater flood.  This module adds
the cheapest available coastal signal: hourly sea level height (MSL)
for the Lagos coast, next 72 h.

Two monitoring points:
  VI / Bar Beach   (6.40°N, 3.40°E) — central Lagos / Eti-Osa shoreline
  Badagry west     (6.43°N, 2.89°E) — western coast; captures backwater
                                       from Ogun / Badagry Creek outflow

Taking the maximum sea level across both points makes the advisory
more sensitive to events that are spatially offset — the 2022 Oct
Niger/Benue surge, for example, was reported more strongly at Badagry
than at Bar Beach.

Threshold calibration (COASTAL_ADVISORY_M = 0.9 m):
  Lagos semi-diurnal tidal range at spring: ~1.5 m; mean higher high
  water ~0.85 m above MSL.  ERA5-Ocean typically under-represents
  coastal surge by 30–50%.  Setting the threshold at 0.9 m sits just
  above the normal spring tide peak in the ERA5-Ocean model, so routine
  tidal variability stays below it while anomalous surge/backwater
  events cross it.  Calibrate against NiHSA tide gauge records and the
  July 2021 surge event when data are available — run
  `python scripts/validate_historical.py` and check `hist_coastal`
  values for 2021_07a and 2022_10 to verify the threshold is set
  correctly for both events.

Usage::

    from floodsight.forecast.marine import get_coastal_summary
    get_coastal_summary()  ->
        {
          "max_sea_level_m":     1.12,
          "peak_time":           "2026-07-05T04:00",
          "current_sea_level_m": 0.61,
          "advisory":            True,
          "threshold_m":         0.9,
          "point":               "VI / Bar Beach",
          "source":              "open-meteo-marine",
          "fetched_at":          "...",
        }

Results cached in-process for 30 minutes.
Failures raise RuntimeError — callers treat the signal as optional.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Two monitoring points along the Lagos coast.
# Taking the max across both makes the advisory more sensitive to
# spatially offset events (eastern tidal surge vs western backwater).
COAST_POINTS: list[tuple[float, float, str]] = [
    (6.40, 3.40, "VI / Bar Beach"),        # central Lagos / Eti-Osa shoreline
    (6.43, 2.89, "Badagry / western"),     # western coast — Ogun/Badagry Creek outflow
]

# Advisory threshold — sea level height above mean sea level (metres).
# 0.9 m sits just above the ERA5-Ocean spring-tide peak for Lagos; anomalous
# surge or river-backwater events push it higher.  Calibrate against
# NiHSA tide gauge records + 2021-07 event before treating as operational.
COASTAL_ADVISORY_M = 0.9

_CACHE_TTL_S = 1800
_cache: tuple[float, dict] | None = None


def summarize_sea_level(times: list[str], heights: list[float | None]) -> dict:
    """Pure summariser — separated from the fetch so it can be unit-tested."""
    pairs = [(t, h) for t, h in zip(times, heights) if h is not None]
    if not pairs:
        raise RuntimeError("Marine API returned no sea level data")
    peak_time, peak = max(pairs, key=lambda p: p[1])
    return {
        "max_sea_level_m":     round(float(peak), 3),
        "peak_time":           peak_time,
        "current_sea_level_m": round(float(pairs[0][1]), 3),
        "advisory":            bool(peak >= COASTAL_ADVISORY_M),
        "threshold_m":         COASTAL_ADVISORY_M,
        "source":              "open-meteo-marine",
    }


def _fetch_point(lat: float, lon: float, forecast_days: int = 3) -> tuple[list[str], list[float | None]]:
    """Fetch hourly sea_level_height_msl for one lat/lon. Returns (times, heights)."""
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=sea_level_height_msl"
        f"&forecast_days={forecast_days}&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    hourly = data.get("hourly", {})
    return hourly.get("time", []), hourly.get("sea_level_height_msl", [])


def get_coastal_summary(force: bool = False) -> dict:
    """
    Sea level summary for the Lagos coast, next 72 h (30-min cache).

    Fetches both coastal monitoring points and returns the result for
    whichever point shows the higher peak sea level.  If one point fails,
    the other is used.  If both fail, RuntimeError is raised.
    """
    global _cache
    now = time.time()
    if _cache is not None and not force and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]

    best: dict | None = None
    errors: list[str] = []

    for lat, lon, label in COAST_POINTS:
        try:
            times, heights = _fetch_point(lat, lon)
            summary = summarize_sea_level(times, heights)
            summary["point"] = label
            if best is None or summary["max_sea_level_m"] > best["max_sea_level_m"]:
                best = summary
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            log.debug("Coastal point %s unavailable: %s", label, exc)

    if best is None:
        raise RuntimeError(f"All coastal monitoring points failed: {errors}")

    if errors:
        log.warning("Coastal: %d/%d points available; errors: %s",
                    len(COAST_POINTS) - len(errors), len(COAST_POINTS), errors)

    best["fetched_at"] = datetime.now(timezone.utc).isoformat()

    if best["advisory"]:
        log.warning(
            "COASTAL ADVISORY: sea level peaks at %.3f m (>= %.2f m) at %s [%s]",
            best["max_sea_level_m"], COASTAL_ADVISORY_M,
            best["peak_time"], best["point"],
        )

    _cache = (now, best)
    return best


def try_coastal_summary() -> dict | None:
    """Non-raising wrapper — coastal data is an optional signal."""
    try:
        return get_coastal_summary()
    except Exception as exc:
        log.warning("Coastal signal unavailable: %s", exc)
        return None
