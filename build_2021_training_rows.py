"""
Build 2021-07-12 training rows from the FwDET depth raster and append
them to data/processed/real_training_dataset.csv.

Run from the project root with the floodsight conda env active:
    python build_2021_training_rows.py
"""
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

DEPTH_PATH   = Path("data/processed/depth_lekki_20210712.tif")
DEM_PATH     = Path("data/processed/dem_mosaic.tif")
# Terrain derivatives are saved by floodsight/processing/terrain.py to
# data/processed/terrain/{name}.tif
_T = Path("data/processed/terrain")
SLOPE_PATH   = _T / "slope_deg.tif"
FLOW_PATH    = _T / "flow_accum.tif"
HAND_PATH    = _T / "hand_m.tif"
LC_PATH      = Path("data/processed/landcover_mosaic.tif")
POP_PATH     = Path("data/processed/population_mosaic.tif")
SAR_CACHE    = Path("data/raw/sentinel1/cache")
OUT_CSV      = Path("data/processed/real_training_dataset.csv")

# ---------------------------------------------------------------------------
# Validate required files before doing any work
# ---------------------------------------------------------------------------
_required = {
    "depth raster":      DEPTH_PATH,
    "DEM":               DEM_PATH,
    "slope":             SLOPE_PATH,
    "flow accumulation": FLOW_PATH,
    "HAND":              HAND_PATH,
    "land cover":        LC_PATH,
    "population":        POP_PATH,
}
missing = [(label, p) for label, p in _required.items() if not p.exists()]
if missing:
    print("ERROR — the following required files are missing:")
    for label, p in missing:
        print(f"  {label}: {p}")
    print("\nCheck that the terrain pipeline has been run:")
    print("  python -m floodsight.processing.terrain --dem data/processed/dem_mosaic.tif")
    raise SystemExit(1)

DEPTH_THRESHOLD = 0.01  # m — only include pixels with depth > this
EVENT_NAME      = "lekki_2021_07_12"
RAIN_DATE       = "2021-07-12"

# ---------------------------------------------------------------------------
# 1. Load depth raster and find flooded pixels
# ---------------------------------------------------------------------------
print("Loading depth raster ...")
with rasterio.open(DEPTH_PATH) as src:
    depth   = src.read(1)
    dtf     = src.transform
    depth_crs = src.crs

rows_f, cols_f = np.where(depth > DEPTH_THRESHOLD)
n = len(rows_f)
print(f"  Flooded pixels (>{DEPTH_THRESHOLD} m): {n}")
if n == 0:
    print("No flooded pixels — nothing to add. Exiting.")
    sys.exit(0)

xs, ys = np.array(rasterio.transform.xy(dtf, rows_f, cols_f))
coords  = list(zip(xs.tolist(), ys.tolist()))

# ---------------------------------------------------------------------------
# 2. Helper: sample a raster at the flooded pixel coordinates
# ---------------------------------------------------------------------------
def sample_raster(path, coords, src_crs):
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

# ---------------------------------------------------------------------------
# 3. Sample terrain features
# ---------------------------------------------------------------------------
print("Sampling terrain features ...")
elev        = sample_raster(DEM_PATH,   coords, depth_crs)
slope       = sample_raster(SLOPE_PATH, coords, depth_crs)
flow_accum  = sample_raster(FLOW_PATH,  coords, depth_crs)
hand        = sample_raster(HAND_PATH,  coords, depth_crs)
landcover   = sample_raster(LC_PATH,    coords, depth_crs)
population  = sample_raster(POP_PATH,   coords, depth_crs)
print(f"  elev range:  [{elev.min():.1f}, {elev.max():.1f}] m")
print(f"  hand NaNs:   {np.isnan(hand).sum()}")
print(f"  pop  NaNs:   {np.isnan(population).sum()}")

