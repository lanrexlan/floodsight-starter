"""
scripts/generate_paper_figures.py
Generate all six publication-quality figures for the FloodSight NHESS paper.

Output: outputs/figures/  (PNG, 300 DPI, CMYK-safe RGB palette)

Figures produced:
  Fig1_system_architecture.png
  Fig2_study_area.png
  Fig3_susceptibility_map.png
  Fig4_swmm_kosofe_network.png
  Fig5_spatial_validation.png
  Fig6_historical_validation.png

Usage (from project root):
    python scripts/generate_paper_figures.py
"""

from __future__ import annotations
import json
import warnings
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patches as patches
import matplotlib.patheffects as pe
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.lines import Line2D
from matplotlib import cm
from scipy import stats

warnings.filterwarnings("ignore")

ROOT    = Path(__file__).resolve().parent.parent
FIG_DIR = ROOT / "outputs" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

DPI = 300

# ── Shared colour palette (CMYK-safe RGB) ─────────────────────────────────
RISK_COLORS = {
    "Low":       "#2E7D5B",
    "Moderate":  "#D9A441",
    "High":      "#D9622B",
    "Very High": "#C23B3B",
}
SEVERITY_COLORS = {
    "Nuisance": "#FFF176",
    "Moderate": "#FF8F00",
    "Severe":   "#C62828",
}
NAVY   = "#1F3864"
GREY   = "#EEEEEE"
LGREY  = "#CCCCCC"
WHITE  = "#FFFFFF"

LABEL_FONT = "DejaVu Sans"
plt.rcParams.update({
    "font.family":       LABEL_FONT,
    "axes.titlesize":    10,
    "axes.labelsize":    9,
    "xtick.labelsize":   8,
    "ytick.labelsize":   8,
    "legend.fontsize":   8,
    "figure.dpi":        DPI,
    "savefig.dpi":       DPI,
    "savefig.bbox":      "tight",
    "savefig.pad_inches":0.05,
})

# ══════════════════════════════════════════════════════════════════════════════
# FIG 1 — System Architecture Flowchart
# ══════════════════════════════════════════════════════════════════════════════

