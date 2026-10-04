from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.data_provider import get_grid, get_grid_geojson, get_streets_geojson, get_swmm_flooding_geojson, nearest_cell
from api.schemas import RiskAtPoint

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/grid")
def risk_grid(request: Request):
    """Full grid as GeoJSON (risk_class, flood_score per cell).

    Returns the cached WGS84 GeoJSON dict — serialisation only happens once
    per process lifetime (see data_provider.get_grid_geojson).
    """
    from api.assets import map_response
    return map_response("grid", request)


@router.get("/point", response_model=RiskAtPoint)
def risk_at_point(lat: float, lon: float):
    try:
        cell = nearest_cell(lat, lon)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Risk data temporarily unavailable.") from exc

    _, source = get_grid()
    return RiskAtPoint(
        cell_id=str(cell["cell_id"]),
        lat=lat,
        lon=lon,
        elevation_m=float(cell["elevation_m"]),
        flood_score=float(cell["flood_score"]),
        hazard_score=float(cell.get("hazard_score", cell["flood_score"])),
        risk_class=str(cell["risk_class"]),
        data_source=source,
    )


@router.get("/streets")
def risk_streets(request: Request, bbox: str | None = None):
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
    from api.assets import map_response, prepared_asset
    from api.data_provider import STREETS_RISK_PATH
    if prepared_asset("streets") is None and not STREETS_RISK_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Street risk data not available. "
                "Run scripts/05_tag_street_risk.py to generate it."
            ),
        )
    if bbox is not None:
        from api.street_tiles import street_window
        return street_window(bbox, request)
    return map_response("streets", request)


@router.get("/swmm-flooding")
def swmm_flooding():
    """
    SWMM 5.2 flooded-junction GeoJSON — Kosofe, Alimosho, and Eti-Osa.

    Each feature is a junction that overflowed during the 150 mm / 4 h design
    storm.  Properties: ``flood_class`` (Severe / Moderate / Nuisance),
    ``max_rate_cms``, ``hours_flooded``, ``total_vol_10e6l``, ``colour``
    (CSS hex), ``lga``, ``lga_display``.

    Serves ``swmm_flooding_all.geojson`` (3 LGAs) when available,
    falling back to the legacy Kosofe-only file.

    **Pre-requisite:**
      python scripts/07_parse_swmm_results.py --lga all
      python scripts/08_merge_swmm_results.py
    Returns 404 until at least one SWMM flooding GeoJSON exists.
    """
    geojson = get_swmm_flooding_geojson()
    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "SWMM flooding data not available. "
                "Run: python scripts/07_parse_swmm_results.py --lga all "
                "then: python scripts/08_merge_swmm_results.py"
            ),
        )
    return geojson
