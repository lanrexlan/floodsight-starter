"""
GET /forecast/rainfall  — live 24h/72h precipitation forecast for a point.
GET /forecast/alerts    — risk grid annotated with live alert levels.
GET /forecast/summary   — lightweight alert counts (no geometry); for SMS briefings.

Powered by Open-Meteo (free, no API key required).
Results cached 30 min in-process.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query

from api.data_provider import get_grid
from floodsight.config import WGS84

log = logging.getLogger(__name__)

# Default to the pilot grid centre (lon 3.36–3.45, lat 6.44–6.62)
PILOT_LAT = 6.530
PILOT_LON = 3.405

router = APIRouter(prefix="/forecast", tags=["forecast"])


def _load_grid_geojson() -> tuple[dict, str]:
    """Load the risk grid as a plain GeoJSON dict (WGS84).
    Returns (geojson_dict, data_source)."""
    grid, source = get_grid()
    grid_wgs84 = grid.to_crs(WGS84)
    geojson = json.loads(grid_wgs84.to_json())
    return geojson, source


# ---------------------------------------------------------------------------
# /forecast/rainfall
# ---------------------------------------------------------------------------

@router.get("/rainfall")
def get_rainfall_forecast(
    lat: float = Query(PILOT_LAT, description="Latitude  (default: pilot grid centre)"),
    lon: float = Query(PILOT_LON, description="Longitude (default: pilot grid centre)"),
):
    """
    Returns the next-24h and next-72h accumulated precipitation forecast
    from Open-Meteo for the requested coordinates.

    Use these values to pre-populate the dashboard rainfall sliders with
    live data so users see current alert levels without adjusting sliders.

    Results are cached for 30 minutes — the dashboard should call this once
    on page load, not on every map click.
    """
    try:
        from floodsight.forecast.openmeteo import fetch_forecast
        return fetch_forecast(lat, lon)
    except RuntimeError as exc:
        log.warning("Forecast fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.error("Unexpected error in forecast endpoint: %s", exc)
        raise HTTPException(status_code=500, detail="Internal forecast error") from exc


# ---------------------------------------------------------------------------
# /forecast/alerts  — grid-level live alert status
# ---------------------------------------------------------------------------

@router.get("/alerts")
def get_grid_alerts(
    lat: float = Query(PILOT_LAT, description="Latitude  for forecast lookup"),
    lon: float = Query(PILOT_LON, description="Longitude for forecast lookup"),
):
    """
    Fetches the live rainfall forecast and applies the alert engine to every
    cell in the risk grid.  Returns a GeoJSON FeatureCollection identical to
    /risk/grid but with an extra ``alert_level`` property on each feature.

    Because Lagos is a small region (~20 × 10 km) a single forecast point is
    used for all cells; the dominant error source is the ML model, not
    spatial rainfall variability at this scale.
    """
    # 1. Get live forecast
    try:
        from floodsight.forecast.openmeteo import fetch_forecast
        fc = fetch_forecast(lat, lon)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rain_24h = fc["rain_24h_mm"]
    rain_72h = fc["rain_72h_mm"]

    # 2. Load risk grid
    from floodsight.alerts.engine import compute_alert_level

    grid, source = _load_grid_geojson()
    features = grid.get("features", [])

    # 3. Annotate each feature with alert_level
    for feat in features:
        props = feat.get("properties", {})
        risk_class = props.get("risk_class", "Low")
        props["alert_level"] = compute_alert_level(risk_class, rain_24h, rain_72h)
        props["forecast_rain_24h_mm"] = rain_24h
        props["forecast_rain_72h_mm"] = rain_72h

    grid["forecast"] = {
        "rain_24h_mm": rain_24h,
        "rain_72h_mm": rain_72h,
        "source": fc["forecast_source"],
        "fetched_at": fc["fetched_at"],
    }
    grid["data_source"] = source
    return grid


# ---------------------------------------------------------------------------
# /forecast/summary  — lightweight counts for SMS briefings (no geometry)
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_alert_summary(
    lat: float = Query(PILOT_LAT, description="Latitude  for forecast lookup"),
    lon: float = Query(PILOT_LON, description="Longitude for forecast lookup"),
):
    """
    Returns alert-level counts without the full GeoJSON geometry.
    Intended for lightweight callers such as the morning SMS briefing.

    Response shape:
    {
      "total_cells": 53075,
      "alert_counts": {"Warning": 1234, "Watch": 5678, "No Alert": 46163},
      "highest_alert": "Warning",
      "forecast": {
        "rain_24h_mm": 42.1,
        "rain_72h_mm": 87.5,
        "source": "open-meteo",
        "fetched_at": "2025-06-01T05:00:00+00:00"
      }
    }
    """
    # 1. Live forecast
    try:
        from floodsight.forecast.openmeteo import fetch_forecast
        fc = fetch_forecast(lat, lon)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    rain_24h = fc["rain_24h_mm"]
    rain_72h = fc["rain_72h_mm"]

    # 2. Load risk grid and count alert levels directly from the GeoDataFrame
    #    (avoids the slow JSON serialisation that /alerts does for the full grid)
    from floodsight.alerts.engine import compute_alert_level

    gdf, _ = get_grid()

    counts: dict = {"Warning": 0, "Watch": 0, "No Alert": 0}
    for risk_class in gdf["risk_class"]:
        level = compute_alert_level(risk_class, rain_24h, rain_72h)
        counts[level] = counts.get(level, 0) + 1

    # Determine highest alert (Warning > Watch > No Alert)
    if counts.get("Warning", 0) > 0:
        highest = "Warning"
    elif counts.get("Watch", 0) > 0:
        highest = "Watch"
    else:
        highest = "No Alert"

    return {
        "total_cells": len(gdf),
        "alert_counts": counts,
        "highest_alert": highest,
        "forecast": {
            "rain_24h_mm": rain_24h,
            "rain_72h_mm": rain_72h,
            "source": fc["forecast_source"],
            "fetched_at": fc["fetched_at"],
        },
    }
