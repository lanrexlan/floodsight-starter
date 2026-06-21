"""
Compute a real flood depth-in-meters layer for a given rainfall scenario,
using the HAND-based synthetic rating curve (Track A from ROADMAP.md
Phase 1) — no ML model, no labeled data required.

Usage:
    python scripts/04_compute_hand_depth.py --rain-24h 120 --catchment-km2 25
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main(args):
    import numpy as np
    import rasterio

    from floodsight.config import PROCESSED_DIR
    from floodsight.processing.depth_hand import (
        build_rating_curve,
        discharge_to_depth_raster,
        rainfall_to_discharge_scs,
    )

    hand_path = PROCESSED_DIR / "terrain" / "hand_m.tif"
    if not hand_path.exists():
        raise FileNotFoundError(
            f"{hand_path} not found — run scripts/02_build_grid_and_features.py first."
        )

    with rasterio.open(hand_path) as src:
        hand = src.read(1)
        cell_size_m = abs(src.transform.a)
        profile = src.profile

    # Rough proxy for channel length: count of "definitely drainage" cells
    # (HAND == 0) times cell size. Refine by vectorizing the actual stream
    # network once you've validated drainage_threshold_cells visually.
    channel_length_m = float((hand == 0).sum()) * cell_size_m
    if channel_length_m == 0:
        channel_length_m = cell_size_m * 100  # fallback so curve-building doesn't divide by zero

    log.info("Building synthetic rating curve (channel_length=%.0fm)", channel_length_m)
    curve = build_rating_curve(hand, cell_size_m, channel_length_m)

    if args.discharge_cms is not None:
        discharge = args.discharge_cms
    else:
        discharge = rainfall_to_discharge_scs(args.rain_24h, args.catchment_km2)
        log.info(
            "Estimated discharge from %.0fmm/24h over %.1fkm2 (SCS-CN method): %.1f m3/s",
            args.rain_24h, args.catchment_km2, discharge,
        )

    depth = discharge_to_depth_raster(hand, curve, discharge)

    out_path = PROCESSED_DIR / "depth_hand_scenario.tif"
    profile.update(dtype="float32", nodata=0)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(depth.astype("float32"), 1)
    log.info("Saved depth scenario to %s", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rain-24h", type=float, default=100.0, help="mm in last 24h")
    parser.add_argument("--catchment-km2", type=float, default=20.0)
    parser.add_argument(
        "--discharge-cms", type=float, default=None,
        help="Skip the rainfall-to-discharge estimate and use this discharge directly "
             "(e.g. a real GloFAS value)",
    )
    main(parser.parse_args())
