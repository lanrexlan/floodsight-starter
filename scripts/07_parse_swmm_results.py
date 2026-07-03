"""
scripts/07_parse_swmm_results.py
Parse SWMM 5.2 .rpt output -> per-LGA GeoJSON flood map for FloodSight.

Phase 17:       Kosofe pilot.
Phase 18 T3:    Extended to Alimosho and Eti-Osa.

Reads
-----
  data/processed/swmm_{lga}.rpt          SWMM status report
  data/processed/swmm_{lga}_network.gpkg Junctions layer (for coordinates)

Writes
------
  data/processed/swmm_flooding_{lga}.geojson   Flooded junction points
  data/processed/swmm_summary_{lga}.json       Run-level continuity stats

Usage
-----
  python scripts/07_parse_swmm_results.py                     # default: kosofe
  python scripts/07_parse_swmm_results.py --lga alimosho
  python scripts/07_parse_swmm_results.py --lga eti_osa
  python scripts/07_parse_swmm_results.py --lga all           # parse all three
  python scripts/07_parse_swmm_results.py "C:/path/to/custom.rpt"  # positional arg

SWMM 5.2.4 Node Flooding Summary column format (no type column):
  Node  Hours_Flooded  Max_Rate(CMS)  Day  HR:MIN  Total_Vol(10^6L)  Ponded_Depth(m)
"""

from __future__ import annotations

import argparse
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
ROOT = Path(__file__).resolve().parent.parent
UTM  = "EPSG:32631"

# All supported LGAs (must match 06_build_swmm_network.py LGA_CONFIGS keys)
SUPPORTED_LGAS = ["kosofe", "alimosho", "eti_osa"]

# LGA display names for GeoJSON metadata
LGA_DISPLAY = {
    "kosofe":   "Kosofe, Lagos",
    "alimosho": "Alimosho, Lagos",
    "eti_osa":  "Eti-Osa, Lagos",
}


# ============================================================================
# 0.  RESOLVE PATHS FOR A GIVEN LGA
# ============================================================================

def resolve_paths(lga_name: str, rpt_override: str | None = None) -> tuple[Path, Path, Path, Path]:
    """
    Return (rpt_path, net_gpkg, out_geojson, out_summary) for the given LGA.
    rpt_override: if provided (positional CLI arg), use that path for the .rpt.
    """
    rpt_default = ROOT / f"data/processed/swmm_{lga_name}.rpt"
    net_gpk     = ROOT / f"data/processed/swmm_{lga_name}_network.gpkg"
    out_geo     = ROOT / f"data/processed/swmm_flooding_{lga_name}.geojson"
    out_sum     = ROOT / f"data/processed/swmm_summary_{lga_name}.json"

    if rpt_override:
        p = Path(rpt_override)
        if p.exists():
            log.info("Using .rpt from argument: %s", p)
            return p, net_gpk, out_geo, out_sum
        log.warning("Override .rpt not found: %s", p)

    if rpt_default.exists():
        return rpt_default, net_gpk, out_geo, out_sum

    # Auto-search fallback (Windows EPA SWMM default locations)
    import os
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
            if lga_name in rpt.stem.lower() or "swmm" in rpt.stem.lower():
                log.info("Auto-found .rpt at: %s", rpt)
                return rpt, net_gpk, out_geo, out_sum

    return rpt_default, net_gpk, out_geo, out_sum


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

def load_junction_coords(net_gpk: Path) -> pd.DataFrame:
    gdf = gpd.read_file(net_gpk, layer="junctions")
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
    lga_name: str = "kosofe",
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
            "lga":               lga_name,
            "pilot_area":        LGA_DISPLAY.get(lga_name, lga_name),
            "n_flooded_nodes":   len(features),
            "severity_counts":   counts,
            "severity_basis":    "peak_overflow_rate_cms",
        },
    }


# ============================================================================
# MAIN
# ============================================================================

