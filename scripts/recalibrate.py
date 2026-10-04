"""
Phase 6 recalibration script.

Does two things:
  1. Retrains the ML depth model on the current real_training_dataset.csv
     (via the canonical trainer, floodsight/ml/train.py — grouped split,
     provenance-aware metrics).
  2. Analyses field verifications against the DISPATCH CELL SNAPSHOT —
     the Watch/Warning cells the system actually alerted on (recorded by
     /alerts/dispatch into Supabase `dispatch_cells`) — to compute
     false-positive and false-negative rates and flag cells that are
     systematically wrong.

     The old behaviour (matching verifications against /depth/predict
     calls, i.e. dashboard clicks, with no event-date check) measured the
     wrong thing and is kept only as a clearly-labelled fallback for
     event dates that predate dispatch snapshotting.

Data sources (preferred -> fallback):
  verifications : Supabase `verifications`  -> data/logs/verifications.jsonl
  dispatches    : Supabase `dispatch_cells` -> (none)
  predictions   : Supabase `prediction_log` -> data/logs/predictions.jsonl

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

# Make `floodsight` importable when the script is run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR       = Path("data")
LOGS_DIR       = DATA_DIR / "logs"
TRAIN_CSV      = DATA_DIR / "processed" / "real_training_dataset.csv"
PRED_LOG       = LOGS_DIR / "predictions.jsonl"
VERIFY_LOG     = LOGS_DIR / "verifications.jsonl"
MATCH_RADIUS_M = 100   # metres — max distance to match a verification to an alerted cell


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


def _load_verifications() -> list[dict]:
    try:
        from floodsight.db.supabase_client import get_verifications

        rows = get_verifications()
        print(f"  Verifications loaded from Supabase: {len(rows)}")
        return rows
    except RuntimeError:
        rows = _load_jsonl(VERIFY_LOG)
        print(f"  Supabase not configured — verifications from local JSONL: {len(rows)}")
        return rows
    except Exception as exc:
        print(f"  Supabase verifications read failed ({exc}) — local JSONL fallback")
        return _load_jsonl(VERIFY_LOG)


def _load_dispatch_cells() -> dict[str, list[dict]]:
    """All dispatch cell snapshots, grouped by event_date."""
    try:
        from floodsight.db.supabase_client import get_dispatch_cells

        rows = get_dispatch_cells()
    except RuntimeError:
        print("  Supabase not configured — no dispatch snapshots available")
        return {}
    except Exception as exc:
        print(f"  Supabase dispatch_cells read failed ({exc})")
        return {}

    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(str(r["event_date"]), []).append(r)
    print(f"  Dispatch snapshots loaded: {len(rows)} cells across {len(by_date)} event date(s)")
    return by_date


def _load_predictions() -> list[dict]:
    try:
        from floodsight.db.supabase_client import get_predictions

        return get_predictions(limit=10000)
    except RuntimeError:
        return _load_jsonl(PRED_LOG)
    except Exception:
        return _load_jsonl(PRED_LOG)


# ---------------------------------------------------------------------------
# Retrain
# ---------------------------------------------------------------------------

def retrain() -> None:
    if not TRAIN_CSV.exists():
        print(f"ERROR: training dataset not found at {TRAIN_CSV}")
        raise SystemExit(1)

    from floodsight.ml.provenance import normalize_dataset
    df = normalize_dataset(pd.read_csv(TRAIN_CSV))
    print(f"Training dataset: {len(df)} rows across {df['event_name'].nunique()} event(s)")
    if "label_source" in df.columns:
        print(df["label_source"].value_counts().to_string())
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
    print("Quote ONLY metrics.holdout_real_rows_only externally.")
    print("Push to GitHub to update the live Render deployment.")


# ---------------------------------------------------------------------------
# Verification gap analysis
# ---------------------------------------------------------------------------

def analyse() -> None:
    print("\n=== Verification gap analysis ===")

    verifs = _load_verifications()
    if not verifs:
        print("\n  No verifications filed yet. Submit reports via POST /verify "
              "(with the VERIFY_SECRET bearer token) after each flood event.")
        return

    dispatch_by_date = _load_dispatch_cells()

    # ------------------------------------------------------------------
    # Primary path: verification vs dispatched Watch/Warning cells,
    # matched on event_date + location.
    # ------------------------------------------------------------------
    results: list[dict] = []
    no_snapshot_dates: set[str] = set()

    for v in verifs:
        if v.get("lat") is None or v.get("lon") is None:
            continue
        event_date = str(v.get("event_date", ""))
        cells = dispatch_by_date.get(event_date)
        if not cells:
            no_snapshot_dates.add(event_date)
            continue

        dists = [
            _haversine_m(v["lat"], v["lon"], c["lat"], c["lon"]) for c in cells
        ]
        best = int(np.argmin(dists))
        matched = cells[best] if dists[best] <= MATCH_RADIUS_M else None

        results.append({
            "event_date":       event_date,
            "lat":              v["lat"],
            "lon":              v["lon"],
            "observed_flooded": v["observed_flooded"],
            "observed_depth_m": v.get("observed_depth_m"),
            # warned = a Watch/Warning cell was dispatched within radius
            "warned":           matched is not None,
            "alert_level":      matched["alert_level"] if matched else None,
            "match_dist_m":     dists[best] if matched else None,
        })

    if results:
        _report(pd.DataFrame(results), basis="dispatched alerts (dispatch_cells)")

    if no_snapshot_dates:
        print(f"\n  No dispatch snapshot for event date(s): {sorted(no_snapshot_dates)}")
        print("  Falling back to prediction-log matching for those dates "
              "(legacy behaviour — measures dashboard clicks, not dispatched alerts).")
        _analyse_against_predictions(
            [v for v in verifs if str(v.get("event_date", "")) in no_snapshot_dates]
        )


def _analyse_against_predictions(verifs: list[dict]) -> None:
    """Legacy fallback: match verifications to /depth/predict calls.

    Only used for event dates without a dispatch snapshot. Predictions are
    filtered to the verification's event_date (same UTC day) — the old code
    matched across ALL dates by proximity alone, which was meaningless.
    """
    preds = _load_predictions()
    preds = [p for p in preds if p.get("lat") and p.get("lon")]
    if not preds:
        print("  No usable prediction log entries — nothing to fall back on.")
        return

    FLOOD_DEPTH_THRESH = 0.05  # m — predicted above this => "warning issued"
    results = []
    for v in verifs:
        if v.get("lat") is None or v.get("lon") is None:
            continue
        event_date = str(v.get("event_date", ""))
        same_day = [p for p in preds if str(p.get("ts", ""))[:10] == event_date]
        if not same_day:
            continue
        dists = [_haversine_m(v["lat"], v["lon"], p["lat"], p["lon"]) for p in same_day]
        best = int(np.argmin(dists))
        matched = same_day[best] if dists[best] <= MATCH_RADIUS_M else None
        results.append({
            "event_date":       event_date,
            "lat":              v["lat"],
            "lon":              v["lon"],
            "observed_flooded": v["observed_flooded"],
            "observed_depth_m": v.get("observed_depth_m"),
            "warned":           bool(matched and matched["predicted_depth_m"] >= FLOOD_DEPTH_THRESH),
            "alert_level":      None,
            "match_dist_m":     dists[best] if matched else None,
            "predicted_depth_m": matched["predicted_depth_m"] if matched else None,
        })

    if not results:
        print("  No same-day predictions could be matched to these verifications.")
        return

    _report(pd.DataFrame(results), basis="prediction log (legacy fallback)")


def _report(df: pd.DataFrame, basis: str) -> None:
    print(f"\n  --- Results (basis: {basis}) ---")
    print(f"  Verifications analysed : {len(df)}")

    tp = df[ df["warned"] &  df["observed_flooded"]]
    fp = df[ df["warned"] & ~df["observed_flooded"]]
    fn = df[~df["warned"] &  df["observed_flooded"]]
    tn = df[~df["warned"] & ~df["observed_flooded"]]

    precision = len(tp) / (len(tp) + len(fp)) if (len(tp) + len(fp)) > 0 else float("nan")
    recall    = len(tp) / (len(tp) + len(fn)) if (len(tp) + len(fn)) > 0 else float("nan")

    print(f"  True positives  (warned,  flooded)    : {len(tp)}")
    print(f"  False positives (warned,  not flooded): {len(fp)}  <- over-alerts")
    print(f"  False negatives (no warn, flooded)    : {len(fn)}  <- missed floods")
    print(f"  True negatives  (no warn, not flooded): {len(tn)}")
    print(f"  Precision: {precision:.2f}   Recall: {recall:.2f}")

    # Depth accuracy where we have both a prediction and an observed depth
    if "predicted_depth_m" in df.columns:
        both = df[df["observed_depth_m"].notna() & df["predicted_depth_m"].notna()]
        if len(both) > 0:
            errors = both["predicted_depth_m"] - both["observed_depth_m"]
            print(f"\n  Depth accuracy (n={len(both)}): "
                  f"MAE={errors.abs().mean():.3f} m   "
                  f"bias={errors.mean():+.3f} m (positive = over-predict)")

    if len(fp) >= 2:
        print("\n  Systematic false-positive locations (warned but not flooded):")
        for _, row in fp.iterrows():
            print(f"    ({row['lat']:.4f}, {row['lon']:.4f})  "
                  f"level={row.get('alert_level')}  date={row['event_date']}")
        print("  -> Consider lowering susceptibility weight for these cells "
              "or adding an exclusion mask.")

    if len(fn) >= 2:
        print("\n  Systematic false-negative locations (flooded but no warning):")
        for _, row in fn.iterrows():
            print(f"    ({row['lat']:.4f}, {row['lon']:.4f})  "
                  f"observed_depth={row.get('observed_depth_m', '?')}  date={row['event_date']}")
        print("  -> These cells need a lower warning threshold or additional "
              "training rows.")

    print("\n  To improve the model, add verified depths as training rows via:")
    print("  python scripts/build_event_training_rows.py --event-name <name> --depth-raster <path> ...")
    print("  Then re-run: python scripts/recalibrate.py --retrain")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6 recalibration")
    parser.add_argument("--retrain", action="store_true", help="Retrain the ML model")
    parser.add_argument("--analyse", action="store_true",
                        help="Analyse verification vs dispatched-alert gap")
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
