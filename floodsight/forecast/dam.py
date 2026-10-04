"""
Dam-release monitoring via Open-Meteo Flood API (GloFAS v4 reanalysis +
ensemble forecast, free, no API key required).

Why: Two of the eight back-tested FloodSight misses were Ogun river
floods, almost certainly caused by Oyan Dam releases (May 2019, June 2018).
Rainfall-only alerts cannot detect dam-release floods — rainfall can be
minimal while upstream reservoir drawdown sends a surge downstream.

Monitoring point: Isheri Olofin (6.67°N, 3.43°E) — the last gauging
station on the Ogun river before it enters Lagos State and spreads into
the Agege/Alimosho lowlands.  A discharge spike here gives ~6–12 h lead
time before peak inundation in Agege/Alimosho.

DAM_ADVISORY_M3S = 300 m³/s (bankfull-based; see constant definition below).
The Ogun at Isheri runs at 40–120 m³/s during normal wet season;
GloFAS v4 underestimates West African peak flows by ~20–40% at 0.1° —
the conservative 300 m³/s threshold partly compensates.

Per-cell wiring: deferred until Ogun floodplain cells are mapped.
Currently surfaces as an operator-facing "dam" block in /forecast/alerts
and /forecast/summary — the same integration pattern as the coastal signal.

Usage::

    from floodsight.forecast.dam import try_dam_summary
    try_dam_summary()  ->
        {
          "max_discharge_m3s":   512.4,
          "peak_day":            "2026-07-08",
          "current_discharge_m3s": 87.3,
          "advisory":            True,
          "threshold_m3s":       400,
          "river":               "Ogun at Isheri",
          "source":              "open-meteo-flood-glofas",
          "fetched_at":          "...",
        }
    Returns None on fetch failure (non-fatal — dam data is optional).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Monitoring point: last Ogun gauge before Lagos State border.
OGUN_LAT = 6.67
OGUN_LON = 3.43

# Advisory threshold — Ogun at Isheri.
# Bankfull capacity of the Ogun channel at Isheri is ~200–250 m³/s based
# on channel-morphology studies (Oyegoke et al., 2008; OORBDA gauging
# records).  300 m³/s (~2× wet-season mean) is set as the advisory trigger:
# high enough to filter normal wet-season peaks (40–120 m³/s) and low
# enough to give 6–12 h lead time before floodplain inundation in Agege
# and Ifako-Ijaiye.  Major release events (2011, 2020) exceeded 800 m³/s.
# GloFAS v4 underestimates West African peak flows by ~20–40% at 0.1°
# resolution — the conservative 300 m³/s threshold partly compensates.
# Recalibrate against NiHSA/OORBDA gauge records when available.
DAM_ADVISORY_M3S = 300.0

_CACHE_TTL_S = 1800   # 30-min cache — matches marine.py
_cache: tuple[float, dict] | None = None


def summarise_discharge(dates: list[str], flows: list[float | None]) -> dict:
    """Pure summariser — testable without the network call."""
    pairs = [(d, q) for d, q in zip(dates, flows) if q is not None]
    if not pairs:
        raise RuntimeError("Flood API returned no discharge data")
    peak_day, peak = max(pairs, key=lambda p: p[1])
    return {
        "max_discharge_m3s":     round(float(peak), 1),
        "peak_day":              peak_day,
        "current_discharge_m3s": round(float(pairs[0][1]), 1),
        "advisory":              bool(peak >= DAM_ADVISORY_M3S),
        "threshold_m3s":         DAM_ADVISORY_M3S,
        "river":                 "Ogun at Isheri",
        "source":                "open-meteo-flood-glofas",
    }


def get_dam_summary(force: bool = False) -> dict:
    """Ogun river discharge forecast, 16-day horizon (30-min cache)."""
    global _cache
    now = time.time()
    if _cache is not None and not force and now - _cache[0] < _CACHE_TTL_S:
        return _cache[1]

    from floodsight.forecast.provider import endpoint, credential_query
    url = (
        endpoint("flood", "flood")
        + f"?latitude={OGUN_LAT}&longitude={OGUN_LON}"
        "&daily=river_discharge&forecast_days=16&past_days=1" + credential_query()
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(f"Flood API fetch failed: {exc}") from exc

    daily = data.get("daily", {})
    summary = summarise_discharge(
        daily.get("time", []),
        daily.get("river_discharge", []),
    )
    summary["fetched_at"] = datetime.now(timezone.utc).isoformat()

    if summary["advisory"]:
        log.warning(
            "DAM ADVISORY: Ogun discharge peaks at %.0f m³/s "
            "(>= %.0f m³/s threshold) on %s",
            summary["max_discharge_m3s"],
            DAM_ADVISORY_M3S,
            summary["peak_day"],
        )

    _cache = (now, summary)
    return summary


def try_dam_summary() -> dict | None:
    """Non-raising wrapper — dam data is an optional signal."""
    try:
        return get_dam_summary()
    except Exception as exc:
        log.warning("Dam/river signal unavailable: %s", exc)
        return None
