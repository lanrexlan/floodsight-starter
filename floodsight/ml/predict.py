"""
Load the trained depth model and predict depth for new feature rows.
Used directly by the API (api/routers/depth.py).
"""

from __future__ import annotations

import logging

import joblib
import pandas as pd

from floodsight.config import ML_FEATURE_COLUMNS, ML_MODEL_PATH

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_cached = None


def load_model(path=ML_MODEL_PATH):
    global _cached
    if _cached is None:
        bundle = joblib.load(path)
        _cached = bundle
        if bundle["metrics"].get("trained_on_synthetic_data"):
            log.warning(
                "Loaded model was trained on SYNTHETIC data — predictions "
                "are for pipeline testing only, not real depth estimates."
            )
    return _cached


def predict_depth(features: dict) -> float:
    """features: dict with keys matching ML_FEATURE_COLUMNS (see
    floodsight/config.py). Returns predicted depth in meters."""
    bundle = load_model()
    model = bundle["model"]
    row = pd.DataFrame([{col: features[col] for col in ML_FEATURE_COLUMNS}])
    pred = float(model.predict(row)[0])
    return max(pred, 0.0)


def predict_depth_batch(df: pd.DataFrame) -> pd.Series:
    bundle = load_model()
    model = bundle["model"]
    preds = model.predict(df[ML_FEATURE_COLUMNS])
    return pd.Series(preds, index=df.index).clip(lower=0)


def model_metadata() -> dict:
    bundle = load_model()
    return {"features": bundle["features"], "metrics": bundle["metrics"]}
