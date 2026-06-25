from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.data_provider import get_grid, get_grid_geojson, nearest_cell
from api.schemas import RiskAtPoint

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/grid")
def risk_grid():
    """Full grid as GeoJSON (risk_class, flood_score per cell).

    Returns the cached WGS84 GeoJSON dict — serialisation only happens once
    per process lifetime (see data_provider.get_grid_geojson).
    """
    geojson, _ = get_grid_geojson()
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
