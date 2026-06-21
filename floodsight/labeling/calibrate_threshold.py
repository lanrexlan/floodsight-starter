"""
Calibration check for WATER_VV_THRESHOLD_DB (floodsight/labeling/sar_extent.py).

Rather than trust the generic -17dB literature default, this samples
actual VV backscatter values from a KNOWN permanent water body (the
Lagos Lagoon, via your already-downloaded OSM water layer) in the same
Sentinel-1 scenes used for a given event, and reports the real
distribution. If the lagoon's actual values don't cluster sensibly
below the current threshold, that's a direct signal the threshold needs
adjusting for this sensor/processing combination — not a generic guess.

Reuses the scene search, download, and caching logic from sar_extent.py
rather than duplicating it, so it benefits from the same fixes (date
window, re-signed URLs, full-download-not-streamed).

Usage:
    python -m floodsight.labeling.calibrate_threshold --pre 2024-06-25 --during 2024-07-04
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

from floodsight.config import AOI_BBOX, RAW_DIR
from floodsight.labeling.sar_extent import (
    WATER_VV_THRESHOLD_DB,
    _download_asset,
    _search_scene,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

WATER_LAYER_PATH = RAW_DIR / "osm" / "clipped" / "water.gpkg"


def _load_water_polygon():
    import geopandas as gpd

    if not WATER_LAYER_PATH.exists():
        raise FileNotFoundError(
            f"{WATER_LAYER_PATH} not found — run the OSM download first "
            "(floodsight/download/osm.py), this calibration check needs "
            "a known-water polygon to sample against."
        )
    water = gpd.read_file(WATER_LAYER_PATH)
    if water.empty:
        raise ValueError(f"{WATER_LAYER_PATH} loaded but contains no features.")
    return water


def sample_water_backscatter(item, water_gdf) -> np.ndarray:
    """Returns the VV dB values for every pixel falling inside the known
    water polygon, for one Sentinel-1 scene."""
    import planetary_computer
    import rioxarray

    vv_href = planetary_computer.sign(item.assets["vv"].href)
    local_path = _download_asset(vv_href, RAW_DIR / "sentinel1" / "cache", f"{item.id}_vv.tif")
    da = rioxarray.open_rasterio(local_path).squeeze().load()

    water_in_raster_crs = water_gdf.to_crs(da.rio.crs)
    clipped = da.rio.clip(water_in_raster_crs.geometry, water_in_raster_crs.crs, drop=True)

    vv_db = (10 * np.log10(clipped.where(clipped > 0))).to_numpy()
    return vv_db[~np.isnan(vv_db)]


def report_stats(label: str, values: np.ndarray) -> None:
    if len(values) == 0:
        log.warning(
            "%s: no valid pixels sampled inside the water polygon for this "
            "scene — the lagoon may not actually overlap this scene's "
            "footprint, or the water layer geometry needs checking.",
            label,
        )
        return
    pcts = np.percentile(values, [5, 25, 50, 75, 95])
    log.info(
        "%s — %d pixels sampled inside known water:\n"
        "  5th/25th/50th/75th/95th percentile (dB): %.2f / %.2f / %.2f / %.2f / %.2f\n"
        "  mean: %.2f, current threshold: %.2f",
        label, len(values), *pcts, values.mean(), WATER_VV_THRESHOLD_DB,
    )
    frac_below = float((values < WATER_VV_THRESHOLD_DB).mean())
    log.info(
        "  %.1f%% of known-water pixels fall BELOW the current threshold "
        "(i.e. would be correctly classified as water). Low %% here means "
        "the threshold is too strict for this scene.",
        frac_below * 100,
    )


def main(pre_date: datetime, during_date: datetime, window_days: int = 8):
    water_gdf = _load_water_polygon()

    pre_item = _search_scene(pre_date, AOI_BBOX, window_days=window_days)
    during_item = _search_scene(during_date, AOI_BBOX, window_days=window_days)
    if pre_item is None or during_item is None:
        log.error("Could not find scenes for calibration — same date-window issue as sar_extent.py.")
        return

    pre_values = sample_water_backscatter(pre_item, water_gdf)
    during_values = sample_water_backscatter(during_item, water_gdf)

    report_stats("PRE-event scene", pre_values)
    report_stats("DURING-event scene", during_values)

    if len(pre_values) and len(during_values):
        combined_median = float(np.median(np.concatenate([pre_values, during_values])))
        log.info(
            "Suggested threshold based on median known-water backscatter "
            "across both scenes: %.2f dB (current default: %.2f dB)",
            combined_median, WATER_VV_THRESHOLD_DB,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", required=True, help="Pre-event date YYYY-MM-DD")
    parser.add_argument("--during", required=True, help="During/post-event date YYYY-MM-DD")
    parser.add_argument("--window-days", type=int, default=8)
    args = parser.parse_args()
    main(
        datetime.strptime(args.pre, "%Y-%m-%d"),
        datetime.strptime(args.during, "%Y-%m-%d"),
        window_days=args.window_days,
    )
