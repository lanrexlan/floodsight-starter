"""
Provides the grid the API serves from. If you've run the full processing
pipeline (scripts/02-04) and produced data/processed/scored_grid.gpkg,
that real data is served. Otherwise this falls back to an in-memory
synthetic demo grid covering the same AOI bbox, so `uvicorn api.main:app`
works immediately on a fresh checkout with zero setup — useful for
frontend/API development and for demoing the dashboard before the GIS
pipeline has been run on your machine.

The synthetic fallback is clearly flagged in every API response via the
`data_source` field — never silently confused with real model output.
"""

from __future__ import annotations

import json
import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from floodsight.config import AOI_BBOX, PROCESSED_DIR, WGS84, WORKING_CRS
from floodsight.processing.susceptibility import compute_flood_score

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SCORED_GRID_PATH = PROCESSED_DIR / "scored_grid.gpkg"

_cached_grid: gpd.GeoDataFrame | None = None
_cached_source: str | None = None

# GeoJSON cache — serialise the 54 k-cell grid to a Python dict exactly ONCE
# per process lifetime.  On Render's 512 MB free tier, serialising the grid
# on every /risk/grid or /forecast/alerts request causes an OOM 502 because
# each call peaks at ~350 MB (GeoDataFrame + WGS84 copy + JSON string + dict).
# Caching the final dict keeps persistent memory at ~300 MB (GDF + dict) and
# removes the per-request serialisation spike entirely.
_cached_grid_geojson: tuple[dict, str] | None = None


def _build_synthetic_demo_grid(n_cells_per_side: int = 35) -> gpd.GeoDataFrame:
    """A small synthetic grid with plausible-looking (but fake) terrain
    and population values, used only when no real processed grid exists
    on disk yet."""
    rng = np.random.default_rng(7)

    lon_min, lat_min, lon_max, lat_max = AOI_BBOX
    aoi = gpd.GeoDataFrame(geometry=[box(*AOI_BBOX)], crs=WGS84).to_crs(WORKING_CRS)
    minx, miny, maxx, maxy = aoi.total_bounds

    xs = np.linspace(minx, maxx, n_cells_per_side)
    ys = np.linspace(miny, maxy, n_cells_per_side)
    cell_w = (maxx - minx) / n_cells_per_side
    cell_h = (maxy - miny) / n_cells_per_side

    rows = []
    for x in xs:
        for y in ys:
            rows.append(
                {
                    "geometry": box(x, y, x + cell_w, y + cell_h),
                    "centroid_x": x + cell_w / 2,
                    "centroid_y": y + cell_h / 2,
                }
            )
    grid = gpd.GeoDataFrame(rows, crs=WORKING_CRS)
    grid["cell_id"] = grid.index.astype(str)

    # Fake a coastline gradient: cells with higher index (further from
    # bbox origin, roughly "inland") get higher elevation/lower risk, so
    # the demo grid at least *looks* like a coastal flood gradient.
    n = len(grid)
    norm_pos = (grid["centroid_x"] - minx) / (maxx - minx)
    grid["elevation_m"] = (norm_pos * 12 + rng.normal(0, 1.0, n)).clip(0, None)
    grid["slope_deg"] = rng.exponential(1.2, n).clip(0, 15)
    grid["flow_accum"] = rng.exponential(150, n)
    grid["hand_m"] = (grid["elevation_m"] * rng.uniform(0.2, 0.5, n)).clip(0, None)
    grid["dist_to_water_m"] = (norm_pos * 1500 + rng.exponential(150, n))
    grid["landcover_class"] = rng.choice([50, 50, 80, 90, 40], n)
    grid["population_density"] = rng.exponential(4000, n)

    grid = compute_flood_score(grid)
    return grid


def _tag_lga_names(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Spatial-join each grid cell to its LGA name using the downloaded ADM2
    boundary file.  Adds a `lga_name` column; silently skips if the boundary
    file isn't present (e.g. fresh checkout before scripts/01 has been run).
    Called once inside get_grid() so the result is cached with the grid.
    """
    from floodsight.config import RAW_DIR

    boundaries_path = RAW_DIR / "boundaries" / "NGA_ADM2.geojson"
    if not boundaries_path.exists():
        log.info("Boundary file not found — LGA names not tagged (run scripts/01 first)")
        return gdf
    try:
        boundaries = gpd.read_file(boundaries_path)
        name_col = next(
            (c for c in ("shapeName", "shapeName1", "NAME_2") if c in boundaries.columns),
            None,
        )
        if name_col is None:
            log.warning("No recognised name column in boundary file — skipping LGA tagging")
            return gdf

        from floodsight.config import AOI_LGAS

        mask = boundaries[name_col].str.contains("|".join(AOI_LGAS), case=False, na=False)
        boundaries = boundaries[mask][[name_col, "geometry"]]

        gdf_wgs84 = gdf.to_crs(WGS84)
        joined = gpd.sjoin(gdf_wgs84, boundaries, how="left", predicate="intersects")
        # sjoin may produce duplicate rows when a cell overlaps two LGAs — keep first hit
        joined = joined[~joined.index.duplicated(keep="first")]

        gdf = gdf.copy()
        gdf["lga_name"] = joined[name_col].values
        log.info(
            "Tagged %d/%d cells with LGA names",
            gdf["lga_name"].notna().sum(), len(gdf),
        )
    except Exception as exc:
        log.warning("LGA name tagging failed (%s) — proceeding without LGA names", exc)
    return gdf


def get_grid(force_reload: bool = False) -> tuple[gpd.GeoDataFrame, str]:
    global _cached_grid, _cached_source
    if _cached_grid is not None and not force_reload:
        return _cached_grid, _cached_source

    if SCORED_GRID_PATH.exists():
        log.info("Loading real processed grid from %s", SCORED_GRID_PATH)
        _cached_grid = gpd.read_file(SCORED_GRID_PATH)
        _cached_grid = _tag_lga_names(_cached_grid)
        _cached_source = "processed_pipeline"
    else:
        log.warning(
            "No processed grid found at %s — serving a SYNTHETIC demo grid. "
            "Run scripts/02-04 to generate real data.",
            SCORED_GRID_PATH,
        )
        _cached_grid = _build_synthetic_demo_grid()
        _cached_source = "synthetic_demo"

    return _cached_grid, _cached_source


def get_grid_geojson() -> tuple[dict, str]:
    """
    Returns (geojson_dict, source) for the pilot grid in WGS84.

    The result is cached after the first call so the expensive GeoDataFrame →
    GeoJSON serialisation only happens once per process lifetime.  Callers must
    treat the returned dict as **read-only** — it is a shared object and
    mutating it would corrupt the cache for subsequent requests.
    """
    global _cached_grid_geojson
    if _cached_grid_geojson is not None:
        return _cached_grid_geojson

    gdf, source = get_grid()
    log.info(
        "Serialising %d-cell grid to GeoJSON (one-time; cached for all future requests) …",
        len(gdf),
    )
    gdf_wgs84 = gdf.to_crs(WGS84)
    geojson = json.loads(gdf_wgs84.to_json())
    geojson["data_source"] = source
    _cached_grid_geojson = (geojson, source)
    log.info("Grid GeoJSON cached — %d features.", len(geojson.get("features", [])))
    return _cached_grid_geojson


def nearest_cell(lat: float, lon: float) -> pd.Series:
    grid, _ = get_grid()
    point = gpd.GeoSeries([gpd.points_from_xy([lon], [lat])[0]], crs=WGS84).to_crs(grid.crs)[0]
    idx = grid.geometry.distance(point).idxmin()
    return grid.loc[idx]
