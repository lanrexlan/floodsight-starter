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


class DepthPredictionResponse(BaseModel):
    model_config = {"protected_namespaces": ()}  # silences a pydantic
    # warning: it treats any field starting with "model_" as
    # potentially conflicting with its own internal ML-model-related
    # conventions. model_trained_on_synthetic_data is just a plain bool
    # field, not an actual conflict — this is cosmetic only.

    predicted_depth_m: float
    model_trained_on_synthetic_data: bool
    note: str | None = None


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
