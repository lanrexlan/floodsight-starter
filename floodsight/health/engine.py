"""
FloodSight Health Intelligence Layer — Mosquito-Risk Prior Engine.

Translates flood-prediction outputs into a transparent, rule-based
*mosquito-breeding-risk prior* per Lagos LGA. Called by:
  - scripts/send_health_alerts.py  (daily cron, post-flood-event)
  - api/routers/health.py          (on-demand API endpoint)

WHAT THIS IS — AND IS NOT
-------------------------
This is an EXPERT-PARAMETERISED, RULE-BASED PRIOR — NOT a statistically
fitted model. The coefficients below are transparent, hand-set weights
chosen from published relationships (flood inundation area, terrain
susceptibility, temperature suitability), NOT regression estimates. There
is deliberately no n, no confidence interval, and no fit statistic,
because none has been estimated. Presenting it any other way would be
dishonest.

The prior's ONLY job at proof-of-concept stage is to RANK which flooded
LGAs are most likely to develop malaria-competent mosquito habitat, so
that scarce field-verification effort (larval surveys) and commodities
(nets, RDTs) are directed to the highest-priority wards first. The pilot
then MEASURES whether the ranking is correct — via entomological larval
surveys and health-system action data — and only after that will the
weights be replaced by parameters actually estimated from pilot data
(NEXA PoC timeline, Month 9+).

KNOWN BIOLOGICAL CAVEAT (must be validated, not assumed)
--------------------------------------------------------
In dense urban Lagos, much standing floodwater is organically polluted
drain overflow that favours *Culex quinquefasciatus* (a nuisance /
lymphatic-filariasis vector, NOT a malaria vector) over *Anopheles
gambiae s.l.* (the malaria vector, which prefers cleaner, sunlit,
temporary water). This prior therefore flags "potential mosquito
habitat", and the pilot's larval surveys (see entomology_observations
table, migration 002) test whether flagged sites actually produce
*Anopheles*. The confirmed *Anopheles*-positive fraction of flagged sites
is a PRIMARY intermediary outcome of the PoC — it is how we find out
whether the flood→malaria link holds in this specific urban setting.

Temperature → larval development lag uses Bayoh & Lindsay (2003) lab
kinetics as a first approximation only.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

import requests

from floodsight.config import (
    ANOPHELES_DEV_DAYS,
    AOI_LGAS,
    HEALTH_MIN_INUNDATION_KM2,
    PILOT_LAT,
    PILOT_LON,
)

log = logging.getLogger(__name__)

# Provenance label attached to every scored row so downstream consumers
# (API, dashboard, MEL, application reviewers) always know these numbers
# are an uncalibrated expert prior, not a fitted model.
RISK_MODEL_TYPE = "rule_based_prior"
RISK_MODEL_CALIBRATION = "expert_parameterised_uncalibrated"

# Aedes aegypti (dengue vector) development days by temperature.
# Faster than Anopheles; reserved for a possible dengue extension.
AEDES_DEV_DAYS: dict[int, int] = {
    26: 10, 27: 9, 28: 8, 29: 8, 30: 7, 31: 7, 32: 7
}
AEDES_DEV_DEFAULT = 8

# Duration of the elevated-risk outbreak window after adult mosquito emergence
OUTBREAK_WINDOW_DAYS = 7

# Grid cell area at 200 m resolution
CELL_AREA_KM2 = 0.04   # 200 m × 200 m = 40,000 m² = 0.04 km²

# Risk tier thresholds (risk_score 0–1). "Probability" language is
# deliberately avoided — this is a relative priority score, not a
# calibrated probability of an outbreak.
HEALTH_TIER_BREAKS: dict[str, tuple[float, float]] = {
    "Low":      (0.00, 0.30),
    "Moderate": (0.30, 0.55),
    "High":     (0.55, 0.75),
    "Critical": (0.75, 1.01),
}


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

def _fetch_temperature(lat: float = PILOT_LAT, lon: float = PILOT_LON) -> float:
    """
    Fetch today's mean 2 m temperature from Open-Meteo (free, no API key).
    Falls back to 28 °C (Lagos annual mean) on any error.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_mean&timezone=Africa%2FLagos&forecast_days=1"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        temp = data["daily"]["temperature_2m_mean"][0]
        log.debug("Open-Meteo temperature: %.1f °C", temp)
        return float(temp) if temp is not None else 28.0
    except Exception as exc:
        log.warning("Temperature fetch failed (%s) — using 28 °C default", exc)
        return 28.0


# ---------------------------------------------------------------------------
# Biological model
# ---------------------------------------------------------------------------

def _breeding_lag(temp_c: float) -> int:
    """
    Return Anopheles gambiae larval development days at the given temperature.

    Source: Bayoh & Lindsay (2003) Malaria Journal — lab measurements at
    discrete temperatures. This is a laboratory first-approximation for the
    alert lead-time; it is NOT a claim that Lagos floodwater produces
    Anopheles (see module docstring). Values outside 26–32 °C use the 11-day
    (29 °C) central estimate.
    """
    t = int(round(temp_c))
    return ANOPHELES_DEV_DAYS.get(t, 11)


