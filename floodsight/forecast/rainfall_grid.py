"""
Phase 14: Spatial rainfall grid — per-cell observed + forecast rainfall.

Instead of applying a single city-centre forecast to all 24,933 grid cells,
this module fetches GFS data at a 3×3 grid of points across the Lagos AOI
and optionally layers IMERG satellite observed rainfall on top.

Architecture
------------
             ┌──────────────────────┐   ┌───────────────────────┐
observed_24h │  GPM IMERG  (0.1°)   │ or│  GFS analysis (0.25°) │  ← fallback
             └──────────────────────┘   └───────────────────────┘
                                │
forecast_24/72h   GFS (0.25°, 9-point grid across AOI)
                                │
                                ▼
              nearest-neighbour interpolation → each cell centroid
                                │
                                ▼
              per-cell { rain_24h_mm, rain_72h_mm }

Why nearest-neighbour
---------------------
GFS cells are ~28 km wide — larger than most Lagos LGAs.  Smooth
interpolation (IDW, kriging) would imply sub-model-resolution accuracy
that the source data does not support.  Nearest-neighbour is fast,
deterministic, and matches the native Voronoi structure of GFS tiles.

Caching
-------
Each GRID_POINT result is cached independently inside openmeteo.py for
30 minutes.  All 9 points are fetched in parallel so wall-time on a cold
cache is ~1 s rather than ~9 s.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd

log = logging.getLogger(__name__)

# 3×3 strategic points covering the Lagos AOI
# (lon 3.00–3.80 E, lat 6.30–6.80 N, spacing ≈ 0.30°)
# Row order: south → north; column order: west → east.
GRID_POINTS: list[tuple[float, float]] = [
    (6.35, 3.10), (6.35, 3.40), (6.35, 3.70),   # south: Amuwo-Odofin / Lagos Island / Eti-Osa
    (6.55, 3.10), (6.55, 3.40), (6.55, 3.70),   # middle: Alimosho / Ikeja / Kosofe
    (6.75, 3.10), (6.75, 3.40), (6.75, 3.70),   # north: Ifako-Ijaiye / Agege / Ikorodu
]

# Centre point used as the city-level summary for the status card
_CENTRE_POINT = (6.55, 3.40)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_rainfall_grid() -> dict[tuple[float, float], dict]:
    """
    Fetch GFS observed + forecast at all 9 GRID_POINTS in parallel.

    Returns
    -------
    dict mapping (lat, lon) → forecast dict (same shape as
    openmeteo.fetch_forecast output).  Partial results are returned on
    individual point failures.  Raises RuntimeError only if every point fails.
    """
    from floodsight.forecast.openmeteo import fetch_forecast

    results: dict[tuple[float, float], dict] = {}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=len(GRID_POINTS)) as pool:
        future_to_key = {
            pool.submit(fetch_forecast, lat, lon): (lat, lon)
            for lat, lon in GRID_POINTS
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                log.warning("Rainfall grid point %s failed: %s", key, exc)

    if not results:
        raise RuntimeError(
            f"All {len(GRID_POINTS)} rainfall grid points failed: {'; '.join(errors)}"
        )
    if errors:
        log.warning(
            "Rainfall grid: %d/%d points OK, %d failed",
            len(results), len(GRID_POINTS), len(errors),
        )
    return results


def _try_imerg_observed() -> dict[tuple[float, float], float] | None:
    """
    Attempt to fetch IMERG Late Run daily observed rainfall.
    Returns {(lat, lon): mm} at 0.1° resolution, or None on any failure.
    Failures are always silent — callers fall back to GFS observed data.
    """
    try:
        from floodsight.forecast.imerg import fetch_imerg_daily
        return fetch_imerg_daily()
    except Exception as exc:
        log.debug("IMERG overlay skipped: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

def interpolate_to_cells(
    gdf: "gpd.GeoDataFrame",
    rainfall_grid: dict[tuple[float, float], dict] | None = None,
    imerg_observed: dict[tuple[float, float], float] | None = None,
) -> "pd.DataFrame":
    """
    Nearest-neighbour interpolation from rainfall grid points to every
    grid cell centroid.

    Parameters
    ----------
    gdf :
        Scored grid GeoDataFrame (any CRS — re-projected to WGS84 internally).
    rainfall_grid :
        Output of fetch_rainfall_grid(). Fetched automatically if None.
    imerg_observed :
        Optional IMERG observed rainfall at 0.1° from _try_imerg_observed().
        When present, replaces the GFS-derived observed_24h_mm for each cell,
        giving higher-accuracy combined 72h risk.

    Returns
    -------
    pd.DataFrame with one row per gdf cell:
        rain_24h_mm, rain_72h_mm, observed_24h_mm,
        forecast_24h_mm, forecast_48h_mm, source_lat, source_lon
    """
    from scipy.spatial import cKDTree
    import pandas as pd
    from floodsight.config import WGS84

    if rainfall_grid is None:
        rainfall_grid = fetch_rainfall_grid()

    # Project cells to WGS84 and extract centroids (lat, lon)
    gdf_wgs = gdf.to_crs(WGS84)
    centroids = gdf_wgs.geometry.centroid
    cell_lats = centroids.y.values
    cell_lons = centroids.x.values
    cell_coords = np.column_stack([cell_lats, cell_lons])

    # --- GFS nearest-neighbour (forecast + fallback observed) ---
    gfs_keys = list(rainfall_grid.keys())
    gfs_arr  = np.array(gfs_keys)            # shape (N, 2): [[lat, lon], ...]
    gfs_tree = cKDTree(gfs_arr)
    _, gfs_idx = gfs_tree.query(cell_coords, k=1)

    # --- IMERG nearest-neighbour (observed only, optional) ---
    imerg_nn = None
    imerg_vals = None
    if imerg_observed:
        imerg_keys = list(imerg_observed.keys())
        imerg_arr  = np.array(imerg_keys)
        imerg_tree = cKDTree(imerg_arr)
        _, imerg_idx = imerg_tree.query(cell_coords, k=1)
        imerg_vals_arr = np.array([imerg_observed[k] for k in imerg_keys])
        imerg_nn   = imerg_idx
        imerg_vals = imerg_vals_arr

    rows = []
    for i in range(len(gdf)):
        gfs_key = gfs_keys[gfs_idx[i]]
        fc = rainfall_grid[gfs_key]

        gfs_obs = fc.get("observed_24h_mm", 0.0)
        fc24    = fc.get("forecast_24h_mm", fc["rain_24h_mm"])
        fc48    = fc.get("forecast_48h_mm", 0.0)

        # IMERG observed replaces GFS observed when available
        obs24 = (
            float(imerg_vals[imerg_nn[i]])
            if imerg_nn is not None and imerg_vals is not None
            else gfs_obs
        )

        rows.append({
            "rain_24h_mm":      round(fc24, 1),          # what's COMING (alert signal)
            "rain_72h_mm":      round(obs24 + fc48, 1),  # combined 72h risk window
            "observed_24h_mm":  round(obs24, 1),
            "forecast_24h_mm":  round(fc24, 1),
            "forecast_48h_mm":  round(fc48, 1),
            "source_lat":       gfs_key[0],
            "source_lon":       gfs_key[1],
        })

    df = pd.DataFrame(rows, index=gdf.index)
    obs_source = "IMERG" if imerg_nn is not None else "GFS"
    log.info(
        "Spatial rainfall (%s obs): %d cells | r24 %.1f–%.1f mm | r72 %.1f–%.1f mm",
        obs_source, len(df),
        df["rain_24h_mm"].min(), df["rain_24h_mm"].max(),
        df["rain_72h_mm"].min(), df["rain_72h_mm"].max(),
    )
    return df


def get_centre_forecast(
    rainfall_grid: dict[tuple[float, float], dict],
) -> dict:
    """
    Return the city-centre (Ikeja-area) point forecast for the status card.
    Falls back to any available point if the centre point failed.
    """
    return rainfall_grid.get(_CENTRE_POINT) or next(iter(rainfall_grid.values()))
