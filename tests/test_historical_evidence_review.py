"""Desk-review evidence must not silently turn into scientific acceptance."""
import json
from pathlib import Path

import pytest
from shapely.geometry import box

from scripts.review_groundsource import (allocate, event_month, literal_events,
                                         months_in_interval, review_groups,
                                         sha256, temporal_matches, verify_freeze)


@pytest.mark.parametrize("name,expected", [
    ("2011_07", "2011-07"), ("2024_07b", "2024-07"),
    ("2021_07a", "2021-07"), ("lekki_2024_07_03", "2024-07")])
def test_synthetic_and_proxy_events_use_whole_month(name, expected):
    assert event_month(name) == expected


def test_unknown_training_id_fails_closed():
    with pytest.raises(ValueError, match="Unrecognized"):
        event_month("unknown")


def test_allocation_quarantines_month_not_just_claimed_peak():
    result, months = allocate("2024-07-30", "2024-08-02", {"2024-07": []}, ["2024-08"])
    assert result == "quarantine_known_training_or_tuning_month"
    assert months == ["2024-07"]


def test_whole_reserved_month_not_only_positive_episode():
    result, _ = allocate("2025-08-31", "2025-08-31", {}, ["2025-08"])
    assert result == "reserved_historical_challenge_not_pristine_holdout"


def test_intervals_cross_year_and_reversed_dates():
    assert months_in_interval("2024-12-31", "2025-01-01") == {"2024-12", "2025-01"}
    with pytest.raises(ValueError, match="Reversed"):
        months_in_interval("2025-01-02", "2025-01-01")


def test_literal_inspection_does_not_import_or_execute(tmp_path):
    path = tmp_path / "unsafe.py"
    path.write_text("raise RuntimeError('must not run')\nEVENTS: list = [{'id':'a'}]\n")
    assert literal_events(path, "EVENTS") == [{"id": "a"}]


def props(uuid, area=1, start="2025-08-04", end="2025-08-04"):
    return {"source_uuid": uuid, "reported_place_area_km2": area,
            "start_date": start, "end_date": end}


def test_broad_place_cannot_bridge_two_local_review_groups():
    properties = [props("a"), props("b"), props("large", area=100)]
    geometries = [box(0, 0, 10, 10), box(2000, 0, 2010, 10), box(-1, -1, 3000, 11)]
    groups = review_groups(properties, geometries)
    assert len({g[0] for g in groups.values()}) == 3
    assert "not_used_to_bridge" in groups[2][2]


def test_local_groups_are_stable_not_unique_flood_claims():
    p = [props("a"), props("b"), props("c", start="2025-09-01", end="2025-09-01")]
    geoms = [box(0, 0, 10, 10), box(20, 0, 30, 10), box(0, 0, 10, 10)]
    a = review_groups(p, geoms)
    b = review_groups(list(reversed(p)), list(reversed(geoms)))
    assert a[0][0] == a[1][0] != a[2][0]
    assert a[0][0] == b[2][0]
    assert a[0][1] == 2
    assert "not_verified_unique_event" in a[0][2]


def test_temporal_match_is_only_overlap_not_publication_date():
    cases = [{"id": "aug", "start": "2025-08-03", "end": "2025-08-04",
              "publication_date": "2025-09-29"}]
    assert temporal_matches("2025-08-04", "2025-08-05", cases) == ["aug"]
    assert temporal_matches("2025-09-29", "2025-09-29", cases) == []


def test_manifest_does_not_claim_measurements_acquired_or_contact_sent():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "data/validation/reviewed_event_sources.json").read_text())
    assert manifest["measurement_lead"]["contacted"] is False
    assert manifest["measurement_lead"]["public_download_found"] is False
    assert all("depth_m" not in case for case in manifest["cases"])
    assert manifest["reserved_months"] == ["2025-08", "2025-09"]


def test_hash_freeze_detects_changes(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"before")
    initial = sha256(path)
    path.write_bytes(b"after")
    assert sha256(path) != initial


def test_proposal_verification_fails_on_changed_or_missing_evidence(tmp_path):
    path = tmp_path / "source.json"
    path.write_text("original")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/historical_evidence_review.json").write_text(
        json.dumps({"input_sha256": {"source.json": sha256(path)}}))
    verify_freeze(tmp_path)
    path.write_text("modified")
    with pytest.raises(ValueError, match="snapshot changed"):
        verify_freeze(tmp_path)
    path.unlink()
    with pytest.raises(ValueError, match="snapshot changed"):
        verify_freeze(tmp_path)


def test_saved_review_has_no_automatic_wet_or_depth_acceptance():
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "reports/historical_evidence_review.json").read_text())
    assert sum(report["allocations"].values()) == report["candidate_reports"]
    assert sum(report["service_geometry_context"].values()) == report["candidate_reports"]
    assert report["individual_polygons_verified"] == 0
    assert report["independent_measured_depth_rows"] == 0
    assert report["verified_dry_rows"] == 0
    assert report["scientific_acceptance"] is False
    assert report["experimental_depth_release_approved"] is False
    assert report["predictions_computed"] is False
    assert report["model_performance_used_for_selection"] is False
    assert len(report["reserved_source_uuids"]) == report["allocations"][
        "reserved_historical_challenge_not_pristine_holdout"]
