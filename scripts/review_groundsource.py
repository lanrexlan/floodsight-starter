"""Offline evidence triage; never produces wet-cell truth or model predictions.

Small reported places are grouped for manual review by proximity and time.
Groups are NOT independent floods. Broad places cannot bridge local groups.
Only local research outputs are written; no training or production integration.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_freeze(root=ROOT):
    """Check the exact proposal snapshot; changed/missing files fail closed."""
    report = json.loads((root / "reports/historical_evidence_review.json").read_text(encoding="utf-8"))
    expected_files = {**report["input_sha256"], **report.get("output_sha256", {})}
    changed = [relative for relative, expected in expected_files.items()
               if not (root / relative).is_file() or sha256(root / relative) != expected]
    if changed:
        raise ValueError("Proposal snapshot changed: " + ", ".join(changed))
    return report


def literal_events(path, name):
    """Inspect constants without importing APIs, secrets or network callers."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing literal {name} in {path}")


def event_month(event_id):
    match = re.search(r"(?:^|_)(20\d{2})_(0[1-9]|1[0-2])(?:_|[ab]?$)", event_id)
    if not match:
        raise ValueError(f"Unrecognized training event ID: {event_id}")
    return f"{match[1]}-{match[2]}"


def months_in_interval(start, end):
    a, b = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    if b < a:
        raise ValueError("Reversed date interval")
    if (b - a).days > 3660:
        raise ValueError("Implausibly long date interval needs separate review")
    months = set()
    while a <= b:
        months.add(a.strftime("%Y-%m"))
        a += timedelta(days=1)
    return months


def audit_exposure(root):
    exposure = defaultdict(set)
    strata = Counter()
    path = root / "data/processed/real_training_dataset.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            event = row["event"]
            label = row["label_source"]
            strata[(event, label)] += 1
            exposure[event_month(event)].add(f"training:{event}:{label}")
    for relative, name in [("api/routers/validate.py", "FLOOD_EVENTS"),
                           ("scripts/10_augment_training_data.py", "AUGMENT_EVENTS")]:
        for event in literal_events(root / relative, name):
            exposure[event["peak_date"][:7]].add(f"{name}:{event['id']}")
    return {m: sorted(v) for m, v in sorted(exposure.items())}, [
        {"event_id": e, "label_source": s, "rows": n}
        for (e, s), n in sorted(strata.items())]


def allocate(start, end, exposure, reserved):
    months = months_in_interval(start, end)
    overlap = sorted(months & exposure.keys())
    if overlap:
        return "quarantine_known_training_or_tuning_month", overlap
    if months & set(reserved):
        return "reserved_historical_challenge_not_pristine_holdout", []
    return "unallocated_review_only", []


def temporal_matches(start, end, cases):
    """A temporal match NEVER upgrades a polygon's spatial or label status."""
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [c["id"] for c in cases if a <= date.fromisoformat(c["end"])
            and b >= date.fromisoformat(c["start"])]


