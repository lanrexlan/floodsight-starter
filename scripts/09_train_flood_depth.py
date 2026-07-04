#!/usr/bin/env python3
"""
Phase 21 — ML Flood Depth Prediction Pipeline
==============================================

Trains a GradientBoostingRegressor on:
  1. Real historical flood observations  (616 rows, Lekki 2024 events)
  2. SWMM-derived synthetic depth samples (up to 5,000 from 6,340 junctions)

Then applies the model to the full 24,933-cell Lagos grid under a
100-year design storm (rain_24h_mm=150, rain_72h_mm=150).

Outputs
-------
  data/processed/flood_depth_ml.gpkg          — full grid + predicted depths
  data/processed/flood_depth_ml.geojson       — centroid points (for API)
  data/processed/flood_depth_ml_summary.json  — model metrics + stats
  data/models/depth_model.joblib              — overwrites synthetic model

Usage
-----
  python scripts/09_train_flood_depth.py
  python scripts/09_train_flood_depth.py --max-swmm 3000
  python scripts/09_train_flood_depth.py --no-swmm   # historical only
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import KDTree
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT      = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # make `floodsight` importable when run directly
DATA      = ROOT / "data"
PROCESSED = DATA / "processed"
MODELS    = DATA / "models"
MODELS.mkdir(parents=True, exist_ok=True)

TRAINING_CSV = PROCESSED / "real_training_dataset.csv"
SWMM_GEOJSON = PROCESSED / "swmm_flooding_all.geojson"
GRID_GPKG    = PROCESSED / "scored_grid.gpkg"
OUT_GPKG     = PROCESSED / "flood_depth_ml.gpkg"
OUT_GEOJSON  = PROCESSED / "flood_depth_ml.geojson"
OUT_SUMMARY  = PROCESSED / "flood_depth_ml_summary.json"
MODEL_PATH   = MODELS / "depth_model.joblib"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEATURES = [
    "elevation_m",
    "slope_deg",
    "flow_accum",
    "hand_m",
    "dist_to_water_m",
    "landcover_class",
    "population_density",
    "rain_24h_mm",
    "rain_72h_mm",
]
TARGET = "depth_m"

# 100-year design storm for Lagos (mm)
DESIGN_RAIN_24H = 150.0
DESIGN_RAIN_72H = 150.0

# Seeded RNG for SWMM depth sampling (reproducible)
RNG = np.random.default_rng(42)

# Lognormal (mean, sigma) parameters for synthetic depth per SWMM flood class.
# Calibrated so that:
#   Severe   → median ≈ 2.2m, clipped to [0.6, 3.0]
#   Moderate → median ≈ 0.74m, clipped to [0.15, 0.9]
#   Nuisance → median ≈ 0.14m, clipped to [0.03, 0.20]
_LOGNORM_PARAMS = {
    "Severe":   (0.80, 0.50),
    "Moderate": (-0.30, 0.50),
    "Nuisance": (-2.00, 0.50),
}
_DEPTH_CLIPS = {
    "Severe":   (0.60, 3.00),
    "Moderate": (0.15, 0.90),
    "Nuisance": (0.03, 0.20),
}


def _classify_depth(d: float) -> tuple[str, str]:
    """Return (depth_class, hex_colour) for a predicted depth in metres."""
    if d < 0.05: return "None",    "#FFFFFF"
    if d < 0.30: return "Low",     "#FFF176"
    if d < 1.00: return "Medium",  "#FF9800"
    if d < 2.00: return "High",    "#F44336"
    return               "Extreme", "#B71C1C"


# ---------------------------------------------------------------------------
# Step 1: Load historical training data
# ---------------------------------------------------------------------------

def load_historical(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    log.info(
        "Historical data loaded: %d rows | depth range %.3f – %.3f m",
        len(df), df[TARGET].min(), df[TARGET].max(),
    )
    # Keep features + target + provenance/grouping metadata — the canonical
    # trainer uses event_name for the grouped split and label_source for
    # honest real-vs-synthetic metric reporting.
    keep = FEATURES + [TARGET]
    for meta_col in ("event_name", "label_source"):
        if meta_col in df.columns:
            keep.append(meta_col)
    return df[keep].copy()


# ---------------------------------------------------------------------------
# Step 2: Build SWMM-derived synthetic training samples
# ---------------------------------------------------------------------------

def _swmm_to_utm(features: list[dict]) -> tuple[np.ndarray, list[dict]]:
    """Reproject SWMM node coordinates WGS84 → EPSG:32631."""
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)
    xs, ys, props = [], [], []
    for feat in features:
        lon, lat = feat["geometry"]["coordinates"]
        x, y = tf.transform(lon, lat)
        xs.append(x)
        ys.append(y)
        props.append(feat["properties"])
    return np.column_stack([xs, ys]), props


def build_swmm_samples(
    swmm_path: Path,
    grid_gdf: gpd.GeoDataFrame,
    max_samples: int = 5000,
) -> pd.DataFrame:
    """
    For each SWMM flooded junction (up to max_samples):
      1. Find its nearest grid cell via KD-Tree (EPSG:32631)
      2. Copy the cell's terrain features
      3. Sample a synthetic depth calibrated to the SWMM flood class
      4. Set rain to a design-storm value (slightly varied for diversity)

    Returns a DataFrame with the same columns as the historical CSV.
    """
    with open(swmm_path) as f:
        gj = json.load(f)
    all_feats = gj["features"]
    log.info("SWMM: %d flooded junctions across 3 LGAs", len(all_feats))

    # Reproject SWMM points → UTM
    swmm_xy, swmm_props = _swmm_to_utm(all_feats)

    # Grid centroids (centroid_x / centroid_y already in EPSG:32631)
    grid_cx = grid_gdf["centroid_x"].values
    grid_cy = grid_gdf["centroid_y"].values
    tree = KDTree(np.column_stack([grid_cx, grid_cy]))

    # Nearest-cell lookup for every SWMM junction
    dists, idxs = tree.query(swmm_xy, workers=-1)

    # Sub-sample to avoid SWMM dominating the training set
    n = len(all_feats)
    sel = (
        RNG.choice(n, size=max_samples, replace=False)
        if n > max_samples
        else np.arange(n)
    )
    if n > max_samples:
        log.info("Sub-sampling SWMM: %d → %d", n, max_samples)

    rows = []
    for i in sel:
        if dists[i] > 500:      # skip junctions far from any grid cell
            continue

        cell   = grid_gdf.iloc[idxs[i]]
        props  = swmm_props[i]
        fcls   = props.get("flood_class", "Nuisance")
        mu, sg = _LOGNORM_PARAMS.get(fcls, (-2.0, 0.5))
        lo, hi = _DEPTH_CLIPS.get(fcls, (0.03, 0.20))

        depth = float(np.clip(RNG.lognormal(mean=mu, sigma=sg), lo, hi))

        # Vary rainfall ±15% around design storm for training diversity
        rain24 = float(np.clip(RNG.normal(DESIGN_RAIN_24H, 15.0),  80.0, 200.0))
        rain72 = float(np.clip(RNG.normal(DESIGN_RAIN_72H, 20.0), 100.0, 220.0))

        hand_val = cell["hand_m"]

        rows.append({
            "elevation_m":        float(cell["elevation_m"]      or 0.0),
            "slope_deg":          float(cell["slope_deg"]         or 0.0),
            "flow_accum":         float(cell["flow_accum"]        or 1.0),
            "hand_m":             float(hand_val) if hand_val is not None else np.nan,
            "dist_to_water_m":    float(cell["dist_to_water_m"]   or 0.0),
            "landcover_class":    float(cell["landcover_class"]    or 10.0),
            "population_density": float(cell["population_density"] or 0.0),
            "rain_24h_mm":        rain24,
            "rain_72h_mm":        rain72,
            TARGET:               depth,
            # Provenance: these depths are drawn from a lognormal calibrated
            # to SWMM flood classes — simulation-derived pseudo-labels, NOT
            # observed. The canonical trainer excludes them from the honest
            # (real-rows-only) metric.
            "event_name":         "swmm_design_storm",
            "label_source":       "swmm_synthetic",
        })

    df_swmm = pd.DataFrame(rows)
    log.info(
        "SWMM synthetic samples: %d rows | depth range %.3f – %.3f m",
        len(df_swmm), df_swmm[TARGET].min(), df_swmm[TARGET].max(),
    )
    return df_swmm


# ---------------------------------------------------------------------------
# Step 3: Train the model
# ---------------------------------------------------------------------------

def train(df: pd.DataFrame) -> tuple:
    """
    Train via the CANONICAL trainer (floodsight/ml/train.py).

    This script previously contained its own diverged copy of the training
    logic (different hyperparameters, different bundle keys, a random
    row-wise split that leaked events between train and test). It now
    delegates so there is exactly one training code path.

    Returns (fitted_model, metrics_dict, hand_impute_median) for backward
    compatibility with the rest of this script.
    """
    from floodsight.ml.train import train_model

    model, metrics = train_model(df, is_synthetic=False)
    hand_median = float(metrics.get("hand_impute_median_m", 0.0))
    return model, metrics, hand_median


# ---------------------------------------------------------------------------
# Step 4: Apply model to full grid
# ---------------------------------------------------------------------------

def predict_grid(
    model: GradientBoostingRegressor,
    grid_gdf: gpd.GeoDataFrame,
    hand_median: float,
) -> gpd.GeoDataFrame:
    """Predict flood depth for every grid cell under the design storm."""
    gdf = grid_gdf.copy()

    Xg = pd.DataFrame({
        "elevation_m":        gdf["elevation_m"].fillna(0.0),
        "slope_deg":          gdf["slope_deg"].fillna(0.0),
        "flow_accum":         gdf["flow_accum"].fillna(1.0),
        "hand_m":             pd.to_numeric(gdf["hand_m"], errors="coerce").fillna(hand_median),
        "dist_to_water_m":    gdf["dist_to_water_m"].fillna(0.0),
        "landcover_class":    gdf["landcover_class"].fillna(10.0),
        "population_density": gdf["population_density"].fillna(0.0),
        "rain_24h_mm":        DESIGN_RAIN_24H,
        "rain_72h_mm":        DESIGN_RAIN_72H,
    })

    depths = np.clip(model.predict(Xg[FEATURES].values), 0.0, None)
    gdf["predicted_depth_m"] = np.round(depths, 3)

    classes, colours = zip(*[_classify_depth(float(d)) for d in depths])
    gdf["depth_class"]  = list(classes)
    gdf["depth_colour"] = list(colours)

    return gdf


# ---------------------------------------------------------------------------
# Step 5: Build centroid GeoJSON for the API endpoint
# ---------------------------------------------------------------------------

def build_api_geojson(gdf: gpd.GeoDataFrame) -> dict:
    """
    Lightweight centroid GeoJSON (WGS84) for GET /depth/ml-grid.
    Keeps only the columns the dashboard needs.
    """
    gdf_wgs = gdf.to_crs("EPSG:4326")
    keep = [
        "cell_id", "predicted_depth_m", "depth_class", "depth_colour",
        "elevation_m", "flood_score", "risk_class",
    ]

    features = []
    for _, row in gdf_wgs.iterrows():
        cx = float(row.geometry.centroid.x)
        cy = float(row.geometry.centroid.y)
        props = {}
        for col in keep:
            if col in row.index:
                v = row[col]
                props[col] = None if pd.isna(v) else v
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(cx, 6), round(cy, 6)],
            },
            "properties": props,
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "n_cells":            len(features),
            "design_rain_24h_mm": DESIGN_RAIN_24H,
            "design_rain_72h_mm": DESIGN_RAIN_72H,
            "crs":                "EPSG:4326",
            "generated":          time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


# ---------------------------------------------------------------------------
# Step 6: Summary statistics
# ---------------------------------------------------------------------------

def build_summary(
    gdf: gpd.GeoDataFrame,
    metrics: dict,
    n_hist: int,
    n_swmm: int,
    elapsed: float,
) -> dict:
    depths = gdf["predicted_depth_m"].values
    class_counts = gdf["depth_class"].value_counts().to_dict()

    top_cells = (
        gdf[gdf["depth_class"].isin(["High", "Extreme"])]
        .nlargest(10, "predicted_depth_m")[
            ["cell_id", "predicted_depth_m", "depth_class", "risk_class"]
        ]
        .fillna("")
        .to_dict(orient="records")
    )

    return {
        "phase":       "Phase 21 — ML Flood Depth Prediction",
        "model":       "GradientBoostingRegressor (sklearn)",
        "design_storm": {
            "rain_24h_mm":  DESIGN_RAIN_24H,
            "rain_72h_mm":  DESIGN_RAIN_72H,
            "description":  "100-year return period design storm — Lagos",
        },
        "training_data": {
            "historical_rows": n_hist,
            "swmm_rows":       n_swmm,
            "total_rows":      n_hist + n_swmm,
        },
        "grid": {
            "n_cells":      int(len(gdf)),
            "crs":          str(gdf.crs),
            "resolution_m": 200,
        },
        "depth_stats": {
            "min_m":    round(float(depths.min()),              3),
            "mean_m":   round(float(depths.mean()),             3),
            "median_m": round(float(np.median(depths)),         3),
            "max_m":    round(float(depths.max()),              3),
            "p90_m":    round(float(np.percentile(depths, 90)), 3),
            "p99_m":    round(float(np.percentile(depths, 99)), 3),
        },
        "depth_class_counts": class_counts,
        "top_flood_cells":    top_cells,
        "model_metrics":      metrics,
        "elapsed_s":          round(elapsed, 1),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 21: Train ML flood depth model and predict across Lagos grid."
    )
    parser.add_argument(
        "--max-swmm", type=int, default=5000,
        help="Max SWMM synthetic training samples (default 5000)",
    )
    parser.add_argument(
        "--no-swmm", action="store_true",
        help="Skip SWMM augmentation; train on historical data only",
    )
    parser.add_argument(
        "--skip-gpkg", action="store_true",
        help="Skip saving the polygon GPKG (fast; GeoJSON + model are always saved)",
    )
    args = parser.parse_args()

    t0 = time.time()

    # ------------------------------------------------------------------
    # 1. Historical data
    # ------------------------------------------------------------------
    if not TRAINING_CSV.exists():
        log.error("Training CSV not found: %s", TRAINING_CSV)
        sys.exit(1)
    df_hist = load_historical(TRAINING_CSV)

    # ------------------------------------------------------------------
    # 2. Grid
    # ------------------------------------------------------------------
    if not GRID_GPKG.exists():
        log.error("Scored grid not found: %s", GRID_GPKG)
        sys.exit(1)
    log.info("Loading scored grid …")
    grid_gdf = gpd.read_file(GRID_GPKG)
    log.info("Grid: %d cells  CRS=%s", len(grid_gdf), grid_gdf.crs)

    # ------------------------------------------------------------------
    # 3. SWMM augmentation
    # ------------------------------------------------------------------
    n_swmm = 0
    if args.no_swmm or not SWMM_GEOJSON.exists():
        if not args.no_swmm:
            log.warning("SWMM GeoJSON not found; training on historical data only")
        df_train = df_hist
    else:
        df_swmm  = build_swmm_samples(SWMM_GEOJSON, grid_gdf, max_samples=args.max_swmm)
        n_swmm   = len(df_swmm)
        df_train = pd.concat([df_hist, df_swmm], ignore_index=True)
        log.info(
            "Combined training set: %d rows  (historical=%d  SWMM=%d)",
            len(df_train), len(df_hist), n_swmm,
        )

    # ------------------------------------------------------------------
    # 4. Train
    # ------------------------------------------------------------------
    model, metrics, hand_median = train(df_train)

    # ------------------------------------------------------------------
    # 5. Save model via the canonical trainer's bundle format
    # ------------------------------------------------------------------
    from floodsight.ml.train import save_model

    save_model(model, metrics, path=MODEL_PATH)

    # ------------------------------------------------------------------
    # 6. Predict on full grid
    # ------------------------------------------------------------------
    log.info(
        "Predicting depth for %d cells (150 mm/24h design storm) …",
        len(grid_gdf),
    )
    result_gdf = predict_grid(model, grid_gdf, hand_median)

    # ------------------------------------------------------------------
    # 7. Build and save centroid GeoJSON (for /depth/ml-grid API) — FAST
    # ------------------------------------------------------------------
    log.info("Building API GeoJSON (centroid points) …")
    api_gj = build_api_geojson(result_gdf)
    OUT_GEOJSON.write_text(
        json.dumps(api_gj, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info("GeoJSON saved → %s  (%d features)", OUT_GEOJSON, len(api_gj["features"]))

    # ------------------------------------------------------------------
    # 8. Summary — FAST
    # ------------------------------------------------------------------
    elapsed = time.time() - t0
    summary = build_summary(result_gdf, metrics, len(df_hist), n_swmm, elapsed)
    OUT_SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Summary → %s", OUT_SUMMARY)

    # ------------------------------------------------------------------
    # 9. Save GPKG (polygon layer — for GIS / QGIS use) — SLOW, optional
    # Write to /tmp first (avoids pyogrio issues with Windows-mounted FS),
    # then copy to the final destination.
    # ------------------------------------------------------------------
    if not args.skip_gpkg:
        log.info("Writing GPKG (polygon layer — this may take ~60s) …")
        tmp_gpkg = Path("/tmp/flood_depth_ml.gpkg")
        tmp_gpkg.unlink(missing_ok=True)
        result_gdf.to_file(str(tmp_gpkg), driver="GPKG", layer="flood_depth_ml", engine="fiona")
        shutil.copy2(tmp_gpkg, OUT_GPKG)
        log.info("GPKG saved → %s", OUT_GPKG)
    else:
        log.info("Skipping GPKG (--skip-gpkg set)")

    # Final log
    cc = summary["depth_class_counts"]
    log.info("=== Phase 21 complete in %.1f s ===", elapsed)
    log.info("Depth class counts: %s", cc)
    log.info(
        "Model: RMSE=%.3f m  MAE=%.3f m  R²=%.3f",
        metrics["rmse_m"], metrics["mae_m"], metrics["r2"],
    )


if __name__ == "__main__":
    main()
