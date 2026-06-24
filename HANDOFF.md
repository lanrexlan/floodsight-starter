# FloodSight — Cowork Handoff Note

Please read `README.md` and `ROADMAP.md` before doing anything else. This note
summarises where we are and exactly what to do next.

---

## What this project is

FloodSight is an open-data flood intelligence platform for Lagos, Nigeria.
The pilot covers three LGAs: Eti-Osa, Lagos Island, and Kosofe.

The codebase has five main layers:
- **Data download** (`floodsight/download/`) — DEM, land cover, population,
  OSM, CHIRPS rainfall, Sentinel-1 SAR via Element84 / ASF / HyP3
- **Processing** (`floodsight/processing/`) — terrain derivatives (slope,
  flow accumulation, HAND), susceptibility scoring, HAND-based depth
- **Labeling** (`floodsight/labeling/`) — SAR-based flood extent detection
  (FwDET), Otsu thresholding, depth estimation from SAR extent + DEM
- **ML** (`floodsight/ml/`) — gradient-boosting depth model, now trained on
  real labeled events (616 rows, two events)
- **API + dashboard** (`api/`, `dashboard/`) — FastAPI backend, Leaflet
  frontend, deployed live on Render

---

## Current state (as of this handoff)

### Completed phases

- **Phase 0:** Claims aligned with reality, risk class skew fixed
- **Phase 1:** HAND-based physical depth (`depth_hand.py`)
- **Phase 2 (partial):** CHIRPS rainfall pipeline working; GloFAS not tested
- **Phase 3:** API + dashboard live on Render (auto-deploys on push to main)
- **Phase 4:** Real labeled training dataset built — **DONE**
- **Phase 5:** ML depth model trained on real data — **DONE**

### Phase 4+5 outcomes

**Training dataset** (`data/processed/real_training_dataset.csv`) — 616 rows:
- 527 rows: `lekki_2024_07_03` — 2024 Lekki flood, depth 0.01–1.30m,
  rain_24h=22.54mm, rain_72h=67.54mm
- 89 rows: `lekki_2021_07_12` — 2021 Lagos tidal surge, depth 0.012–0.262m,
  rain_24h and rain_72h from CHIRPS (downloaded and patched in)

**Model** (`data/models/depth_model.joblib`) — GradientBoostingRegressor:
- 300 estimators, max_depth=4, learning_rate=0.05, subsample=0.8
- Trained on 492 rows / tested on 124 rows
- MAE=0.130m, RMSE=0.200m, R²=0.106
- Feature importances: slope_deg=0.308, dist_to_water_m=0.253,
  hand_m=0.167, flow_accum=0.126, elevation_m=0.088, landcover_class=0.032,
  population_density=0.018, rain_24h_mm=0.005, rain_72h_mm=0.003

R²=0.106 is expected at this stage: only two events from the same location
means the model is fitting terrain variation more than rainfall variation.
R² improves once more geographically diverse events (different wards,
different storm tracks) are added.

---

## What is in progress — pick up HERE

**Phase 6: Pilot season + recalibration** (see ROADMAP.md §Phase 6).

The core loop:
1. Run the live system (API + alerting) through the 2025 rainy season
   (April–October) in the 3 pilot LGAs
2. Collect community / field verification reports for each warning issued —
   specifically: was the warned area actually flooded? depth estimate
   reasonable?
3. Use that feedback to:
   a. **Recalibrate susceptibility weights** — the v0 weights
      (`SUSCEPTIBILITY_WEIGHTS` in `floodsight/config.py`) were set from
      the README heuristics, not ground truth. Compare flagged vs. verified
      flood locations and adjust the weight vector.
   b. **Retrain the ML model** — add the new labeled events from the pilot
      season to `data/processed/real_training_dataset.csv` (same format as
      the 616 rows already there) and re-run:
      `python -m floodsight.ml.train --data data/processed/real_training_dataset.csv`
   c. **Fix false-positive / false-negative hot spots** — cells that
      trigger warnings but never flood (lower susceptibility weight or add
      exclusion mask), or cells that flood but aren't warned (increase
      sensitivity for that HAND tier).
4. Target: after ≥ one full season and ≥ 3 new labeled events, R² should
   be above 0.4 and the ±0.3m accuracy claim in the pitch deck becomes
   defensible.

