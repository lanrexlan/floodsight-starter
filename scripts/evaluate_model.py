"""Leave one observed event out; compare to a baseline without synthetic test labels."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from floodsight.config import ML_FEATURE_COLUMNS, ML_TARGET_COLUMN
from floodsight.ml.provenance import normalize_dataset
from floodsight.ml.train import _metrics_block


def evaluate(df):
    df = normalize_dataset(df)
    observed = df[df.label_source == "sar_fwdet"]
    events = sorted(observed.event_name.unique())
    folds = []
    for event in events:
        # Report observed-only and augmented strategies separately. Synthetic
        # rows never turn into observed evidence merely by improving a score.
        for strategy, source in (("observed_only", observed), ("with_augmentation", df)):
            train = source[source.event_name != event]
            test = observed[observed.event_name == event]
            if len(train) < 2:
                continue
            xtrain, xtest = train[ML_FEATURE_COLUMNS].copy(), test[ML_FEATURE_COLUMNS].copy()
            hand_median = xtrain.hand_m.median()
            hand_median = 0.0 if pd.isna(hand_median) else float(hand_median)
            xtrain["hand_m"] = xtrain.hand_m.fillna(hand_median)
            xtest["hand_m"] = xtest.hand_m.fillna(hand_median)
            model = GradientBoostingRegressor(n_estimators=300, max_depth=4, learning_rate=.05, subsample=.8, random_state=42)
            model.fit(xtrain, train[ML_TARGET_COLUMN])
            predictions = np.maximum(model.predict(xtest), 0)
            folds.append({"held_out_event": event, "strategy": strategy,
                          "train_rows": len(train), "observed_test_rows": len(test),
                          "model": _metrics_block(test[ML_TARGET_COLUMN], predictions),
                          "baseline": _metrics_block(test[ML_TARGET_COLUMN], np.full(len(test), train[ML_TARGET_COLUMN].mean()))})
    return {"status": "experimental", "observed_events": events,
            "observed_rows": len(observed), "unknown_rows": int((df.label_source == "unknown").sum()),
            "folds": folds, "launch_evidence": "Additional independent flood AND non-flood observations, location holdouts, and prospective alert lead-time/false-alarm measurements required."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/processed/real_training_dataset.csv")
    parser.add_argument("--output", default="reports/model_validation.json")
    args = parser.parse_args()
    report = evaluate(pd.read_csv(args.data))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
