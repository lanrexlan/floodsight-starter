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

Threshold calibration (October 2026) — two tiers
------------------------------------------------
The original single threshold (0.9 m) was an uncalibrated placeholder
that assumed 0.9 m sat "just above the spring-tide peak".  It does not.
Calibrated against the full available model record — daily maxima across
both monitoring points, 2023-01-01 to 2026-10-01 (1,354 days, 3.7 yr;
the Open-Meteo marine series returns no data before early 2023) — the
daily-max distribution is:

    p50 0.61 m · p90 0.88 m · p95 0.97 m · p99 1.08 m · max 1.15 m

Because the advisory looks 72 h ahead, the fraction of days it is ACTIVE:

    0.90 m  -> 50.4 days/yr (13.8%)   <- the old placeholder
    1.00 m  -> 28.1 days/yr
    1.05 m  -> 15.4 days/yr  (4.2%)
    1.10 m  ->  5.4 days/yr
    1.20 m  ->  0   days/yr  (never reached in 3.7 yr)

Every top-ranked day falls at an equinox (Mar/Apr, Oct) and there were
ZERO active days in Jun, Jul, Dec or Jan: the series is dominated by
predictable astronomical spring tides, not storm surge.  At 0.9 m the old
advisory upgraded five coastal LGAs from No Alert to Watch on ~50 dry,
calm days a year, and was quietest in June-July, Lagos's peak flood months.

No single threshold separates surge from spring tide in a tide-dominated
series, so the signal is split into two tiers with different effects:

  COASTAL_SURGE_M = 1.20 m
      Above the 3.7-yr maximum, so astronomical tide alone never reaches
      it.  Treated as genuine surge/backwater: upgrades coastal-LGA cells
      No Alert -> Watch and Watch -> Warning, because surge floods dry days.

  COASTAL_HIGH_TIDE_M = 1.05 m
      Top ~4% of water levels.  Escalates ONLY cells already at Watch from
      rainfall (Watch -> Warning) — the tide-locking mechanism, where high
      water backs up drainage outfalls during rain.  Never raises an alert
      on a dry day.

Limitations — keep in mind before treating this as operational truth:
  * No coastal flood event in the validation set falls inside the
    2023-2026 data window, so these thresholds control the FALSE-ALARM
    rate; they have not been tested against a real surge.  The July 2021
    tidal-rain surge (2021_07a) predates the record and cannot be scored.
  * Model sea level is reported at 0.01 m resolution and, per the
    literature, under-represents surge by 30-50%; a real event may read
    lower here than at a tide gauge.
  * Re-run `python scripts/calibrate_coastal_threshold.py` as the record
    grows, and replace with NiHSA tide-gauge records when obtainable.

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

# Thresholds — sea level height above mean sea level (metres).
# Calibrated Oct 2026 against 1,354 days of model record; see module docstring.
COASTAL_SURGE_M     = 1.20   # above 3.7-yr max (1.15 m): genuine surge only
COASTAL_HIGH_TIDE_M = 1.05   # top ~4% of levels: compounds with rain only

# Backward-compatible name. "advisory" has always meant the tier that raises
# alerts on its own, which is now the surge tier.
COASTAL_ADVISORY_M = COASTAL_SURGE_M

# How each tier changes a coastal-LGA cell's rain-driven alert level.
_SURGE_UPGRADE     = {"No Alert": "Watch",    "Watch": "Warning", "Warning": "Warning"}
_HIGH_TIDE_UPGRADE = {"No Alert": "No Alert", "Watch": "Warning", "Warning": "Warning"}

_CACHE_TTL_S = 1800
_cache: tuple[float, dict] | None = None


def summarize_sea_level(times: list[str], heights: list[float | None]) -> dict:
    """Pure summariser — separated from the fetch so it can be unit-tested."""
    pairs = [(t, h) for t, h in zip(times, heights) if h is not None]
    if not pairs:
        raise RuntimeError("Marine API returned no sea level data")
    peak_time, peak = max(pairs, key=lambda p: p[1])
    surge     = bool(peak >= COASTAL_SURGE_M)
    high_tide = bool(peak >= COASTAL_HIGH_TIDE_M)
    return {
        "max_sea_level_m":       round(float(peak), 3),
        "peak_time":             peak_time,
        "current_sea_level_m":   round(float(pairs[0][1]), 3),
        "advisory":              surge,          # surge tier (raises alerts alone)
        "high_tide":             high_tide,      # compounds with rain only
        "tier":                  "surge" if surge else ("high_tide" if high_tide else None),
        "threshold_m":           COASTAL_SURGE_M,
        "high_tide_threshold_m": COASTAL_HIGH_TIDE_M,
        "source":                "open-meteo-marine",
    }


def coastal_upgrade(level: str, coastal: dict | None) -> str:
    """
    Apply the coastal signal to one coastal-LGA cell's rain-driven alert level.

    Single source of truth for the forecast, summary and historical-validation
    paths, which previously each applied a blanket No Alert -> Watch upgrade.

      surge tier      No Alert -> Watch, Watch -> Warning
      high-tide tier  Watch -> Warning only; a dry cell stays No Alert
      neither         unchanged
    """
    if not coastal:
        return level
    if coastal.get("advisory"):
        return _SURGE_UPGRADE.get(level, level)
    if coastal.get("high_tide"):
        return _HIGH_TIDE_UPGRADE.get(level, level)
    return level


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
            "COASTAL SURGE: sea level peaks at %.3f m (>= %.2f m) at %s [%s]",
            best["max_sea_level_m"], COASTAL_SURGE_M,
            best["peak_time"], best["point"],
        )
    elif best["high_tide"]:
        log.info(
            "Coastal high tide: %.3f m (>= %.2f m) at %s [%s] — escalates rain Watch only",
            best["max_sea_level_m"], COASTAL_HIGH_TIDE_M,
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