def fig1_architecture():
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_xlim(0, 12); ax.set_ylim(0, 7)
    ax.axis("off")

    def box(ax, x, y, w, h, text, colour, fontsize=8, text_colour="white"):
        rect = FancyBboxPatch((x - w/2, y - h/2), w, h,
                               boxstyle="round,pad=0.07", linewidth=1.2,
                               edgecolor="white", facecolor=colour, zorder=3)
        ax.add_patch(rect)
        ax.text(x, y, text, ha="center", va="center", fontsize=fontsize,
                color=text_colour, fontweight="bold", zorder=4,
                multialignment="center")

    def arrow(ax, x1, y1, x2, y2, colour="#555555"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=colour,
                                   lw=1.4, mutation_scale=14), zorder=2)

    def section_label(ax, x, y, text):
        ax.text(x, y, text, ha="center", va="center", fontsize=7.5,
                color="#666666", style="italic")

    # Row heights
    R1, R2, R3, R4, R5 = 6.3, 5.0, 3.6, 2.3, 1.0

    # ── Row 1: Data Sources ────────────────────────────────────────────────
    ax.text(6, 6.75, "FloodSight System Architecture", ha="center",
            fontsize=13, fontweight="bold", color=NAVY)

    data_items = [
        (1.2,  "SRTM DEM\n30 m"),
        (2.8,  "ESA\nWorldCover"),
        (4.4,  "OpenStreetMap\nRoads"),
        (6.0,  "WorldPop\nDensity"),
        (7.6,  "Open-Meteo\nForecast"),
        (9.2,  "Open-Meteo\nERA5 Archive"),
        (10.8, "GADM\nBoundaries"),
    ]
    for x, lbl in data_items:
        box(ax, x, R1, 1.35, 0.70, lbl, "#455A64", fontsize=7)

    section_label(ax, 6, 6.68, "INPUT DATA (globally free, no API key required)")

    # ── Row 2: Processing ─────────────────────────────────────────────────
    proc_items = [
        (2.2,  "GIS Pipeline\n(scripts/01–05)\nElevation, HAND,\nFlow accum., Slope"),
        (5.4,  "Susceptibility\nScoring\n(Eq. 1, 200m grid)\n24,933 cells"),
        (8.6,  "SWMM 5.2\nHydraulic Model\n(Kosofe pilot)\n2,285 nodes"),
    ]
    for x, lbl in proc_items:
        box(ax, x, R2, 2.4, 0.95, lbl, NAVY, fontsize=7.5)

    # ── Row 3: Alert Engine ───────────────────────────────────────────────
    box(ax, 3.8, R3, 2.6, 0.80, "Alert Engine\n24h / 72h threshold rules\n(Lagos-calibrated)", "#6A1520", fontsize=7.5)
    box(ax, 8.2, R3, 2.6, 0.80, "Results Parser\nNode Flooding Summary\n1,185 flooded junctions", "#1A5276", fontsize=7.5)

    # ── Row 4: API ────────────────────────────────────────────────────────
    box(ax, 6.0, R4, 3.2, 0.75,
        "FastAPI Server  (Python 3.11)\n/risk/grid  |  /forecast/alerts  |  /risk/swmm-flooding",
        "#2E4053", fontsize=7.5)

    # ── Row 5: Outputs ────────────────────────────────────────────────────
    out_items = [
        (2.0,  "MapLibre GL JS\nDashboard\n3D risk map +\nSWMM flood layer", "#1B5E20"),
        (6.0,  "Supabase\nSubscription DB\nPhone numbers\n+ LGA preferences", "#4A235A"),
        (10.0, "Twilio SMS\nAlert Delivery\nWarning / Watch\nper subscriber", "#7B341E"),
    ]
    for x, lbl, col in out_items:
        box(ax, x, R5, 2.6, 0.85, lbl, col, fontsize=7.5)

    # ── Arrows ────────────────────────────────────────────────────────────
    # Data → Processing
    for dx, _ in data_items[:4]:
        arrow(ax, dx, R1 - 0.35, 2.2, R2 + 0.48)
    for dx, _ in data_items[4:]:
        arrow(ax, dx, R1 - 0.35, 8.6, R2 + 0.48)
    arrow(ax, 4.4, R1 - 0.35, 5.4, R2 + 0.48)

    # GIS Pipeline → Susceptibility
    arrow(ax, 3.4, R2, 4.1, R2)
    # Susceptibility → Alert Engine
    arrow(ax, 5.4, R2 - 0.48, 3.8, R3 + 0.40)
    # SWMM → Results Parser
    arrow(ax, 8.6, R2 - 0.48, 8.2, R3 + 0.40)
    # Alert + SWMM → API
    arrow(ax, 3.8, R3 - 0.40, 4.4, R4 + 0.38)
    arrow(ax, 8.2, R3 - 0.40, 7.6, R4 + 0.38)
    # API → Outputs
    arrow(ax, 4.4, R4 - 0.38, 2.0, R5 + 0.43)
    arrow(ax, 6.0, R4 - 0.38, 6.0, R5 + 0.43)
    arrow(ax, 7.6, R4 - 0.38, 10.0, R5 + 0.43)

    # ── Row labels ────────────────────────────────────────────────────────
    label_x = 11.7
    for y, lbl in [(R1, "Data"), (R2, "Processing"), (R3, "Engine"),
                   (R4, "API"), (R5, "Delivery")]:
        ax.text(label_x, y, lbl, ha="center", va="center", fontsize=7,
                color="#888888", style="italic",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=LGREY, lw=0.5))

    fig.patch.set_facecolor("white")
    out = FIG_DIR / "Fig1_system_architecture.png"
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ══════════════════════════════════════════════════════════════════════════════
# FIG 2 — Study Area Map
# ══════════════════════════════════════════════════════════════════════════════

