"""
Build the real labeled training dataset once you have historical-event
depth labels (from floodsight/labeling/fwdet.py) to combine with the
static + rainfall features already sampled onto the grid
(floodsight/processing/features.py).

This is the Phase 4 deliverable from ROADMAP.md: a table of
(terrain/rainfall features) -> (observed depth) for as many historical
events as you can reconstruct. Even 10-20 well-labeled events is enough
to move past floodsight/ml/synthetic.py and start training on reality.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import rasterio

from floodsight.config import ML_FEATURE_COLUMNS, PROCESSED_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def add_event_labels(
    feature_grid: pd.DataFrame,
    depth_label_raster: Path,
    rain_24h_mm: float,
    rain_72h_mm: float,
    event_name: str,
) -> pd.DataFrame:
    """
    feature_grid: output of processing/features.py (one row per grid
    cell, with centroid_x/centroid_y in the working CRS and all static
    feature columns already populated).
    depth_label_raster: output of labeling/fwdet.py for one historical
    event, aligned to the same grid.
    rain_24h_mm / rain_72h_mm: the actual rainfall totals for that event
    (from CHIRPS/GPM for the event date — see floodsight/download/).

    Returns a copy of feature_grid with rain_24h_mm, rain_72h_mm, and
    depth_m (the label) populated for this event, plus an `event` column
    so you can concatenate multiple events into one training table.
    """
    df = feature_grid.copy()

    with rasterio.open(depth_label_raster) as src:
        coords = list(zip(df["centroid_x"], df["centroid_y"]))
        df["depth_m"] = [v[0] for v in src.sample(coords)]

    df["rain_24h_mm"] = rain_24h_mm
    df["rain_72h_mm"] = rain_72h_mm
    df["event_name"] = event_name
    df["label_source"] = "sar_fwdet"

    return df


def build_real_dataset(event_tables: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate per-event labeled tables (each from add_event_labels)
    into one training-ready dataset, keeping only the columns the model
    needs plus the event tag for traceability/leakage-safe splitting."""
    combined = pd.concat(event_tables, ignore_index=True)
    keep_cols = ML_FEATURE_COLUMNS + ["depth_m", "event"]
    missing = set(keep_cols) - set(combined.columns)
    if missing:
        raise ValueError(f"Combined dataset missing columns: {missing}")

    combined = combined.dropna(subset=ML_FEATURE_COLUMNS + ["depth_m"])
    log.info(
        "Built real training dataset: %d rows across %d events",
        len(combined),
        combined["event"].nunique(),
    )

    out_path = PROCESSED_DIR / "real_training_dataset.csv"
    combined[keep_cols].to_csv(out_path, index=False)
    log.info("Saved %s", out_path)
    return combined[keep_cols]
