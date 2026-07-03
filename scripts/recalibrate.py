"""
Phase 6 recalibration script.

Does two things:
  1. Retrains the ML depth model on the current real_training_dataset.csv.
  2. Analyses the verification log (data/logs/verifications.jsonl) against
     the prediction log (data/logs/predictions.jsonl) to compute
     false-positive and false-negative rates, and flags cells that are
     systematically wrong.

Usage (from project root, conda activate floodsight):

    # Retrain only
    python scripts/recalibrate.py --retrain

    # Analyse verification gap only (no retrain)
    python scripts/recalibrate.py --analyse

    # Both
    python scripts/recalibrate.py --retrain --analyse

After running, the updated model is saved to data/models/depth_model.joblib
and Render will pick it up on the next push to GitHub main.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR       = Path("data")
LOGS_DIR       = DATA_DIR / "logs"
TRAIN_CSV      = DATA_DIR / "processed" / "real_training_dataset.csv"
PRED_LOG       = LOGS_DIR / "predictions.jsonl"
VERIFY_LOG     = LOGS_DIR / "verifications.jsonl"
MATCH_RADIUS_M = 100   # metres — max distance to match a prediction to a verification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres."""
    R = 6_371_000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Retrain
# ---------------------------------------------------------------------------

def retrain() -> None:
    if not TRAIN_CSV.exists():
        print(f"ERROR: training dataset not found at {TRAIN_CSV}")
        raise SystemExit(1)

    df = pd.read_csv(TRAIN_CSV)
    print(f"Training dataset: {len(df)} rows across {df['event_name'].nunique()} event(s)")
    print(df.groupby("event_name")[["depth_m", "rain_24h_mm"]].describe().round(2))

    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "floodsight.ml.train", "--data", str(TRAIN_CSV)],
        capture_output=False,
    )
    if result.returncode != 0:
        print("ERROR: training failed.")
        raise SystemExit(result.returncode)
    print("\nModel retrained and saved to data/models/depth_model.joblib")
    print("Push to GitHub to update the live Render deployment.")


# ---------------------------------------------------------------------------
# Verification gap analysis
# ---------------------------------------------------------------------------

def analyse() -> None:
    preds = _load_jsonl(PRED_LOG)
    verifs = _load_jsonl(VERIFY_LOG)

    print(f"\n=== Verification gap analysis ===")
    print(f"  Prediction log entries : {len(preds)}")
    print(f"  Verification entries   : {len(verifs)}")

    if not verifs:
        print("\n  No verifications filed yet. Submit reports via POST /verify after each flood event.")
        return

    # --- match each verification to nearest prediction on same event date ---
    results = []
    for v in verifs:
        if v.get("lat") is None or v.get("lon") is None:
            continue
        event_date = v.get("event_date", "")
        # predictions don't carry event_date; match by proximity
        preds_with_loc = [p for p in preds if p.get("lat") and p.get("lon")]
        if not preds_with_loc:
            continue
        dists = [_haversine_m(v["lat"], v["lon"], p["lat"], p["lon"]) for p in preds_with_loc]
        best_idx = int(np.argmin(dists))
        best_dist = dists[best_idx]
        if best_dist > MATCH_RADIUS_M:
            matched_pred = None
        else:
            matched_pred = preds_with_loc[best_idx]

        results.append({
            "event_date":       event_date,
            "lat":              v["lat"],
            "lon":              v["lon"],
            "observed_flooded": v["observed_flooded"],
            "observed_depth_m": v.get("observed_depth_m"),
            "predicted_depth_m": matched_pred["predicted_depth_m"] if matched_pred else None,
            "match_dist_m":     best_dist if matched_pred else None,
        })

    if not results:
        print("  No verifications could be matched to predictions (predictions missing lat/lon?).")
        return

    df = pd.DataFrame(results)
    matched = df[df["predicted_depth_m"].notna()].copy()
    unmatched = len(df) - len(matched)
    print(f"\n  Matched to predictions : {len(matched)}  (unmatched: {unmatched})")

    if matched.empty:
        print("  No matched pairs — start including lat/lon in /depth/predict calls.")
        return

    # Classify each matched pair
    FLOOD_DEPTH_THRESH = 0.05  # m — predicted above this => "warning issued"
    matched["warned"] = matched["predicted_depth_m"] >= FLOOD_DEPTH_THRESH
    tp = matched[ matched["warned"] &  matched["observed_flooded"]]
    fp = matched[ matched["warned"] & ~matched["observed_flooded"]]
    fn = matched[~matched["warned"] &  matched["observed_flooded"]]
    tn = matched[~matched["warned"] & ~matched["observed_flooded"]]

    precision = len(tp) / (len(tp) + len(fp)) if (len(tp) + len(fp)) > 0 else float("nan")
    recall    = len(tp) / (len(tp) + len(fn)) if (len(tp) + len(fn)) > 0 else float("nan")

    print(f"\n  Warning threshold: predicted_depth_m >= {FLOOD_DEPTH_THRESH} m")
    print(f"  True positives  (warned,  flooded)  : {len(tp)}")
    print(f"  False positives (warned,  not flooded): {len(fp)}  ← over-alerts")
    print(f"  False negatives (no warn, flooded)  : {len(fn)}  ← missed floods")
    print(f"  True negatives  (no warn, not flooded): {len(tn)}")
    print(f"  Precision: {precision:.2f}   Recall: {recall:.2f}")

    # Depth accuracy on flooded, warned cells
    flooded_matched = matched[matched["observed_flooded"] & matched["warned"]].copy()
    if len(flooded_matched) > 0 and flooded_matched["observed_depth_m"].notna().any():
        flooded_matched = flooded_matched[flooded_matched["observed_depth_m"].notna()]
        errors = flooded_matched["predicted_depth_m"] - flooded_matched["observed_depth_m"]
        mae = errors.abs().mean()
        bias = errors.mean()
        print(f"\n  Depth accuracy on confirmed-flooded cells (n={len(flooded_matched)}):")
        print(f"    MAE={mae:.3f} m   bias={bias:+.3f} m (positive = over-predict)")

    # Flag systematic false-positive locations
    if len(fp) >= 2:
        print(f"\n  Systematic false-positive locations (warned but never flooded):")
        for _, row in fp.iterrows():
            print(f"    ({row['lat']:.4f}, {row['lon']:.4f})  predicted={row['predicted_depth_m']:.3f} m  date={row['event_date']}")
        print("\n  → Consider lowering susceptibility weight for these cells or adding an exclusion mask.")

    # Flag systematic false-negative locations
    if len(fn) >= 2:
        print(f"\n  Systematic false-negative locations (flooded but no warning issued):")
        for _, row in fn.iterrows():
            print(f"    ({row['lat']:.4f}, {row['lon']:.4f})  observed_depth={row.get('observed_depth_m', '?')} m  date={row['event_date']}")
        print("\n  → These cells need lower warning threshold or additional training rows.")

    print("\n  To improve the model, add the verified depth values as training rows via:")
    print("  python scripts/build_event_training_rows.py --event-name <name> --depth-raster <path> ...")
    print("  Then re-run: python scripts/recalibrate.py --retrain")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6 recalibration")
    parser.add_argument("--retrain", action="store_true", help="Retrain the ML model")
    parser.add_argument("--analyse", action="store_true",
                        help="Analyse verification vs prediction gap")
    args = parser.parse_args()

    if not args.retrain and not args.analyse:
        parser.print_help()
        print("\nNote: pass --retrain, --analyse, or both.")
        raise SystemExit(0)

    if args.retrain:
        retrain()
    if args.analyse:
        analyse()


if __name__ == "__main__":
    main()