def fig2_study_area():
    adm2 = gpd.read_file(ROOT / "data/raw/boundaries/NGA_ADM2.geojson")
    adm1 = gpd.read_file(ROOT / "data/raw/boundaries/NGA_ADM1.geojson")

    # Filter to Lagos State (ADM1)
    lagos_state = adm1[adm1["shapeName"].str.lower().str.contains("lagos", na=False)]
    if lagos_state.empty:
        lagos_state = adm1[adm1["shapeName"].str.lower().str.contains("lag", na=False)]

    # FloodSight LGAs
    AOI_LGAS = [
        "Agege","Ajeromi","Alimosho","Amuwo","Eti-Osa","Ifako",
        "Ikeja","Ikorodu","Kosofe","Lagos Island","Lagos Mainland",
        "Mushin","Ojo","Oshodi","Surulere"
    ]
    aoi_mask = adm2["shapeName"].apply(
        lambda n: any(lga.lower() in str(n).lower() for lga in AOI_LGAS)
    )
    aoi_lgas = adm2[aoi_mask].copy()
    kosofe = aoi_lgas[aoi_lgas["shapeName"].str.lower().str.contains("kosofe", na=False)]
    non_aoi = adm2[~aoi_mask & adm2["shapeName"].apply(
        lambda n: bool(lagos_state.geometry.iloc[0].contains(
            gpd.GeoSeries([adm2.loc[adm2["shapeName"] == n, "geometry"].iloc[0]],
                          crs=adm2.crs).iloc[0]
        )) if not adm2.loc[adm2["shapeName"] == n, "geometry"].empty else False
    )]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5),
                              gridspec_kw={"width_ratios": [1.4, 1]})

    # ── Left panel: full Lagos ─────────────────────────────────────────────
    ax = axes[0]
    adm2.plot(ax=ax, color="#EEEEEE", edgecolor="#BBBBBB", linewidth=0.3)
    if not lagos_state.empty:
        lagos_state.boundary.plot(ax=ax, color=NAVY, linewidth=1.5, zorder=4)
    aoi_lgas.plot(ax=ax, color="#B8D4E8", edgecolor="#5588AA", linewidth=0.7, zorder=2)
    if not kosofe.empty:
        kosofe.plot(ax=ax, color="#E74C3C", edgecolor="#C0392B", linewidth=1.5, zorder=3)

    # Kosofe pilot bbox rectangle
    from matplotlib.patches import Rectangle
    bbox_rect = Rectangle((3.37, 6.54), 3.50-3.37, 6.65-6.54,
                            linewidth=2, edgecolor="#C0392B",
                            facecolor="none", linestyle="--", zorder=5)
    ax.add_patch(bbox_rect)

    # LGA name labels
    for _, row in aoi_lgas.iterrows():
        cx = row.geometry.centroid.x
        cy = row.geometry.centroid.y
        if 3.0 <= cx <= 3.82 and 6.3 <= cy <= 6.82:
            name = str(row["shapeName"])
            short = name.split("-")[0][:10]
            ax.text(cx, cy, short, fontsize=5.5, ha="center", va="center",
                    color=NAVY, fontweight="bold", zorder=6)

    ax.set_xlim(2.95, 3.85); ax.set_ylim(6.25, 6.90)
    ax.set_xlabel("Longitude (°E)", fontsize=8)
    ax.set_ylabel("Latitude (°N)", fontsize=8)
    ax.set_title("(a) Lagos study area — 15 flood-prone LGAs", fontsize=9, fontweight="bold")
    ax.tick_params(labelsize=7)

    patch_aoi = mpatches.Patch(color="#B8D4E8", edgecolor="#5588AA", label="FloodSight LGAs (15)")
    patch_kos = mpatches.Patch(color="#E74C3C", edgecolor="#C0392B", label="Kosofe (SWMM pilot)")
    ax.legend(handles=[patch_aoi, patch_kos], fontsize=7, loc="upper left",
              framealpha=0.9)

    # Scale bar approx.
    ax.plot([3.65, 3.75], [6.27, 6.27], "k-", linewidth=2)
    ax.text(3.70, 6.275, "~10 km", ha="center", va="bottom", fontsize=6)

    # Inset: Nigeria context
    ax_inset = ax.inset_axes([0.70, 0.65, 0.30, 0.32])
    adm1.plot(ax=ax_inset, color="#DDDDDD", edgecolor="#AAAAAA", linewidth=0.3)
    if not lagos_state.empty:
        lagos_state.plot(ax=ax_inset, color="#E74C3C", zorder=2)
    ax_inset.set_xlim(2.5, 15); ax_inset.set_ylim(4, 14)
    ax_inset.axis("off")
    ax_inset.set_title("Nigeria", fontsize=6)
    ax_inset.patch.set_edgecolor("#AAAAAA")
    ax_inset.patch.set_linewidth(0.8)

    # ── Right panel: Kosofe zoom ─────────────────────────────────────────
    ax2 = axes[1]
    adm2.plot(ax=ax2, color="#EEEEEE", edgecolor="#BBBBBB", linewidth=0.5)
    if not kosofe.empty:
        kosofe.plot(ax=ax2, color="#FADBD8", edgecolor="#C0392B", linewidth=1.8, zorder=3)

    # Try to add water bodies
    water_path = ROOT / "data/raw/osm/clipped/water.gpkg"
    if water_path.exists():
        water = gpd.read_file(water_path).to_crs("EPSG:4326")
        water.plot(ax=ax2, color="#AED6F1", edgecolor="#5DADE2", linewidth=0.5, zorder=4)

    # Try to add roads
    roads_path = ROOT / "data/raw/osm/clipped/roads.gpkg"
    if roads_path.exists():
        roads = gpd.read_file(roads_path).to_crs("EPSG:4326")
        major = roads[roads["highway"].isin(["motorway","trunk","primary","secondary"])] if "highway" in roads.columns else roads
        major.plot(ax=ax2, color="#888888", linewidth=0.5, zorder=5)

    ax2.set_xlim(3.35, 3.52); ax2.set_ylim(6.52, 6.67)
    ax2.set_xlabel("Longitude (°E)", fontsize=8)
    ax2.set_title("(b) Kosofe LGA — SWMM pilot area\n(bbox: 3.37–3.50°E, 6.54–6.65°N)", fontsize=9, fontweight="bold")
    ax2.tick_params(labelsize=7)
    ax2.set_ylabel("")

    # North arrow
    ax2.annotate("N", xy=(3.505, 6.655), fontsize=9, fontweight="bold",
                 ha="center", va="bottom")
    ax2.annotate("", xy=(3.505, 6.658), xytext=(3.505, 6.648),
                 arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))

    plt.suptitle("Figure 2. Study area: Lagos State, Nigeria", fontsize=10,
                 fontweight="bold", y=1.01)
    plt.tight_layout()
    out = FIG_DIR / "Fig2_study_area.png"
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ══════════════════════════════════════════════════════════════════════════════
# FIG 3 — Flood Susceptibility Map
# ══════════════════════════════════════════════════════════════════════════════