**Concrete next step:**
Instrument the API to log every `/depth/predict` call with timestamp, grid
cell ID, predicted depth, and alert level. Store logs in
`data/logs/predictions.jsonl` (append-only). After each flood event during
the rainy season, add a verification column (field-confirmed depth or
boolean flooded/not-flooded) and use `build_event_training_rows.py` (extend
`build_2021_training_rows.py` to accept any event date + depth raster) to
grow the dataset.

---

## SAR data source chain (important — Planetary Computer is dead for this)

`floodsight/labeling/sar_extent.py` was rewritten in Phase 4. The source
chain for Sentinel-1 SAR VV data is now:

1. **Element84 Earth Search v1** (`sentinel-1-grd` collection) — discovers
   scenes by date + AOI. Asset URLs are `s3://sentinel-s1-l1c/...`
   (requester-pays), so direct download fails.
2. **ASF fallback** — for each Element84 scene, `_download_vv_via_asf()`
   searches ASF using `absoluteOrbit` + `intersectsWith` (AOI bbox WKT) +
   a ±5min/+30min time window around the scene's start timestamp. This
   finds the right geographic segment even though Element84 scene IDs
   don't match ASF's CMR catalog names.
3. **HyP3 RTC fallback** — if ASF direct download fails (auth or missing
   scene), `_water_mask_from_element84_item()` submits an RTC job via
   HyP3 SDK and downloads the calibrated sigma0 GeoTiff. The HyP3 output
   zip name differs from the input scene name; detection uses the shared
   start timestamp (`scene_name.split("_")[4]`).

**One-time setup required for ASF downloads:**
The Earthdata account must pre-authorize the ASF Cumulus app — visit once:
`https://urs.earthdata.nasa.gov/approve_app?client_id=BO_n7nTIlMljdvU6kRRB3g`

**Cached SAR files** (large, in `.gitignore`):
- `data/raw/sentinel1/cache/*20210630T180159*_VV.tif` (HyP3 pre-event 2021)
- `data/raw/sentinel1/cache/*20210712T180159*_VV.tif` (HyP3 during-event 2021)
- `data/raw/sentinel1/flood_extent_20210710.tif` (2021 flood extent mask)
- `data/processed/depth_lekki_20210712.tif` (FwDET depth raster, 2021)
- `data/raw/sentinel1/flood_extent_20240704.tif` (2024 flood extent mask)

---

## Known issues / caveats

1. **Copernicus DEM GLO-30 is a DSM** — rooftop heights inflate slope/HAND
   in dense urban cells. Documented in `floodsight/processing/depth_hand.py`.
2. **HAND is NaN for ~5,149 cells** — ~3,952 are confirmed lagoon/creek;
   ~1,197 are DEM conditioning edge effects. Imputed to 0 in training data.
3. **R²=0.106** — low but expected. Two events from the same location means
   terrain dominates. More diverse events will fix this.
4. **Rainfall features have near-zero importance** (rain_24h=0.005,
   rain_72h=0.003) — because both events have similar CHIRPS totals. As
   events from different storm tracks are added, this will flip.
5. **2024 SAR "during" scene (July 3) was pre-peak** — the real flood peak
   was July 4. rain_24h/72h for 2024 rows are conservative.
6. **SAR water threshold** uses Otsu's method (per-scene automatic) —
   confirmed working: -10.51 dB (2021-06-30), -10.73 dB (2021-07-12).

---

## Environment

- Conda env: `floodsight` (Python 3.11, numpy<2 pinned for pysheds)
- Activate: `conda activate floodsight`
- Run from project root: `cd C:\Users\User\Downloads\floodsight-starter\floodsight-starter`
- Credentials: `.env` in project root (NASA Earthdata + Africa's Talking)
- API locally: `uvicorn api.main:app --reload --port 8080`
- Live deployment: Render (auto-deploys on push to GitHub main)

---

## Roadmap phases reference

| Phase | Status | Description |
|---|---|---|
| 0 | Done | Align claims with reality, fix risk class skew |
| 1 | Done | HAND-based physical depth |
| 2 | Partial | CHIRPS working; GloFAS not tested |
| 3 | Done | API + dashboard live on Render |
| 4 | **Done** | Real labeled training dataset (616 rows, 2 events) |
| 5 | **Done** | ML depth model trained on real data (MAE=0.130m) |
| 6 | **In progress** | Pilot season + recalibration — see above |