def _run_lga(lga_name: str, rpt_override: str | None = None) -> None:
    """Parse SWMM results for one LGA."""
    rpt, net_gpk, out_geo, out_sum = resolve_paths(lga_name, rpt_override)

    log.info("")
    log.info("=== FloodSight: Parse SWMM Results — %s ===", lga_name.upper())

    if not rpt.exists():
        log.error(
            "SWMM .rpt file not found: %s\n"
            "Run SWMM first:\n"
            "  \"C:\\Program Files\\EPA SWMM 5.2.4 (64-bit)\\runswmm.exe\" "
            "data\\processed\\swmm_%s.inp data\\processed\\swmm_%s.rpt",
            rpt, lga_name, lga_name,
        )
        return

    if not net_gpk.exists():
        log.error(
            "Network GeoPackage not found: %s\n"
            "Run first: python scripts/06_build_swmm_network.py --lga %s",
            net_gpk, lga_name,
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
            "No node flooding data found — check [REPORT] has NODES ALL "
            "in swmm_%s.inp.", lga_name,
        )
        summary = {"lga": lga_name, "continuity": continuity, "n_flooded_nodes": 0}
        out_sum.parent.mkdir(parents=True, exist_ok=True)
        out_sum.write_text(json.dumps(summary, indent=2))
        log.info("Wrote summary to %s", out_sum)
        return

    flooding["flood_class"] = flooding["max_rate_cms"].apply(classify_flood)
    log.info("Flood severity breakdown:\n%s", flooding["flood_class"].value_counts().to_string())

    log.info("Loading junction coordinates from %s ...", net_gpk)
    junctions = load_junction_coords(net_gpk)
    log.info("  %d junctions loaded", len(junctions))

    geojson = build_geojson(flooding, junctions, nonconverging, lga_name=lga_name)
    log.info("GeoJSON: %d flooded nodes with coordinates", len(geojson["features"]))

    out_geo.parent.mkdir(parents=True, exist_ok=True)
    out_geo.write_text(json.dumps(geojson, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s", out_geo)

    summary = {
        "lga":                lga_name,
        "pilot_area":         LGA_DISPLAY.get(lga_name, lga_name),
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
    out_sum.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    log.info("Wrote %s", out_sum)

    log.info("")
    pf = continuity.get("pct_flooded") or 0
    fl = continuity.get("flooding_vol_ha_m") or 0
    wi = continuity.get("wet_inflow_ha_m") or 0
    log.info("=== DONE: %s ===", lga_name.upper())
    log.info("  Key finding: %.1f%% of wet-weather inflow floods (%.0f ha-m / %.0f ha-m)", pf, fl, wi)
    log.info("  Severe   (>1.0 cms): %d", sum(1 for f in geojson["features"] if f["properties"]["flood_class"] == "Severe"))
    log.info("  Moderate (0.1-1.0):  %d", sum(1 for f in geojson["features"] if f["properties"]["flood_class"] == "Moderate"))
    log.info("  Nuisance (<0.1 cms): %d", sum(1 for f in geojson["features"] if f["properties"]["flood_class"] == "Nuisance"))
    log.info("  Next: python scripts/08_merge_swmm_results.py  (after all LGAs done)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse SWMM 5.2 .rpt results for Lagos LGAs."
    )
    parser.add_argument(
        "--lga",
        default="kosofe",
        choices=SUPPORTED_LGAS + ["all"],
        help="LGA to parse (default: kosofe). Use 'all' to parse every LGA.",
    )
    parser.add_argument(
        "rpt_path",
        nargs="?",
        default=None,
        help="Optional: explicit path to a .rpt file (overrides default path).",
    )
    args = parser.parse_args()

    if args.lga == "all":
        for lga in SUPPORTED_LGAS:
            _run_lga(lga, rpt_override=None)
    else:
        _run_lga(args.lga, rpt_override=args.rpt_path)


if __name__ == "__main__":
    main()
