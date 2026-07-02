"""
scripts/06_build_swmm_network.py
Phase 17 — Approximate SWMM 5.2 drainage network, Kosofe pilot area.

Approach
--------
Real pipe-dimension data for Lagos is held by the Office of Drainage Services
(Dar Al-Handasah master plan, not public).  Until that data is obtained, we
build a physically plausible network from open data:

  • Conduit skeleton   OSM arterial roads (primary / secondary / tertiary) —
                       in Lagos drainage channels run alongside major roads.
                       Canal / river polygon centrelines from water.gpkg are
                       added as open-channel conduits.
  • Pipe diameters     Road-class proxy (see DIAMETER_M below).
  • Elevations         DEM-derived elevation_m column from scored_grid.gpkg.
  • Subcatchments      Voronoi polygons clipped to pilot bbox; area +
                       imperviousness estimated from grid landcover_class.
  • Outfalls           Lowest-elevation boundary nodes (≤ 5 m).

Outputs
-------
  data/processed/swmm_kosofe.inp          Valid SWMM 5.2 input file
  data/processed/swmm_kosofe_network.gpkg Junctions + conduits for QGIS

Usage
-----
  python scripts/06_build_swmm_network.py

Dependencies (already in requirements.txt):
  geopandas, shapely, numpy, scipy, networkx
"""

from __future__ import annotations

import logging
import math
import textwrap
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.spatial import KDTree, Voronoi
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import split, unary_union

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
ROADS_GPK  = ROOT / "data/raw/osm/clipped/roads.gpkg"
WATER_GPK  = ROOT / "data/raw/osm/clipped/water.gpkg"
GRID_GPK   = ROOT / "data/processed/scored_grid.gpkg"
OUT_INP    = ROOT / "data/processed/swmm_kosofe.inp"
OUT_NET    = ROOT / "data/processed/swmm_kosofe_network.gpkg"

# ── Kosofe pilot bounding box (WGS-84) ──────────────────────────────────────
BBOX_WGS84 = (3.37, 6.54, 3.50, 6.65)   # (min_lon, min_lat, max_lon, max_lat)
BBOX_BOX   = box(*BBOX_WGS84)

# ── UTM zone 31N — metric CRS for Lagos ──────────────────────────────────────
UTM = "EPSG:32631"

# ── Drainage network road types (will be used as conduit skeleton) ────────────
ARTERIAL_TYPES = {
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
}

# ── Pipe diameter proxy (m) by highway / waterway type ───────────────────────
DIAMETER_M: dict[str, float] = {
    "canal":          2.0,   # open channel
    "river":          3.0,   # major open channel
    "tidal_channel":  3.0,
    "primary":        1.2,
    "primary_link":   1.2,
    "secondary":      0.9,
    "secondary_link": 0.9,
    "tertiary":       0.6,
    "tertiary_link":  0.6,
    "residential":    0.375,
    "unclassified":   0.375,
    "_default":       0.375,
}

MANNINGS_N = 0.013  # concrete-lined pipe / brick culvert

# ── SWMM subcatchment defaults ────────────────────────────────────────────────
IMPERV_BY_LANDCOVER = {
    "urban_high":  0.90,
    "urban_low":   0.70,
    "mixed":       0.55,
    "vegetation":  0.30,
    "water":       0.05,
    "_default":    0.65,  # Lagos average
}

# ── Snap tolerance for joining road endpoints into junctions (metres) ─────────
SNAP_TOL = 15.0


# ════════════════════════════════════════════════════════════════════════════
# 1. LOAD & CLIP DATA
# ════════════════════════════════════════════════════════════════════════════

def _load_roads() -> gpd.GeoDataFrame:
    log.info("Loading roads …")
    roads = gpd.read_file(ROADS_GPK)
    roads = roads.to_crs("EPSG:4326")

    # Clip to pilot bbox
    roads = roads[roads.geometry.intersects(BBOX_BOX)].copy()

    # Keep arterial types only
    if "highway" in roads.columns:
        roads = roads[roads["highway"].isin(ARTERIAL_TYPES)].copy()
    else:
        log.warning("No 'highway' column found — using all road features.")

    log.info("  %d arterial road segments in Kosofe", len(roads))
    return roads.to_crs(UTM)


