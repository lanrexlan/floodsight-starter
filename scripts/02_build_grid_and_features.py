"""
Mosaic downloaded raster tiles, reproject to the working CRS, build the
30m grid clipped to the pilot LGAs, compute terrain derivatives, and join
everything onto the grid. Produces data/processed/feature_grid.gpkg,
ready for scripts/03_compute_susceptibility.py.

Usage:
    python scripts/02_build_grid_and_features.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def mosaic_and_reproject(
    tile_paths: list[Path], out_path: Path, dst_crs: str, categorical: bool = False
) -> Path:
    """
    categorical: set True for classification rasters (e.g. land cover)
    so reprojection uses nearest-neighbor resampling instead of bilinear
    — bilinear would blend adjacent class codes into meaningless
    intermediate values (e.g. averaging class 50 and class 80 into a
    nonsense "65"). Continuous rasters (DEM, population) should use the
    default bilinear.
    """
    import numpy as np
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import calculate_default_transform, reproject, Resampling

    if not tile_paths:
        raise FileNotFoundError(
            "No source tiles given — run scripts/01_download_all.py first."
        )

    srcs = [rasterio.open(p) for p in tile_paths]
    mosaic, mosaic_transform = merge(srcs)
    src_crs = srcs[0].crs
    src_nodata = srcs[0].nodata
    for s in srcs:
        s.close()

    transform, width, height = calculate_default_transform(
        src_crs, dst_crs, mosaic.shape[2], mosaic.shape[1],
        *rasterio.transform.array_bounds(mosaic.shape[1], mosaic.shape[2], mosaic_transform),
    )

    dtype = mosaic.dtype
    # Prefer the source raster's own declared nodata (most correct — it's
    # whatever the publisher actually used). Fall back to a
    # dtype-appropriate sentinel only if the source didn't declare one,
    # since an out-of-range sentinel (e.g. -9999 on a uint8 raster) is a
    # hard crash, not just a wrong value.
    if src_nodata is not None:
        nodata = src_nodata
    elif np.issubdtype(dtype, np.unsignedinteger):
        nodata = 0
    else:
        nodata = -9999

    profile = {
        "driver": "GTiff", "height": height, "width": width, "count": 1,
        "dtype": dtype, "crs": dst_crs, "transform": transform, "nodata": nodata,
    }

    resampling = Resampling.nearest if categorical else Resampling.bilinear

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        reproject(
            source=mosaic[0], destination=rasterio.band(dst, 1),
            src_transform=mosaic_transform, src_crs=src_crs,
            src_nodata=src_nodata, dst_nodata=nodata,
            dst_transform=transform, dst_crs=dst_crs, resampling=resampling,
        )
    log.info("Saved mosaic+reprojected raster to %s (nodata=%s, resampling=%s)",
              out_path, nodata, resampling.name)
    return out_path


def main():
    from floodsight.config import AOI_LGAS, PROCESSED_DIR, RAW_DIR, WORKING_CRS
    from floodsight.download.boundaries import filter_pilot_lgas
    from floodsight.processing import features, grid, terrain

    boundaries_path = RAW_DIR / "boundaries" / "NGA_ADM2.geojson"
    clip_gdf = None
    if boundaries_path.exists():
        log.info("Clipping to pilot LGAs: %s", AOI_LGAS)
        clip_gdf = filter_pilot_lgas(boundaries_path)
    else:
        log.warning(
            "No ADM2 boundary file found at %s — building grid from the "
            "raw bbox instead of the precise LGA polygons. Run "
            "scripts/01_download_all.py first for a tighter AOI.",
            boundaries_path,
        )

    log.info("=== Mosaicking DEM tiles ===")
    dem_tiles = sorted((RAW_DIR / "dem").glob("*.tif"))
    dem_path = mosaic_and_reproject(dem_tiles, PROCESSED_DIR / "dem_mosaic.tif", WORKING_CRS)

    log.info("=== Mosaicking land cover tiles ===")
    lc_tiles = sorted((RAW_DIR / "landcover").glob("*.tif"))
    lc_path = mosaic_and_reproject(
        lc_tiles, PROCESSED_DIR / "landcover_mosaic.tif", WORKING_CRS, categorical=True
    )

    log.info("=== Reprojecting population raster ===")
    pop_tiles = sorted((RAW_DIR / "population").glob("*.tif"))
    pop_path = mosaic_and_reproject(
        pop_tiles, PROCESSED_DIR / "population_mosaic.tif", WORKING_CRS
    )

    log.info("=== Computing terrain derivatives (slope, flow accum, HAND) ===")
    terrain_outputs = terrain.save_terrain_rasters(dem_path, PROCESSED_DIR / "terrain")

    log.info("=== Building modelling grid ===")
    g = grid.build_fishnet_grid(clip_to=clip_gdf)

    log.info("=== Loading OSM water layer ===")
    import geopandas as gpd

    water_path = RAW_DIR / "osm" / "clipped" / "water.gpkg"
    if water_path.exists():
        water_gdf = gpd.read_file(water_path)
    else:
        log.warning(
            "No OSM water layer found at %s — distance-to-water will be "
            "wrong (all zero). Run scripts/01_download_all.py without "
            "--skip-osm first.",
            water_path,
        )
        water_gdf = gpd.GeoDataFrame(geometry=[], crs=WORKING_CRS)

    log.info("=== Joining features onto grid ===")
    feature_grid = features.build_feature_table(
        grid=g,
        dem_path=dem_path,
        slope_path=terrain_outputs["slope_deg"],
        flow_accum_path=terrain_outputs["flow_accum"],
        hand_path=terrain_outputs["hand_m"],
        landcover_path=lc_path,
        population_path=pop_path,
        water_gdf=water_gdf,
    )

    out_path = PROCESSED_DIR / "feature_grid.gpkg"
    feature_grid.to_file(out_path, driver="GPKG")
    log.info("Saved feature grid to %s (%d cells)", out_path, len(feature_grid))


if __name__ == "__main__":
    main()