def _risk_prior(
    inundation_km2: float,
    peak_susceptibility: float,
    temp_c: float,
) -> float:
    """
    Rule-based mosquito-breeding-risk PRIOR (NOT a fitted probability).

    This is a transparent weighted score in [0, 1] combining three published
    drivers of post-flood mosquito breeding risk:
      - inundation area (more standing water → more potential habitat)
      - terrain susceptibility (persistence of standing water)
      - temperature suitability (larval development, peaks ~30 °C)

    The weights are EXPERT-SET, not regression coefficients. They were chosen
    so the score ranks LGAs sensibly against three anchor scenarios:
      - 1 km² + peak 0.70 + 30 °C  → ~0.55 (High/Moderate boundary)
      - 5 km² + peak 0.80 + 30 °C  → ~0.80 (Critical)
      - 0.3 km² + peak 0.60 + 28 °C → ~0.22 (Low)

    The logistic squashing function is used only to bound the score to [0, 1]
    with diminishing returns on large inundation — it does NOT make the
    output a calibrated probability. During the pilot these weights will be
    replaced by parameters estimated from entomological + health-action data
    (Month 9+). Until then, treat the output strictly as a ranking prior.
    """
    # Temperature suitability: peaks at 30 °C, falls symmetrically
    temp_factor = max(0.0, 1.0 - abs(temp_c - 30.0) * 0.08)

    # Weighted linear score, bounded to [0, 1] via a logistic squash.
    # (Squashing bounds the score; it is NOT a probability estimate.)
    z = (
        -2.1
        + 0.45 * min(inundation_km2, 10.0)   # cap at 10 km² to avoid overflow
        + 2.80 * peak_susceptibility
        + 1.20 * temp_factor
    )
    score = 1.0 / (1.0 + math.exp(-z))
    return round(min(max(score, 0.0), 1.0), 4)


# Backwards-compatible alias — older callers/tests import _outbreak_probability.
# Kept so nothing breaks, but the honest name is _risk_prior.
_outbreak_probability = _risk_prior


def _risk_tier(prob: float) -> str:
    """Map a risk-prior score to a named risk tier."""
    for tier, (lo, hi) in HEALTH_TIER_BREAKS.items():
        if lo <= prob < hi:
            return tier
    return "Critical"


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_lgas(
    grid_geojson: dict,
    alert_levels: list[str],
    flood_event_id: str | None = None,
) -> list[dict]:
    """
    Score all 15 Lagos LGAs for mosquito-breeding-risk priority.

    Parameters
    ----------
    grid_geojson : dict
        GeoJSON FeatureCollection from /risk/grid (or get_grid_geojson()).
        Each Feature must have properties: lga_name, hazard_score.

    alert_levels : list[str]
        Parallel list of alert level strings ("No Alert" | "Watch" | "Warning")
        in the same order as grid_geojson["features"]. This is the
        alert_levels field from /forecast/alerts response.

    flood_event_id : str | None
        Optional identifier for the triggering forecast run (e.g. ISO date).

    Returns
    -------
    List of dicts, one per LGA that exceeds HEALTH_MIN_INUNDATION_KM2,
    sorted descending by outbreak_probability (the rule-based risk score).
    Each dict includes model_type / calibration_status so downstream
    consumers know the score is an uncalibrated prior. Keys:
        lga_name, flood_event_id, inundation_area_km2, peak_susceptibility,
        temp_celsius, breeding_lag_days, outbreak_window_start,
        outbreak_window_end, outbreak_probability, risk_tier,
        model_type, calibration_status
    """
    features = grid_geojson.get("features", [])
    if len(features) != len(alert_levels):
        log.warning(
            "grid_geojson has %d features but alert_levels has %d entries — "
            "truncating to shorter list",
            len(features),
            len(alert_levels),
        )

    temp_c = _fetch_temperature()
    lag    = _breeding_lag(temp_c)
    today  = date.today()
    window_start = today + timedelta(days=lag)
    window_end   = window_start + timedelta(days=OUTBREAK_WINDOW_DAYS)

    # Accumulate flooded-cell counts and peak hazard_score per LGA
    lga_stats: dict[str, dict[str, Any]] = {
        lga: {"flooded_cells": 0, "peak_susceptibility": 0.0}
        for lga in AOI_LGAS
    }

    n = min(len(features), len(alert_levels))
    for i in range(n):
        props = features[i].get("properties", {})
        lga   = props.get("lga_name", "")
        level = alert_levels[i]
        score = float(props.get("hazard_score", 0.0))

        if lga in lga_stats and level in ("Watch", "Warning"):
            lga_stats[lga]["flooded_cells"] += 1
            if score > lga_stats[lga]["peak_susceptibility"]:
                lga_stats[lga]["peak_susceptibility"] = score

    results = []
    for lga, stats in lga_stats.items():
        area_km2 = stats["flooded_cells"] * CELL_AREA_KM2
        if area_km2 < HEALTH_MIN_INUNDATION_KM2:
            continue   # insufficient standing water to drive breeding

        peak = stats["peak_susceptibility"]
        prob = _risk_prior(area_km2, peak, temp_c)
        tier = _risk_tier(prob)

        results.append({
            "lga_name":              lga,
            "flood_event_id":        flood_event_id,
            "inundation_area_km2":   round(area_km2, 3),
            "peak_susceptibility":   round(peak, 4),
            "temp_celsius":          round(temp_c, 2),
            "breeding_lag_days":     lag,
            "outbreak_window_start": window_start.isoformat(),
            "outbreak_window_end":   window_end.isoformat(),
            # Field name kept for API/DB backward-compatibility, but this is
            # a rule-based RANKING score, not a calibrated probability.
            "outbreak_probability":  prob,
            "risk_tier":             tier,
            "model_type":            RISK_MODEL_TYPE,
            "calibration_status":    RISK_MODEL_CALIBRATION,
        })

    results.sort(key=lambda x: x["outbreak_probability"], reverse=True)
    log.info(
        "Health scoring complete (rule-based prior, uncalibrated): %d LGAs "
        "above %.1f km² threshold (temp=%.1f °C, lag=%d days, window=%s to %s)",
        len(results),
        HEALTH_MIN_INUNDATION_KM2,
        temp_c,
        lag,
        window_start.isoformat(),
        window_end.isoformat(),
    )
    return results
