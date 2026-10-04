from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field, ConfigDict, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", validate_default=True)


class LocatedInput(InputModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def supported_location(self):
        from floodsight.config import AOI_BBOX
        west, south, east, north = AOI_BBOX
        if not (west <= self.lon <= east and south <= self.lat <= north):
            raise ValueError("Location is outside FloodSight's Lagos pilot coverage.")
        return self


class RiskAtPoint(BaseModel):
    cell_id: str
    lat: float
    lon: float
    elevation_m: float
    flood_score: float
    hazard_score: float | None = None
    risk_class: str
    data_source: str = Field(description="'processed_pipeline' or 'synthetic_demo'")


class DepthPredictionRequest(InputModel):
    elevation_m: float = Field(ge=-100, le=9000)
    slope_deg: float = Field(ge=0, le=90)
    flow_accum: float = Field(ge=0)
    hand_m: float | None = Field(default=None, ge=0)
    dist_to_water_m: float = Field(ge=0)
    landcover_class: int = Field(ge=0, le=255)
    population_density: float = Field(ge=0)
    rain_24h_mm: float = Field(ge=0, le=3000)
    rain_72h_mm: float = Field(ge=0, le=9000)
    # Optional geo-reference — included in the prediction log so verifications
    # can be matched back to specific predictions later.
    lat: float | None = None
    lon: float | None = None
    cell_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def paired_coordinates(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Supply both lat and lon, or neither.")
        if self.lat is not None:
            from api.coordinates import validate_location
            from fastapi import HTTPException
            try:
                validate_location(self.lat, self.lon)
            except HTTPException as exc:
                raise ValueError(exc.detail) from exc
        return self


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


class VerifyRequest(LocatedInput):
    """Field verification for a specific location after a flood event.

    Submitted by community reporters or field partners to confirm/deny
    whether a warned cell actually flooded. Used in Phase 6 to recalibrate
    the model and susceptibility weights.
    """

    event_date: date = Field(description="ISO date of the flood event, e.g. '2025-07-15'")
    observed_flooded: bool = Field(
        description="True if the location was observed to be flooded"
    )
    observed_depth_m: float | None = Field(
        default=None,
        ge=0, le=20,
        description="Estimated flood depth in metres (optional but valuable)",
    )
    reporter: str | None = Field(
        default=None, max_length=120, description="Name or identifier of the person reporting"
    )
    notes: str | None = Field(
        default=None, max_length=2000, description="Free-text notes (photos, source, caveats)"
    )


class VerifyResponse(BaseModel):
    status: str
    message: str
    verification_id: str


class AlertRequest(LocatedInput):
    rain_24h_mm: float = Field(ge=0, le=3000)
    rain_72h_mm: float = Field(ge=0, le=9000)
    predicted_depth_m: float | None = Field(default=None, ge=0, le=20)


class AlertResponse(BaseModel):
    lat: float
    lon: float
    risk_class: str
    alert_level: str
    rain_24h_mm: float
    rain_72h_mm: float
    data_source: str
