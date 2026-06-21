"""
Run the susceptibility scoring (flood_score, risk_class) on the feature
grid produced by scripts/02_build_grid_and_features.py, and save the
result as data/processed/scored_grid.gpkg — what api/data_provider.py
serves to the dashboard.

Usage:
    python scripts/03_compute_susceptibility.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main(use_quantile_breaks: bool = False):
    import geopandas as gpd

    from floodsight.config import PROCESSED_DIR
    from floodsight.processing.susceptibility import compute_flood_score

    in_path = PROCESSED_DIR / "feature_grid.gpkg"
    if not in_path.exists():
        raise FileNotFoundError(
            f"{in_path} not found — run scripts/02_build_grid_and_features.py first."
        )

    grid = gpd.read_file(in_path)
    scored = compute_flood_score(grid, use_quantile_breaks=use_quantile_breaks)

    out_path = PROCESSED_DIR / "scored_grid.gpkg"
    scored.to_file(out_path, driver="GPKG")
    log.info("Saved scored grid to %s", out_path)
    log.info(
        "Histogram check — if Low/Very High are nearly empty like the "
        "original repo's table, see ROADMAP.md Phase 0 known-defects note:\n%s",
        scored["flood_score"].describe(),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quantile", action="store_true",
        help="Classify risk by quartile of this AOI's own score distribution "
             "instead of fixed 0.25/0.50/0.75 breakpoints. Use this if the "
             "default run gives a lopsided distribution (e.g. almost "
             "everything 'High').",
    )
    args = parser.parse_args()
    main(use_quantile_breaks=args.quantile)
