"""
scripts/07_parse_swmm_results.py
Parse SWMM 5.2 .rpt output -> GeoJSON flood map for FloodSight dashboard.

Reads
-----
  data/processed/swmm_kosofe.rpt          SWMM status report
  data/processed/swmm_kosofe_network.gpkg Junctions layer (for coordinates)

Writes
------
  data/processed/swmm_flooding.geojson    Flooded junction points
  data/processed/swmm_summary.json        Run-level continuity stats

Usage
-----
  python scripts/07_parse_swmm_results.py
  python scripts/07_parse_swmm_results.py "C:/path/to/swmm_kosofe.rpt"

SWMM 5.2.4 Node Flooding Summary column format (no type column):
  Node  Hours_Flooded  Max_Rate(CMS)  Day  HR:MIN  Total_Vol(10^6L)  Ponded_Depth(m)
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# -- Paths -------------------------------------------------------------------
ROOT        = Path(__file__).resolve().parent.parent
RPT_DEFAULT = ROOT / "data/processed/swmm_kosofe.rpt"
NET_GPK     = ROOT / "data/processed/swmm_kosofe_network.gpkg"
OUT_GEOJSON = ROOT / "data/processed/swmm_flooding.geojson"
OUT_SUMMARY = ROOT / "data/processed/swmm_summary.json"

UTM = "EPSG:32631"


# ============================================================================
# 0.  LOCATE .RPT FILE
# ============================================================================

def resolve_rpt_path() -> Path:
    import os
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            log.info("Using .rpt from argument: %s", p)
            return p
        log.warning("Argument path not found: %s", p)
    if RPT_DEFAULT.exists():
        return RPT_DEFAULT
    search_roots = [
        Path(os.environ.get("USERPROFILE", "")),
        Path(os.environ.get("TEMP", "")),
        Path("C:/Program Files/EPA SWMM 5.2.4 (64-bit)"),
        Path("C:/Program Files (x86)/EPA SWMM 5.2"),
    ]
    for root in search_roots:
        if not root.exists():
            continue
        for rpt in root.rglob("*.rpt"):
            if "kosofe" in rpt.stem.lower() or "swmm" in rpt.stem.lower():
                log.info("Auto-found .rpt at: %s", rpt)
                return rpt
    return RPT_DEFAULT


# ============================================================================
# 1.  PARSE .RPT FILE
# ============================================================================

def _find_section(lines: list[str], header: str) -> int:
    h = header.lower()
    for i, ln in enumerate(lines):
        if h in ln.lower():
            return i
    return -1


def parse_node_flooding(lines: list[str]) -> pd.DataFrame:
    """
    Parse the 'Node Flooding Summary' table from the .rpt file.

    SWMM 5.2.4 row format (no 'type' column, time split across two tokens):
      Node   Hours_Flooded   Max_Rate(CMS)   Day   HR:MIN   Total_Vol(10e6L)   Ponded_Depth(m)
      J0002       5.30           2.209         0    02:30       21.261             0.000

    parts indices:
      [0]=node_id  [1]=hours_flooded  [2]=max_rate_cms
      [3]=day  [4]=hr:min(skip)  [5]=total_vol_10e6l  [6]=max_ponded_m
    """
    rows = []
    idx = _find_section(lines, "Node Flooding Summary")
    if idx == -1:
        log.warning("'Node Flooding Summary' section not found in .rpt file.")
        return pd.DataFrame()

    # Scan up to 35 lines for first data row (starts with J or O)
    data_start = idx
    for i in range(idx, min(idx + 35, len(lines))):
        ln = lines[i].strip()
        if ln and (ln.startswith("J") or ln.startswith("O")):
            data_start = i
            break

    for ln in lines[data_start:]:
        stripped = ln.strip()
        if not stripped:
            break
        if stripped.startswith("----") or stripped.startswith("****"):
            break
        parts = stripped.split()
        # Need at least 7 tokens; parts[4] is "HH:MM" so float() will raise for it
        if len(parts) >= 7 and (parts[0].startswith("J") or parts[0].startswith("O")):
            try:
                rows.append({
                    "node_id":         parts[0],
                    "hours_flooded":   float(parts[1]),
                    "max_rate_cms":    float(parts[2]),
                    # parts[3]=day, parts[4]=hr:min -- skip both
                    "total_vol_10e6l": float(parts[5]),
                    "max_ponded_m":    float(parts[6]),
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)
    log.info("Node Flooding Summary: %d flooded nodes parsed", len(df))
    return df


def parse_continuity(lines: list[str]) -> dict:
    """Extract Runoff and Flow Routing continuity tables."""
    result: dict = {}

    def _extract_pct(section_header: str) -> float | None:
        idx = _find_section(lines, section_header)
        if idx == -1:
            return None
        for ln in lines[idx: idx + 20]:
            if "Continuity Error" in ln:
                m = re.search(r"[-+]?\d+\.\d+", ln)
                if m:
                    return float(m.group(0))
        return None

    def _extract_volume(section_header: str, label: str) -> float | None:
        idx = _find_section(lines, section_header)
        if idx == -1:
            return None
        for ln in lines[idx: idx + 30]:
            if label.lower() in ln.lower():
                m = re.search(r"[\d,]+\.\d+", ln)
                if m:
                    return float(m.group(0).replace(",", ""))
        return None

    result["runoff_continuity_error_pct"] = _extract_pct("Runoff Quantity Continuity")
    result["routing_continuity_error_pct"] = _extract_pct("Flow Routing Continuity")
    result["total_precip_mm"]   = _extract_volume("Runoff Quantity Continuity", "Total Precipitation")
    result["surface_runoff_mm"] = _extract_volume("Runoff Quantity Continuity", "Surface Runoff")
    result["infiltration_mm"]   = _extract_volume("Runoff Quantity Continuity", "Infiltration Loss")
    result["flooding_vol_ha_m"] = _extract_volume("Flow Routing Continuity", "Flooding Loss")
    result["outflow_vol_ha_m"]  = _extract_volume("Flow Routing Continuity", "External Outflow")
    result["wet_inflow_ha_m"]   = _extract_volume("Flow Routing Continuity", "Wet Weather Inflow")

    if result["wet_inflow_ha_m"] and result["flooding_vol_ha_m"]:
        result["pct_flooded"] = round(
            100.0 * result["flooding_vol_ha_m"] / result["wet_inflow_ha_m"], 2
        )
    else:
        result["pct_flooded"] = None

    log.info(
        "Continuity: runoff_err=%.3f%%, routing_err=%.3f%%, pct_flooded=%.1f%%",
        result.get("runoff_continuity_error_pct") or 0,
        result.get("routing_continuity_error_pct") or 0,
        result.get("pct_flooded") or 0,
    )
    return result


def parse_nonconverging(lines: list[str]) -> list[dict]:
    """Parse 'Most Frequent Nonconverging Nodes' table.
    Handles both 'JXXXX (XX%)' and 'Node JXXXX (XX%)' formats."""
    rows = []
    idx = _find_section(lines, "Most Frequent Nonconverging Nodes")
    if idx == -1:
        return rows
    for ln in lines[idx + 1: idx + 20]:
        stripped = ln.strip()
        if not stripped or stripped.startswith("*"):
            break
        parts = stripped.split()
        # Find first token starting with J or O
        node_id = None
        for p in parts:
            if p.startswith("J") or p.startswith("O"):
                node_id = p
                break
        if node_id:
            m = re.search(r"([\d.]+)%", ln)
            if m:
                rows.append({"node_id": node_id, "pct_nonconverging": float(m.group(1))})
    return rows


# ============================================================================
# 2.  CLASSIFY FLOOD SEVERITY
# ============================================================================

def classify_flood(max_rate_cms: float) -> str:
    """
    Flood severity class by peak overflow rate (SWMM 5.2.4 has no depth column).
    Calibrated to Lagos road drainage capacity:
      < 0.1 cms  -> Nuisance  (minor ponding, road passable)
      0.1-1.0cms -> Moderate  (road impacted, property risk)
      > 1.0 cms  -> Severe    (life safety risk, structure inundation)
    """
    if max_rate_cms < 0.1:
        return "Nuisance"
    elif max_rate_cms < 1.0:
        return "Moderate"
    else:
        return "Severe"


FLOOD_COLOUR = {
    "Nuisance":  "#FFF176",
    "Moderate":  "#FF8F00",
    "Severe":    "#C62828",
}


# ============================================================================
# 3.  JOIN TO NETWORK COORDINATES
# ============================================================================

def load_junction_coords() -> pd.DataFrame:
    gdf = gpd.read_file(NET_GPK, layer="junctions")
    gdf_wgs = gdf.to_crs("EPSG:4326")
    return pd.DataFrame({
        "node_id":      gdf["name"],
        "lon":          gdf_wgs.geometry.x,
        "lat":          gdf_wgs.geometry.y,
        "elevation_m":  gdf["elevation_m"],
        "is_outfall":   gdf["is_outfall"],
    })


# ============================================================================
# 4.  BUILD GEOJSON
# ============================================================================

def build_geojson(
    flooding: pd.DataFrame,
    junctions: pd.DataFrame,
    nonconverging: list[dict],
) -> dict:
    nc_map = {r["node_id"]: r["pct_nonconverging"] for r in nonconverging}

    merged = flooding.merge(junctions, on="node_id", how="left")
    missing = merged["lon"].isna().sum()
    if missing:
        log.warning("  %d flooded nodes have no coordinates (subnetwork mismatch)", missing)
    merged = merged.dropna(subset=["lon", "lat"])

    features = []
    for _, row in merged.iterrows():
        flood_class = classify_flood(float(row["max_rate_cms"]))
        feat = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(float(row["lon"]), 6), round(float(row["lat"]), 6)],
            },
            "properties": {
                "node_id":           row["node_id"],
                "hours_flooded":     round(float(row["hours_flooded"]), 2),
                "max_rate_cms":      round(float(row["max_rate_cms"]), 3),
                "total_vol_10e6l":   round(float(row["total_vol_10e6l"]), 3),
                "max_ponded_m":      round(float(row["max_ponded_m"]), 3),
                "elevation_m":       round(float(row["elevation_m"]), 2),
                "flood_class":       flood_class,
                "colour":            FLOOD_COLOUR[flood_class],
                "pct_nonconverging": nc_map.get(row["node_id"]),
                "label": (
                    f"{row['node_id']} | {flood_class} | "
                    f"rate={row['max_rate_cms']:.2f}cms | "
                    f"flooded={row['hours_flooded']:.1f}h | "
                    f"vol={row['total_vol_10e6l']:.1f}e6L"
                ),
            },
        }
        features.append(feat)

    features.sort(key=lambda f: -f["properties"]["max_rate_cms"])

    counts = merged["max_rate_cms"].apply(classify_flood).value_counts().to_dict()
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source":            "SWMM 5.2.4 Node Flooding Summary",
            "design_storm_mm":   150,
            "storm_duration_hr": 4,
            "pilot_area":        "Kosofe, Lagos",
            "n_flooded_nodes":   len(features),
            "severity_counts":   counts,
            "severity_basis":    "peak_overflow_rate_cms",
        },
    }


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    log.info("=== FloodSight: Parse SWMM Results ===")

    rpt = resolve_rpt_path()

    if not rpt.exists():
        log.error(
            "SWMM .rpt file not found.\n\n"
            "Run:  \"C:\\Program Files\\EPA SWMM 5.2.4 (64-bit)\\runswmm.exe\" "
            "data\\processed\\swmm_kosofe.inp data\\processed\\swmm_kosofe.rpt\n"
            "Then: python scripts/07_parse_swmm_results.py\n"
        )
        return

    if not NET_GPK.exists():
        log.error(
            "Network GeoPackage not found at %s -- run 06_build_swmm_network.py first.",
            NET_GPK,
        )
        return

    log.info("Reading %s ...", rpt)
    lines = rpt.read_text(encoding="utf-8", errors="replace").splitlines()
    log.info("  %d lines in .rpt file", len(lines))

    flooding      = parse_node_flooding(lines)
    continuity    = parse_continuity(lines)
    nonconverging = parse_nonconverging(lines)

    if flooding.empty:
        log.warning(
            "No node flooding data found in .rpt.\n"
            "Check that [REPORT] section has NODES ALL in swmm_kosofe.inp."
        )
        summary = {"continuity": continuity, "n_flooded_nodes": 0}
        OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        OUT_SUMMARY.write_text(json.dumps(summary, indent=2))
        log.info("Wrote summary to %s", OUT_SUMMARY)
        return

    flooding["flood_class"] = flooding["max_rate_cms"].apply(classify_flood)
    log.info("Flood severity breakdown:\n%s", flooding["flood_class"].value_counts().to_string())

    log.info("Loading junction coordinates from network GeoPackage ...")
    junctions = load_junction_coords()
    log.info("  %d junctions in network GeoPackage", len(junctions))

    geojson = build_geojson(flooding, junctions, nonconverging)
    log.info("GeoJSON: %d flooded nodes with coordinates", len(geojson["features"]))

    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_GEOJSON.write_text(json.dumps(geojson, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s", OUT_GEOJSON)

    summary = {
        "continuity":         continuity,
        "n_flooded_nodes":    len(geojson["features"]),
        "severity_counts":    geojson["metadata"]["severity_counts"],
        "top_flooded_nodes": (
            flooding.nlargest(10, "max_rate_cms")
            [["node_id", "hours_flooded", "max_rate_cms", "total_vol_10e6l"]]
            .to_dict(orient="records")
        ),
        "nonconverging_nodes": nonconverging,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    log.info("Wrote %s", OUT_SUMMARY)

    log.info("")
    log.info("=== DONE ===")
    pf = continuity.get("pct_flooded") or 0
    fl = continuity.get("flooding_vol_ha_m") or 0
    wi = continuity.get("wet_inflow_ha_m") or 0
    log.info("  Key finding: %.1f%% of wet-weather inflow floods (%.0f ha-m / %.0f ha-m)", pf, fl, wi)
    log.info("  Severe nodes (>1.0 cms peak rate):  %d", sum(1 for f in geojson["features"] if f["properties"]["flood_class"] == "Severe"))
    log.info("  Moderate nodes (0.1-1.0 cms):       %d", sum(1 for f in geojson["features"] if f["properties"]["flood_class"] == "Moderate"))
    log.info("  Nuisance nodes (<0.1 cms):           %d", sum(1 for f in geojson["features"] if f["properties"]["flood_class"] == "Nuisance"))
    log.info("  Next steps:")
    log.info("    1. Add swmm_flooding.geojson as a layer in dashboard/app.js")
    log.info("    2. Compare flooded nodes against Phase 10 historical events")
    log.info("    3. Cite continuity stats in journal paper methods section")


if __name__ == "__main__":
    main()
