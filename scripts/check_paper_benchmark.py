"""Use published summaries for dimensional/QC checks, not depth validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assess(data):
    if data["observed_depth_rows"] or any(data[field] for field in [
            "usable_for_depth_training", "usable_for_independent_depth_acceptance", "depth_release_approved"]):
        raise ValueError("Published-summary intake must not be promoted to depth truth")
    table = data["table_7"]
    if table["label_type"] != "scenario_forcing_and_simulated_basin_outputs":
        raise ValueError("Unexpected basin label type")
    expected_units = {"peak_discharge": "m3/s", "rainfall": "mm", "loss": "mm",
                      "excess": "mm", "impervious": "%"}
    if table["units"] != expected_units:
        raise ValueError("Unexpected units; refusing comparison")
    expected_columns = ["subbasin", "peak_discharge", "rainfall", "loss", "excess", "impervious"]
    if table["columns"] != expected_columns:
        raise ValueError("Unexpected column mapping")
    residuals, flows, ids = [], [], set()
    for row in table["rows"]:
        if len(row) != 6 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in row):
            raise ValueError("Invalid numerical row")
        basin, flow, rain, loss, excess, impervious = row
        if basin in ids or min(flow, rain, loss, excess, impervious) < 0 or impervious > 100:
            raise ValueError("Invalid basin values")
        ids.add(basin)
        flows.append(flow)
        residuals.append({"subbasin": basin, "rain_minus_loss_minus_excess_mm": round(rain - loss - excess, 4)})
    if not flows:
        raise ValueError("Empty basin summary")
    # Diagnostic identity only: do not repair source values or assert a model error.
    queries = [r for r in residuals if abs(r["rain_minus_loss_minus_excess_mm"]) > 0.05]
    return {
        "status": "published_values_used_for_research_qc_not_validation_acceptance",
        "source_doi": data["source"]["doi"],
        "basin_rows_checked": len(flows),
        "published_peak_discharge_range_m3_s": [min(flows), max(flows)],
        "rainfall_loss_excess_identity_residuals_mm": residuals,
        "values_to_query_not_automatically_correct": queries,
        "qc_screening_tolerance_mm": 0.05,
        "qc_tolerance_meaning": "Screen for author clarification, not scientific accuracy or conservation threshold",
        "floodsight_comparison": {
            "numerical_error_computed": False,
            "reason": "No matched catchment, event forcing or paired measured outcomes",
            "authors_metrics_transferable_to_floodsight": False,
            "modeled_runoff_mm_is_ground_referenced_depth": False,
            "modeled_area_is_verified_wet_cell_truth": False
        },
        "independent_observed_depth_rows_added": 0,
        "scientific_acceptance": False,
        "depth_release_approved": False
    }


def run(root=ROOT):
    path = root / "data/validation/lagos_paper_benchmark.json"
    raw = path.read_bytes()
    report = assess(json.loads(raw))
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    target = root / "reports/lagos_paper_benchmark_checks.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(run(), indent=2))