def fig3_susceptibility():
    grid = gpd.read_file(ROOT / "data/processed/scored_grid.gpkg").to_crs("EPSG:4326")
    adm2 = gpd.read_file(ROOT / "data/raw/boundaries/NGA_ADM2.geojson")

    fig, axes = plt.subplots(1, 2, figsize=(13, 6),
                              gridspec_kw={"width_ratios": [1.6, 1]})

    # ── Left panel: choropleth map ────────────────────────────────────────
    ax = axes[0]
    adm2.plot(ax=ax, color="#EEEEEE", edgecolor="#CCCCCC", linewidth=0.3, zorder=1)

    order = ["Low", "Moderate", "High", "Very High"]
    for rc in order:
        subset = grid[grid["risk_class"] == rc]
        subset.plot(ax=ax, color=RISK_COLORS[rc], linewidth=0, zorder=2, alpha=0.85)

    ax.set_xlim(2.98, 3.82); ax.set_ylim(6.28, 6.82)
    ax.set_xlabel("Longitude (°E)", fontsize=8)
    ax.set_ylabel("Latitude (°N)", fontsize=8)
    ax.set_title("(a) Flood susceptibility — 15 LGAs, 200-m grid (n = 24,933 cells)",
                 fontsize=9, fontweight="bold")
    ax.tick_params(labelsize=7)

    handles = [mpatches.Patch(color=RISK_COLORS[rc], label=rc) for rc in order]
    ax.legend(handles=handles, title="Risk Class", fontsize=8, title_fontsize=8,
              loc="upper left", framealpha=0.9)

    # ── Right panel: histogram + class stats ─────────────────────────────
    ax2 = axes[1]
    scores = grid["flood_score"].dropna()
    n, bins, patches_ = ax2.hist(scores, bins=40, edgecolor="white", linewidth=0.3)

    # colour histogram bars by risk class
    breaks = [(0.00, 0.53, "Low"), (0.53, 0.58, "Moderate"),
              (0.58, 0.64, "High"), (0.64, 1.01, "Very High")]
    for bar, left in zip(patches_, bins[:-1]):
        for lo, hi, rc in breaks:
            if lo <= left < hi:
                bar.set_facecolor(RISK_COLORS[rc])
                break

    # Vertical threshold lines
    for lo, _, rc in breaks[1:]:
        ax2.axvline(lo, color="#333333", linewidth=0.8, linestyle="--", zorder=5)
        ax2.text(lo + 0.002, ax2.get_ylim()[1] * 0.95 if ax2.get_ylim()[1] > 0 else 200,
                 f"{lo}", fontsize=6, color="#333333", rotation=90, va="top")

    counts = grid["risk_class"].value_counts()
    text = "\n".join([f"{rc}: {counts.get(rc,0):,} cells ({100*counts.get(rc,0)/len(grid):.1f}%)"
                      for rc in order])
    ax2.text(0.98, 0.97, text, transform=ax2.transAxes, fontsize=7.5,
             va="top", ha="right",
             bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=LGREY, lw=0.8))

    ax2.set_xlabel("Flood score (0–1)", fontsize=8)
    ax2.set_ylabel("Number of grid cells", fontsize=8)
    ax2.set_title("(b) Distribution of flood scores\n(quartile risk-class breaks, Lagos AOI)",
                  fontsize=9, fontweight="bold")
    ax2.tick_params(labelsize=7)
    ax2.text(0.03, 0.97, f"n = {len(grid):,} cells\nMean = {scores.mean():.3f}\nSD = {scores.std():.3f}",
             transform=ax2.transAxes, fontsize=7.5, va="top",
             bbox=dict(boxstyle="round,pad=0.3", fc=GREY, ec=LGREY, lw=0.5))

    plt.suptitle("Figure 3. FloodSight flood susceptibility map — Lagos, Nigeria",
                 fontsize=10, fontweight="bold", y=1.01)
    plt.tight_layout()
    out = FIG_DIR / "Fig3_susceptibility_map.png"
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ══════════════════════════════════════════════════════════════════════════════
# FIG 4 — SWMM Kosofe Network + Flooded Nodes
# ══════════════════════════════════════════════════════════════════════════════

