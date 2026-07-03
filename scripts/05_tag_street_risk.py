"""
Phase 15: Tag OSM road segments with flood risk class.

Spatial-joins the OSM road network to the scored risk grid so each road
segment inherits the risk_class (and flood_score) of the grid cell it falls
in.  The output is served by the API at /risk/streets and rendered as a
colour-coded street layer in the dashboard at zoom ≥ 13.

Inputs
------
  data/raw/osm/clipped/roads.gpkg        60 MB — full driving network for AOI
  data/processed/scored_grid.gpkg        ~6 MB — 24 933 cells with risk_class

Output
------
  data/processed/streets_risk.gpkg       ~5 MB — filtered + tagged road segments

Road type filter
----------------
All motorway / trunk / primary / secondary / tertiary roads and their link
variants are always included (they're the arterial network every resident
navigates by).

Residential and unclassified roads are included ONLY where risk_class is
"High" or "Very High" — this keeps the residential count to the genuinely
at-risk streets rather than every quiet lane in Lagos.

Usage
-----
    conda activate floodsight
    python scripts/05_tag_street_risk.py

Runtime: ~2–4 minutes on a laptop (dominated by the 60 MB GPKG read and
the spatial join on ~200 k road segments).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Road types always kept (main arterial network)
ARTERIAL_TYPES = {
    "motorway", "motorway_link",
    "trunk",    "trunk_link",
    "primary",  "primary_link",
    "secondary","secondary_link",
    "tertiary", "tertiary_link",
}

# Road types kept only when risk is High or Very High
RESIDENTIAL_TYPES = {"residential", "unclassified", "road", "living_street"}

# Columns to keep in the output (everything else is dropped)
KEEP_COLS = {"name", "highway", "risk_class", "flood_score", "geometry"}


def main() -> None:
    import geopandas as gpd
    import numpy as np
    from scipy.spatial import cKDTree

    from floodsight.config import PROCESSED_DIR, RAW_DIR, WORKING_CRS, WGS84

    roads_path  = RAW_DIR  / "osm" / "clipped" / "roads.gpkg"
    grid_path   = PROCESSED_DIR / "scored_grid.gpkg"
    output_path = PROCESSED_DIR / "streets_risk.gpkg"

    if not roads_path.exists():
        raise FileNotFoundError(
            f"{roads_path} not found — run scripts/01_download_all.py first."
        )
    if not grid_path.exists():
        raise FileNotFoundError(
            f"{grid_path} not found — run scripts/02 and 03 first."
        )

    # ------------------------------------------------------------------
    # 1. Load inputs
    # ------------------------------------------------------------------
    log.info("Loading roads from %s …", roads_path)
    roads = gpd.read_file(roads_path)
    log.info("  %d raw road segments", len(roads))

    log.info("Loading scored grid from %s …", grid_path)
    grid = gpd.read_file(grid_path)
    log.info("  %d grid cells", len(grid))

    # ------------------------------------------------------------------
    # 2. Filter road types
    # ------------------------------------------------------------------
    hw = roads["highway"].astype(str)

    # Roads that are lists (e.g. ["primary","residential"]) — keep if any type matches
    def _hw_match(val: str, type_set: set) -> bool:
        # pyrosm sometimes stores multi-type strings as Python list literals
        for t in type_set:
            if t in val:
                return True
        return False

    arterial_mask    = hw.apply(lambda v: _hw_match(v, ARTERIAL_TYPES))
    residential_mask = hw.apply(lambda v: _hw_match(v, RESIDENTIAL_TYPES))
    roads = roads[arterial_mask | residential_mask].copy()
    log.info("  %d segments after road-type filter", len(roads))

    # ------------------------------------------------------------------
    # 3. Reproject to working CRS for join
    # ------------------------------------------------------------------
    roads = roads.to_crs(WORKING_CRS)
    grid  = grid.to_crs(WORKING_CRS)

    # ------------------------------------------------------------------
    # 4. Spatial join: each road segment → nearest grid cell
    #    Use representative_point() (guaranteed inside geometry) rather
    #    than centroid (can fall outside for curved roads).
    # ------------------------------------------------------------------
    log.info("Computing road representative points …")
    road_pts = roads.geometry.representative_point()
    road_xy  = np.column_stack([road_pts.x, road_pts.y])

    log.info("Building KD-tree from %d grid centroids …", len(grid))
    grid_xy = np.column_stack([
        grid.geometry.centroid.x,
        grid.geometry.centroid.y,
    ])
    tree = cKDTree(grid_xy)

    log.info("Querying nearest grid cell for each road segment …")
    _, nearest_idx = tree.query(road_xy, k=1)

    roads = roads.copy()
    roads["risk_class"]  = grid["risk_class"].iloc[nearest_idx].values
    roads["flood_score"] = grid["flood_score"].iloc[nearest_idx].values

    # ------------------------------------------------------------------
    # 5. Apply residential risk filter
    # ------------------------------------------------------------------
    is_residential = roads["highway"].astype(str).apply(
        lambda v: _hw_match(v, RESIDENTIAL_TYPES)
    )
    is_arterial = roads["highway"].astype(str).apply(
        lambda v: _hw_match(v, ARTERIAL_TYPES)
    )
    high_risk = roads["risk_class"].isin({"High", "Very High"})

    keep = is_arterial | (is_residential & high_risk)
    roads = roads[keep].copy()
    log.info(
        "  %d segments after residential risk filter "
        "(%d arterial, %d high-risk residential)",
        len(roads),
        is_arterial[keep].sum(),
        (is_residential & high_risk)[keep].sum(),
    )

    # ------------------------------------------------------------------
    # 6. Tidy columns and reproject to WGS84
    # ------------------------------------------------------------------
    drop_cols = [c for c in roads.columns if c not in KEEP_COLS]
    roads.drop(columns=drop_cols, inplace=True)

    # Normalise name: fill NaN with empty string
    if "name" in roads.columns:
        roads["name"] = roads["name"].fillna("").astype(str)

    roads = roads.to_crs(WGS84)

    # ------------------------------------------------------------------
    # 7. Save
    # ------------------------------------------------------------------
    roads.to_file(output_path, driver="GPKG")
    log.info(
        "Saved %d tagged road segments to %s",
        len(roads), output_path,
    )
    log.info(
        "Risk distribution:\n%s",
        roads["risk_class"].value_counts().to_string(),
    )


if __name__ == "__main__":
    main()
