"""
Smoke tests — verify the core logic (susceptibility scoring, alert
engine, HAND depth conversion, FwDET depth estimation, ML train/predict)
works correctly without needing any downloaded data or external network
access. Run these any time you touch the math, not just before a release.

Usage:
    pip install pytest
    pytest tests/ -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def test_susceptibility_scoring_basic():
    from floodsight.processing.susceptibility import compute_flood_score

    df = pd.DataFrame(
        {
            "elevation_m": [0.0, 5.0, 15.0],
            "slope_deg": [0.5, 2.0, 8.0],
            "flow_accum": [500, 100, 10],
            "dist_to_water_m": [10, 200, 2000],
            "landcover_class": [80, 50, 10],
            "population_density": [8000, 2000, 100],
        }
    )
    scored = compute_flood_score(df)
    assert "flood_score" in scored.columns
    assert "risk_class" in scored.columns
    # Lowest elevation + closest to water + highest flow + water landcover
    # should score strictly higher risk than the highest/driest cell.
    assert scored.loc[0, "flood_score"] > scored.loc[2, "flood_score"]
    assert set(scored["risk_class"]).issubset({"Low", "Moderate", "High", "Very High"})


def test_alert_engine_thresholds():
    from floodsight.alerts.engine import compute_alert_level

    assert compute_alert_level("High", 110, 0) == "Warning"
    assert compute_alert_level("High", 60, 0) == "Watch"
    assert compute_alert_level("Moderate", 110, 0) == "Watch"
    assert compute_alert_level("Low", 150, 200) == "No Alert"


def test_alert_engine_depth_override():
    from floodsight.alerts.engine import compute_alert_level

    assert compute_alert_level("Low", 0, 0, predicted_depth_m=0.4) == "Watch"
    assert compute_alert_level("Low", 0, 0, predicted_depth_m=0.6) == "Warning"
    assert compute_alert_level("Low", 0, 0, predicted_depth_m=0.1) == "No Alert"


def test_fwdet_depth_estimation_bowl():
    from floodsight.labeling.fwdet import estimate_depth

    dem = np.array(
        [
            [10, 9, 8, 9, 10],
            [9, 6, 4, 6, 9],
            [8, 4, 1, 4, 8],
            [9, 6, 4, 6, 9],
            [10, 9, 8, 9, 10],
        ],
        dtype=float,
    )
    flood_mask = dem <= 6
    depth = estimate_depth(flood_mask, dem, smooth_iterations=0)

    assert (depth[~flood_mask] == 0).all(), "Non-flooded cells must be zero"
    assert depth.min() >= 0, "Depth must never be negative"
    assert depth[2, 2] > 0, "The lowest interior point should have positive depth"
    assert depth[2, 2] == depth.max(), "The lowest point should be the deepest"


def test_hand_rating_curve_monotonic():
    from floodsight.processing.depth_hand import build_rating_curve, stage_for_discharge

    rng = np.random.default_rng(0)
    hand = rng.exponential(1.5, size=(50, 50))
    curve = build_rating_curve(hand, cell_size_m=30, channel_length_m=1500)

    assert (curve["discharge_cms"].diff().dropna() >= 0).all(), "Rating curve must be monotonic"

    low_stage = stage_for_discharge(curve, curve["discharge_cms"].min())
    high_stage = stage_for_discharge(curve, curve["discharge_cms"].max())
    assert high_stage >= low_stage


def test_hand_discharge_to_depth():
    from floodsight.processing.depth_hand import build_rating_curve, discharge_to_depth_raster

    hand = np.array([[0.0, 0.5, 1.0], [0.2, 0.8, 2.0], [0.1, 1.5, 3.0]])
    curve = build_rating_curve(hand, cell_size_m=30, channel_length_m=90)
    depth = discharge_to_depth_raster(hand, curve, discharge_cms=float(curve["discharge_cms"].median()))

    assert depth.shape == hand.shape
    assert (depth >= 0).all()
    # Cells with lower HAND should never have less depth than cells with
    # higher HAND, for the same water surface stage.
    assert depth[0, 0] >= depth[2, 2]


def test_ml_train_predict_roundtrip(tmp_path, monkeypatch):
    from floodsight.ml.synthetic import generate_synthetic_dataset
    from floodsight.ml.train import save_model, train_model

    dataset = generate_synthetic_dataset(n_samples=500)
    model, metrics = train_model(dataset, is_synthetic=True)

    assert metrics["mae_m"] < 1.0, "Sanity bound — synthetic data is easy, MAE should be small"
    assert metrics["trained_on_synthetic_data"] is True

    model_path = tmp_path / "model.joblib"
    save_model(model, metrics, path=model_path)
    assert model_path.exists()

    import floodsight.ml.predict as predict_mod

    predict_mod._cached = None  # reset module-level cache between tests
    bundle = predict_mod.load_model(path=model_path)
    assert bundle["metrics"]["trained_on_synthetic_data"] is True


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