def fig4_swmm_network():
    net   = gpd.read_file(ROOT / "data/processed/swmm_kosofe_network.gpkg",
                           layer="junctions").to_crs("EPSG:4326")
    conds = gpd.read_file(ROOT / "data/processed/swmm_kosofe_network.gpkg",
                           layer="conduits").to_crs("EPSG:4326")
    with open(ROOT / "data/processed/swmm_flooding.geojson") as f:
        gj = json.load(f)

    flood_pts = gpd.GeoDataFrame.from_features(gj["features"], crs="EPSG:4326")
    adm2 = gpd.read_file(ROOT / "data/raw/boundaries/NGA_ADM2.geojson")

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.5))

    for ax_i, ax in enumerate(axes):
        adm2.plot(ax=ax, color="#F5F5F5", edgecolor="#CCCCCC", linewidth=0.5, zorder=1)
        conds.plot(ax=ax, color="#AAAAAA", linewidth=0.3, zorder=2, label="Conduit")

        if ax_i == 0:
            # Left: all junctions, coloured by flooded/non-flooded
            non_flood = net[~net["name"].isin(flood_pts["node_id"])]
            flood_all = net[net["name"].isin(flood_pts["node_id"])]
            non_flood.plot(ax=ax, color="#2196F3", markersize=0.6,
                           zorder=3, label=f"Non-flooded ({len(non_flood):,})")
            flood_all.plot(ax=ax, color="#F44336", markersize=1.2,
                           zorder=4, label=f"Flooded ({len(flood_all):,})")
            ax.set_title("(a) SWMM drainage network — Kosofe pilot\n"
                         f"{len(net):,} junctions | {len(conds):,} conduits | 150 mm / 4-h storm",
                         fontsize=9, fontweight="bold")
            h1 = Line2D([0], [0], color="#AAAAAA", lw=1, label="Conduit (600 mm ⌀)")
            h2 = Line2D([0], [0], marker="o", color="w", markerfacecolor="#2196F3",
                        markersize=5, label=f"Non-flooded ({len(non_flood):,})")
            h3 = Line2D([0], [0], marker="o", color="w", markerfacecolor="#F44336",
                        markersize=5, label=f"Flooded ({len(flood_all):,})")
            ax.legend(handles=[h1, h2, h3], fontsize=7, loc="lower right", framealpha=0.9)
        else:
            # Right: flooded nodes coloured by severity
            for sev, col in SEVERITY_COLORS.items():
                sub = flood_pts[flood_pts["flood_class"] == sev]
                ms = {"Nuisance": 2, "Moderate": 3, "Severe": 5}.get(sev, 3)
                sub.plot(ax=ax, color=col, markersize=ms, zorder=5,
                         edgecolor="none" if sev == "Nuisance" else "#333333",
                         linewidth=0.2)
            ax.set_title("(b) SWMM flooded junctions by severity class\n"
                         "(Severe > 1.0 m³/s | Moderate 0.1–1.0 | Nuisance < 0.1)",
                         fontsize=9, fontweight="bold")
            handles = [
                Line2D([0],[0], marker="o", color="w",
                       markerfacecolor=SEVERITY_COLORS[sev], markersize=ms+2,
                       label=f"{sev} ({(flood_pts['flood_class']==sev).sum():,})")
                for sev, ms in [("Nuisance", 4), ("Moderate", 5), ("Severe", 7)]
            ]
            ax.legend(handles=handles, fontsize=7, loc="lower right", framealpha=0.9)

        ax.set_xlim(3.35, 3.52); ax.set_ylim(6.52, 6.67)
        ax.set_xlabel("Longitude (°E)", fontsize=8)
        ax.set_ylabel("Latitude (°N)" if ax_i == 0 else "", fontsize=8)
        ax.tick_params(labelsize=7)

    plt.suptitle("Figure 4. SWMM 5.2 Kosofe pilot drainage network and flooded junctions",
                 fontsize=10, fontweight="bold", y=1.01)
    plt.tight_layout()
    out = FIG_DIR / "Fig4_swmm_kosofe_network.png"
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ══════════════════════════════════════════════════════════════════════════════
# FIG 5 — Spatial Validation (flood rate + peak rate by risk class)
# ══════════════════════════════════════════════════════════════════════════════