def review_groups(properties, metric_geometries, distance_m=500, gap_days=1):
    """Heuristic connected components, not hydrological event deduplication."""
    from shapely import STRtree

    parent = list(range(len(properties)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    intervals = [(date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"]))
                 for p in properties]
    eligible = [i for i, p in enumerate(properties)
                if p["reported_place_area_km2"] is not None
                and 0 < p["reported_place_area_km2"] <= 4
                and metric_geometries[i].is_valid]
    tree = STRtree([metric_geometries[i] for i in eligible])
    for i in eligible:
        a, b = intervals[i]
        for pos in tree.query(metric_geometries[i], predicate="dwithin", distance=distance_m):
            j = eligible[int(pos)]
            if j <= i:
                continue
            c, d = intervals[j]
            if a <= d + timedelta(days=gap_days) and c <= b + timedelta(days=gap_days):
                parent[find(j)] = find(i)
    members = defaultdict(list)
    for i in range(len(properties)):
        members[find(i)].append(i)
    output = {}
    for indices in members.values():
        uuids = sorted(properties[i]["source_uuid"] for i in indices)
        group = "review_" + hashlib.sha256("\n".join(uuids).encode()).hexdigest()[:16]
        span = (max(intervals[i][1] for i in indices) - min(intervals[i][0] for i in indices)).days
        flags = ["not_verified_unique_event"]
        if span > 7:
            flags.append("long_temporal_chain_requires_review")
        if any(properties[i]["reported_place_area_km2"] is None
               or properties[i]["reported_place_area_km2"] > 4 for i in indices):
            flags.append("broad_or_unknown_place_not_used_to_bridge_groups")
        for i in indices:
            output[i] = (group, len(indices), "|".join(flags))
    return output


def run(root=ROOT, refresh_proposal=False):
    import geopandas as gpd
    import shapely
    from shapely.geometry import shape

    input_path = root / "data/raw/scientific/groundsource_lagos_candidates.geojson"
    manifest_path = root / "data/validation/reviewed_event_sources.json"
    inventory_path = root / "reports/groundsource_lagos_inventory.json"
    report_path = root / "reports/historical_evidence_review.json"
    if report_path.exists() and not refresh_proposal:
        # Do not silently replace a selected test proposal after development.
        return verify_freeze(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    collection = json.loads(input_path.read_text(encoding="utf-8"))
    properties = [f["properties"] for f in collection["features"]]
    # Raw intake is immutable. Verify label separation before any review output.
    if len(properties) != inventory["candidate_reports"]:
        raise ValueError("Candidate count differs from intake provenance")
    if any(p["depth_m"] is not None or p["review_status"] != "unreviewed" for p in properties):
        raise ValueError("Unexpected labels/review state; refusing automatic relabeling")
    exposure, strata = audit_exposure(root)
    if set(exposure) & set(manifest["reserved_months"]):
        raise ValueError("Proposed reserve overlaps known training/tuning: revise explicitly")
    geometries = gpd.GeoSeries([shape(f["geometry"]) for f in collection["features"]], crs=4326)
    metric = geometries.to_crs(32631)
    grid = gpd.read_file(root / "data/processed/scored_grid.gpkg").to_crs(32631)
    service = shapely.union_all(grid.geometry.values)
    groups = review_groups(properties, metric.values)
    allocations, coverages, matches = Counter(), Counter(), Counter()
    reserves, rows = [], []
    marine = manifest["marine_covariate_exposure"]
    for i, p in enumerate(properties):
        allocation, known_months = allocate(p["start_date"], p["end_date"], exposure,
                                           manifest["reserved_months"])
        hits = temporal_matches(p["start_date"], p["end_date"], manifest["cases"])
        geometry = metric.iloc[i]
        if not geometry.is_valid or geometry.area <= 0:
            coverage, fraction = "invalid_geometry_review_required", None
        else:
            fraction = geometry.intersection(service).area / geometry.area
            coverage = "reported_place_intersects_grid_not_observed_wet" if fraction > 0 else "outside_service_grid"
        marine_exposed = p["start_date"] <= marine["end"] and p["end_date"] >= marine["start"]
        group, size, flags = groups[i]
        rows.append({"source_uuid": p["source_uuid"], "start_date": p["start_date"],
                     "end_date": p["end_date"], "reported_place_area_km2": p["reported_place_area_km2"],
                     "review_group": group, "review_group_reports": size, "group_flags": flags,
                     "allocation": allocation, "known_exposure_months": "|".join(known_months),
                     "marine_input_calibration_exposed": marine_exposed,
                     "service_geometry_context": coverage, "place_area_fraction_in_grid": fraction,
                     "temporally_overlapping_cases_not_spatial_verification": "|".join(hits),
                     "polygon_review_status": "unreviewed", "depth_m": None,
                     "verified_dry": False, "use_as_cell_label": False})
        allocations[allocation] += 1
        coverages[coverage] += 1
        matches.update(hits)
        if allocation.startswith("reserved_"):
            reserves.append(p["source_uuid"])
    frozen_paths = [input_path, manifest_path, inventory_path,
                    root / "scripts/review_groundsource.py",
                    root / "data/processed/real_training_dataset.csv",
                    root / "data/processed/scored_grid.gpkg",
                    root / "data/models/depth_model.joblib",
                    root / "api/routers/validate.py",
                    root / "scripts/10_augment_training_data.py",
                    root / "scripts/calibrate_coastal_threshold.py",
                    root / "floodsight/forecast/marine.py", root / "floodsight/config.py"]
    # Missing evidence/model files are errors, not silently ignored provenance.
    hashes = {p.relative_to(root).as_posix(): sha256(p) for p in frozen_paths}
    report = {"review_date": manifest["review_date"], "candidate_reports": len(rows),
              "corroborated_community_level_cases": len(manifest["cases"]),
              "individual_polygons_verified": 0, "independent_measured_depth_rows": 0,
              "verified_dry_rows": 0, "scientific_acceptance": False,
              "experimental_depth_release_approved": False,
              "allocations": dict(allocations), "service_geometry_context": dict(coverages),
              "temporal_case_overlap_counts_not_verified_polygon_counts": dict(matches),
              "provisional_review_groups_not_unique_events": len({g[0] for g in groups.values()}),
              "grouping_parameters": {"place_area_max_km2": 4, "distance_m": 500, "gap_days": 1},
              "known_training_and_tuning_months": exposure, "training_strata": strata,
              "reserved_months": manifest["reserved_months"], "reserved_source_uuids": sorted(reserves),
              "input_sha256": hashes, "predictions_computed": False,
              "model_performance_used_for_selection": False,
              "holdout_status": "Proposed new-label historical challenge; NOT pristine whole-system or prospective validation",
              "limitations": manifest["limitations"]}
    output = root / "data/raw/scientific/groundsource_review_queue.csv"
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report["output_sha256"] = {output.relative_to(root).as_posix(): sha256(output)}
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-freeze", action="store_true", help="Verify existing proposal only")
    parser.add_argument("--refresh-proposal", action="store_true",
                        help="Explicitly replace proposal snapshot; requires renewed independent review")
    args = parser.parse_args()
    if args.verify_freeze and args.refresh_proposal:
        parser.error("Cannot verify and replace the proposal together")
    result = verify_freeze() if args.verify_freeze else run(refresh_proposal=args.refresh_proposal)
    print(json.dumps({k: result[k] for k in ["candidate_reports", "allocations",
          "corroborated_community_level_cases", "service_geometry_context",
          "temporal_case_overlap_counts_not_verified_polygon_counts",
          "provisional_review_groups_not_unique_events"]}, indent=2))
