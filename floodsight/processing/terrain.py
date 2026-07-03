"""
Derive terrain features from the DEM: slope, flow accumulation, and HAND
(Height Above Nearest Drainage) — matching README workflow step 6, and
providing the HAND layer that depth_hand.py needs for Phase 1 of the
roadmap (physically-based flood depth without a trained ML model).

Requires: pip install pysheds rasterio numpy
pysheds docs: https://mattbartos.com/pysheds/
(pysheds' API has shifted across versions — if compute_hand signature
below doesn't match your installed version, check
`help(pysheds.grid.Grid.compute_hand)` for your version.)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def compute_slope_degrees(dem: np.ndarray, cell_size_m: float) -> np.ndarray:
    """Slope in degrees from a DEM array, using a simple finite-difference
    gradient. For production accuracy on irregular grids, prefer
    richdem.TerrainAttribute(dem, attrib='slope_degrees') instead — this
    numpy version has no extra dependency and is fine for a 30m regular grid."""
    gy, gx = np.gradient(dem, cell_size_m)
    slope_rad = np.arctan(np.hypot(gx, gy))
    return np.degrees(slope_rad)


def compute_flow_accumulation_and_hand(
    dem_path: Path,
    drainage_threshold_cells: int = 500,
):
    """
    Returns (flow_dir, flow_accumulation, hand) as numpy arrays aligned to
    the input DEM grid.

    drainage_threshold_cells: number of upstream cells above which a cell
    is treated as part of the drainage network for HAND computation.
    Tune this against a visual check (the resulting "streams" should
    roughly match OSM water features / visible drainage in the AOI) —
    there's no universal correct value, it depends on DEM resolution and
    local relief.
    """
    from pysheds.grid import Grid

    grid = Grid.from_raster(str(dem_path))
    dem = grid.read_raster(str(dem_path))

    log.info("Conditioning DEM (fill pits, fill depressions, resolve flats)")
    pit_filled = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit_filled)
    conditioned = grid.resolve_flats(flooded)

    log.info("Computing D8 flow direction and accumulation")
    fdir = grid.flowdir(conditioned)
    acc = grid.accumulation(fdir)

    log.info("Computing HAND with drainage threshold = %d cells", drainage_threshold_cells)
    drainage_mask = acc > drainage_threshold_cells
    hand = grid.compute_hand(fdir, conditioned, drainage_mask)

    return np.asarray(fdir), np.asarray(acc), np.asarray(hand)


def save_terrain_rasters(dem_path: Path, out_dir: Path) -> dict[str, Path]:
    """Run the full terrain derivative pipeline and write each layer as a
    GeoTIFF aligned to the input DEM."""
    import rasterio

    out_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        profile = src.profile
        cell_size_m = abs(src.transform.a)

    slope = compute_slope_degrees(dem, cell_size_m)
    fdir, acc, hand = compute_flow_accumulation_and_hand(dem_path)

    outputs = {}
    for name, arr in [("slope_deg", slope), ("flow_accum", acc), ("hand_m", hand)]:
        out_path = out_dir / f"{name}.tif"
        profile.update(dtype="float32", count=1, nodata=-9999)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(arr.astype("float32"), 1)
        outputs[name] = out_path
        log.info("Saved %s", out_path)

    return outputs


if __name__ == "__main__":
    import argparse

    from floodsight.config import PROCESSED_DIR

    parser = argparse.ArgumentParser()
    parser.add_argument("--dem", required=True, type=Path, help="Path to merged/clipped DEM")
    args = parser.parse_args()
    save_terrain_rasters(args.dem, PROCESSED_DIR / "terrain")