def fig5_spatial_validation():
    # Rebuild data (same analysis as generate_swmm_validation.py)
    grid = gpd.read_file(ROOT / "data/processed/scored_grid.gpkg").to_crs("EPSG:32631")
    net  = gpd.read_file(ROOT / "data/processed/swmm_kosofe_network.gpkg",
                          layer="junctions").to_crs("EPSG:32631")
    net  = net[~net["is_outfall"]].copy()

    with open(ROOT / "data/processed/swmm_flooding.geojson") as f:
        gj = json.load(f)
    flood_ids   = {feat["properties"]["node_id"] for feat in gj["features"]}
    flood_props = {feat["properties"]["node_id"]: feat["properties"] for feat in gj["features"]}

    net["flooded"] = net["name"].isin(flood_ids)

    # Clip to Kosofe bbox
    net_wgs = net.to_crs("EPSG:4326")
    mask = ((net_wgs.geometry.x >= 3.37) & (net_wgs.geometry.x <= 3.50) &
            (net_wgs.geometry.y >= 6.54) & (net_wgs.geometry.y <= 6.65))
    net = net[mask].copy()

    joined = gpd.sjoin_nearest(
        net[["name", "flooded", "geometry"]],
        grid[["risk_class", "flood_score", "geometry"]],
        how="left", max_distance=500,
    ).drop_duplicates("name").dropna(subset=["risk_class"])

    RISK_ORDER = ["Low", "Moderate", "High", "Very High"]
    joined_f = joined[joined["flooded"]].copy()
    joined_f["max_rate_cms"] = joined_f["name"].map(
        lambda n: flood_props.get(n, {}).get("max_rate_cms"))
    joined_f = joined_f.dropna(subset=["max_rate_cms"])

    # ── Figure layout ─────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.5))

    # Panel (a): Flood rate by risk class
    ax = axes[0]
    counts = joined.groupby("risk_class")["flooded"].agg(["sum", "count"]).reindex(RISK_ORDER)
    rates  = (counts["sum"] / counts["count"] * 100).values
    colors = [RISK_COLORS[rc] for rc in RISK_ORDER]
    bars = ax.bar(RISK_ORDER, rates, color=colors, edgecolor="white", linewidth=0.8, zorder=3)
    ax.axhline(y=rates[:3].mean(), color="#333333", linewidth=1.2, linestyle="--",
               zorder=4, label=f"Low/Mod/High mean ({rates[:3].mean():.1f}%)")
    for bar, rate, n in zip(bars, rates, counts["count"].values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.8,
                f"{rate:.1f}%\n(n={n:,})", ha="center", va="bottom", fontsize=7.5)
    ax.set_ylabel("SWMM overflow rate (%)", fontsize=9)
    ax.set_xlabel("Susceptibility Risk Class", fontsize=9)
    ax.set_title("(a) Flood occurrence rate\nby risk class", fontsize=9, fontweight="bold")
    ax.set_ylim(0, 95)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(fontsize=7.5)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.text(0.97, 0.03, f"χ² = 87.98, df = 3\np < 0.001",
            transform=ax.transAxes, fontsize=8, va="bottom", ha="right",
            bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", ec="#CCCC00", lw=0.8))

    # Panel (b): Boxplot of peak rate by risk class
    ax2 = axes[1]
    data_by_class = [joined_f[joined_f["risk_class"] == rc]["max_rate_cms"].values
                     for rc in RISK_ORDER]
    bp = ax2.boxplot(data_by_class, patch_artist=True,
                     medianprops=dict(color="black", linewidth=1.5),
                     whiskerprops=dict(linewidth=1.0),
                     capprops=dict(linewidth=1.0),
                     flierprops=dict(marker=".", markersize=2, alpha=0.5))
    for patch, rc in zip(bp["boxes"], RISK_ORDER):
        patch.set_facecolor(RISK_COLORS[rc])
        patch.set_alpha(0.8)
    ax2.set_yscale("log")
    ax2.set_xticklabels(RISK_ORDER, fontsize=8)
    ax2.set_ylabel("Peak overflow rate (m³/s, log scale)", fontsize=9)
    ax2.set_xlabel("Susceptibility Risk Class", fontsize=9)
    ax2.set_title("(b) Peak overflow rate distribution\nby risk class (flooded nodes only)",
                  fontsize=9, fontweight="bold")
    ax2.grid(axis="y", alpha=0.3)
    means = [joined_f[joined_f["risk_class"]==rc]["max_rate_cms"].mean() for rc in RISK_ORDER]
    ax2.plot(range(1, 5), means, "D--", color="black", markersize=5,
             label="Mean", linewidth=1.0, zorder=5)
    for i, (rc, m) in enumerate(zip(RISK_ORDER, means)):
        ax2.text(i+1, m*1.3, f"{m:.2f}", ha="center", va="bottom", fontsize=7)
    ax2.legend(fontsize=7.5)
    ax2.text(0.97, 0.03, "Kruskal-Wallis\nH = 10.56, p = 0.014",
             transform=ax2.transAxes, fontsize=8, va="bottom", ha="right",
             bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", ec="#CCCC00", lw=0.8))

    # Panel (c): Mean rate trend with 95% CI bootstrap
    ax3 = axes[2]
    means_arr = np.array(means)
    ci_low, ci_high = [], []
    rng = np.random.default_rng(42)
    for rc in RISK_ORDER:
        vals = joined_f[joined_f["risk_class"]==rc]["max_rate_cms"].dropna().values
        boot = [rng.choice(vals, len(vals), replace=True).mean() for _ in range(2000)]
        ci_low.append(np.percentile(boot, 2.5))
        ci_high.append(np.percentile(boot, 97.5))

    x = np.arange(4)
    ax3.bar(x, means_arr, color=colors, edgecolor="white", linewidth=0.8,
            alpha=0.8, zorder=3)
    ax3.errorbar(x, means_arr,
                 yerr=[means_arr - np.array(ci_low), np.array(ci_high) - means_arr],
                 fmt="none", color="black", capsize=5, linewidth=1.5, zorder=4)
    for i, (m, lo, hi) in enumerate(zip(means_arr, ci_low, ci_high)):
        ax3.text(i, hi + 0.05, f"{m:.2f}", ha="center", va="bottom", fontsize=7.5,
                 fontweight="bold")
    ax3.set_xticks(x); ax3.set_xticklabels(RISK_ORDER, fontsize=8)
    ax3.set_ylabel("Mean peak overflow rate (m³/s)", fontsize=9)
    ax3.set_xlabel("Susceptibility Risk Class", fontsize=9)
    ax3.set_title("(c) Mean peak rate ± 95% CI\n(bootstrap, n = 2,000)",
                  fontsize=9, fontweight="bold")
    ax3.grid(axis="y", alpha=0.3, zorder=0)
    ax3.text(0, means_arr[-1]*0.85, f"2.9× ratio\n(Low → Very High)", fontsize=8,
             color="#333333", style="italic")

    plt.suptitle("Figure 5. Spatial validation: SWMM flood behaviour vs. susceptibility risk class",
                 fontsize=10, fontweight="bold", y=1.02)
    plt.tight_layout()
    out = FIG_DIR / "Fig5_spatial_validation.png"
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ══════════════════════════════════════════════════════════════════════════════
# FIG 6 — Historical Alert Validation
# ══════════════════════════════════════════════════════════════════════════════

def fig6_historical_validation():
    with open(ROOT / "outputs/validation_results.json") as f:
        val = json.load(f)
    events = val["events"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    names = [e["name"].replace(" Lagos Floods", "").replace(" Floods", "")
             for e in events]
    r24 = [e["rain_24h_mm"] for e in events]
    r72 = [e["rain_72h_mm"] for e in events]
    correct = [e["correct"] for e in events]
    predicted = [e["predicted_alert"] for e in events]

    # Thresholds (from config.py)
    WARN_24, WARN_72 = 70, 100
    WATCH_24, WATCH_72 = 25, 40

    x = np.arange(len(events))
    w = 0.35

    # ── Left: 24h and 72h rainfall bars ──────────────────────────────────
    ax = axes[0]
    bar1 = ax.bar(x - w/2, r24, w, label="24-h rainfall (ERA5)", color="#2196F3",
                  edgecolor="white", linewidth=0.5, alpha=0.85)
    bar2 = ax.bar(x + w/2, r72, w, label="72-h rainfall (ERA5)", color="#0D47A1",
                  edgecolor="white", linewidth=0.5, alpha=0.85)

    # Threshold lines
    ax.axhline(WARN_24, color="#C62828", linewidth=1.5, linestyle="-",
               label=f"Warning threshold (24h = {WARN_24} mm)")
    ax.axhline(WARN_72, color="#C62828", linewidth=1.5, linestyle="--",
               label=f"Warning threshold (72h = {WARN_72} mm)")
    ax.axhline(WATCH_24, color="#F57F17", linewidth=1.0, linestyle="-",
               label=f"Watch threshold (24h = {WATCH_24} mm)")
    ax.axhline(WATCH_72, color="#F57F17", linewidth=1.0, linestyle="--",
               label=f"Watch threshold (72h = {WATCH_72} mm)")

    # Correct/incorrect markers
    for i, (c, pred) in enumerate(zip(correct, predicted)):
        colour = "#1B5E20" if c else "#B71C1C"
        symbol = "✓" if c else "✗"
        ax.text(i, max(r24[i], r72[i]) + 3, symbol, ha="center", va="bottom",
                fontsize=12, color=colour, fontweight="bold")
        pred_short = {"Warning": "WARN", "Watch": "WTCH", "No Alert": "—"}.get(pred, pred)
        ax.text(i, -8, pred_short, ha="center", va="top", fontsize=6.5,
                color={"Warning": "#C62828", "Watch": "#F57F17", "No Alert": "#555"}.get(pred, "#555"))

    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=35, ha="right", fontsize=7.5)
    ax.set_ylabel("Rainfall accumulation (mm, ERA5)", fontsize=9)
    ax.set_title("(a) ERA5 rainfall vs. FloodSight alert thresholds\n(✓ = correct alert, ✗ = miss)",
                 fontsize=9, fontweight="bold")
    ax.legend(fontsize=6.5, loc="upper right", ncol=1)
    ax.set_ylim(-15, max(max(r24), max(r72)) * 1.18)
    ax.grid(axis="y", alpha=0.3)
    ax.text(0.02, 0.97, f"Overall accuracy: 4/8 events (50%)\nKosofe-specific: 2/3 (67%)",
            transform=ax.transAxes, fontsize=8, va="top",
            bbox=dict(boxstyle="round,pad=0.3", fc="lightyellow", ec="#CCCC00", lw=0.8))

    # ── Right: Confusion-style summary ───────────────────────────────────
    ax2 = axes[1]

    # Scatter: 24h vs 72h, coloured by outcome
    colours_pts = []
    markers_pts = []
    for e in events:
        pred = e["predicted_alert"]
        c = e["correct"]
        if pred == "Warning":
            colours_pts.append("#C62828")
            markers_pts.append("^")
        elif pred == "Watch":
            colours_pts.append("#F57F17")
            markers_pts.append("s")
        else:
            colours_pts.append("#777777")
            markers_pts.append("o")

    for i, (e, col, mk) in enumerate(zip(events, colours_pts, markers_pts)):
        ec = "#1B5E20" if e["correct"] else "#B71C1C"
        ax2.scatter(e["rain_24h_mm"], e["rain_72h_mm"], c=col, marker=mk, s=120,
                    edgecolors=ec, linewidth=2.0, zorder=5)
        ax2.text(e["rain_24h_mm"] + 1, e["rain_72h_mm"] + 1,
                 names[i][:12], fontsize=6.5, color="#333333")

    # Threshold regions
    ax2.axvline(WARN_24, color="#C62828", linewidth=1.3, linestyle="-", alpha=0.7)
    ax2.axhline(WARN_72, color="#C62828", linewidth=1.3, linestyle="--", alpha=0.7)
    ax2.axvline(WATCH_24, color="#F57F17", linewidth=1.0, linestyle="-", alpha=0.7)
    ax2.axhline(WATCH_72, color="#F57F17", linewidth=1.0, linestyle="--", alpha=0.7)

    ax2.set_xlabel("24-h ERA5 rainfall (mm)", fontsize=9)
    ax2.set_ylabel("72-h ERA5 rainfall (mm)", fontsize=9)
    ax2.set_title("(b) 24-h vs. 72-h rainfall — event scatter\n(shape = FloodSight alert; edge = ✓ green / ✗ red)",
                  fontsize=9, fontweight="bold")
    ax2.grid(alpha=0.25)

    h_warn = Line2D([0],[0], marker="^", color="w", markerfacecolor="#C62828",
                    markersize=9, label="Warning issued")
    h_watch = Line2D([0],[0], marker="s", color="w", markerfacecolor="#F57F17",
                     markersize=8, label="Watch issued")
    h_none = Line2D([0],[0], marker="o", color="w", markerfacecolor="#777777",
                    markersize=8, label="No Alert issued")
    h_corr = Line2D([0],[0], marker="o", color="w", markerfacecolor="w",
                    markeredgecolor="#1B5E20", markeredgewidth=2, markersize=8, label="Correct")
    h_miss = Line2D([0],[0], marker="o", color="w", markerfacecolor="w",
                    markeredgecolor="#B71C1C", markeredgewidth=2, markersize=8, label="Miss")
    ax2.legend(handles=[h_warn, h_watch, h_none, h_corr, h_miss],
               fontsize=7, loc="upper left", framealpha=0.9)

    plt.suptitle("Figure 6. FloodSight historical alert validation — eight Lagos flood events (2011–2023)",
                 fontsize=10, fontweight="bold", y=1.02)
    plt.tight_layout()
    out = FIG_DIR / "Fig6_historical_validation.png"
    fig.savefig(out, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"Generating figures → {FIG_DIR}/")
    print()

    tasks = [
        ("Fig 1: System Architecture",       fig1_architecture),
        ("Fig 2: Study Area Map",             fig2_study_area),
        ("Fig 3: Susceptibility Map",         fig3_susceptibility),
        ("Fig 4: SWMM Kosofe Network",        fig4_swmm_network),
        ("Fig 5: Spatial Validation",         fig5_spatial_validation),
        ("Fig 6: Historical Validation",      fig6_historical_validation),
    ]

    for name, fn in tasks:
        print(f"→ {name} ...")
        try:
            fn()
        except Exception as exc:
            print(f"  ERROR: {exc}")
            import traceback; traceback.print_exc()

    print()
    files = sorted(FIG_DIR.glob("*.png"))
    print(f"Done. {len(files)} figures written to {FIG_DIR}/")
    for f in files:
        kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({kb} KB)")
    print()
    print("For NHESS submission: all figures should be ≥ 300 DPI (confirmed),")
    print("RGB colour mode, and submitted as separate .png files.")
    print("Recommended figure widths: single-column = 8.3 cm, double-column = 17.4 cm.")


if __name__ == "__main__":
    main()
