# FloodSight Lagos

FloodSight is a flood susceptibility and weather advisory pilot for selected Lagos areas. The map uses a weighted terrain/drainage overlay on 200 m × 200 m cells. Rainfall, coastal and river signals drive advisory thresholds. Experimental ML depth estimates and a health research layer are separate from the susceptibility map.

Current release status and open launch requirements: [RELEASE_STATUS.md](RELEASE_STATUS.md). Deployment and incident procedures: [DEPLOYMENT.md](DEPLOYMENT.md). Earlier phase documents are historical context.

## Run locally

Use Python 3.11. From this folder:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-deploy.txt
.venv\Scripts\python scripts/prepare_release_assets.py
.venv\Scripts\python -m uvicorn api.main:app --reload --port 8000
```

Open http://localhost:8000/floodsight.html for the public page, http://localhost:8000/dashboard/ for the map, and http://localhost:8000/docs for API documentation. Serve pages through this app; opening HTML files directly is not the complete supported workflow. The frontend uses the same origin as the API. The map uses MapLibre.

Configure private settings from `.env.example` as needed. Do not overwrite an existing `.env`. Without SMS/database credentials, subscriptions are unavailable; the map can still show static susceptibility. A weather outage is displayed explicitly. Synthetic map fallback is available for development only and clearly labelled.

## What the supplied data supports

The scored grid contains 24,933 cells across 15 pilot LGAs. Road colours inherit area susceptibility; they are not independently validated road inundation predictions. Local search selects LGA centres, not addresses. GPS and map point queries use mapped-cell coverage checks.

The current training CSV has 2,536 rows: 616 SAR/FwDET-labelled rows across two events, plus 1,920 synthetic rows. These remote-sensing-derived labels are not the same as calibrated field depth measurements. Historical model artifacts have their own saved provenance, exposed by `/depth/model_info`; do not confuse that with the current CSV composition.

Run:

```powershell
.venv\Scripts\python scripts/evaluate_model.py
```

The resulting `reports/model_validation.json` evaluates each observed event separately and compares a baseline. Current generalization is poor. Additional observed flood and non-flood events, independent locations, uncertainty calibration, and prospective warning delivery/lead-time evidence remain required.

No Alert means no configured threshold exceeded; it does not guarantee that flooding will not occur. The 150 mm design-storm layer is a rainfall scenario, not a validated 100-year return period. Health probabilities are uncalibrated research estimates. Production disables experimental depth and outbound public/research alerts unless explicitly enabled.

## API and storage

- `/risk/grid`: compact cached map; deployment prepares compressed files.
- `/risk/point?lat=&lon=`: indexed lookup; invalid/outside/unmapped locations return 422.
- `/risk/streets?bbox=west,south,east,north`: small street viewport windows.
- `/forecast/rainfall`, `/forecast/alerts`, `/forecast/summary`: weather and threshold advisories.
- `/subscribe`, `/subscribe/confirm`: explicit consent and production phone verification.
- `/verify`, `/depth/predictions_log`, private health views, and operator actions: authenticated access.
- `/health`: process liveness. `/ready`: configured production services/schema.
- `/product-status`: coverage, stage, scoring bands and alert thresholds.
- `/places/search`, `/places/reverse`: local area search/labels.
- `/privacy.html`: subscriber privacy information.

Supabase persists subscriptions, reports, predictions and delivery records. Production never accepts a local verification file as durable storage. Apply the numbered SQL migrations, configure retention, and test recovery before resident enrolment. `DISPATCH_SECRET` is operator access; `VERIFY_SECRET` is field-partner access (falls back to operator access).

## Verification

```powershell
.venv\Scripts\python -m pip install pytest httpx rasterio
.venv\Scripts\python -m pytest tests -q
```

CI adds a disposable PostgreSQL service to test migrations, private access, concurrent cost limits, single-use OTP, SMS reservations, and retention. It also scans dependencies and builds the deployment container. No production credentials or resident messages are used by the tests.

GIS download/processing scripts require the broader geospatial dependencies in `requirements.txt`. Keep that environment separate from the serving environment. Trained joblib artifacts require the pinned serving scikit-learn version; only load trusted model files.
