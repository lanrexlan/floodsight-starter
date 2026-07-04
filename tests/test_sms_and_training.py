"""
Tests for the July 2026 review fixes:

  * SMS templates — opt-out never truncated, GSM-7 only, ≤160 chars
    (the old Warning template was 178 chars: the trim cut "Reply STOP"
    and the appended U+2026 forced UCS-2 encoding → 3 billed segments).
  * Canonical trainer — grouped-by-event split, label provenance, and
    hand_impute_median saved in the bundle.
  * Phone normalization (was previously untested).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------

AREAS = [
    None,
    "Kosofe",
    "Eti-Osa",
    "Ajeromi-Ifelodun",
    "Oshodi-Isolo & surrounding wards",  # unusually long
    "X" * 120,                            # pathological
]


@pytest.mark.parametrize("level", ["Watch", "Warning"])
@pytest.mark.parametrize("area", AREAS)
def test_sms_single_segment_with_optout(level, area):
    from floodsight.notifications.sms import _build_message, is_gsm7

    msg = _build_message(level, area)
    assert len(msg) <= 160, f"{level}/{area!r}: {len(msg)} chars — splits billing"
    assert msg.endswith("Reply STOP to opt out"), "opt-out must never be truncated"
    assert is_gsm7(msg), f"non-GSM-7 char forces UCS-2 (3x billing): {msg!r}"
    assert "…" not in msg  # the old ellipsis bug


def test_sms_mentions_area():
    from floodsight.notifications.sms import _build_message

    assert "Kosofe" in _build_message("Warning", "Kosofe")
    assert "your area" in _build_message("Watch", None)


# ---------------------------------------------------------------------------
# Canonical trainer
# ---------------------------------------------------------------------------

def _mixed_provenance_dataset(n_events: int = 6, rows_per_event: int = 60) -> pd.DataFrame:
    """Synthetic multi-event dataset with real + pseudo-labeled rows."""
    from floodsight.config import ML_FEATURE_COLUMNS, ML_TARGET_COLUMN

    rng = np.random.default_rng(0)
    frames = []
    for i in range(n_events):
        df = pd.DataFrame(
            rng.normal(size=(rows_per_event, len(ML_FEATURE_COLUMNS))),
            columns=ML_FEATURE_COLUMNS,
        )
        df[ML_TARGET_COLUMN] = (
            0.5 * df["hand_m"].abs() + rng.normal(0, 0.1, rows_per_event)
        ).clip(0)
        df["event_name"] = f"event_{i}"
        # events 0-1 real, rest synthetic
        df["label_source"] = "sar_fwdet" if i < 2 else "synthetic_augmented"
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def test_trainer_grouped_split_and_provenance(tmp_path):
    import joblib

    from floodsight.ml.train import save_model, train_model

    df = _mixed_provenance_dataset()
    model, metrics = train_model(df, is_synthetic=False)

    # Grouped split: no event on both sides
    assert metrics["split_strategy"] == "grouped_by_event"
    held_out = set(metrics["held_out_events"])
    assert held_out, "some events must be held out"
    n_test_rows = sum(df["event_name"].isin(held_out))
    assert metrics["n_test"] == n_test_rows, "test set must be exactly the held-out events"

    # Provenance recorded
    prov = metrics["label_provenance"]
    assert prov["real_rows"] == 120
    assert prov["synthetic_rows"] == 240
    assert prov["synthetic_fraction"] == pytest.approx(240 / 360, abs=0.001)

    # hand median present and bundle round-trips it
    assert "hand_impute_median_m" in metrics
    path = tmp_path / "m.joblib"
    save_model(model, metrics, path=path)
    bundle = joblib.load(path)
    assert bundle["hand_impute_median"] == metrics["hand_impute_median_m"]
    assert bundle["label_provenance"]["synthetic_rows"] == 240


def test_trainer_reports_real_only_holdout_when_possible(tmp_path):
    from floodsight.ml.train import train_model

    # Try a few seeds implicitly via dataset size — with 2 real events out
    # of 6 the grouped split may or may not hold a real event out; the
    # metric key must exist either way (value or None).
    df = _mixed_provenance_dataset()
    _, metrics = train_model(df, is_synthetic=False)
    assert "holdout_real_rows_only" in metrics


def test_predict_uses_bundle_hand_median(tmp_path):
    import joblib

    import floodsight.ml.predict as predict_mod
    from floodsight.ml.train import save_model, train_model

    df = _mixed_provenance_dataset()
    model, metrics = train_model(df, is_synthetic=False)
    path = tmp_path / "m.joblib"
    save_model(model, metrics, path=path)

    predict_mod._cached = None
    bundle = predict_mod.load_model(path=path)
    assert predict_mod._hand_median(bundle) == metrics["hand_impute_median_m"]

    # No silent 3.0 default for legacy bundles — falls back to 0.0
    legacy = {k: v for k, v in bundle.items() if k != "hand_impute_median"}
    assert predict_mod._hand_median(legacy) == 0.0
    predict_mod._cached = None


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

def test_normalize_phone():
    from floodsight.db.supabase_client import normalize_phone

    assert normalize_phone("08012345678") == "+2348012345678"
    assert normalize_phone("2348012345678") == "+2348012345678"
    assert normalize_phone("+234 801 234 5678") == "+2348012345678"
    with pytest.raises(ValueError):
        normalize_phone("")
    with pytest.raises(ValueError):
        normalize_phone("not-a-number")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
