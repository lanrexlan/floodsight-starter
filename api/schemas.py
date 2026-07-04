from __future__ import annotations

from pydantic import BaseModel, Field


class RiskAtPoint(BaseModel):
    cell_id: str
    lat: float
    lon: float
    elevation_m: float
    flood_score: float
    risk_class: str
    data_source: str = Field(description="'processed_pipeline' or 'synthetic_demo'")


class DepthPredictionRequest(BaseModel):
    elevation_m: float
    slope_deg: float
    flow_accum: float
    hand_m: float
    dist_to_water_m: float
    landcover_class: int
    population_density: float
    rain_24h_mm: float
    rain_72h_mm: float
    # Optional geo-reference — included in the prediction log so verifications
    # can be matched back to specific predictions later.
    lat: float | None = None
    lon: float | None = None
    cell_id: str | None = None


class DepthPredictionResponse(BaseModel):
    model_config = {"protected_namespaces": ()}  # silences a pydantic
    # warning: it treats any field starting with "model_" as
    # potentially conflicting with its own internal ML-model-related
    # conventions. model_trained_on_synthetic_data is just a plain bool
    # field, not an actual conflict — this is cosmetic only.

    predicted_depth_m: float
    model_trained_on_synthetic_data: bool
    # Fraction of training labels that are synthetic/pseudo-labeled
    # (SWMM- or severity-model-derived rather than SAR/FwDET-observed).
    # None only for old bundles that predate provenance tracking.
    synthetic_label_fraction: float | None = None
    note: str | None = None


class VerifyRequest(BaseModel):
    """Field verification for a specific location after a flood event.

    Submitted by community reporters or field partners to confirm/deny
    whether a warned cell actually flooded. Used in Phase 6 to recalibrate
    the model and susceptibility weights.
    """

    lat: float
    lon: float
    event_date: str = Field(description="ISO date of the flood event, e.g. '2025-07-15'")
    observed_flooded: bool = Field(
        description="True if the location was observed to be flooded"
    )
    observed_depth_m: float | None = Field(
        default=None,
        description="Estimated flood depth in metres (optional but valuable)",
    )
    reporter: str | None = Field(
        default=None, description="Name or identifier of the person reporting"
    )
    notes: str | None = Field(
        default=None, description="Free-text notes (photos, source, caveats)"
    )


class VerifyResponse(BaseModel):
    status: str
    message: str
    verification_id: str


class AlertRequest(BaseModel):
    lat: float
    lon: float
    rain_24h_mm: float
    rain_72h_mm: float
    predicted_depth_m: float | None = None


class AlertResponse(BaseModel):
    lat: float
    lon: float
    risk_class: str
    alert_level: str
    rain_24h_mm: float
    rain_72h_mm: float
    data_source: str
