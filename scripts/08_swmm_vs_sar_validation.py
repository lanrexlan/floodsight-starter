"""
scripts/08_swmm_vs_sar_validation.py

Validate SWMM 5.2 flooded junctions against Sentinel-1 SAR flood extents
(Phase 10 historical events).

Approach:
  - Two SAR flood-extent rasters (binary 0/1, UTM 32631):
      flood_extent_20210710.tif  → July 2011-era proxy (nearest archival)
      flood_extent_20240704.tif  → July 2024 event
  - SWMM flooded junctions (1,185 points) from data/processed/swmm_flooding.geojson
  - For each raster: count how many SWMM flooded/non-flooded junctions fall
    inside SAR-confirmed flood pixels.
  - Also map Phase 10 events to LGAs that overlap the Kosofe pilot area.

Outputs:
  outputs/swmm_sar_validation.json   — detailed statistics
  outputs/figures/Fig_SAR_overlap.png — 2-panel map (one per SAR scene)

Usage:
    python scripts/08_swmm_vs_sar_validation.py
"""

from __future__ import annotations
import json, warnings
from pathlib import Path

import numpy as np
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape
import pandas as pd

warnings.filterwarnings("ignore")

ROOT    = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs"
FIG_DIR = ROOT / "outputs" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

UTM = "EPSG:32631"
WGS = "EPSG:4326"

# ── Kosofe pilot bbox in UTM 31N (approx) ─────────────────────────────────
# 3.37–3.50 °E, 6.54–6.65 °N → projected
KOSOFE_BBOX_WGS = (3.37, 6.54, 3.50, 6.65)

SAR_FILES = {
    "2021-07-10": ROOT / "data/raw/sentinel1/flood_extent_20210710.tif",
    "2024-07-04": ROOT / "data/raw/sentinel1/flood_extent_20240704.tif",
}

# ── Phase 10 event notes for each SAR scene ───────────────────────────────
SAR_EVENT_NOTES = {
    "2021-07-10": (
        "Nearest available SAR archive to July 2011 Lagos floods "
        "(Kosofe/Alimosho/Ojo). NEMA: thousands displaced."
    ),
    "2024-07-04": (
        "July 2024 Lagos floods — Ikorodu Road corridor / Kosofe LGA. "
        "Flash flooding following intense storm."
    ),
}

# ──────────────────────────────────────────────────────────────────────────
def raster_to_flood_poly(tif_path: Path) -> gpd.GeoDataFrame:
    """Convert binary flood raster to vector polygons (flooded pixels only)."""
    with rasterio.open(tif_path) as src:
        arr = src.read(1)
        transform = src.transform
        crs = src.crs
        # vectorise only flooded pixels (value == 1)
        mask = (arr == 1).astype(np.uint8)
        geom_val = list(shapes(mask, mask=mask, transform=transform))
    if not geom_val:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    geoms = [shape(g) for g, v in geom_val if v == 1]
    return gpd.GeoDataFrame(geometry=geoms, crs=crs)


def load_swmm_nodes() -> gpd.GeoDataFrame:
    path = ROOT / "data/processed/swmm_flooding.geojson"
    if not path.exists():
        raise FileNotFoundError(f"Run scripts/07 first: {path}")
    flooded = gpd.read_file(path).to_crs(UTM)
    flooded["flooded"] = True

    # Load full junction network for non-flooded too
    net_path = ROOT / "data/processed/swmm_kosofe_network.gpkg"
    if net_path.exists():
        net = gpd.read_file(net_path, layer="junctions").to_crs(UTM)
        net = net[~net.get("is_outfall", pd.Series(False, index=net.index))]
        # clip to Kosofe bbox (WGS84 → UTM)
        net_wgs = net.to_crs(WGS)
        x, y = net_wgs.geometry.x, net_wgs.geometry.y
        mask = (x >= 3.37) & (x <= 3.50) & (y >= 6.54) & (y <= 6.65)
        net = net[mask].copy()
        net["flooded"] = net["name"].isin(flooded["node_id"])
        net["node_id"] = net["name"]
        for col in ["flood_class", "max_rate_cms", "hours_flooded",
                    "total_vol_10e6l", "colour"]:
            if col not in net.columns:
                net[col] = None
        flood_props = flooded.set_index("node_id")
        for col in ["flood_class", "max_rate_cms", "hours_flooded",
                    "total_vol_10e6l", "colour"]:
            if col in flood_props.columns:
                net.loc[net["flooded"], col] = net.loc[net["flooded"], "node_id"].map(
                    flood_props[col]
                )
        return net
    else:
        # Fallback: only return the flooded nodes
        return flooded


