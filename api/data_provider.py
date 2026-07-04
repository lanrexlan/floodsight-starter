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
import threading

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
_grid_lock = threading.Lock()  # guards get_grid_geojson() cache population


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

    with _grid_lock:
        # Double-checked locking: re-test after acquiring so the startup
        # warmup thread and a simultaneous first user request don't both
        # re-load the 9 MB GPKG.
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


STREETS_RISK_PATH = PROCESSED_DIR / "streets_risk.gpkg"
_cached_streets_geojson: tuple[dict, str] | None = None


def get_streets_geojson() -> tuple[dict | None, str]:
    """
    Returns (geojson_dict, source) for the tagged street network in WGS84.

    Returns (None, 'not_found') if streets_risk.gpkg hasn't been generated
    yet — the /risk/streets endpoint returns 404 in that case.

    Cached for the process lifetime (like get_grid_geojson).
    Run scripts/05_tag_street_risk.py to generate the file.
    """
    global _cached_streets_geojson
    if _cached_streets_geojson is not None:
        return _cached_streets_geojson

    if not STREETS_RISK_PATH.exists():
        log.info(
            "streets_risk.gpkg not found at %s — run scripts/05_tag_street_risk.py",
            STREETS_RISK_PATH,
        )
        return None, "not_found"

    log.info("Loading streets risk from %s …", STREETS_RISK_PATH)
    gdf = gpd.read_file(STREETS_RISK_PATH)
    # Script always saves in WGS84 — no reprojection needed here
    geojson = json.loads(gdf.to_json())
    geojson["data_source"] = "osm_risk_tagged"
    _cached_streets_geojson = (geojson, "osm_risk_tagged")
    log.info(
        "Streets GeoJSON cached — %d segments", len(geojson.get("features", []))
    )
    return _cached_streets_geojson


# Phase 18 Track 3: prefer the merged all-LGA file; fall back to legacy Kosofe-only file.
_SWMM_ALL_PATH     = PROCESSED_DIR / "swmm_flooding_all.geojson"    # merged (Track 3+)
_SWMM_LEGACY_PATH  = PROCESSED_DIR / "swmm_flooding.geojson"        # Kosofe-only (Phase 17)
_cached_swmm_geojson: dict | None = None


def get_swmm_flooding_geojson() -> dict | None:
    """
    Returns the SWMM flooded-junction GeoJSON dict, or None if no file exists.

    Priority:
      1. swmm_flooding_all.geojson   — merged Kosofe + Alimosho + Eti-Osa (Track 3)
      2. swmm_flooding.geojson       — legacy Kosofe-only file (Phase 17)

    Generate with:
      python scripts/07_parse_swmm_results.py --lga all
      python scripts/08_merge_swmm_results.py

    Cached for the process lifetime.
    """
    global _cached_swmm_geojson
    if _cached_swmm_geojson is not None:
        return _cached_swmm_geojson

    path = _SWMM_ALL_PATH if _SWMM_ALL_PATH.exists() else _SWMM_LEGACY_PATH

    if not path.exists():
        log.info(
            "No SWMM flooding GeoJSON found (checked %s and %s). "
            "Run scripts/07_parse_swmm_results.py --lga all, then "
            "scripts/08_merge_swmm_results.py",
            _SWMM_ALL_PATH, _SWMM_LEGACY_PATH,
        )
        return None

    log.info("Loading SWMM flooding GeoJSON from %s ...", path)
    with open(path, encoding="utf-8") as fh:
        geojson = json.load(fh)
    _cached_swmm_geojson = geojson
    log.info(
        "SWMM GeoJSON cached — %d flooded nodes (source: %s)",
        len(geojson.get("features", [])), path.name,
    )
    return _cached_swmm_geojson


def nearest_cell(lat: float, lon: float) -> pd.Series:
    grid, _ = get_grid()
    point = gpd.GeoSeries([gpd.points_from_xy([lon], [lat])[0]], crs=WGS84).to_crs(grid.crs)[0]
    idx = grid.geometry.distance(point).idxmin()
    return grid.loc[idx]

