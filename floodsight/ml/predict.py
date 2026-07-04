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


def _hand_median(bundle) -> float:
    """
    Serving-time hand_m imputation value — must match training-time
    imputation. All bundles saved by the canonical trainer
    (floodsight/ml/train.py) include it. If an old bundle lacks it, fall
    back to 0.0 (the documented treatment of NaN HAND — lagoon/creek
    cells) and warn loudly, rather than the old silent hardcoded 3.0 m
    which shifted predictions.
    """
    v = bundle.get("hand_impute_median")
    if v is None:
        log.warning(
            "Model bundle has no hand_impute_median — retrain with "
            "floodsight.ml.train. Imputing hand_m NaN with 0.0."
        )
        return 0.0
    return float(v)


def label_provenance(bundle) -> dict | None:
    """Real vs synthetic label composition of the training data, if recorded."""
    return bundle.get("label_provenance") or bundle["metrics"].get("label_provenance")


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
        prov = label_provenance(bundle)
        if prov and prov.get("synthetic_fraction", 0) > 0:
            log.warning(
                "Loaded model trained on mixed-provenance labels: %d real / "
                "%d synthetic rows (%.0f%% synthetic).",
                prov.get("real_rows", 0), prov.get("synthetic_rows", 0),
                100 * prov.get("synthetic_fraction", 0),
            )
    return _cached


def predict_depth(features: dict) -> float:
    """Return predicted flood depth in metres for a single feature dict.

    Keys must match ML_FEATURE_COLUMNS (see floodsight/config.py).
    hand_m may be None/NaN — imputed with training-set median from bundle.
    """
    bundle      = load_model()
    model       = bundle["model"]
    hand_median = _hand_median(bundle)

    row_data = {}
    for col in ML_FEATURE_COLUMNS:
        v = features.get(col)
        if col == "hand_m" and (v is None or (isinstance(v, float) and pd.isna(v))):
            v = hand_median
        row_data[col] = v

    row  = pd.DataFrame([row_data])
    pred = float(model.predict(row.values)[0])
    return max(pred, 0.0)


def predict_depth_batch(df: pd.DataFrame) -> pd.Series:
    """Batch prediction — df must contain all ML_FEATURE_COLUMNS."""
    bundle      = load_model()
    model       = bundle["model"]
    hand_median = _hand_median(bundle)

    Xb = df[ML_FEATURE_COLUMNS].copy()
    Xb["hand_m"] = pd.to_numeric(Xb["hand_m"], errors="coerce").fillna(hand_median)
    preds = model.predict(Xb.values)
    return pd.Series(preds, index=df.index).clip(lower=0)


def model_metadata() -> dict:
    bundle = load_model()
    return {
        "features": bundle["features"],
        "metrics": bundle["metrics"],
        "label_provenance": label_provenance(bundle),
    }
