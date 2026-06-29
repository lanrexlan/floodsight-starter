"""
GET /forecast/rainfall  — live observed + forecast precipitation for a point.
GET /forecast/alerts    — risk grid annotated with live alert levels.
GET /forecast/summary   — lightweight alert counts (no geometry); for SMS briefings.

Phase 11: Dual-stream rainfall — observed (past 24 h) + forecast (next 72 h).
Powered by Open-Meteo (free, no API key required).
Results cached 30 min in-process.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from api.data_provider import get_grid, get_grid_geojson

log = logging.getLogger(__name__)

# Phase 13: default to Lagos city centre (covers all 15 LGAs).
# GFS grid cells are 0.25° (~28 km) so one point lookup is representative
# for the entire city; the same forecast is applied to every grid cell.
PILOT_LAT = 6.520   # approximately Ikeja / city geographic centre
PILOT_LON = 3.370

router = APIRouter(prefix="/forecast", tags=["forecast"])


def _load_grid_geojson() -> tuple[dict, str]:
    """Returns the cached WGS84 GeoJSON dict (read-only — do not mutate)."""
    return get_grid_geojson()


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
    Returns a **compact** alert payload — no geometry, just one alert-level
    string per grid cell in the same order as ``/risk/grid`` features.

    The dashboard loads ``/risk/grid`` for geometry and ``/forecast/alerts``
    for alert levels, then merges them client-side.  This split keeps each
    response small and avoids serialising the full 54 k-cell GeoJSON twice
    per page load — which was OOM-killing Render's 512 MB free tier.

    Response shape::

        {
          "alert_levels":  ["No Alert", "Watch", "Warning", ...],  // 54 k items
          "alert_counts":  {"Warning": 1234, "Watch": 5678, "No Alert": 46163},
          "highest_alert": "Warning",
          "total_cells":   54115,
          "forecast": {
            "observed_24h_mm": 5.2, "forecast_24h_mm": 18.0, ...
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

    # 2. Compute alert levels by iterating the GeoDataFrame column directly —
    #    no GeoJSON serialisation; this is the same O(n) loop used by /summary.
    from floodsight.alerts.engine import compute_alert_level

    gdf, _ = get_grid()
    alert_levels = [
        compute_alert_level(rc, rain_24h, rain_72h)
        for rc in gdf["risk_class"]
    ]

    # 3. Count levels + per-LGA breakdown
    counts: dict[str, int] = {"Warning": 0, "Watch": 0, "No Alert": 0}
    lga_alerts: dict[str, int] = {}
    has_lga = "lga_name" in gdf.columns

    for i, level in enumerate(alert_levels):
        counts[level] = counts.get(level, 0) + 1
        if has_lga and level in ("Warning", "Watch"):
            lga = gdf["lga_name"].iloc[i]
            if lga and str(lga) != "nan":
                lga_alerts[lga] = lga_alerts.get(lga, 0) + 1

    # Sort LGAs by alerted cell count descending; keep top 6
    lga_alerts = dict(
        sorted(lga_alerts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    )

    highest = (
        "Warning" if counts["Warning"] > 0
        else "Watch" if counts["Watch"] > 0
        else "No Alert"
    )

    return {
        "alert_levels":  alert_levels,
        "alert_counts":  counts,
        "highest_alert": highest,
        "lga_alerts":    lga_alerts,
        "total_cells":   len(gdf),
        "forecast": {
            # Phase 11 dual-stream fields
            "observed_24h_mm":  fc.get("observed_24h_mm", 0.0),
            "forecast_24h_mm":  fc.get("forecast_24h_mm", rain_24h),
            "forecast_48h_mm":  fc.get("forecast_48h_mm", 0.0),
            "forecast_72h_mm":  fc.get("forecast_72h_mm", rain_72h),
            # Alert engine compat (unchanged names)
            "rain_24h_mm":      rain_24h,
            "rain_72h_mm":      rain_72h,
            # Metadata
            "source":           fc["forecast_source"],
            "data_mode":        fc.get("data_mode", "forecast_only"),
            "fetched_at":       fc["fetched_at"],
        },
    }


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
            # Phase 11 dual-stream fields
            "observed_24h_mm":  fc.get("observed_24h_mm", 0.0),
            "forecast_24h_mm":  fc.get("forecast_24h_mm", rain_24h),
            "forecast_48h_mm":  fc.get("forecast_48h_mm", 0.0),
            "forecast_72h_mm":  fc.get("forecast_72h_mm", rain_72h),
            # Alert engine compat (unchanged names)
            "rain_24h_mm":      rain_24h,
            "rain_72h_mm":      rain_72h,
            # Metadata
            "source":           fc["forecast_source"],
            "data_mode":        fc.get("data_mode", "forecast_only"),
            "fetched_at":       fc["fetched_at"],
        },
    }
