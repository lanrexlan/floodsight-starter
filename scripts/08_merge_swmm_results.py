"""
scripts/08_merge_swmm_results.py
Phase 18 Track 3 — Merge per-LGA SWMM flood GeoJSONs into a single city-wide file.

Reads
-----
  data/processed/swmm_flooding_kosofe.geojson
  data/processed/swmm_flooding_alimosho.geojson
  data/processed/swmm_flooding_eti_osa.geojson

Writes
------
  data/processed/swmm_flooding_all.geojson
      Combined FeatureCollection with an "lga" property on every feature.
      Used by the dashboard and the FloodSight API for city-wide SWMM coverage.

  data/processed/swmm_summary_all.json
      City-level summary: total flooded nodes, severity counts per LGA,
      and combined continuity statistics.

Usage
-----
  python scripts/08_merge_swmm_results.py

Run AFTER 07_parse_swmm_results.py has been executed for all three LGAs:
  python scripts/07_parse_swmm_results.py --lga kosofe
  python scripts/07_parse_swmm_results.py --lga alimosho
  python scripts/07_parse_swmm_results.py --lga eti_osa
  python scripts/08_merge_swmm_results.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

SUPPORTED_LGAS = ["kosofe", "alimosho", "eti_osa"]

LGA_DISPLAY = {
    "kosofe":   "Kosofe",
    "alimosho": "Alimosho",
    "eti_osa":  "Eti-Osa",
}

OUT_GEOJSON = ROOT / "data/processed/swmm_flooding_all.geojson"
OUT_SUMMARY = ROOT / "data/processed/swmm_summary_all.json"


def _load_geojson(lga: str) -> dict | None:
    path = ROOT / f"data/processed/swmm_flooding_{lga}.geojson"
    if not path.exists():
        log.warning("Missing: %s — skipping %s (run 07_parse_swmm_results.py --lga %s first)", path, lga, lga)
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    log.info("  %s: %d flooded nodes", lga, len(data.get("features", [])))
    return data


def _load_summary(lga: str) -> dict | None:
    path = ROOT / f"data/processed/swmm_summary_{lga}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def merge_geojsons(per_lga: dict[str, dict]) -> dict:
    """
    Combine all per-LGA FeatureCollections.
    Adds "lga" and "lga_display" properties to every feature.
    """
    all_features = []
    total_meta: dict = {
        "source":          "SWMM 5.2.4 Node Flooding Summary — all Lagos LGAs",
        "design_storm_mm": 150,
        "storm_duration_hr": 4,
        "lgas_included":   [],
        "n_flooded_nodes": 0,
        "severity_counts": {"Severe": 0, "Moderate": 0, "Nuisance": 0},
        "severity_by_lga": {},
    }

    for lga, data in per_lga.items():
        feats = data.get("features", [])
        meta  = data.get("metadata", {})

        for feat in feats:
            feat["properties"]["lga"]         = lga
            feat["properties"]["lga_display"]  = LGA_DISPLAY.get(lga, lga)
            all_features.append(feat)

        total_meta["lgas_included"].append(lga)
        total_meta["n_flooded_nodes"] += meta.get("n_flooded_nodes", len(feats))

        lga_counts = meta.get("severity_counts", {})
        total_meta["severity_by_lga"][lga] = lga_counts
        for sev, cnt in lga_counts.items():
            total_meta["severity_counts"][sev] = total_meta["severity_counts"].get(sev, 0) + cnt

    # Sort all features by severity then peak rate (worst first)
    severity_order = {"Severe": 0, "Moderate": 1, "Nuisance": 2}
    all_features.sort(
        key=lambda f: (
            severity_order.get(f["properties"].get("flood_class", "Nuisance"), 3),
            -f["properties"].get("max_rate_cms", 0),
        )
    )

    return {
        "type":     "FeatureCollection",
        "features": all_features,
        "metadata": total_meta,
    }


def merge_summaries(per_lga: dict[str, dict]) -> dict:
    """Build a city-wide summary dict from per-LGA summaries."""
    combined: dict = {
        "lgas":              list(per_lga.keys()),
        "n_flooded_total":   0,
        "severity_total":    {"Severe": 0, "Moderate": 0, "Nuisance": 0},
        "by_lga":            {},
    }

    for lga, summ in per_lga.items():
        if summ is None:
            continue
        n = summ.get("n_flooded_nodes", 0)
        sc = summ.get("severity_counts", {})
        combined["n_flooded_total"] += n
        combined["by_lga"][lga] = {
            "n_flooded":      n,
            "severity":       sc,
            "pct_flooded":    summ.get("continuity", {}).get("pct_flooded"),
            "top_nodes":      summ.get("top_flooded_nodes", [])[:5],
        }
        for sev, cnt in sc.items():
            combined["severity_total"][sev] = combined["severity_total"].get(sev, 0) + cnt

    return combined


def main() -> None:
    log.info("=== FloodSight: Merge SWMM Results (all LGAs) ===")

    geo_data:  dict[str, dict] = {}
    summ_data: dict[str, dict] = {}

    for lga in SUPPORTED_LGAS:
        g = _load_geojson(lga)
        s = _load_summary(lga)
        if g is not None:
            geo_data[lga]  = g
            summ_data[lga] = s

    if not geo_data:
        log.error(
            "No per-LGA GeoJSON files found. "
            "Run 07_parse_swmm_results.py for each LGA first."
        )
        return

    log.info("Merging %d LGA(s): %s", len(geo_data), ", ".join(geo_data))

    merged_geo  = merge_geojsons(geo_data)
    merged_summ = merge_summaries(summ_data)

    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_GEOJSON.write_text(
        json.dumps(merged_geo, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %s  (%d features)", OUT_GEOJSON, len(merged_geo["features"]))

    OUT_SUMMARY.write_text(
        json.dumps(merged_summ, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %s", OUT_SUMMARY)

    log.info("")
    log.info("=== DONE ===")
    sc = merged_geo["metadata"]["severity_counts"]
    log.info(
        "  City-wide: %d flooded nodes | Severe=%d | Moderate=%d | Nuisance=%d",
        merged_geo["metadata"]["n_flooded_nodes"],
        sc.get("Severe", 0), sc.get("Moderate", 0), sc.get("Nuisance", 0),
    )
    log.info("  Next steps:")
    log.info("    1. Update dashboard/app.js to load swmm_flooding_all.geojson")
    log.info("    2. Add LGA colour-coding to the SWMM flood layer")
    log.info("    3. Cite expanded coverage in the journal paper")


if __name__ == "__main__":
    main()
