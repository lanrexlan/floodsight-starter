"""
Sample all raster/vector layers onto the modelling grid's cell centroids,
matching README workflow steps 7-9 ("Extract OSM features", "Create
distance-to-water raster", "Add raster and vector values to each grid
cell").

Requires: pip install geopandas rasterio shapely
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import Point

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def sample_raster_at_points(raster_path, points_gdf: gpd.GeoDataFrame, band: int = 1) -> np.ndarray:
    """Sample a single-band raster at each point in points_gdf (must be in
    the raster's CRS already — reproject points_gdf.to_crs(raster_crs)
    before calling if needed)."""
    with rasterio.open(raster_path) as src:
        if points_gdf.crs != src.crs:
            points_gdf = points_gdf.to_crs(src.crs)
        coords = [(geom.x, geom.y) for geom in points_gdf.geometry]
        values = np.array([v[band - 1] for v in src.sample(coords)], dtype=float)
        nodata = src.nodata
        if nodata is not None:
            values = np.where(values == nodata, np.nan, values)
    return values


def compute_distance_to_water(
    grid_centroids: gpd.GeoDataFrame, water_gdf: gpd.GeoDataFrame
) -> np.ndarray:
    """Euclidean distance (meters) from each grid centroid to the nearest
    water feature, in the working metric CRS. For large datasets, build a
    spatial index first (GeoPandas does this automatically via STRtree on
    .distance() in recent versions, but for big AOIs consider sjoin_nearest
    instead of a full distance matrix).

    If water_gdf is empty (e.g. you haven't run the OSM download yet),
    this returns NaN for every cell rather than crashing — NaN is a
    clearer "not computed" signal than a fabricated distance, and
    susceptibility.py's normalization will need real values here before
    risk_waterdist means anything. Run floodsight/download/osm.py and
    rerun this step once you have it."""
    if water_gdf.empty:
        log.warning(
            "water_gdf is empty — dist_to_water_m will be NaN for every "
            "cell. Run `python -m floodsight.download.osm` (or the helper "
            "in scripts/01_download_all.py) for a real water layer, then "
            "rerun feature building."
        )
        return np.full(len(grid_centroids), np.nan)

    if water_gdf.crs != grid_centroids.crs:
        water_gdf = water_gdf.to_crs(grid_centroids.crs)
    water_union = water_gdf.geometry.unary_union
    return grid_centroids.geometry.apply(lambda pt: pt.distance(water_union)).to_numpy()


def build_feature_table(
    grid: gpd.GeoDataFrame,
    dem_path,
    slope_path,
    flow_accum_path,
    hand_path,
    landcover_path,
    population_path,
    water_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Join every static layer onto the grid centroids and return an
    enriched copy of `grid` ready for processing/susceptibility.py."""
    centroids = grid.copy()
    centroids["geometry"] = centroids.geometry.centroid

    df = grid.copy()
    df["elevation_m"] = sample_raster_at_points(dem_path, centroids)
    df["slope_deg"] = sample_raster_at_points(slope_path, centroids)
    df["flow_accum"] = sample_raster_at_points(flow_accum_path, centroids)
    df["hand_m"] = sample_raster_at_points(hand_path, centroids)
    df["landcover_class"] = sample_raster_at_points(landcover_path, centroids)
    df["population_density"] = sample_raster_at_points(population_path, centroids)
    # WorldPop's nodata is mostly open water (lagoon/creek/sea) — "zero
    # people live in the water" is a real, correct value, not a gap the
    # way a missing DEM/HAND cell is. Filling with 0 here (rather than
    # leaving NaN, which would make the cell drop out of scoring
    # entirely) is a deliberate semantic choice, not a generic NaN patch
    # — don't copy this pattern onto elevation_m/slope_deg/flow_accum/
    # hand_m, where NaN genuinely does mean "unknown."
    df["population_density"] = df["population_density"].fillna(0)
    df["dist_to_water_m"] = compute_distance_to_water(centroids, water_gdf)

    n_missing = df[["elevation_m", "slope_deg", "flow_accum", "hand_m"]].isna().any(axis=1).sum()
    if n_missing:
        log.warning(
            "%d of %d grid cells have at least one missing raster value "
            "(likely outside raster coverage) — drop or fill these before "
            "scoring.",
            n_missing,
            len(df),
        )

    return df