def _load_canals() -> gpd.GeoDataFrame:
    """Extract canal / river polygon centrelines from water.gpkg."""
    log.info("Loading water polygons …")
    water = gpd.read_file(WATER_GPK)
    water = water.to_crs("EPSG:4326")

    canal_types = {"canal", "river", "tidal_channel", "drain"}
    if "water" in water.columns:
        canals = water[water["water"].isin(canal_types)].copy()
    else:
        canals = gpd.GeoDataFrame(columns=["geometry", "water"], crs="EPSG:4326")

    # Clip to pilot bbox
    canals = canals[canals.geometry.intersects(BBOX_BOX)].copy()

    # Convert polygon → centreline using bounding-box longest axis midpoints
    # (simple proxy; a proper skeleton would need scikit-geometry)
    def poly_to_line(geom):
        if geom.is_empty:
            return None
        if geom.geom_type in ("LineString", "MultiLineString"):
            return geom
        # Use minimum rotated rectangle centreline
        try:
            bb = geom.minimum_rotated_rectangle
            coords = list(bb.exterior.coords)
            # midpoints of the two long sides
            def midpt(a, b):
                return ((a[0]+b[0])/2, (a[1]+b[1])/2)
            m1 = midpt(coords[0], coords[1])
            m2 = midpt(coords[2], coords[3])
            return LineString([m1, m2])
        except Exception:
            return LineString([geom.centroid.coords[0], geom.centroid.coords[0]])

    canals["geometry"] = canals["geometry"].apply(poly_to_line)
    canals = canals[canals["geometry"].notna()].copy()
    canals["highway"] = canals["water"].map(lambda x: x if x else "canal")
    log.info("  %d canal/river centrelines in Kosofe", len(canals))
    return canals.to_crs(UTM) if len(canals) else gpd.GeoDataFrame(columns=["geometry","highway"], crs=UTM)


def _load_grid() -> gpd.GeoDataFrame:
    log.info("Loading scored grid …")
    grid = gpd.read_file(GRID_GPK)  # already UTM 32631
    # Clip to pilot bbox
    bbox_utm = gpd.GeoSeries([BBOX_BOX], crs="EPSG:4326").to_crs(UTM).iloc[0]
    grid = grid[grid.geometry.intersects(bbox_utm)].copy()
    log.info("  %d grid cells in Kosofe", len(grid))
    return grid


# ════════════════════════════════════════════════════════════════════════════
# 2. BUILD GRAPH NETWORK
# ════════════════════════════════════════════════════════════════════════════

def _snap_point(pt: tuple[float,float], index: dict, coords: list, tol: float) -> int:
    """Return node id for point, creating new one if none within tol."""
    for nid, c in index.items():
        if math.hypot(pt[0]-c[0], pt[1]-c[1]) < tol:
            return nid
    nid = len(coords)
    coords.append(pt)
    index[nid] = pt
    return nid


