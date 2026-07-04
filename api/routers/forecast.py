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
    lat: float = Query(PILOT_LAT, description="Latitude  for forecast lookup (informational; spatial grid covers full AOI)"),
    lon: float = Query(PILOT_LON, description="Longitude for forecast lookup (informational; spatial grid covers full AOI)"),
):
    """
    Returns a **compact** alert payload — no geometry, just one alert-level
    string per grid cell in the same order as ``/risk/grid`` features.

    Phase 14: Per-cell spatial rainfall.
    Each cell's alert level is computed from its own rainfall value
    (nearest GFS grid point, 0.25° / ~28 km) rather than a single
    city-centre point.  IMERG satellite data (0.1° / ~11 km) replaces
    the GFS-observed component when available.

    Response shape::

        {
          "alert_levels":  ["No Alert", "Watch", "Warning", ...],
          "alert_counts":  {"Warning": 1234, "Watch": 5678, "No Alert": 46163},
          "highest_alert": "Warning",
          "lga_alerts":    {"Kosofe": 980, "Alimosho": 710, ...},
          "total_cells":   24933,
          "spatial_mode":  "imerg+gfs" | "gfs_9point",
          "forecast": { ...city-centre summary for the status card... }
        }
    """
    from floodsight.alerts.engine import compute_alert_level
    from floodsight.forecast.rainfall_grid import (
        fetch_rainfall_grid,
        get_centre_forecast,
        interpolate_to_cells,
        _try_imerg_observed,
    )

    # 1. Fetch spatial rainfall grid (9 points in parallel, 30-min cache)
    try:
        rainfall_grid = fetch_rainfall_grid()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 2. Try IMERG for higher-accuracy observed component (silent fallback)
    imerg_obs, imerg_source = _try_imerg_observed()
    if imerg_obs:
        # e.g. "IMERG_early+gfs" or "IMERG_late+gfs"
        spatial_mode = f"{imerg_source}+gfs"
    else:
        spatial_mode = "gfs_9point"

    # 3. Interpolate per-cell rainfall
    gdf, _ = get_grid()
    cell_rain = interpolate_to_cells(gdf, rainfall_grid, imerg_obs, imerg_source)

    # 4. Coastal/tidal signal — fetch early so it can upgrade coastal-LGA cells.
    # NOTE: COASTAL_ADVISORY_M = 1.0 m MSL is a placeholder; calibrate against
    # NiHSA tide gauge records + lekki_2021_07_12 before treating as operational.
    from floodsight.forecast.marine import try_coastal_summary
    from floodsight.forecast.dam import try_dam_summary
    coastal = try_coastal_summary()
    dam     = try_dam_summary()
    _COASTAL_LGAS    = {"Eti-Osa", "Lagos Island", "Apapa", "Amuwo-Odofin", "Lagos Mainland"}
    _COASTAL_UPGRADE = {"No Alert": "Watch", "Watch": "Warning", "Warning": "Warning"}
    # Ogun river floodplain LGAs — promoted when dam discharge advisory is active.
    # Agege/Ifako-Ijaiye sit astride the Ogun lower reaches; Alimosho (Agbado
    # Creek) is the main inland overflow corridor.  Same one-tier upgrade logic
    # as the coastal signal — Watch→Warning if already Watch, else Watch.
    _OGUN_LGAS       = {"Agege", "Ifako-Ijaiye", "Alimosho"}
    _DAM_UPGRADE     = {"No Alert": "Watch", "Watch": "Warning", "Warning": "Warning"}
    has_lga = "lga_name" in gdf.columns
    _coastal_active  = bool(coastal and coastal.get("advisory") and has_lga)
    _dam_active      = bool(dam     and dam.get("advisory")     and has_lga)

    # 5. Compute per-cell alert levels (coastal/dam LGA cells promoted when advisory)
    alert_levels = []
    for i, (rc, r24, r72) in enumerate(zip(
        gdf["risk_class"],
        cell_rain["rain_24h_mm"],
        cell_rain["rain_72h_mm"],
    )):
        level = compute_alert_level(rc, r24, r72)
        lga   = str(gdf["lga_name"].iloc[i]) if has_lga else ""
        if _coastal_active and lga in _COASTAL_LGAS:
            level = _COASTAL_UPGRADE.get(level, level)
        if _dam_active and lga in _OGUN_LGAS:
            level = _DAM_UPGRADE.get(level, level)
        alert_levels.append(level)

    # 6. Count levels + per-LGA breakdown
    counts: dict[str, int] = {"Warning": 0, "Watch": 0, "No Alert": 0}
    lga_alerts: dict[str, int] = {}

    for i, level in enumerate(alert_levels):
        counts[level] = counts.get(level, 0) + 1
        if has_lga and level in ("Warning", "Watch"):
            lga = gdf["lga_name"].iloc[i]
            if lga and str(lga) != "nan":
                lga_alerts[lga] = lga_alerts.get(lga, 0) + 1

    lga_alerts = dict(
        sorted(lga_alerts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    )

    highest = (
        "Warning" if counts["Warning"] > 0
        else "Watch" if counts["Watch"] > 0
        else "No Alert"
    )

    # 7. City-centre forecast for the status card (backward-compatible)
    cfc = get_centre_forecast(rainfall_grid)

    return {
        "alert_levels":   alert_levels,
        "coastal":        coastal,
        "dam":            dam,
        "alert_counts":   counts,
        "highest_alert":  highest,
        "lga_alerts":     lga_alerts,
        "total_cells":    len(gdf),
        "spatial_mode":   spatial_mode,
        "observed_source": imerg_source or "GFS",
        "forecast": {
            "observed_24h_mm":  cfc.get("observed_24h_mm", 0.0),
            "forecast_24h_mm":  cfc.get("forecast_24h_mm", cfc["rain_24h_mm"]),
            "forecast_48h_mm":  cfc.get("forecast_48h_mm", 0.0),
            "forecast_72h_mm":  cfc.get("forecast_72h_mm", cfc["rain_72h_mm"]),
            "rain_24h_mm":      cfc["rain_24h_mm"],
            "rain_72h_mm":      cfc["rain_72h_mm"],
            "source":           cfc["forecast_source"],
            "data_mode":        cfc.get("data_mode", "observed+forecast"),
            "fetched_at":       cfc["fetched_at"],
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
    from floodsight.alerts.engine import compute_alert_level
    from floodsight.forecast.rainfall_grid import (
        fetch_rainfall_grid,
        get_centre_forecast,
        interpolate_to_cells,
        _try_imerg_observed,
    )

    # 1. Spatial rainfall grid (same logic as /forecast/alerts)
    try:
        rainfall_grid = fetch_rainfall_grid()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    imerg_obs, imerg_source = _try_imerg_observed()
    gdf, _ = get_grid()
    cell_rain = interpolate_to_cells(gdf, rainfall_grid, imerg_obs, imerg_source)

    # 2. Coastal signal — fetched early so it can upgrade coastal-LGA cells.
    from floodsight.forecast.marine import try_coastal_summary
    from floodsight.forecast.dam import try_dam_summary
    coastal = try_coastal_summary()
    dam     = try_dam_summary()
    _COASTAL_LGAS    = {"Eti-Osa", "Lagos Island", "Apapa", "Amuwo-Odofin", "Lagos Mainland"}
    _COASTAL_UPGRADE = {"No Alert": "Watch", "Watch": "Warning", "Warning": "Warning"}
    _OGUN_LGAS       = {"Agege", "Ifako-Ijaiye", "Alimosho"}
    _DAM_UPGRADE     = {"No Alert": "Watch", "Watch": "Warning", "Warning": "Warning"}
    has_lga          = "lga_name" in gdf.columns
    _coastal_active  = bool(coastal and coastal.get("advisory") and has_lga)
    _dam_active      = bool(dam     and dam.get("advisory")     and has_lga)

    # 3. Count alert levels (coastal/dam LGA cells promoted when advisory)
    counts: dict = {"Warning": 0, "Watch": 0, "No Alert": 0}
    for i, (rc, r24, r72) in enumerate(zip(
        gdf["risk_class"],
        cell_rain["rain_24h_mm"],
        cell_rain["rain_72h_mm"],
    )):
        level = compute_alert_level(rc, r24, r72)
        lga   = str(gdf["lga_name"].iloc[i]) if has_lga else ""
        if _coastal_active and lga in _COASTAL_LGAS:
            level = _COASTAL_UPGRADE.get(level, level)
        if _dam_active and lga in _OGUN_LGAS:
            level = _DAM_UPGRADE.get(level, level)
        counts[level] = counts.get(level, 0) + 1

    highest = (
        "Warning" if counts.get("Warning", 0) > 0
        else "Watch" if counts.get("Watch", 0) > 0
        else "No Alert"
    )

    cfc = get_centre_forecast(rainfall_grid)

    return {
        "total_cells":    len(gdf),
        "alert_counts":   counts,
        "highest_alert":  highest,
        "coastal":        coastal,
        "dam":            dam,
        "observed_source": imerg_source or "GFS",
        "forecast": {
            "observed_24h_mm":  cfc.get("observed_24h_mm", 0.0),
            "forecast_24h_mm":  cfc.get("forecast_24h_mm", cfc["rain_24h_mm"]),
            "forecast_48h_mm":  cfc.get("forecast_48h_mm", 0.0),
            "forecast_72h_mm":  cfc.get("forecast_72h_mm", cfc["rain_72h_mm"]),
            "rain_24h_mm":      cfc["rain_24h_mm"],
            "rain_72h_mm":      cfc["rain_72h_mm"],
            "source":           cfc["forecast_source"],
            "data_mode":        cfc.get("data_mode", "observed+forecast"),
            "fetched_at":       cfc["fetched_at"],
        },
    }
