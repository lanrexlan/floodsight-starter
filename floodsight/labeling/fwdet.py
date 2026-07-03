"""
Estimate floodwater depth from a flood-extent mask + DEM, to turn the
Sentinel-1 extent polygons from sar_extent.py into actual depth labels
for ML training (ROADMAP.md Phase 4).

This is a from-scratch reimplementation of the core FwDET v2 algorithm
(Cohen et al. 2019, "The Floodwater Depth Estimation Tool (FwDET v2.0) for
improved remote sensing analysis of coastal flooding", NHESS 19:2053-2065,
https://doi.org/10.5194/nhess-19-2053-2019). The original reference
implementation (ArcGIS/GEE/QGIS toolboxes) lives at:
  https://github.com/csdms-contrib/fwdet

Algorithm (FwDET v2 boundary method):
  1. Identify the boundary cells of the flood extent polygon (cells
     adjacent to non-flooded cells).
  2. For each flooded cell, find its nearest boundary cell(s) and take
     the DEM elevation at that boundary as the estimated water surface
     elevation at that location.
  3. depth = water_surface_elevation - ground_elevation, clipped to >= 0.
  4. Optionally smooth with a focal mean to reduce boundary-cell noise
     (FwDET v2.1).

This gives a defensible depth label per flooded grid cell using only the
extent mask and a DEM — no streamflow data needed — which is exactly
what you need to label historical events where you only have a flood
extent (from SAR) and elevation, not a hydraulic model run.

Usage:
    python -m floodsight.labeling.fwdet --extent path/to/flood_extent.tif --dem path/to/dem.tif
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from scipy import ndimage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def estimate_depth(
    flood_mask: np.ndarray, dem: np.ndarray, smooth_iterations: int = 1
) -> np.ndarray:
    """
    flood_mask: 2D boolean array, True where flooded (from sar_extent.py).
    dem: 2D float array, same shape/grid as flood_mask, elevation in
    meters. May contain NaN for nodata/invalid cells (e.g. padding
    outside a reprojected DEM's valid footprint) — these are excluded
    both from depth output (a flooded cell with no real elevation can't
    get a meaningful depth) and, critically, from being used as a
    boundary reference elevation for OTHER cells. Without that second
    exclusion, a nodata sentinel (e.g. -9999) gets used as if it were a
    real "water surface" elevation, producing depths off by thousands of
    meters wherever the flood extent happens to touch invalid DEM
    padding — which is exactly what happened the first time this ran
    against real Lagos data (DEM mosaic covers a full 1-degree tile, far
    larger than the AOI, with -9999 padding outside its reprojected
    footprint; the Sentinel-1 extent, from a ~250km satellite swath, is
    larger still and overlapped that padding).
    Returns: 2D float array of estimated depth in meters (0 where not
    flooded or where DEM is invalid).
    """
    if flood_mask.shape != dem.shape:
        raise ValueError("flood_mask and dem must share the same grid shape")

    valid_dem = ~np.isnan(dem)
    if not valid_dem.any():
        log.warning("DEM is entirely NaN/nodata — cannot estimate any depth.")
        return np.zeros_like(dem, dtype=float)

    # Boundary cells: flooded cells with at least one non-flooded
    # neighbor, AND a real (non-nodata) DEM value — a boundary cell with
    # invalid elevation can't be trusted as anyone's water surface.
    eroded = ndimage.binary_erosion(flood_mask, structure=np.ones((3, 3)))
    boundary = flood_mask & ~eroded & valid_dem

    if not boundary.any():
        log.warning(
            "No flood-boundary cells have valid DEM data — cannot "
            "estimate depth for this extent/DEM pair (likely means the "
            "flood extent's footprint mostly falls outside the DEM's "
            "valid coverage). Returning all zeros rather than a "
            "fabricated number."
        )
        return np.zeros_like(dem, dtype=float)

    boundary_elev = np.where(boundary, dem, np.nan)

    # Distance-transform-based nearest-boundary assignment: for every
    # flooded cell, find the (row, col) of its nearest valid boundary
    # cell and use that cell's DEM value as the local water surface
    # elevation.
    not_boundary = ~boundary
    _, (nearest_rows, nearest_cols) = ndimage.distance_transform_edt(
        not_boundary, return_indices=True
    )
    water_surface = boundary_elev[nearest_rows, nearest_cols]

    valid_output = flood_mask & valid_dem
    depth = np.where(valid_output, water_surface - dem, 0.0)
    depth = np.clip(depth, 0, None)
    depth = np.nan_to_num(depth, nan=0.0)

    n_excluded = int((flood_mask & ~valid_dem).sum())
    if n_excluded:
        log.warning(
            "%d flooded cells had invalid/nodata DEM and were excluded "
            "from depth output (set to 0, not a real zero-depth claim — "
            "just 'unknown').",
            n_excluded,
        )

    for _ in range(smooth_iterations):
        smoothed = ndimage.uniform_filter(depth, size=3)
        depth = np.where(valid_output, smoothed, 0.0)

    return depth


def estimate_depth_from_files(extent_path: Path, dem_path: Path, out_path: Path) -> Path:
    """Convenience wrapper that reads an extent raster and a DEM, aligns
    the extent onto the DEM's exact grid if they differ (near-universal
    in practice — the Sentinel-1 extent from sar_extent.py is ~10-20m
    resolution and may be in a different UTM zone/CRS than your DEM
    mosaic's working CRS), and writes a depth GeoTIFF.
    Requires: pip install rasterio"""
    import numpy as np
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    with rasterio.open(dem_path) as src_dem:
        dem = src_dem.read(1).astype(float)
        if src_dem.nodata is not None:
            dem = np.where(dem == src_dem.nodata, np.nan, dem)
        dem_profile = src_dem.profile
        dem_crs = src_dem.crs
        dem_transform = src_dem.transform
        dem_shape = (src_dem.height, src_dem.width)

    with rasterio.open(extent_path) as src_ext:
        if src_ext.crs == dem_crs and src_ext.transform == dem_transform and \
           (src_ext.height, src_ext.width) == dem_shape:
            flood_mask = src_ext.read(1).astype(bool)
        else:
            log.info(
                "Extent raster grid (%s, %dx%d) differs from DEM grid "
                "(%s, %dx%d) — reprojecting extent onto the DEM's exact "
                "grid with nearest-neighbor resampling (categorical "
                "0/1 data, same reasoning as the land cover resampling "
                "fix earlier in this project: never bilinear-interpolate "
                "a category).",
                src_ext.crs, src_ext.width, src_ext.height,
                dem_crs, dem_shape[1], dem_shape[0],
            )
            ext_raw = src_ext.read(1)
            aligned = np.zeros(dem_shape, dtype=ext_raw.dtype)
            reproject(
                source=ext_raw,
                destination=aligned,
                src_transform=src_ext.transform,
                src_crs=src_ext.crs,
                dst_transform=dem_transform,
                dst_crs=dem_crs,
                dst_resolution=(dem_transform.a, -dem_transform.e),
                resampling=Resampling.nearest,
            )
            flood_mask = aligned.astype(bool)

    n_flooded = int(flood_mask.sum())
    log.info("Flood mask covers %d of %d DEM cells after alignment", n_flooded, flood_mask.size)
    if n_flooded == 0:
        log.warning(
            "Zero flooded cells after alignment — this usually means the "
            "extent raster's actual coverage doesn't overlap the DEM's "
            "AOI at all (check the bounding boxes), not that the event "
            "produced no detectable water. Verify before trusting an "
            "all-zero depth result."
        )

    depth = estimate_depth(flood_mask, dem)

    out_profile = dem_profile.copy()
    out_profile.update(dtype="float32", count=1, nodata=0)
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(depth.astype("float32"), 1)

    log.info("Saved depth raster to %s (max depth %.2fm)", out_path, float(depth.max()))
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--extent", required=True, type=Path)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("depth_estimate.tif"))
    args = parser.parse_args()
    estimate_depth_from_files(args.extent, args.dem, args.out)
