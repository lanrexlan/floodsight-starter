"""
Build training rows for any labeled flood event and append them to
data/processed/real_training_dataset.csv.

This is the generalized version of build_2021_training_rows.py. Run it
after each new event where you have:
  - A FwDET depth raster (output of floodsight/labeling/fwdet.py)
  - A pre-event HyP3 VV GeoTiff (for dist_to_water computation)
  - A date for CHIRPS rainfall lookup

Usage (from project root, conda activate floodsight):

    python scripts/build_event_training_rows.py \\
        --event-name lekki_2025_07_15 \\
        --depth-raster data/processed/depth_lekki_20250715.tif \\
        --rain-date 2025-07-15 \\
        --pre-event-vv data/raw/sentinel1/cache/S1A_IW_..._VV.tif

All arguments are required except --pre-event-vv (falls back to 0 m if
the VV tif is omitted or not found).

Output: appends N rows to data/processed/real_training_dataset.csv,
where N is the number of flooded pixels (depth > --threshold).

After running this, retrain the model:
    python -m floodsight.ml.train --data data/processed/real_training_dataset.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import rasterio.transform
import rasterio.windows
from rasterio.windows import from_bounds
from scipy.ndimage import distance_transform_edt
from skimage.filters import threshold_otsu

# ---------------------------------------------------------------------------
# Paths to terrain/feature rasters (must already exist)
# ---------------------------------------------------------------------------
_T = Path("data/processed/terrain")
DEM_PATH   = Path("data/processed/dem_mosaic.tif")
SLOPE_PATH = _T / "slope_deg.tif"
FLOW_PATH  = _T / "flow_accum.tif"
HAND_PATH  = _T / "hand_m.tif"
LC_PATH    = Path("data/processed/landcover_mosaic.tif")
POP_PATH   = Path("data/processed/population_mosaic.tif")
OUT_CSV    = Path("data/processed/real_training_dataset.csv")

DEPTH_THRESHOLD_DEFAULT = 0.01  # metres


def _validate_required_rasters() -> None:
    required = {
        "DEM":               DEM_PATH,
        "slope":             SLOPE_PATH,
        "flow accumulation": FLOW_PATH,
        "HAND":              HAND_PATH,
        "land cover":        LC_PATH,
        "population":        POP_PATH,
    }
    missing = [(label, p) for label, p in required.items() if not p.exists()]
    if missing:
        print("ERROR — missing required rasters:")
        for label, p in missing:
            print(f"  {label}: {p}")
        raise SystemExit(1)


def sample_raster(path: Path, coords: list[tuple[float, float]], src_crs) -> np.ndarray:
    """Sample raster at coords (in src_crs). Reprojects if CRS differs."""
    with rasterio.open(path) as src:
        if src.crs != src_crs:
            from pyproj import Transformer
            t = Transformer.from_crs(src_crs, src.crs, always_xy=True)
            cx, cy = t.transform([c[0] for c in coords], [c[1] for c in coords])
            sample_coords = list(zip(cx, cy))
        else:
            sample_coords = coords
        return np.array([v[0] for v in src.sample(sample_coords)], dtype=float)


def compute_dist_to_water(vv_path: Path, xs: np.ndarray, ys: np.ndarray,
                           depth_crs) -> np.ndarray:
    """Distance transform from pre-event water mask derived from HyP3 VV tif."""
    with rasterio.open(vv_path) as src:
        from pyproj import Transformer
        t = Transformer.from_crs(depth_crs, src.crs, always_xy=True)
        cx_all, cy_all = t.transform(xs, ys)
        x_min, x_max = cx_all.min() - 500, cx_all.max() + 500
        y_min, y_max = cy_all.min() - 500, cy_all.max() + 500
        win = from_bounds(x_min, y_min, x_max, y_max, src.transform)
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        vv_data = src.read(1, window=win)
        win_tf = src.window_transform(win)
        pixel_size = abs(win_tf.a)

    vv_db = 10 * np.log10(np.where(vv_data > 0, vv_data, np.nan))
    valid = vv_db[np.isfinite(vv_db)]
    thresh = threshold_otsu(valid) if len(valid) > 100 else -20.0
    print(f"  Otsu water threshold (pre-event VV): {thresh:.2f} dB")
    water_mask = (vv_db < thresh)
    dist_arr = distance_transform_edt(~water_mask) * pixel_size

    row_idx = np.array([int(round((cy - win_tf.f) / win_tf.e)) for cy in cy_all], dtype=int)
    col_idx = np.array([int(round((cx - win_tf.c) / win_tf.a)) for cx in cx_all], dtype=int)
    ri = np.clip(row_idx, 0, dist_arr.shape[0] - 1)
    ci = np.clip(col_idx, 0, dist_arr.shape[1] - 1)
    return dist_arr[ri, ci]


def lookup_rainfall(rain_date: str, python_exe: str = sys.executable) -> tuple[float, float]:
    import subprocess
    r = subprocess.run(
        [python_exe, "-m", "floodsight.processing.rainfall", "--date", rain_date],
        capture_output=True, text=True,
    )
    rain_24h = rain_72h = 0.0
    for line in r.stdout.splitlines():
        if "rain_24h" in line:
            rain_24h = float(line.split("=")[-1].strip())
        if "rain_72h" in line:
            rain_72h = float(line.split("=")[-1].strip())
    return rain_24h, rain_72h


def build_rows(
    event_name: str,
    depth_raster: Path,
    rain_date: str,
    pre_event_vv: Path | None,
    depth_threshold: float,
) -> pd.DataFrame:
    print(f"\n=== Building training rows for event: {event_name} ===")

    # 1. Load depth raster
    print("Loading depth raster ...")
    with rasterio.open(depth_raster) as src:
        depth = src.read(1)
        dtf = src.transform
        depth_crs = src.crs

    rows_f, cols_f = np.where(depth > depth_threshold)
    n = len(rows_f)
    print(f"  Flooded pixels (>{depth_threshold} m): {n}")
    if n == 0:
        print("  No flooded pixels — nothing to add.")
        return pd.DataFrame()

    xs, ys = np.array(rasterio.transform.xy(dtf, rows_f, cols_f))
    coords = list(zip(xs.tolist(), ys.tolist()))

    # 2. Sample terrain features
    print("Sampling terrain features ...")
    elev       = sample_raster(DEM_PATH,   coords, depth_crs)
    slope      = sample_raster(SLOPE_PATH, coords, depth_crs)
    flow_accum = sample_raster(FLOW_PATH,  coords, depth_crs)
    hand       = sample_raster(HAND_PATH,  coords, depth_crs)
    landcover  = sample_raster(LC_PATH,    coords, depth_crs)
    population = sample_raster(POP_PATH,   coords, depth_crs)
    print(f"  elev range: [{elev.min():.1f}, {elev.max():.1f}] m")
    print(f"  hand NaNs:  {np.isnan(hand).sum()}")

    # 3. Distance to water
    if pre_event_vv and pre_event_vv.exists():
        print(f"Computing dist_to_water from {pre_event_vv.name} ...")
        dist_to_water = compute_dist_to_water(pre_event_vv, xs, ys, depth_crs)
        print(f"  dist_to_water range: [{dist_to_water.min():.0f}, {dist_to_water.max():.0f}] m")
    else:
        print("  Pre-event VV not found — setting dist_to_water = 0")
        dist_to_water = np.zeros(n)

    # 4. Rainfall
    print(f"Looking up rainfall for {rain_date} ...")
    rain_24h, rain_72h = lookup_rainfall(rain_date)
    print(f"  rain_24h={rain_24h:.2f} mm   rain_72h={rain_72h:.2f} mm")

    # 5. Assemble
    df = pd.DataFrame({
        "elevation_m":        elev,
        "slope_deg":          slope,
        "flow_accum":         flow_accum,
        "hand_m":             np.where(np.isnan(hand), 0.0, hand),
        "dist_to_water_m":    dist_to_water,
        "landcover_class":    landcover,
        "population_density": np.where(np.isnan(population), 0.0, population),
        "rain_24h_mm":        rain_24h,
        "rain_72h_mm":        rain_72h,
        "depth_m":            depth[rows_f, cols_f],
        "event_name":         event_name,
    })
    print(df["depth_m"].describe().round(3))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build training rows for a labeled flood event and append to real_training_dataset.csv"
    )
    parser.add_argument("--event-name", required=True,
                        help="Short identifier, e.g. lekki_2025_07_15")
    parser.add_argument("--depth-raster", required=True, type=Path,
                        help="Path to FwDET depth raster (.tif)")
    parser.add_argument("--rain-date", required=True,
                        help="ISO date for CHIRPS lookup, e.g. 2025-07-15")
    parser.add_argument("--pre-event-vv", type=Path, default=None,
                        help="Path to pre-event HyP3 VV GeoTiff (optional; used for dist_to_water)")
    parser.add_argument("--threshold", type=float, default=DEPTH_THRESHOLD_DEFAULT,
                        help=f"Minimum depth in metres to include a pixel (default: {DEPTH_THRESHOLD_DEFAULT})")
    parser.add_argument("--no-append", action="store_true",
                        help="Print stats but do NOT write to the CSV (dry-run)")
    args = parser.parse_args()

    _validate_required_rasters()

    depth_path = Path(args.depth_raster)
    if not depth_path.exists():
        print(f"ERROR: depth raster not found: {depth_path}")
        raise SystemExit(1)

    new_rows = build_rows(
        event_name=args.event_name,
        depth_raster=depth_path,
        rain_date=args.rain_date,
        pre_event_vv=args.pre_event_vv,
        depth_threshold=args.threshold,
    )

    if new_rows.empty:
        print("Nothing to append.")
        return

    if args.no_append:
        print(f"\n[dry-run] Would append {len(new_rows)} rows to {OUT_CSV} — skipping write.")
        return

    if OUT_CSV.exists():
        existing = pd.read_csv(OUT_CSV)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows

    combined.to_csv(OUT_CSV, index=False)
    print(f"\nDataset updated: {len(combined)} total rows")
    print(combined.groupby("event_name")[["depth_m", "rain_24h_mm"]].describe().round(2))
    print(f"\nSaved to {OUT_CSV}")
    print("\nNext step — retrain the model:")
    print("  python -m floodsight.ml.train --data data/processed/real_training_dataset.csv")


if __name__ == "__main__":
    main()
