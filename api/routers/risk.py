from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from api.data_provider import get_grid, nearest_cell
from api.schemas import RiskAtPoint
from floodsight.config import WGS84

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/grid")
def risk_grid():
    """Full grid as GeoJSON (risk_class, flood_score per cell) — what the
    dashboard's Leaflet layer fetches directly."""
    grid, source = get_grid()
    grid_wgs84 = grid.to_crs(WGS84)
    geojson = json.loads(grid_wgs84.to_json())
    geojson["data_source"] = source
    return geojson


@router.get("/point", response_model=RiskAtPoint)
def risk_at_point(lat: float, lon: float):
    try:
        cell = nearest_cell(lat, lon)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    _, source = get_grid()
    return RiskAtPoint(
        cell_id=str(cell["cell_id"]),
        lat=lat,
        lon=lon,
        elevation_m=float(cell["elevation_m"]),
        flood_score=float(cell["flood_score"]),
        risk_class=str(cell["risk_class"]),
        data_source=source,
    )
