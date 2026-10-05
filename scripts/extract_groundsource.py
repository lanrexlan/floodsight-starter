"""Create a research-only Lagos review queue, never depth labels or dry controls.

Requires optional local dependency pyarrow; not imported by the deployed API.
Download the pinned public file from SOURCE_URL, then run this script locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import shapely
from shapely.geometry import box, mapping

SOURCE_URL = "https://zenodo.org/api/records/18647054/files/groundsource_2026.parquet/content"
SOURCE_RECORD = "https://zenodo.org/records/18647054"
SOURCE_MD5 = "cd1b5de6508f7aad8e1d1d0dd4cecea6"
SOURCE_BYTES = 667122400
LAGOS_BBOX = (3.0, 6.3, 3.8, 6.8)


def candidate(record, geometry, bbox=LAGOS_BBOX):
    """Preserve a reported place as a place, not a measured flood footprint."""
    flags = ["manual_source_verification_required", "not_measured_depth",
             "reported_place_not_inundation_footprint", "not_confirmed_service_coverage"]
    if not geometry.is_valid:
        flags.append("invalid_geometry")
    area = record["area_km2"]
    if area is None or not float("-inf") < float(area) < float("inf") or area <= 0:
        area = None
        flags.append("invalid_reported_area")
    elif area > 4:
        # Triage heuristic, not an estimate of geolocation error or acceptance.
        flags.append("broad_reported_place_over_4_km2")
    try:
        start = date.fromisoformat(record["start_date"])
        end = date.fromisoformat(record["end_date"])
        if end < start:
            flags.append("reversed_date_interval")
        elif (end - start).days > 1:
            flags.append("multi_day_interval")
    except (TypeError, ValueError):
        flags.append("invalid_date_interval")
    inside = box(*bbox).covers(geometry.centroid)
    if not inside:
        flags.append("place_centroid_outside_lagos_bbox")
    # Identical place/date records can represent repeat reporting. Distinct
    # geometries/dates can ALSO report the same flood; this is not event dedup.
    group = hashlib.sha256(
        shapely.normalize(geometry).wkb
        + str(record["start_date"]).encode()
        + b"/" + str(record["end_date"]).encode()
    ).hexdigest()[:24]
    return {"type": "Feature", "geometry": mapping(geometry), "properties": {
        "source_uuid": record["uuid"], "source_record": SOURCE_RECORD,
        "label_source": "groundsource_news", "label_type": "reported_flood_occurrence",
        "start_date": record["start_date"], "end_date": record["end_date"],
        "reported_place_area_km2": area, "exact_place_date_group": group,
        "place_centroid_in_lagos_bbox": inside, "review_status": "unreviewed",
        "quality_flags": flags, "depth_m": None,
    }}


def summarize(features, source_rows, bbox=LAGOS_BBOX):
    groups = Counter(f["properties"]["exact_place_date_group"] for f in features)
    for feature in features:
        p = feature["properties"]
        p["exact_place_date_report_count"] = groups[p["exact_place_date_group"]]
        if p["exact_place_date_report_count"] > 1 and "repeated_exact_place_date" not in p["quality_flags"]:
            p["quality_flags"].append("repeated_exact_place_date")
    flags = Counter(flag for f in features for flag in f["properties"]["quality_flags"])
    starts = [f["properties"]["start_date"] for f in features
              if "invalid_date_interval" not in f["properties"]["quality_flags"]]
    return {
        "status": "research_candidates_not_validation_acceptance",
        "source_record": SOURCE_RECORD, "source_md5": SOURCE_MD5,
        "license": "CC BY 4.0", "attribution": "Mayo, Zlydenko et al. (2026), Groundsource v1, Google Research; DOI 10.5281/zenodo.18647054",
        "selection_bbox_wgs84": list(bbox), "selection": "Reported-place polygon intersects bounding box; not proof of flooding within service cells.",
        "source_rows_scanned": source_rows, "candidate_reports": len(features),
        "exact_place_date_groups": len(groups),
        "repeat_reports_beyond_first_exact_place_date": sum(n - 1 for n in groups.values()),
        "unique_flood_events": None,
        "place_centroids_inside_bbox": sum(f["properties"]["place_centroid_in_lagos_bbox"] for f in features),
        "start_date_range": [min(starts), max(starts)] if starts else [],
        "quality_flag_report_counts": dict(flags), "reviewed_reports": 0,
        "independent_measured_lagos_depth_rows": 0, "verified_dry_control_rows": 0,
        "usable_for_depth_training": False, "experimental_depth_release_approved": False,
        "limitations": [
            "News-derived and AI-extracted; location/timing require independent manual verification.",
            "Geometries describe reported places, NOT observed water extents or exact sensor positions.",
            "UUID/report counts and exact place/date groups are NOT counts of independent flood events.",
            "No article URLs are present in the released columns inspected; corroboration needs external source lookup.",
            "Unreported dates/places are unknown, not verified dry negatives.",
            "Historical observed rainfall cannot establish forecast lead time; archived forecasts are required.",
            "News coverage bias prevents interpreting changes in report counts as flood-frequency trends.",
        ],
    }


def extract(path, output_dir, report_path):
    path = Path(path)
    if path.stat().st_size != SOURCE_BYTES:
        raise ValueError("Incomplete or unexpected source file size; finish the pinned download first.")
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != SOURCE_MD5:
        raise ValueError("Source checksum mismatch; refuse to create validation evidence.")
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    geo = json.loads(parquet.metadata.metadata[b"geo"])
    crs = geo["columns"]["geometry"]["crs"]["id"]
    if crs != {"authority": "EPSG", "code": 4326}:
        raise ValueError("Unexpected source CRS; do not assume WGS84.")
    aoi = box(*LAGOS_BBOX)
    features, scanned = [], 0
    for batch in parquet.iter_batches(batch_size=8192, columns=[
            "uuid", "area_km2", "geometry", "start_date", "end_date"]):
        records = batch.to_pydict()
        geometries = shapely.from_wkb(records["geometry"])
        bounds = shapely.bounds(geometries)
        coarse = ((bounds[:, 0] <= LAGOS_BBOX[2]) & (bounds[:, 2] >= LAGOS_BBOX[0])
                  & (bounds[:, 1] <= LAGOS_BBOX[3]) & (bounds[:, 3] >= LAGOS_BBOX[1]))
        for i in coarse.nonzero()[0]:
            geometry = geometries[i]
            if not geometry.is_valid:
                # Invalid geometries are not silently repaired into evidence.
                raise ValueError(f"Invalid candidate geometry: {records['uuid'][i]}")
            if geometry.intersects(aoi):
                record = {k: v[i] for k, v in records.items() if k != "geometry"}
                features.append(candidate(record, geometry))
        scanned += batch.num_rows
    report = summarize(features, scanned)
    output_dir, report_path = Path(output_dir), Path(report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "name": "unreviewed_reported_places_not_flood_extent",
                  "attribution": report["attribution"], "license": report["license"],
                  "features": features}
    (output_dir / "groundsource_lagos_candidates.geojson").write_text(
        json.dumps(collection, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    report_path.write_text(json.dumps(report, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/raw/scientific/groundsource_2026.parquet")
    parser.add_argument("--output-dir", default="data/raw/scientific")
    parser.add_argument("--report", default="reports/groundsource_lagos_inventory.json")
    args = parser.parse_args()
    print(json.dumps(extract(args.input, args.output_dir, args.report), indent=2))
