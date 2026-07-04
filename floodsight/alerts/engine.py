"""
Rainfall-triggered alert logic — a direct port of the existing repo's
README rule, extended with:
  - optional depth-based override (HAND/ML depth layer)
  - antecedent soil-saturation modifier: when 30-day accumulated rainfall
    exceeds RAIN_ANTECEDENT_SAT_30D_MM the soil is near field-capacity and
    Watch thresholds are multiplied by RAIN_SAT_WATCH_MULTIPLIER (~0.7×).
    This captures events where modest storm rainfall on saturated soil
    causes flooding that the raw threshold would miss.
"""

from __future__ import annotations

from floodsight.config import (
    RAIN_WARNING_24H_MM,
    RAIN_WARNING_72H_MM,
    RAIN_WATCH_HIGH_24H_MM,
    RAIN_WATCH_HIGH_72H_MM,
    RAIN_WATCH_MODERATE_24H_MM,
    RAIN_WATCH_MODERATE_72H_MM,
    RAIN_ANTECEDENT_SAT_30D_MM,
    RAIN_SAT_WATCH_MULTIPLIER,
)

HIGH_RISK_CLASSES = {"High", "Very High"}


def compute_alert_level(
    risk_class: str,
    rain_24h_mm: float,
    rain_72h_mm: float,
    predicted_depth_m: float | None = None,
    antecedent_30d_mm: float | None = None,
) -> str:
    """
    Compute the alert level for a single grid cell.

    Rules (after July 2026 calibration against 18 documented Lagos events):
      Warning: High/Very High risk AND (rain_24h>=80 OR rain_72h>=100)
      Watch:   High/Very High risk AND (rain_24h>=20 OR rain_72h>=30)
                                   [thresholds reduced 30% when soil saturated]
      Watch:   Moderate risk      AND (rain_24h>=70 OR rain_72h>=100)
      Otherwise: No Alert

    Parameters
    ----------
    risk_class :
        Cell susceptibility class ("Very High", "High", "Moderate", "Low").
    rain_24h_mm :
        Observed or forecast precipitation in the past / next 24 hours.
    rain_72h_mm :
        Rolling 72-hour precipitation (observed + forecast).
    predicted_depth_m :
        Optional HAND/ML flood depth prediction (metres).  If >=0.5m the
        alert is raised to Warning; if >=0.3m it is raised to at least Watch.
        These are starting-point thresholds — replace with NiHSA/SEMA
        operational guidance once validated against evacuation outcomes.
    antecedent_30d_mm :
        Optional 30-day accumulated rainfall preceding the event (mm).
        When >= RAIN_ANTECEDENT_SAT_30D_MM the soil is assumed near
        field-capacity and Watch thresholds are multiplied by
        RAIN_SAT_WATCH_MULTIPLIER (lowered ~30%) to capture flooding from
        smaller storms on saturated ground.
        Pass None (default) to skip the saturation modifier — the engine
        then behaves identically to the previous version.
    """
    # -- Saturation modifier -------------------------------------------------
    saturated = (
        antecedent_30d_mm is not None
        and antecedent_30d_mm >= RAIN_ANTECEDENT_SAT_30D_MM
    )
    if saturated:
        watch_24h = RAIN_WATCH_HIGH_24H_MM * RAIN_SAT_WATCH_MULTIPLIER   # 20*0.7 = 14 mm
        watch_72h = RAIN_WATCH_HIGH_72H_MM * RAIN_SAT_WATCH_MULTIPLIER   # 30*0.7 = 21 mm
    else:
        watch_24h = float(RAIN_WATCH_HIGH_24H_MM)
        watch_72h = float(RAIN_WATCH_HIGH_72H_MM)

    # -- Core rules ----------------------------------------------------------
    if risk_class in HIGH_RISK_CLASSES and (
        rain_24h_mm >= RAIN_WARNING_24H_MM or rain_72h_mm >= RAIN_WARNING_72H_MM
    ):
        level = "Warning"
    elif risk_class in HIGH_RISK_CLASSES and (
        rain_24h_mm >= watch_24h or rain_72h_mm >= watch_72h
    ):
        level = "Watch"
    elif risk_class == "Moderate" and (
        rain_24h_mm >= RAIN_WATCH_MODERATE_24H_MM or rain_72h_mm >= RAIN_WATCH_MODERATE_72H_MM
    ):
        level = "Watch"
    else:
        level = "No Alert"

    # -- Depth override ------------------------------------------------------
    if predicted_depth_m is not None:
        if predicted_depth_m >= 0.5 and level != "Warning":
            level = "Warning"
        elif predicted_depth_m >= 0.3 and level == "No Alert":
            level = "Watch"

    return level
