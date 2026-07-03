# FloodSight — Starter Scaffold

A runnable Python scaffold for FloodSight: open-data ingestion → terrain
processing → flood susceptibility scoring → HAND-based physical depth
estimation → an ML depth model (trainable once you have real labels) →
a FastAPI backend → a Leaflet dashboard. Built to execute
[ROADMAP.md](ROADMAP.md) Phases 0–5 starting from nothing.

**This is a starting point, not a finished product.** Every download
module is wired to a real, currently-working open data source (verified
June 2026 — see the table below), and every processing/ML/API/dashboard
component has been run end-to-end against synthetic data to confirm the
code paths actually work. The real geospatial downloads need to run on
your own machine with internet access to AWS/NASA/Copernicus — they
were not (and could not be) executed from inside the environment that
built this scaffold. Treat the download scripts as correct-as-written,
not as proven against live data, and check the logs the first time you
run each one.

## What's real vs synthetic right now

| Layer | Status |
|---|---|
| Download scripts (DEM, land cover, population, boundaries, OSM, CHIRPS, GPM, GloFAS, Sentinel-1) | Real, working endpoints — not yet run against your AOI |
| Grid building, terrain derivatives, feature joining | Real code, tested with synthetic arrays, not yet run on real Lagos rasters |
| Susceptibility scoring (`flood_score`/`risk_class`) | Real, ported from the original repo formula, **tested end-to-end** |
| HAND-based depth (Track A) | Real, **tested end-to-end** on synthetic terrain — needs real HAND + discharge data to mean anything |
| FwDET-style depth labeling | Real algorithm, **unit-tested** against a synthetic DEM bowl |
| ML depth model | Real training/serving code, **tested end-to-end** — currently only has synthetic training data; produces no real depth predictions until you build the labeled dataset (Phase 4) |
| API | Real, **tested end-to-end** — all 4 endpoints verified working |
| Dashboard | Real Leaflet app, talks to the API; not yet visually verified in a browser (verify on your machine) |

Run `python scripts/run_demo_pipeline.py` to see all of this work
together on synthetic data in under a minute, with zero downloads.

## Quickstart (synthetic demo — zero setup, zero downloads)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # or just the "Core" group, see below

python scripts/run_demo_pipeline.py      # builds a synthetic grid, scores it,
                                          # trains the ML model, runs HAND depth

uvicorn api.main:app --reload --port 8000
# then open dashboard/index.html in a browser
```

You'll see a real (if synthetic-terrain) risk map, and can click anywhere
to get a risk class + alert level, with rainfall sliders driving the
alert engine live.

## Quickstart (real data)

```bash
cp .env.example .env   # fill in NASA Earthdata + CDS credentials (see table below)

python scripts/01_download_all.py              # DEM, land cover, population, OSM, CHIRPS
python scripts/02_build_grid_and_features.py   # mosaic, reproject, build grid, terrain, join
python scripts/03_compute_susceptibility.py    # flood_score / risk_class
python scripts/04_compute_hand_depth.py --rain-24h 120 --catchment-km2 25

