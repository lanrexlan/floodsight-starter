"""
Runs the ENTIRE pipeline end-to-end using synthetic data — zero internet
access, zero downloads, zero credentials required. This exists purely so
you can verify the codebase actually works on your machine in under a
minute, before spending hours on real data downloads.

What it does:
  1. Generates a synthetic feature grid (same schema as the real
     pipeline's output) covering the Lagos pilot AOI.
  2. Runs the real susceptibility scoring code (floodsight/processing/
     susceptibility.py) on it.
  3. Trains the real ML depth model (floodsight/ml/train.py) on
     synthetic labels.
  4. Runs the real HAND-based depth code (floodsight/processing/
     depth_hand.py) on a synthetic HAND surface.
  5. Saves a scored_grid.gpkg so the API/dashboard have something to
     serve immediately.

After running this, start the API (`uvicorn api.main:app --reload`) and
open dashboard/index.html — you'll see real risk classes and can query
real alert logic, all running on synthetic terrain. Swap in real data by
running scripts/01-04 instead.

Usage:
    python scripts/run_demo_pipeline.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main():
    import numpy as np

    from floodsight.config import AOI_BBOX, PROCESSED_DIR, WGS84, WORKING_CRS
    from floodsight.processing.depth_hand import build_rating_curve, discharge_to_depth_raster
    from floodsight.processing.susceptibility import compute_flood_score

    log.info("STEP 1/4 — building synthetic feature grid")
    import geopandas as gpd
    from shapely.geometry import box

    rng = np.random.default_rng(7)
    aoi = gpd.GeoDataFrame(geometry=[box(*AOI_BBOX)], crs=WGS84).to_crs(WORKING_CRS)
    minx, miny, maxx, maxy = aoi.total_bounds

    n_per_side = 60
    xs = np.linspace(minx, maxx, n_per_side)
    ys = np.linspace(miny, maxy, n_per_side)
    cell_w = (maxx - minx) / n_per_side
    cell_h = (maxy - miny) / n_per_side

    rows = []
    for x in xs:
        for y in ys:
            rows.append({"geometry": box(x, y, x + cell_w, y + cell_h)})
    grid = gpd.GeoDataFrame(rows, crs=WORKING_CRS)
    grid["cell_id"] = grid.index.astype(str)
    grid["centroid_x"] = grid.geometry.centroid.x
    grid["centroid_y"] = grid.geometry.centroid.y

    n = len(grid)
    norm_pos = (grid["centroid_x"] - minx) / (maxx - minx)
    grid["elevation_m"] = (norm_pos * 12 + rng.normal(0, 1.0, n)).clip(0, None)
    grid["slope_deg"] = rng.exponential(1.2, n).clip(0, 15)
    grid["flow_accum"] = rng.exponential(150, n)
    grid["hand_m"] = (grid["elevation_m"] * rng.uniform(0.2, 0.5, n)).clip(0, None)
    grid["dist_to_water_m"] = norm_pos * 1500 + rng.exponential(150, n)
    grid["landcover_class"] = rng.choice([50, 50, 80, 90, 40], n)
    grid["population_density"] = rng.exponential(4000, n)
    log.info("Built %d synthetic grid cells", n)

    log.info("STEP 2/4 — running REAL susceptibility scoring code on synthetic features")
    scored = compute_flood_score(grid)
    out_path = PROCESSED_DIR / "scored_grid.gpkg"
    scored.to_file(out_path, driver="GPKG")
    log.info("Saved %s — this is what the API/dashboard will serve", out_path)

    log.info("STEP 3/4 — training REAL ML depth model on synthetic labels")
    from floodsight.ml.synthetic import generate_synthetic_dataset
    from floodsight.ml.train import save_model, train_model

    dataset = generate_synthetic_dataset()
    model, metrics = train_model(dataset, is_synthetic=True)
    save_model(model, metrics)
    log.info("Trained model — held-out MAE on synthetic data: %.3fm", metrics["mae_m"])

    log.info("STEP 4/4 — running REAL HAND-based depth code on a synthetic HAND surface")
    synthetic_hand = grid["hand_m"].to_numpy().reshape(n_per_side, n_per_side)
    curve = build_rating_curve(
        synthetic_hand, cell_size_m=cell_w, channel_length_m=cell_w * n_per_side
    )
    depth = discharge_to_depth_raster(synthetic_hand, curve, discharge_cms=50.0)
    log.info(
        "HAND depth demo: %d/%d cells flooded, max depth %.2fm",
        int((depth > 0).sum()), depth.size, float(depth.max()),
    )

    log.info("")
    log.info("=== Demo pipeline complete ===")
    log.info("Next: uvicorn api.main:app --reload --port 8000")
    log.info("Then: open dashboard/index.html in a browser")


if __name__ == "__main__":
    main()
