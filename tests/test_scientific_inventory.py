"""External reported floods must never masquerade as measured depth or dry truth."""
import pytest
from shapely.geometry import box

from scripts.extract_groundsource import candidate, extract, summarize


def record(**changes):
    return {"uuid": "a", "area_km2": 1.0, "start_date": "2024-07-03",
            "end_date": "2024-07-03", **changes}


def test_reported_place_is_not_measured_depth_or_flood_extent():
    feature = candidate(record(), box(3.4, 6.4, 3.41, 6.41))
    p = feature["properties"]
    assert p["depth_m"] is None
    assert p["review_status"] == "unreviewed"
    assert p["label_type"] == "reported_flood_occurrence"
    assert "reported_place_not_inundation_footprint" in p["quality_flags"]
    assert "not_confirmed_service_coverage" in p["quality_flags"]


def test_broad_cross_boundary_reports_are_flagged():
    f = candidate(record(area_km2=10000), box(2.5, 6.0, 3.1, 6.4))
    assert "broad_reported_place_over_4_km2" in f["properties"]["quality_flags"]
    assert "place_centroid_outside_lagos_bbox" in f["properties"]["quality_flags"]


@pytest.mark.parametrize("changes,flag", [
    ({"start_date": "July 2024"}, "invalid_date_interval"),
    ({"end_date": "2024-07-02"}, "reversed_date_interval"),
    ({"end_date": "2024-07-10"}, "multi_day_interval"),
    ({"area_km2": float("nan")}, "invalid_reported_area"),
])
def test_uncertainty_is_not_silently_normalized(changes, flag):
    assert flag in candidate(record(**changes), box(3.4, 6.4, 3.41, 6.41))["properties"]["quality_flags"]


def test_duplicate_reports_are_not_independent_events():
    geometry = box(3.4, 6.4, 3.41, 6.41)
    features = [candidate(record(uuid=u), geometry) for u in ["a", "b"]]
    report = summarize(features, 100)
    assert report["candidate_reports"] == 2
    assert report["exact_place_date_groups"] == 1
    assert report["unique_flood_events"] is None
    assert report["verified_dry_control_rows"] == 0
    assert report["independent_measured_lagos_depth_rows"] == 0
    assert not report["experimental_depth_release_approved"]
    assert all("repeated_exact_place_date" in f["properties"]["quality_flags"] for f in features)


def test_incomplete_download_cannot_create_evidence(tmp_path):
    path = tmp_path / "incomplete.parquet"
    path.write_bytes(b"partial")
    with pytest.raises(ValueError, match="Incomplete"):
        extract(path, tmp_path / "output", tmp_path / "report.json")
    assert not (tmp_path / "report.json").exists()


def test_checksum_mismatch_cannot_create_evidence(tmp_path, monkeypatch):
    from scripts import extract_groundsource as inventory
    path = tmp_path / "wrong.parquet"
    path.write_bytes(b"wrong")
    monkeypatch.setattr(inventory, "SOURCE_BYTES", 5)
    with pytest.raises(ValueError, match="checksum mismatch"):
        extract(path, tmp_path / "output", tmp_path / "report.json")
    assert not (tmp_path / "report.json").exists()
