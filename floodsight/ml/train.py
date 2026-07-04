"""
Train the depth-prediction model — THE canonical trainer.

This is the single training entry point for FloodSight. It replaced the
diverged duplicate in scripts/09_train_flood_depth.py (which now delegates
here). Any script that trains or retrains the depth model must go through
train_model()/save_model() in this module so that:

  * the train/test split is grouped by event (no event leaks into both
    sides — a random row split massively inflates R2 when rows within an
    event share terrain and rainfall),
  * metrics are reported separately for real-labeled rows
    (label_source == "sar_fwdet") vs synthetic/pseudo-labeled rows —
    ONLY the real-holdout numbers should ever be quoted externally,
  * hand_impute_median is always computed and saved in the bundle
    (floodsight/ml/predict.py needs it; the old scripts/09-only save
    meant the documented retrain path silently dropped it), and
  * the bundle records label provenance so the API can tell users what
    the model was actually trained on.

Usage:
    # with the labeled dataset:
    python -m floodsight.ml.train --data data/processed/real_training_dataset.csv

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
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from floodsight.config import ML_FEATURE_COLUMNS, ML_MODEL_PATH, ML_TARGET_COLUMN

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Provenance values considered "real" ground truth (SAR + FwDET labeled
# events). Everything else (synthetic_augmented, swmm_synthetic, demo
# synthetic) is model-assumed, not observed.
REAL_LABEL_SOURCES = {"sar_fwdet"}


def _metrics_block(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return {
        "mae_m": float(mean_absolute_error(y_true, y_pred)),
        "rmse_m": float(np.sqrt(np.mean((y_true - y_pred) ** 2))),
        "r2": float(r2_score(y_true, y_pred)) if len(np.unique(y_true)) > 1 else float("nan"),
        "n": int(len(y_true)),
    }


def train_model(
    df: pd.DataFrame, is_synthetic: bool = False
) -> tuple[GradientBoostingRegressor, dict]:
    """
    Train the gradient-boosting depth model.

    If df has an ``event_name`` column, the train/test split is grouped by
    event so no event appears on both sides. If df has a ``label_source``
    column, metrics are additionally reported on the real-labeled subset of
    the held-out data — that is the honest, externally quotable number.

    Returns (model, metrics). metrics includes hand_impute_median_m and
    label_provenance; save_model() lifts those into the bundle.
    """
    missing = set(ML_FEATURE_COLUMNS + [ML_TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    df = df.copy()

    # Defensive cleanup: some dataset versions have blank event_name for the
    # 2024 Lekki rows (the `event` column carries the value instead), and
    # may lack label_source entirely. Repair rather than crash the split.
    if "event_name" in df.columns:
        if "event" in df.columns:
            df["event_name"] = df["event_name"].fillna(df["event"])
        df["event_name"] = df["event_name"].fillna("unknown_event")
    if "label_source" not in df.columns and "event_name" in df.columns:
        # Heuristic matching this project's history: lekki_* events are the
        # SAR/FwDET-labeled ones; everything else was augmentation.
        df["label_source"] = np.where(
            df["event_name"].astype(str).str.startswith("lekki_"),
            "sar_fwdet", "synthetic_augmented",
        )
        log.warning(
            "Dataset has no label_source column — derived it from event_name "
            "(lekki_* => sar_fwdet). Add the column to the CSV properly."
        )

    # --- hand_m imputation (median), saved for serving-time consistency ---
    hand = pd.to_numeric(df["hand_m"], errors="coerce")
    hand_median = float(hand.median()) if hand.notna().any() else 0.0
    df["hand_m"] = hand.fillna(hand_median)

    # --- provenance ---
    if "label_source" in df.columns:
        real_mask = df["label_source"].isin(REAL_LABEL_SOURCES)
    else:
        real_mask = pd.Series(not is_synthetic, index=df.index)
    n_real = int(real_mask.sum())
    n_synth = int(len(df) - n_real)
    provenance = {
        "real_rows": n_real,
        "synthetic_rows": n_synth,
        "synthetic_fraction": round(n_synth / len(df), 3) if len(df) else 0.0,
        "real_label_sources": sorted(REAL_LABEL_SOURCES),
    }

    X = df[ML_FEATURE_COLUMNS]
    y = df[ML_TARGET_COLUMN]

    # --- grouped split by event (prevents event leakage) ---
    if "event_name" in df.columns and df["event_name"].nunique() > 1:
        # Scan seeds until at least one REAL-labeled event lands in the
        # held-out set (when real events exist alongside synthetic ones) —
        # otherwise there is nothing honest to report. Deterministic:
        # always starts at seed 42.
        real_events = set(df.loc[real_mask, "event_name"].unique())
        train_idx = test_idx = None
        for seed in range(42, 92):
            splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
            tr, te = next(splitter.split(X, y, groups=df["event_name"]))
            held = set(df["event_name"].iloc[te].unique())
            if train_idx is None:
                train_idx, test_idx = tr, te  # fallback: first split
            if not real_events or n_synth == 0 or (held & real_events):
                train_idx, test_idx = tr, te
                break
        split_strategy = "grouped_by_event"
        test_events = sorted(df["event_name"].iloc[test_idx].unique().tolist())
        log.info("Grouped split — held-out events: %s", test_events)
    else:
        train_idx, test_idx = train_test_split(
            np.arange(len(df)), test_size=0.2, random_state=42
        )
        split_strategy = "random_rows"
        test_events = []
        log.warning(
            "No event_name column (or single event) — falling back to a "
            "random row split. Metrics may be optimistic due to spatial "
            "autocorrelation within events."
        )

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    model = GradientBoostingRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )
    log.info("Training GradientBoostingRegressor on %d samples", len(X_train))
    model.fit(X_train.values, y_train.values)

    y_pred = np.clip(model.predict(X_test.values), 0.0, None)

    metrics = _metrics_block(y_test, y_pred)
    metrics.update(
        {
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "split_strategy": split_strategy,
            "held_out_events": test_events,
            "trained_on_synthetic_data": is_synthetic,
            "hand_impute_median_m": round(hand_median, 4),
            "label_provenance": provenance,
        }
    )

    # --- honest metrics: real-labeled held-out rows only ---
    real_test = real_mask.iloc[test_idx].values
    if real_test.any() and n_synth > 0:
        metrics["holdout_real_rows_only"] = _metrics_block(
            y_test[real_test], y_pred[real_test]
        )
        log.info(
            "Held-out REAL-labeled rows only (quote THIS externally): %s",
            metrics["holdout_real_rows_only"],
        )
    elif n_synth > 0 and not real_test.any():
        metrics["holdout_real_rows_only"] = None
        log.warning(
            "No real-labeled rows in the held-out events — cannot report an "
            "honest real-data metric for this split. Re-run until a lekki_* "
            "event is held out, or use grouped cross-validation."
        )

    log.info(
        "Held-out test metrics (all rows): %s",
        {k: metrics[k] for k in ("mae_m", "rmse_m", "r2", "n_test")},
    )

    if is_synthetic:
        log.warning(
            "*** This model was trained on SYNTHETIC data only (see "
            "floodsight/ml/synthetic.py). Do not deploy or report these "
            "metrics as real model performance — retrain on real labeled "
            "events before using this for anything beyond pipeline testing. ***"
        )
    elif provenance["synthetic_fraction"] > 0:
        log.warning(
            "%.0f%% of training rows are synthetic/pseudo-labeled "
            "(label_source != sar_fwdet). The all-rows metrics above are NOT "
            "a real-world accuracy claim — use holdout_real_rows_only.",
            100 * provenance["synthetic_fraction"],
        )

    importances = dict(zip(ML_FEATURE_COLUMNS, model.feature_importances_.round(3)))
    metrics["feature_importance"] = {k: float(v) for k, v in importances.items()}
    log.info("Feature importances: %s", importances)

    return model, metrics


def save_model(model: GradientBoostingRegressor, metrics: dict, path=ML_MODEL_PATH) -> None:
    bundle = {
        "model": model,
        "metrics": metrics,
        "features": ML_FEATURE_COLUMNS,
        "target": ML_TARGET_COLUMN,
        # Serving-time hand_m imputation must match training-time imputation.
        "hand_impute_median": metrics.get("hand_impute_median_m", 0.0),
        "label_provenance": metrics.get("label_provenance"),
    }
    joblib.dump(bundle, path)
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