def build_graph(roads: gpd.GeoDataFrame, canals: gpd.GeoDataFrame):
    """
    Build a directed drainage graph from road/canal centrelines.

    Returns
    -------
    G           networkx.DiGraph
    node_coords list of (x, y) in UTM
    edge_data   list of dicts with conduit attributes
    """
    log.info("Building drainage graph …")

    G = nx.DiGraph()
    node_index: dict[int, tuple] = {}
    node_coords: list[tuple] = []
    edge_data: list[dict] = []

    all_geoms = []
    for _, row in roads.iterrows():
        hw = row.get("highway", "_default")
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiLineString":
            for part in geom.geoms:
                all_geoms.append((part, hw))
        else:
            all_geoms.append((geom, hw))

    for _, row in canals.iterrows() if len(canals) else []:
        hw = row.get("highway", "canal")
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiLineString":
            for part in geom.geoms:
                all_geoms.append((part, hw))
        else:
            all_geoms.append((geom, hw))

    for geom, hw in all_geoms:
        if geom.geom_type != "LineString":
            continue
        coords_list = list(geom.coords)
        if len(coords_list) < 2:
            continue

        start_pt = coords_list[0]
        end_pt   = coords_list[-1]
        u = _snap_point(start_pt, node_index, node_coords, SNAP_TOL)
        v = _snap_point(end_pt,   node_index, node_coords, SNAP_TOL)

        if u == v:
            continue  # degenerate segment

        length = geom.length
        diam   = DIAMETER_M.get(hw, DIAMETER_M["_default"])

        G.add_edge(u, v)
        edge_data.append({
            "from_node": u,
            "to_node":   v,
            "length_m":  max(length, 1.0),
            "highway":   hw,
            "diameter_m": diam,
            "geom":      geom,
        })

    log.info("  Graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G, node_coords, edge_data


# ════════════════════════════════════════════════════════════════════════════
# 3. ASSIGN ELEVATIONS TO NODES
# ════════════════════════════════════════════════════════════════════════════

def assign_elevations(node_coords: list[tuple], grid: gpd.GeoDataFrame) -> np.ndarray:
    """Nearest-neighbour lookup: node → elevation_m from scored_grid."""
    log.info("Assigning elevations to %d nodes …", len(node_coords))

    grid_ctr = np.column_stack([
        grid.geometry.centroid.x,
        grid.geometry.centroid.y,
    ])
    elev_vals = grid["elevation_m"].to_numpy(dtype=float)
    tree = KDTree(grid_ctr)

    pts = np.array(node_coords)
    _, idx = tree.query(pts, k=1)
    elevations = elev_vals[idx]
    log.info("  Elevation range: %.1f – %.1f m", elevations.min(), elevations.max())
    return elevations


# ════════════════════════════════════════════════════════════════════════════
# 4. ORIENT EDGES DOWNSLOPE
# ════════════════════════════════════════════════════════════════════════════

def orient_downslope(edge_data: list[dict], elevations: np.ndarray) -> list[dict]:
    """Flip any edge whose from_node is lower than to_node."""
    for e in edge_data:
        u, v = e["from_node"], e["to_node"]
        if elevations[u] < elevations[v]:
            e["from_node"], e["to_node"] = v, u
            e["geom"] = LineString(list(e["geom"].coords)[::-1])
    return edge_data


# ════════════════════════════════════════════════════════════════════════════
# 5. IDENTIFY OUTFALLS
# ════════════════════════════════════════════════════════════════════════════

def find_outfalls(
    G2: nx.DiGraph,
    node_coords: list[tuple],
    elevations: np.ndarray,
) -> tuple[set[int], list[tuple], np.ndarray, list[dict]]:
    """
    SWMM ERROR 141: an outfall must have exactly 1 inlet link and 0 outlet links.

    Dead-end road nodes naturally have multiple incoming conduits, so marking
    them as outfalls directly always triggers ERROR 141.

    Strategy (single virtual outfall):
    ─────────────────────────────────
    1. Find the lowest-elevation dead-end sink in the network.
    2. Keep it as a junction (it may have many inlets — that's fine for a junction).
    3. Add ONE new virtual outfall node 50 m south of that sink.
    4. Connect: primary_sink → virtual_outfall via a stub conduit (in=1, out=0 ✓).
    5. All other dead-end nodes stay as junctions; water ponds there — physically
       correct for Lagos's blocked, undersized drainage system.

    Returns
    -------
    outfalls        set containing only the virtual node id
    new_coords      updated node_coords list (virtual node appended)
    new_elevs       updated elevations array (virtual node appended)
    extra_edges     list containing the single stub conduit dict
    """
    log.info("Creating single virtual outfall …")

    # Dead-end sinks in the directed graph
    sinks = [
        nid for nid in range(len(node_coords))
        if G2.has_node(nid) and G2.out_degree(nid) == 0
    ]
    if not sinks:
        sinks = list(range(len(node_coords)))

    # Lowest-elevation sink → primary discharge point (toward Lagos Lagoon)
    primary_sink = min(sinks, key=lambda n: float(elevations[n]))
    sx, sy = node_coords[primary_sink]
    log.info("  Primary sink: node %d (elev=%.2f m) at UTM (%.0f, %.0f)",
             primary_sink, elevations[primary_sink], sx, sy)

    # Virtual outfall node: 50 m south, 0.5 m lower
    virt_id   = len(node_coords)
    virt_elev = max(0.0, float(elevations[primary_sink]) - 0.5)
    vx, vy    = sx, sy - 50.0

    new_coords = list(node_coords) + [(vx, vy)]
    new_elevs  = np.append(elevations, virt_elev)

    # Stub conduit: primary_sink → virtual outfall
    stub = {
        "from_node":  primary_sink,
        "to_node":    virt_id,
        "length_m":   50.0,
        "highway":    "primary",
        "diameter_m": 2.0,   # wide collector so it never throttles
        "geom":       LineString([(sx, sy), (vx, vy)]),
    }

    log.info("  Virtual outfall: node %d at UTM (%.0f, %.0f), elev=%.2f m",
             virt_id, vx, vy, virt_elev)
    log.info("  All other dead-ends remain as junctions (water ponds — correct for Lagos)")

    return {virt_id}, new_coords, new_elevs, [stub]


# ════════════════════════════════════════════════════════════════════════════
# 6. SUBCATCHMENTS (Voronoi)
# ════════════════════════════════════════════════════════════════════════════

def build_subcatchments(
    node_coords: list[tuple],
    grid: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Voronoi tessellation around junction nodes, clipped to pilot bbox.
    Subcatchment attributes (area, %imperv) from scored_grid cells.
    """
    log.info("Building subcatchments …")

    if len(node_coords) < 4:
        log.warning("Too few nodes for Voronoi; skipping subcatchments.")
        return gpd.GeoDataFrame(columns=["junction","area_ha","pct_imperv","geometry"], crs=UTM)

    pts = np.array(node_coords)
    bbox_utm = gpd.GeoSeries([BBOX_BOX], crs="EPSG:4326").to_crs(UTM).iloc[0]
    clip_poly = bbox_utm

    # Add mirror points to bound the Voronoi diagram
    xmin, ymin, xmax, ymax = clip_poly.bounds
    margin = max(xmax - xmin, ymax - ymin) * 0.5
    mirror = np.array([
        [xmin - margin, ymin - margin],
        [xmax + margin, ymin - margin],
        [xmax + margin, ymax + margin],
        [xmin - margin, ymax + margin],
    ])
    all_pts = np.vstack([pts, mirror])

    vor = Voronoi(all_pts)

    # Build polygon for each original point (not mirror points)
    regions = []
    for i in range(len(pts)):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        if -1 in region or len(region) == 0:
            # Infinite region — clip to bbox
            poly = clip_poly
        else:
            verts = [vor.vertices[v] for v in region]
            poly = Polygon(verts)
        poly = poly.intersection(clip_poly)
        regions.append(poly)

    # Join to grid to get imperviousness
    sub_gdf = gpd.GeoDataFrame(
        {"junction": list(range(len(pts))), "geometry": regions},
        crs=UTM,
    )

    # Spatial join to grid
    grid_sub = grid[["landcover_class", "geometry"]].copy()
    joined = gpd.sjoin(grid_sub, sub_gdf, how="left", predicate="within")

    def imperv_for_sub(junc_id):
        cells = joined[joined["index_right"] == junc_id]["landcover_class"]
        if len(cells) == 0:
            return IMPERV_BY_LANDCOVER["_default"]
        counts = cells.value_counts()
        dominant = counts.index[0] if len(counts) > 0 else "_default"
        return IMPERV_BY_LANDCOVER.get(dominant, IMPERV_BY_LANDCOVER["_default"])

    sub_gdf["area_ha"]    = sub_gdf.geometry.area / 10_000.0
    sub_gdf["pct_imperv"] = sub_gdf["junction"].apply(imperv_for_sub)

    log.info("  %d subcatchments built", len(sub_gdf))
    return sub_gdf


# ════════════════════════════════════════════════════════════════════════════
# 7. WRITE SWMM .INP FILE
# ════════════════════════════════════════════════════════════════════════════

def _junc_name(nid: int) -> str:
    return f"J{nid:04d}"

def _cond_name(idx: int) -> str:
    return f"C{idx:04d}"

def _sub_name(nid: int) -> str:
    return f"S{nid:04d}"

def _outfall_name(nid: int) -> str:
    return f"O{nid:04d}"


def write_swmm_inp(
    node_coords:  list[tuple],
    elevations:   np.ndarray,
    edge_data:    list[dict],
    outfalls:     set[int],
    subcatchments: gpd.GeoDataFrame,
    out_path:     Path,
) -> None:
    log.info("Writing SWMM input file …")

    junctions = [nid for nid in range(len(node_coords)) if nid not in outfalls]
    outfall_list = sorted(outfalls)

    lines: list[str] = []

    # ── [TITLE] ─────────────────────────────────────────────────────────────
    lines += [
        "[TITLE]",
        "FloodSight — Kosofe Pilot Drainage Network (approximate)",
        "Generated by scripts/06_build_swmm_network.py",
        "Pipe sizes are road-class proxies; validate against field survey.",
        "",
    ]

    # ── [OPTIONS] ────────────────────────────────────────────────────────────
    lines += [
        "[OPTIONS]",
        ";;Option              Value",
        "FLOW_UNITS           CMS",
        "INFILTRATION         GREEN_AMPT",
        "FLOW_ROUTING         DYNWAVE",
        "LINK_OFFSETS         DEPTH",
        "MIN_SLOPE            0.001",
        "ALLOW_PONDING        YES",
        "SKIP_STEADY_STATE    NO",
        "START_DATE           07/01/2026",
        "START_TIME           00:00:00",
        "REPORT_START_DATE    07/01/2026",
        "REPORT_START_TIME    00:00:00",
        "END_DATE             07/01/2026",
        "END_TIME             06:00:00",
        "SWEEP_START          01/01",
        "SWEEP_END            12/31",
        "DRY_DAYS             0",
        "REPORT_STEP          00:05:00",
        "WET_STEP             00:01:00",
        "DRY_STEP             01:00:00",
        "ROUTING_STEP         0:00:30",
        "RULE_STEP            00:00:00",
        "INERTIAL_DAMPING     PARTIAL",
        "NORMAL_FLOW_LIMITED  SLOPE",
        "FORCE_MAIN_EQUATION  H-W",
        "VARIABLE_STEP        0.75",
        "LENGTHENING_STEP     0",
        "MIN_SURFAREA         12.566",
        "MAX_TRIALS           8",
        "HEAD_TOLERANCE       0.0015",
        "SYS_FLOW_TOL         5",
        "LAT_FLOW_TOL         5",
        "MINIMUM_STEP         0.5",
        "THREADS              1",
        "",
    ]

    # ── [EVAPORATION] ────────────────────────────────────────────────────────
    lines += [
        "[EVAPORATION]",
        ";;Data Source    Parameters",
        "CONSTANT         5.0",
        "DRY_ONLY         NO",
        "",
    ]

    # ── [RAINGAGES] ─────────────────────────────────────────────────────────
    # One gage — data will be loaded from a .dat file (user supplies)
    lines += [
        "[RAINGAGES]",
        ";;Name           Format    Interval SCF      Source",
        "RG1              INTENSITY 0:30     1.0      TIMESERIES TS_RAIN",
        "",
    ]

    # ── [TIMESERIES] ─────────────────────────────────────────────────────────
    # Example: 90 mm in 3 hours (Lagos-typical heavy event, triangular pattern)
    ts = [
        ("00:00", 0.0),
        ("00:30", 20.0),
        ("01:00", 45.0),
        ("01:30", 70.0),
        ("02:00", 90.0),
        ("02:30", 50.0),
        ("03:00", 20.0),
        ("03:30", 5.0),
        ("04:00", 0.0),
    ]
    lines += ["[TIMESERIES]", ";;Name           Date       Time       Value"]
    for t, v in ts:
        lines.append(f"TS_RAIN                     {t}       {v:.1f}")
    lines.append("")

    # ── [JUNCTIONS] ──────────────────────────────────────────────────────────
    lines += [
        "[JUNCTIONS]",
        ";;Name           Elevation  MaxDepth   InitDepth  SurDepth   Aponded",
    ]
    for nid in junctions:
        elev = float(elevations[nid])
        lines.append(f"{_junc_name(nid):<17}{elev:<11.3f}2          0          0          0")
    lines.append("")

    # ── [OUTFALLS] ───────────────────────────────────────────────────────────
    lines += [
        "[OUTFALLS]",
        ";;Name           Elevation  Type       Stage Data       Gated    Route To",
    ]
    for nid in outfall_list:
        elev = float(elevations[nid])
        lines.append(f"{_outfall_name(nid):<17}{elev:<11.3f}FREE                        NO")
    lines.append("")

    # ── [CONDUITS] ───────────────────────────────────────────────────────────
    lines += [
        "[CONDUITS]",
        ";;Name           From Node        To Node          Length     Roughness  InOffset   OutOffset  InitFlow   MaxFlow",
    ]
    for idx, e in enumerate(edge_data):
        u = e["from_node"]
        v = e["to_node"]
        fname = _junc_name(u) if u not in outfalls else _outfall_name(u)
        tname = _junc_name(v) if v not in outfalls else _outfall_name(v)
        length = e["length_m"]
        lines.append(
            f"{_cond_name(idx):<17}{fname:<17}{tname:<17}"
            f"{length:<11.1f}{MANNINGS_N:<11.4f}0          0          0          0"
        )
    lines.append("")

    # ── [XSECTIONS] ──────────────────────────────────────────────────────────
    lines += [
        "[XSECTIONS]",
        ";;Link           Shape        Geom1      Geom2      Geom3      Geom4      Barrels    Culvert",
    ]
    for idx, e in enumerate(edge_data):
        d = e["diameter_m"]
        hw = e["highway"]
        if hw in ("canal", "river", "tidal_channel"):
            # Trapezoidal open channel: width=d, depth=d/2, side slope 1:1
            lines.append(
                f"{_cond_name(idx):<17}TRAPEZOIDAL  {d:<11.2f}{d/2:.2f}       1          1          1"
            )
        else:
            lines.append(
                f"{_cond_name(idx):<17}CIRCULAR     {d:<11.2f}0          0          0          1"
            )
    lines.append("")

    # ── [SUBCATCHMENTS] ──────────────────────────────────────────────────────
    lines += [
        "[SUBCATCHMENTS]",
        ";;Name           Rain Gage        Outlet           Area       %Imperv    Width      %Slope     CurbLen    SnowPack",
    ]
    for _, row in subcatchments.iterrows():
        nid = int(row["junction"])
        outlet = _junc_name(nid) if nid not in outfalls else _outfall_name(nid)
        area = float(row["area_ha"])
        imperv = float(row["pct_imperv"]) * 100.0
        width = math.sqrt(area * 10_000) if area > 0 else 100.0
        # slope from elevation difference to nearest downslope node (simplified)
        slope = max(0.1, float(elevations[nid]) * 0.01)  # 1% of elevation as proxy
        lines.append(
            f"{_sub_name(nid):<17}RG1              {outlet:<17}"
            f"{area:<11.2f}{imperv:<11.1f}{width:<11.1f}{slope:<11.3f}0"
        )
    lines.append("")

    # ── [SUBAREAS] ───────────────────────────────────────────────────────────
    lines += [
        "[SUBAREAS]",
        ";;Subcatchment   N-Imperv   N-Perv     S-Imperv   S-Perv     PctZero    RouteTo",
    ]
    for _, row in subcatchments.iterrows():
        nid = int(row["junction"])
        lines.append(
            f"{_sub_name(nid):<17}0.011      0.1        1.5        3.5        25         OUTLET"
        )
    lines.append("")

    # ── [INFILTRATION] ───────────────────────────────────────────────────────
    # Green-Ampt parameters for tropical laterite soil (typical Lagos)
    lines += [
        "[INFILTRATION]",
        ";;Subcatchment   Suction    Ksat       IMDmax",
    ]
    for _, row in subcatchments.iterrows():
        nid = int(row["junction"])
        lines.append(
            f"{_sub_name(nid):<17}111        10.92      0.26"
        )
    lines.append("")

    # ── [REPORT] ─────────────────────────────────────────────────────────────
    lines += [
        "[REPORT]",
        "SUBCATCHMENTS ALL",
        "NODES ALL",
        "LINKS ALL",
        "",
    ]

    # ── [TAGS] ───────────────────────────────────────────────────────────────
    lines += [
        "[TAGS]",
        # colour-code by road class for SWMM visual
    ]
    for idx, e in enumerate(edge_data):
        hw = e["highway"]
        lines.append(f"Link   {_cond_name(idx)}   {hw}")
    lines.append("")

    # ── [MAP] ─────────────────────────────────────────────────────────────────
    # Bounding box in UTM for SWMM GUI display
    bbox_utm = gpd.GeoSeries([BBOX_BOX], crs="EPSG:4326").to_crs(UTM).iloc[0]
    x0, y0, x1, y1 = bbox_utm.bounds
    lines += [
        "[MAP]",
        f"DIMENSIONS {x0:.0f} {y0:.0f} {x1:.0f} {y1:.0f}",
        "UNITS      Meters",
        "",
    ]

    # ── [COORDINATES] ────────────────────────────────────────────────────────
    lines += [
        "[COORDINATES]",
        ";;Node           X-Coord            Y-Coord",
    ]
    for nid in junctions:
        x, y = node_coords[nid]
        lines.append(f"{_junc_name(nid):<17}{x:<19.3f}{y:.3f}")
    for nid in outfall_list:
        x, y = node_coords[nid]
        lines.append(f"{_outfall_name(nid):<17}{x:<19.3f}{y:.3f}")
    lines.append("")

    # ── [VERTICES] ───────────────────────────────────────────────────────────
    lines += [
        "[VERTICES]",
        ";;Link           X-Coord            Y-Coord",
    ]
    for idx, e in enumerate(edge_data):
        geom = e["geom"]
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            for x, y in coords[1:-1]:  # interior vertices only
                lines.append(f"{_cond_name(idx):<17}{x:<19.3f}{y:.3f}")
    lines.append("")

    # ── [POLYGONS] ────────────────────────────────────────────────────────────
    lines += [
        "[POLYGONS]",
        ";;Subcatchment   X-Coord            Y-Coord",
    ]
    for _, row in subcatchments.iterrows():
        nid = int(row["junction"])
        geom = row["geometry"]
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiPolygon":
            geom = max(geom.geoms, key=lambda g: g.area)
        if geom.geom_type == "Polygon":
            for x, y in list(geom.exterior.coords):
                lines.append(f"{_sub_name(nid):<17}{x:<19.3f}{y:.3f}")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s  (%d lines)", out_path, len(lines))


# ════════════════════════════════════════════════════════════════════════════
# 8. SAVE NETWORK GEOPACKAGE (for QGIS)
# ════════════════════════════════════════════════════════════════════════════

def save_network_gpkg(
    node_coords: list[tuple],
    elevations:  np.ndarray,
    edge_data:   list[dict],
    outfalls:    set[int],
    subcatchments: gpd.GeoDataFrame,
    out_path: Path,
) -> None:
    log.info("Saving network GeoPackage …")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Junctions layer
    junc_gdf = gpd.GeoDataFrame(
        {
            "node_id":    list(range(len(node_coords))),
            "name":       [_junc_name(i) if i not in outfalls else _outfall_name(i)
                           for i in range(len(node_coords))],
            "elevation_m": elevations.tolist(),
            "is_outfall": [nid in outfalls for nid in range(len(node_coords))],
            "geometry":   [Point(x, y) for x, y in node_coords],
        },
        crs=UTM,
    )
    junc_gdf.to_file(out_path, layer="junctions", driver="GPKG")

    # Conduits layer
    cond_gdf = gpd.GeoDataFrame(
        {
            "conduit_id":  [_cond_name(i) for i in range(len(edge_data))],
            "from_node":   [_junc_name(e["from_node"]) if e["from_node"] not in outfalls
                            else _outfall_name(e["from_node"]) for e in edge_data],
            "to_node":     [_junc_name(e["to_node"])   if e["to_node"]   not in outfalls
                            else _outfall_name(e["to_node"])   for e in edge_data],
            "highway":     [e["highway"]    for e in edge_data],
            "diameter_m":  [e["diameter_m"] for e in edge_data],
            "length_m":    [e["length_m"]   for e in edge_data],
            "geometry":    [e["geom"]       for e in edge_data],
        },
        crs=UTM,
    )
    cond_gdf.to_file(out_path, layer="conduits", driver="GPKG", append=True)

    # Subcatchments layer
    if len(subcatchments):
        subcatchments.to_file(out_path, layer="subcatchments", driver="GPKG", append=True)

    log.info("Saved %s", out_path)


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("=== FloodSight Phase 17: SWMM Network Builder ===")
    log.info("Pilot area: Kosofe (lon %.2f-%.2f, lat %.2f-%.2f)",
             BBOX_WGS84[0], BBOX_WGS84[2], BBOX_WGS84[1], BBOX_WGS84[3])

    roads  = _load_roads()
    canals = _load_canals()
    grid   = _load_grid()

    G, node_coords, edge_data = build_graph(roads, canals)

    if not node_coords:
        log.error("No nodes found — check roads.gpkg exists and Kosofe bbox is correct.")
        return

    elevations = assign_elevations(node_coords, grid)
    edge_data  = orient_downslope(edge_data, elevations)

    # Rebuild directed graph from oriented edges
    G2 = nx.DiGraph()
    for e in edge_data:
        G2.add_edge(e["from_node"], e["to_node"])

    # find_outfalls returns one virtual outfall + updated coords/elevations/edges
    outfalls, node_coords, elevations, extra_edges = find_outfalls(
        G2, node_coords, elevations
    )
    edge_data.extend(extra_edges)   # add stub conduit to virtual outfall

    subcatchments = build_subcatchments(node_coords, grid)

    write_swmm_inp(node_coords, elevations, edge_data, outfalls, subcatchments, OUT_INP)
    save_network_gpkg(node_coords, elevations, edge_data, outfalls, subcatchments, OUT_NET)

    log.info("")
    log.info("=== DONE ===")
    log.info("  SWMM input:  %s", OUT_INP)
    log.info("  Network viz: %s", OUT_NET)
    log.info("")
    log.info("Next steps:")
    log.info("  1. Open %s in EPA SWMM 5.2 (free download)", OUT_INP)
    log.info("  2. Check for disconnected nodes (Run > Status Report)")
    log.info("  3. Load %s in QGIS to verify network layout", OUT_NET)
    log.info("  4. Replace pipe diameters when real data is obtained")
    log.info("  5. Run design storm: 90mm/3hr (1-in-10yr for Lagos)")


if __name__ == "__main__":
    main()