uvicorn api.main:app --reload --port 8000      # now serves data/processed/scored_grid.gpkg
```

`scripts/01_download_all.py` downloads several large files (the OSM
Nigeria extract alone is several hundred MB). Use `--skip-osm`,
`--skip-rainfall`, `--skip-gpm` to skip what you don't need yet.

## Open data sources used (verified June 2026)

| Theme | Dataset | Access | Account needed? |
|---|---|---|---|
| Elevation | Copernicus DEM GLO-30 | [AWS S3](https://registry.opendata.aws/copernicus-dem/): `s3://copernicus-dem-30m` (no-sign-request) | No |
| Land cover | ESA WorldCover 10m v200 (2021) | [AWS S3](https://esa-worldcover.org/en/data-access): `s3://esa-worldcover/v200/2021/map` (no-sign-request) | No |
| Population | WorldPop Nigeria, 100m constrained UN-adjusted | [HDX](https://data.humdata.org/dataset/worldpop-population-counts-for-nigeria) / [WorldPop hub](https://hub.worldpop.org/geodata/summary?id=28031) | No |
| Admin boundaries | geoBoundaries Nigeria ADM0-2 | [GitHub raw](https://github.com/wmgeolab/geoBoundaries) / [HDX](https://data.humdata.org/dataset/geoboundaries-admin-boundaries-for-nigeria) | No |
| Roads/buildings/water | OpenStreetMap, Nigeria extract | [Geofabrik](https://download.geofabrik.de/africa/nigeria.html) | No |
| Rainfall (historical/near-real-time) | CHIRPS daily, Africa 0.05° | [UCSB Climate Hazards Center](https://www.chc.ucsb.edu/data/chirps), direct HTTPS index | No |
| Rainfall (near-real-time upgrade path) | GPM IMERG | [NASA GES DISC](https://www.earthdata.nasa.gov/data/catalog/ges-disc-gpm-3imergdf-07) via `earthaccess` | Yes — free [Earthdata account](https://urs.earthdata.nasa.gov/users/new) |
| River discharge | GloFAS historical/forecast | [Copernicus Early Warning Data Store](https://ewds.climate.copernicus.eu/datasets/cems-glofas-historical) via `cdsapi` | Yes — free [EWDS account](https://ewds.climate.copernicus.eu/) |
| SAR flood extent (for labeling) | Sentinel-1 RTC | [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc) STAC API | No |

Two notes worth knowing before you rely on these:

- **CHIRPS v2 → v3 transition**: CHIRPS v2 production ends December
  2026. The download script targets v2's stable URL pattern; if you're
  reading this after the transition, check
  [chc.ucsb.edu/data/chirps3](https://chc.ucsb.edu/data/chirps3) for
  v3's path layout and update `floodsight/download/rainfall_chirps.py`.
- **GloFAS moved data stores in 2024** — it now lives on the Early
  Warning Data Store (`ewds.climate.copernicus.eu`), not the general
  Climate Data Store referenced in a lot of older tutorials you'll find
  online. The URL in `.cdsapirc` (see `.env.example`) must point at
  `ewds.climate.copernicus.eu/api`, not `cds.climate.copernicus.eu/api`.

## Installing dependencies

```bash
pip install -r requirements.txt
```

That installs everything. If the combined geospatial install (GDAL
bindings via `rasterio`/`geopandas`) is slow or flaky in your
environment, install in two passes — the "Core" group (top of
`requirements.txt`) is enough to run the synthetic demo, train the ML
model, and serve the API/dashboard with zero geo setup; add the
"Geospatial processing" group when you're ready to run the real
pipeline.

`pysheds` (used for flow direction/accumulation/HAND in
`floodsight/processing/terrain.py`) has shifted its API across
versions. If `grid.compute_hand(...)` doesn't match the signature in
this codebase, run `help(pysheds.grid.Grid.compute_hand)` for your
installed version and adjust — pin a known-good version with
`pip install pysheds==0.3.5` if you want to match what this scaffold
was written against.

## Project structure

```text
floodsight-starter/
  floodsight/
    config.py              # AOI, paths, weights, thresholds — edit this first
    download/               # one module per data source, each independently runnable
    processing/
      grid.py                # 30m fishnet grid, clipped to pilot LGAs
      terrain.py              # slope, flow accumulation, HAND (pysheds)
      features.py              # samples all rasters/vectors onto the grid
      susceptibility.py         # flood_score / risk_class — ported v0 logic
      depth_hand.py              # HAND synthetic rating curve -> real depth in meters
    labeling/
      sar_extent.py            # Sentinel-1 change detection -> flood extent
      fwdet.py                   # extent + DEM -> depth labels (FwDET reimplementation)
    ml/
      synthetic.py              # synthetic training data (demo/testing only)
      dataset.py                  # builds the REAL labeled dataset once you have events
      train.py                     # gradient-boosting baseline trainer
      predict.py                    # loads trained model, serves predictions
    alerts/
      engine.py                # rainfall + risk class (+ optional depth) -> alert level
  api/                        # FastAPI app — /risk, /depth, /alerts
  dashboard/                  # Leaflet single-page app, talks to the API
  scripts/                    # orchestration: run these in order for the real pipeline
  tests/                      # pytest smoke suite — run this after any change to the math
  data/{raw,processed,models} # gitignored; regenerated by scripts/
```

## API reference

Once running (`uvicorn api.main:app --reload --port 8000`), full
interactive docs are at `http://localhost:8000/docs`. Summary:

| Endpoint | Method | Purpose |
|---|---|---|
| `/risk/grid` | GET | Full grid as GeoJSON, styled by `risk_class` — what the dashboard renders |
| `/risk/point?lat=&lon=` | GET | Nearest-cell risk info for a single point |
| `/depth/predict` | POST | ML depth prediction from a feature dict (see `api/schemas.py`) |
| `/alerts/current` | POST | Risk class + rainfall (+ optional depth) → alert level |

Every response includes a `data_source` (or `model_trained_on_synthetic_data`)
field so you always know whether you're looking at real pipeline output
or the synthetic fallback — check this before trusting any number.

## Testing

```bash
pip install pytest
pytest tests/ -v
```

Covers susceptibility scoring, the alert engine (including the depth
override), the FwDET depth algorithm, the HAND rating curve, and an
ML train/save/load roundtrip — all without needing downloaded data.
Run this after touching any of the scoring/depth/alert math.

## Where this fits in the roadmap

This scaffold gets you a runnable Phase 0–3 system (susceptibility
scoring, HAND-based physical depth, a trainable ML layer, API,
dashboard) on day one. The two things only you can do from here:

1. **Phase 1 calibration** — set `DEFAULT_MANNING_N` and
   `DEFAULT_CHANNEL_SLOPE` in `floodsight/processing/depth_hand.py`
   from real channel data once you have it, and validate
   `drainage_threshold_cells` in `terrain.py` against visible drainage
   in the AOI.
2. **Phase 4 labeled dataset** — run `labeling/sar_extent.py` +
   `labeling/fwdet.py` against real historical Lagos flood dates, feed
   the results into `ml/dataset.py`, and retrain `ml/train.py` on that
   instead of `ml/synthetic.py`. That's the one step that turns the ML
   layer from a demonstration into something you can actually report
   accuracy numbers for.

See [ROADMAP.md](ROADMAP.md) for the full phased plan, including
Phase 6 (pilot season + recalibration) and the open questions that
need a team decision before Phase 4 can start.
