from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.data_provider import get_grid, get_grid_geojson, get_streets_geojson, nearest_cell
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


@router.get("/streets")
def risk_streets():
    """
    OSM road segments tagged with flood risk class.

    Returns all arterial roads (motorway → tertiary) and high-risk
    residential / unclassified roads, each tagged with ``risk_class``
    and ``flood_score`` from the nearest scored grid cell.

    Intended for the dashboard street layer which activates at zoom ≥ 13
    where individual roads become visible.  The dashboard loads this lazily
    on first zoom-in so it doesn't slow the initial page load.

    **Pre-requisite:** run ``scripts/05_tag_street_risk.py`` to generate
    ``data/processed/streets_risk.gpkg``.  Returns 404 until that file exists.
    """
    geojson, _ = get_streets_geojson()
    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Street risk data not available. "
                "Run scripts/05_tag_street_risk.py to generate it."
            ),
        )
    return geojson
