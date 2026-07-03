"""
Train the depth-prediction baseline model.

Per ROADMAP.md Phase 5: start with a gradient-boosted regression baseline
before justifying an LSTM or physics-informed NN. This is cheap to train,
easy to interpret (feature_importances_), and gives you a real,
reportable accuracy number instead of an aspirational one.

Usage:
    # with real labeled data (once you have it — see floodsight/labeling/):
    python -m floodsight.ml.train --data path/to/labeled_dataset.csv

    # with synthetic data, to verify the pipeline works end-to-end:
    python -m floodsight.ml.train --synthetic
"""

from __future__ import annotations

import argparse
import logging

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from floodsight.config import ML_FEATURE_COLUMNS, ML_MODEL_PATH, ML_TARGET_COLUMN

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def train_model(
    df: pd.DataFrame, is_synthetic: bool = False
) -> tuple[GradientBoostingRegressor, dict]:
    missing = set(ML_FEATURE_COLUMNS + [ML_TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    X = df[ML_FEATURE_COLUMNS]
    y = df[ML_TARGET_COLUMN]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = GradientBoostingRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )
    log.info("Training GradientBoostingRegressor on %d samples", len(X_train))
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    metrics = {
        "mae_m": float(mean_absolute_error(y_test, y_pred)),
        "rmse_m": float(np.sqrt(np.mean((y_test - y_pred) ** 2))),
        "r2": float(r2_score(y_test, y_pred)),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "trained_on_synthetic_data": is_synthetic,
    }
    log.info("Held-out test metrics: %s", metrics)
    if is_synthetic:
        log.warning(
            "*** This model was trained on SYNTHETIC data only (see "
            "floodsight/ml/synthetic.py). Do not deploy or report these "
            "metrics as real model performance — retrain on real labeled "
            "events before using this for anything beyond pipeline testing. ***"
        )

    importances = dict(zip(ML_FEATURE_COLUMNS, model.feature_importances_.round(3)))
    log.info("Feature importances: %s", importances)

    return model, metrics


def save_model(model: GradientBoostingRegressor, metrics: dict, path=ML_MODEL_PATH) -> None:
    joblib.dump({"model": model, "metrics": metrics, "features": ML_FEATURE_COLUMNS}, path)
    log.info("Saved model + metrics to %s", path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default=None, help="Path to labeled CSV dataset")
    parser.add_argument(
        "--synthetic", action="store_true", help="Train on synthetic demo data instead"
    )
    args = parser.parse_args()

    if args.synthetic or not args.data:
        from floodsight.ml.synthetic import generate_synthetic_dataset

        log.info("No --data given (or --synthetic set): using synthetic demo dataset")
        dataset = generate_synthetic_dataset()
        synthetic = True
    else:
        dataset = pd.read_csv(args.data)
        synthetic = False

    trained_model, eval_metrics = train_model(dataset, is_synthetic=synthetic)
    save_model(trained_model, eval_metrics)