# ---------------------------------------------------------------------------
# 4. Distance to water from pre-event HyP3 VV (2021-06-30)
# ---------------------------------------------------------------------------
print("Computing dist_to_water from pre-event SAR VV ...")
hyp3_vv = next(SAR_CACHE.glob("*20210630T180159*_VV.tif"), None)
if hyp3_vv:
    print(f"  Pre-event VV: {hyp3_vv.name}")
    with rasterio.open(hyp3_vv) as src:
        from pyproj import Transformer
        t = Transformer.from_crs(depth_crs, src.crs, always_xy=True)
        cx_all, cy_all = t.transform(xs, ys)
        x_min = cx_all.min() - 500
        x_max = cx_all.max() + 500
        y_min = cy_all.min() - 500
        y_max = cy_all.max() + 500
        win = from_bounds(x_min, y_min, x_max, y_max, src.transform)
        win = win.intersection(
            rasterio.windows.Window(0, 0, src.width, src.height)
        )
        vv_data   = src.read(1, window=win)
        win_tf    = src.window_transform(win)
        pixel_size = abs(win_tf.a)

    vv_db = 10 * np.log10(np.where(vv_data > 0, vv_data, np.nan))
    valid  = vv_db[np.isfinite(vv_db)]
    thresh = threshold_otsu(valid) if len(valid) > 100 else -20.0
    print(f"  Otsu water threshold: {thresh:.2f} dB")
    water_mask = (vv_db < thresh)
    dist_arr   = distance_transform_edt(~water_mask) * pixel_size

    row_idx = np.array(
        [int(round((cy - win_tf.f) / win_tf.e)) for cy in cy_all], dtype=int
    )
    col_idx = np.array(
        [int(round((cx - win_tf.c) / win_tf.a)) for cx in cx_all], dtype=int
    )
    ri = np.clip(row_idx, 0, dist_arr.shape[0] - 1)
    ci = np.clip(col_idx, 0, dist_arr.shape[1] - 1)
    dist_to_water = dist_arr[ri, ci]
    print(f"  dist_to_water range: [{dist_to_water.min():.0f}, {dist_to_water.max():.0f}] m")
else:
    print("  Pre-event VV not found in cache — setting dist_to_water = 0")
    dist_to_water = np.zeros(n)

# ---------------------------------------------------------------------------
# 5. Rainfall for 2021-07-12
# ---------------------------------------------------------------------------
print(f"Looking up rainfall for {RAIN_DATE} ...")
rain_24h = rain_72h = 0.0
try:
    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "floodsight.processing.rainfall", "--date", RAIN_DATE],
        capture_output=True, text=True,
    )
    for line in r.stdout.splitlines():
        if "rain_24h" in line:
            rain_24h = float(line.split("=")[-1].strip())
        if "rain_72h" in line:
            rain_72h = float(line.split("=")[-1].strip())
    print(f"  rain_24h={rain_24h:.2f} mm   rain_72h={rain_72h:.2f} mm")
except Exception as e:
    print(f"  Rainfall lookup failed ({e}) — using 0.0 for both")

# ---------------------------------------------------------------------------
# 6. Assemble DataFrame and append to CSV
# ---------------------------------------------------------------------------
print("Assembling 2021 training rows ...")
df21 = pd.DataFrame({
    "elevation_m":        elev,
    "slope_deg":          slope,
    "flow_accum":         flow_accum,
    "hand_m":             np.where(np.isnan(hand),       0.0, hand),
    "dist_to_water_m":    dist_to_water,
    "landcover_class":    landcover,
    "population_density": np.where(np.isnan(population), 0.0, population),
    "rain_24h_mm":        rain_24h,
    "rain_72h_mm":        rain_72h,
    "depth_m":            depth[rows_f, cols_f],
    "event_name":         EVENT_NAME,
})
print(df21["depth_m"].describe())

existing = pd.read_csv(OUT_CSV)
combined = pd.concat([existing, df21], ignore_index=True)
combined.to_csv(OUT_CSV, index=False)

print(f"\nDataset updated: {len(existing)} (2024) + {len(df21)} (2021) = {len(combined)} total rows")
print(combined.groupby("event_name")[["depth_m", "rain_24h_mm"]].describe().round(2))
print(f"\nSaved to {OUT_CSV}")