def overlap_stats(nodes: gpd.GeoDataFrame,
                  flood_poly: gpd.GeoDataFrame) -> dict:
    """For each node, check if it falls within the SAR flood polygon."""
    if flood_poly.empty:
        return {"error": "No flood polygons in this SAR scene"}

    # Spatial join: points within flood polygons
    joined = gpd.sjoin(nodes, flood_poly, how="left", predicate="within")
    within_sar = ~joined["index_right"].isna()

    flooded_mask   = nodes["flooded"]
    n_total        = len(nodes)
    n_swmm_flooded = flooded_mask.sum()
    n_swmm_nonflooded = (~flooded_mask).sum()

    # True positives: SWMM says flooded AND in SAR flood extent
    tp = (flooded_mask & within_sar).sum()
    # False positives: SWMM says flooded but NOT in SAR extent
    fp = (flooded_mask & ~within_sar).sum()
    # False negatives: SWMM says NOT flooded but IS in SAR extent
    fn = (~flooded_mask & within_sar).sum()
    # True negatives: SWMM says NOT flooded and NOT in SAR extent
    tn = (~flooded_mask & ~within_sar).sum()

    sar_extent_nodes = within_sar.sum()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    pct_swmm_flooded_in_sar = tp / n_swmm_flooded * 100 if n_swmm_flooded > 0 else 0.0
    pct_sar_extent_swmm_flooded = tp / sar_extent_nodes * 100 if sar_extent_nodes > 0 else 0.0

    return {
        "n_total_junctions":          int(n_total),
        "n_swmm_flooded":             int(n_swmm_flooded),
        "n_swmm_nonflooded":          int(n_swmm_nonflooded),
        "n_nodes_in_sar_extent":      int(sar_extent_nodes),
        "true_positives_tp":          int(tp),
        "false_positives_fp":         int(fp),
        "false_negatives_fn":         int(fn),
        "true_negatives_tn":          int(tn),
        "precision":                  round(precision, 3),
        "recall":                     round(recall, 3),
        "f1_score":                   round(f1, 3),
        "pct_swmm_flooded_in_sar":    round(pct_swmm_flooded_in_sar, 1),
        "pct_sar_in_swmm_flooded":    round(pct_sar_extent_swmm_flooded, 1),
    }


