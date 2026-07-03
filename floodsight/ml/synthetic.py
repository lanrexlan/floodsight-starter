"""
Generate synthetic (feature -> depth) training data so the ML pipeline
(dataset.py / train.py / predict.py) is runnable end-to-end today, before
you've built the real labeled dataset from historical events (ROADMAP.md
Phase 4: Sentinel-1 extent + FwDET depth labeling).

THIS DATA IS NOT REAL. It encodes a plausible, physically-motivated
relationship (lower elevation/HAND + more rainfall + closer to water +
higher imperviousness -> deeper water) purely so you can verify the
training/serving code path works before real labels exist. A model
trained only on this synthetic set should never be deployed or reported
as having a real accuracy figure — its only purpose is to make the rest
of the scaffold runnable and testable. Swap this out for
floodsight.ml.dataset.build_real_dataset() the moment you have even a
handful of labeled historical events.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from floodsight.config import ML_FEATURE_COLUMNS


def generate_synthetic_dataset(n_samples: int = 5000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    elevation_m = rng.uniform(0, 15, n_samples)
    slope_deg = rng.exponential(1.5, n_samples).clip(0, 20)
    flow_accum = rng.exponential(200, n_samples)
    hand_m = (elevation_m * rng.uniform(0.2, 0.6, n_samples)).clip(0, None)
    dist_to_water_m = rng.exponential(400, n_samples)
    landcover_class = rng.choice([10, 30, 40, 50, 80, 90, 95], n_samples)
    population_density = rng.exponential(3000, n_samples)
    rain_24h_mm = rng.uniform(0, 180, n_samples)
    rain_72h_mm = rain_24h_mm + rng.uniform(0, 120, n_samples)

    impervious_bonus = np.where(landcover_class == 50, 0.25, 0.0)
    wetland_bonus = np.where(np.isin(landcover_class, [90, 95]), 0.2, 0.0)

    raw_depth = (
        0.018 * rain_24h_mm
        + 0.008 * rain_72h_mm
        - 0.35 * hand_m
        - 0.0008 * dist_to_water_m
        - 0.05 * slope_deg
        + 0.5 * impervious_bonus * (rain_24h_mm / 100)
        + 0.5 * wetland_bonus
        + rng.normal(0, 0.15, n_samples)
    )
    depth_m = np.clip(raw_depth, 0, None)

    df = pd.DataFrame(
        {
            "elevation_m": elevation_m,
            "slope_deg": slope_deg,
            "flow_accum": flow_accum,
            "hand_m": hand_m,
            "dist_to_water_m": dist_to_water_m,
            "landcover_class": landcover_class,
            "population_density": population_density,
            "rain_24h_mm": rain_24h_mm,
            "rain_72h_mm": rain_72h_mm,
            "depth_m": depth_m,
        }
    )
    assert list(ML_FEATURE_COLUMNS) == [c for c in df.columns if c != "depth_m"]
    return df


if __name__ == "__main__":
    df = generate_synthetic_dataset()
    print(df.describe())
