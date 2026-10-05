"""A researcher's published model scores cannot validate FloodSight depth."""
import copy
import json
from pathlib import Path

import pytest

from scripts.check_paper_benchmark import assess


def benchmark():
    path = Path(__file__).resolve().parents[1] / "data/validation/lagos_paper_benchmark.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_published_summaries_remain_separate_from_observations():
    result = assess(benchmark())
    assert result["basin_rows_checked"] == 7
    assert result["independent_observed_depth_rows_added"] == 0
    assert result["scientific_acceptance"] is False
    assert result["depth_release_approved"] is False
    assert result["floodsight_comparison"]["numerical_error_computed"] is False
    assert result["floodsight_comparison"]["authors_metrics_transferable_to_floodsight"] is False


def test_declined_request_does_not_grant_data_or_acceptance():
    data = benchmark()
    assert data["author_contacted"] is True
    request = data["underlying_data_request"]
    assert request["status"] == "sharing_declined"
    assert request["underlying_data_acquired"] is False
    assert request["reuse_permission_acquired"] is False
    assert data["observed_depth_rows"] == []
    assert assess(data)["scientific_acceptance"] is False


def test_transcribed_values_are_preserved_and_residuals_flagged_not_repaired():
    data = benchmark()
    original = copy.deepcopy(data)
    result = assess(data)
    assert data == original
    assert result["values_to_query_not_automatically_correct"] == [
        {"subbasin": 2, "rain_minus_loss_minus_excess_mm": 0.49},
        {"subbasin": 5, "rain_minus_loss_minus_excess_mm": -0.09}]


@pytest.mark.parametrize("unit", ["m", "mm", "m3"])
def test_discharge_unit_mismatch_fails_closed(unit):
    data = benchmark()
    data["table_7"]["units"]["peak_discharge"] = unit
    with pytest.raises(ValueError, match="units"):
        assess(data)


@pytest.mark.parametrize("field", ["usable_for_depth_training", "usable_for_independent_depth_acceptance",
                                 "depth_release_approved"])
def test_cannot_promote_published_summaries_to_depth_truth(field):
    data = benchmark()
    data[field] = True
    with pytest.raises(ValueError, match="depth truth"):
        assess(data)


def test_invalid_numbers_fail_closed():
    data = benchmark()
    data["table_7"]["rows"][0][1] = float("nan")
    with pytest.raises(ValueError, match="numerical"):
        assess(data)