def plot_overlap(nodes: gpd.GeoDataFrame,
                 within_flags: list[pd.Series],
                 labels: list[str],
                 titles: list[str]):
    """2-panel map of SAR flood extents vs SWMM junction status."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.5))

    RISK_COLORS = {
        "Severe":   "#C62828",
        "Moderate": "#FF8F00",
        "Nuisance": "#FFF176",
    }

    for ax, within, label, title in zip(axes, within_flags, labels, titles):
        # SAR flood footprint background: nodes in SAR extent
        sar_bg = nodes[within].copy()
        sar_bg.plot(ax=ax, color="#AED6F1", markersize=12, marker="s",
                    zorder=2, label="SAR flood extent", alpha=0.5)

        # Non-flooded junctions
        non_flood = nodes[~nodes["flooded"]]
        non_flood.plot(ax=ax, color="#90A4AE", markersize=1.2, zorder=3,
                       label=f"Non-flooded ({len(non_flood):,})")

        # SWMM flooded junctions, coloured by severity
        for sev, col in RISK_COLORS.items():
            if "flood_class" in nodes.columns:
                sub = nodes[nodes["flooded"] & (nodes["flood_class"] == sev)]
            else:
                sub = nodes[nodes["flooded"]]
            ms = {"Nuisance": 3, "Moderate": 5, "Severe": 7}.get(sev, 4)
            sub.plot(ax=ax, color=col, markersize=ms, zorder=5,
                     edgecolor="#333333", linewidth=0.3,
                     label=f"SWMM {sev} ({len(sub):,})")

        # TP ring: SWMM-flooded AND in SAR extent
        tp_nodes = nodes[nodes["flooded"] & within]
        tp_nodes.plot(ax=ax, color="none", markersize=14, marker="o",
                      edgecolor="#00E676", linewidth=1.8, zorder=6,
                      label=f"SAR ∩ SWMM flooded ({len(tp_nodes):,})")

        ax.set_xlim(*nodes.total_bounds[[0, 2]])
        ax.set_ylim(*nodes.total_bounds[[1, 3]])
        ax.set_title(title, fontsize=9, fontweight="bold")
        ax.set_xlabel("Easting (m, UTM 31N)", fontsize=8)
        ax.set_ylabel("Northing (m, UTM 31N)", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7, loc="lower right", framealpha=0.9,
                  markerscale=1.2)

    plt.suptitle(
        "SWMM flooded junctions vs. Sentinel-1 SAR flood extents — Kosofe pilot",
        fontsize=10, fontweight="bold", y=1.01
    )
    plt.tight_layout()
    out = FIG_DIR / "Fig_SAR_overlap.png"
    fig.savefig(out, dpi=300, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")
    return out


# ──────────────────────────────────────────────────────────────────────────
def main():
    print("Loading SWMM junctions ...")
    nodes = load_swmm_nodes()
    print(f"  {len(nodes):,} junctions in Kosofe pilot area "
          f"({nodes['flooded'].sum():,} SWMM-flooded)")

    results = {}
    within_flags = []

    for date, tif_path in SAR_FILES.items():
        print(f"\nProcessing SAR scene {date} ...")
        flood_poly = raster_to_flood_poly(tif_path)
        print(f"  {len(flood_poly):,} flood polygons vectorised from SAR")

        stats = overlap_stats(nodes, flood_poly)
        stats["sar_date"] = date
        stats["sar_file"] = tif_path.name
        stats["event_note"] = SAR_EVENT_NOTES[date]
        results[date] = stats

        # Build per-node SAR-within flag for the map
        if not flood_poly.empty:
            joined = gpd.sjoin(nodes, flood_poly, how="left", predicate="within")
            within = ~joined["index_right"].isna()
        else:
            within = pd.Series(False, index=nodes.index)
        within_flags.append(within)

        print(f"  TP={stats.get('true_positives_tp',0)}  "
              f"FP={stats.get('false_positives_fp',0)}  "
              f"FN={stats.get('false_negatives_fn',0)}  "
              f"TN={stats.get('true_negatives_tn',0)}")
        print(f"  Precision={stats.get('precision',0):.3f}  "
              f"Recall={stats.get('recall',0):.3f}  "
              f"F1={stats.get('f1_score',0):.3f}")
        print(f"  {stats.get('pct_swmm_flooded_in_sar',0):.1f}% of SWMM-flooded nodes "
              f"fall inside SAR flood extent")

    # ── Phase 10 LGA-level match ────────────────────────────────────────────
    kosofe_events = []
    with open(ROOT / "outputs/validation_results.json") as f:
        val = json.load(f)
    for ev in val["events"]:
        areas_lower = ev["areas"].lower()
        if "kosofe" in areas_lower or "gbagada" in areas_lower or "ikorodu" in areas_lower:
            kosofe_events.append({
                "id": ev["id"],
                "name": ev["name"],
                "areas": ev["areas"],
                "predicted_alert": ev["predicted_alert"],
                "correct": ev["correct"],
            })
    results["phase10_kosofe_events"] = kosofe_events

    # ── Plot ────────────────────────────────────────────────────────────────
    print("\nGenerating overlap map ...")
    plot_labels = list(SAR_FILES.keys())
    plot_titles = [
        f"(a) SAR {plot_labels[0]}\n(July 2011 flood proxy — {results[plot_labels[0]].get('true_positives_tp',0)} SWMM ∩ SAR nodes)",
        f"(b) SAR {plot_labels[1]}\n(July 2024 event — {results[plot_labels[1]].get('true_positives_tp',0)} SWMM ∩ SAR nodes)",
    ]
    plot_overlap(nodes, within_flags, plot_labels, plot_titles)

    # ── Save JSON ────────────────────────────────────────────────────────────
    out_json = OUT_DIR / "swmm_sar_validation.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {out_json.name}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("SWMM vs SAR VALIDATION SUMMARY")
    print("="*60)
    for date, s in results.items():
        if date == "phase10_kosofe_events":
            continue
        print(f"\n  Scene: {date}  ({s['event_note'][:60]}...)")
        print(f"    Nodes in SAR flood extent : {s['n_nodes_in_sar_extent']:,}")
        print(f"    SWMM-flooded in SAR (TP)  : {s['true_positives_tp']:,} "
              f"({s['pct_swmm_flooded_in_sar']:.1f}% of SWMM-flooded)")
        print(f"    Precision / Recall / F1   : "
              f"{s['precision']:.3f} / {s['recall']:.3f} / {s['f1_score']:.3f}")

    print(f"\n  Phase 10 events overlapping Kosofe pilot:")
    for ev in kosofe_events:
        flag = "✓" if ev["correct"] else "✗"
        print(f"    {flag} {ev['name']} — {ev['areas']}")

    print()


if __name__ == "__main__":
    main()
