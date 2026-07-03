"""
Rainfall-triggered alert logic — a direct port of the existing repo's
README rule, extended with an optional depth-based override once the
HAND/ML depth layer is available (a non-trivial predicted depth is a
stronger, more specific signal than a risk-class + rainfall threshold
combination, so it can upgrade an alert level even if the legacy rule
wouldn't have fired).
"""

from __future__ import annotations

from floodsight.config import (
    RAIN_WARNING_24H_MM,
    RAIN_WARNING_72H_MM,
    RAIN_WATCH_HIGH_24H_MM,
    RAIN_WATCH_HIGH_72H_MM,
    RAIN_WATCH_MODERATE_24H_MM,
    RAIN_WATCH_MODERATE_72H_MM,
)

HIGH_RISK_CLASSES = {"High", "Very High"}


def compute_alert_level(
    risk_class: str,
    rain_24h_mm: float,
    rain_72h_mm: float,
    predicted_depth_m: float | None = None,
) -> str:
    """
    Ported rule (README "Rainfall alert logic"):
      Warning: High/Very High risk AND (rain_24h>=100 OR rain_72h>=150)
      Watch:   High/Very High risk AND (rain_24h>=50  OR rain_72h>=100)
      Watch:   Moderate risk      AND (rain_24h>=100 OR rain_72h>=150)
      Otherwise: No Alert

    Depth override: if a HAND/ML depth prediction is supplied and exceeds
    0.3m (roughly ankle-deep — the point at which pedestrian movement and
    vehicle access become unsafe per standard flood-risk-to-life
    guidance), the alert is raised to at least Watch, and to Warning above
    0.5m, regardless of what the legacy rule alone would have produced.
    These thresholds are a starting point — replace with NiHSA/SEMA
    operational guidance once available; nothing here has been validated
    against real evacuation outcomes yet.
    """
    if risk_class in HIGH_RISK_CLASSES and (
        rain_24h_mm >= RAIN_WARNING_24H_MM or rain_72h_mm >= RAIN_WARNING_72H_MM
    ):
        level = "Warning"
    elif risk_class in HIGH_RISK_CLASSES and (
        rain_24h_mm >= RAIN_WATCH_HIGH_24H_MM or rain_72h_mm >= RAIN_WATCH_HIGH_72H_MM
    ):
        level = "Watch"
    elif risk_class == "Moderate" and (
        rain_24h_mm >= RAIN_WATCH_MODERATE_24H_MM or rain_72h_mm >= RAIN_WATCH_MODERATE_72H_MM
    ):
        level = "Watch"
    else:
        level = "No Alert"

    if predicted_depth_m is not None:
        if predicted_depth_m >= 0.5 and level != "Warning":
            level = "Warning"
        elif predicted_depth_m >= 0.3 and level == "No Alert":
            level = "Watch"

    return level
