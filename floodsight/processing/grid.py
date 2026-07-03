"""
Build the 30m modelling grid clipped to the AOI, matching the original
README workflow step 5 ("Create a 30m modelling grid").

Requires: pip install geopandas shapely
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from floodsight.config import AOI_BBOX, GRID_RESOLUTION_M, PROCESSED_DIR, WGS84, WORKING_CRS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def build_fishnet_grid(
    bbox_wgs84: tuple[float, float, float, float] = AOI_BBOX,
    resolution_m: int = GRID_RESOLUTION_M,
    clip_to: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """
    Build a square fishnet grid at `resolution_m` covering bbox_wgs84,
    in the project's working (metric) CRS. If `clip_to` is given (e.g.
    the dissolved pilot-LGA boundary from boundaries.py), the grid is
    clipped to that polygon so cells aren't generated over open ocean
    or outside the pilot area.
    """
    aoi_gdf = gpd.GeoDataFrame(geometry=[box(*bbox_wgs84)], crs=WGS84).to_crs(WORKING_CRS)
    minx, miny, maxx, maxy = aoi_gdf.total_bounds

    xs = np.arange(minx, maxx, resolution_m)
    ys = np.arange(miny, maxy, resolution_m)

    cells = []
    for x in xs:
        for y in ys:
            cells.append(box(x, y, x + resolution_m, y + resolution_m))

    grid = gpd.GeoDataFrame(geometry=cells, crs=WORKING_CRS)
    grid["cell_id"] = grid.index.astype(str)
    grid["centroid_x"] = grid.geometry.centroid.x
    grid["centroid_y"] = grid.geometry.centroid.y

    log.info("Built fishnet grid with %d cells at %dm resolution", len(grid), resolution_m)

    if clip_to is not None:
        clip_to = clip_to.to_crs(WORKING_CRS)
        grid = gpd.overlay(grid, clip_to[["geometry"]], how="intersection")
        log.info("Clipped grid to AOI polygon: %d cells remain", len(grid))

    return grid


def save_grid(grid: gpd.GeoDataFrame, name: str = "modelling_grid") -> None:
    out_path = PROCESSED_DIR / f"{name}.gpkg"
    grid.to_file(out_path, driver="GPKG")
    log.info("Saved grid to %s", out_path)


if __name__ == "__main__":
    grid = build_fishnet_grid()
    save_grid(grid)
