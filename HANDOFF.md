# FloodSight — Cowork Handoff Note

Please read `README.md`, `ROADMAP.md`, and **`IMPROVEMENTS.md`** (the
July 2026 prioritized review — it is the current work queue) before doing
anything else.

> This note was rewritten in July 2026. The previous version described the
> Phase 5 state (616 rows, 3 LGAs, 30 m grid, R2=0.106) long after the repo
> had moved to Phase 22 — exactly the docs-vs-repo drift ROADMAP.md warns
> about. If numbers here ever disagree with the repo again, trust the repo
> and fix this file.

---

## What this project is

FloodSight is an open-data flood intelligence platform for Lagos, Nigeria.
Coverage: **15 flood-prone LGAs city-wide on a 200 m grid (~25k cells)**
(expanded in Phase 13 from the original 3-LGA / 30 m pilot).

The codebase has five main layers:
- **Data download** (`floodsight/download/`) — DEM, land cover, population,
  OSM, CHIRPS rainfall, Sentinel-1 SAR via Element84 / ASF / HyP3
- **Processing** (`floodsight/processing/`) — terrain derivatives (slope,
  flow accumulation, HAND), susceptibility scoring, HAND-based depth
- **Labeling** (`floodsight/labeling/`) — SAR flood extent (Otsu), FwDET
  depth estimation from extent + DEM
- **ML** (`floodsight/ml/`) — gradient-boosting depth model;
  `floodsight/ml/train.py` is the **single canonical trainer** (grouped
  split, provenance-aware metrics; scripts/09 delegates to it)
- **API + dashboard + alerting** (`api/`, `dashboard/`) — FastAPI backend
  and Leaflet frontend on Render; SMS alerts via Africa's Talking;
  subscribers + feedback logs in Supabase

## Current state (as of July 2026)

| Phase | Status | Description |
|---|---|---|
| 0-5 | Done | Susceptibility, HAND depth, pipeline, dashboard, first real labels |
| 13 | Done | City-wide expansion: 15 LGAs, 200 m grid |
| 14 | Done | Spatial rainfall (GFS 9-point + IMERG observed) |
| 16 | Done | Resident SMS subscriptions (Supabase + Africa's Talking) |
| 17-18 | Done | SWMM drainage models (Kosofe, Alimosho, Eti-Osa), NDPR consent |
| 21 | Done | ML depth grid under 100-yr design storm (/depth/ml-grid) |
| 22 | Done, then **corrected** | Training data augmentation — see warning below |
| Review fixes | **Done (July 2026)** | See IMPROVEMENTS.md items 1-7 |
| 6 (pilot loop) | **In progress — pick up here** | Rainy-season verification + recalibration |

## WARNING: Training data & metrics — read before quoting ANY accuracy number

`data/processed/real_training_dataset.csv` (2,536 rows) is **mixed
provenance**, tracked by the `label_source` column:

- 616 rows `sar_fwdet` — real SAR/FwDET-labeled observations
  (lekki_2024_07_03: 527, lekki_2021_07_12: 89)
- 1,920 rows `synthetic_augmented` — Phase 22 pseudo-labels: depths drawn
  from a severity-scaled lognormal, terrain resampled from Lekki cells

The previously-quoted Phase 22 numbers (R2=0.31, MAE=0.31 m) came from a
random row split that leaked every event into both train and test, on
76%-synthetic data, with the bundle mislabeled `trained_on_synthetic_data:
False`. **Do not quote them.**

The canonical trainer now (a) splits by event group and (b) reports
`metrics.holdout_real_rows_only` — performance on real-labeled held-out
rows. That is the only externally quotable number. Check the live values
via `GET /depth/model_info`. Expect it to be poor until more real events
are labeled — that is the honest state, and growing the real-labeled set
is the whole point of Phase 6.

To retrain (single path — do not resurrect a second trainer):

    python -m floodsight.ml.train --data data/processed/real_training_dataset.csv
    # or scripts/recalibrate.py --retrain (wraps the same module)

`scripts/09_train_flood_depth.py` (design-storm grid product) and
`scripts/10_augment_training_data.py` (event augmentation) both delegate
training to the canonical module and tag their rows with `label_source`
(`swmm_synthetic` / `synthetic_augmented`). Script 10 only seeds terrain
from real rows.

## Infrastructure changes made in the July 2026 review

- **Feedback logs persist in Supabase** (`prediction_log`, `verifications`,
  `dispatch_cells`) — run `scripts/sql/03_logs.sql` in the Supabase SQL
  editor once. Local JSONL under `data/logs/` is a dev-only fallback;
  Render's disk is EPHEMERAL and is wiped on every deploy.
- **Dispatch snapshots**: every `/alerts/dispatch` run records the
  Watch/Warning cells for that Lagos date. `scripts/recalibrate.py
  --analyse` computes FP/FN against this snapshot (matched by event_date +
  location), not against dashboard clicks.
- **Auth**: `DELETE /subscribe/{phone}`, `POST /verify`,
  `GET /depth/predictions_log`, and verification entries now require
  bearer secrets (`DISPATCH_SECRET`; `VERIFY_SECRET` optionally for field
  partners). Set both in Render. Comparison is constant-time (`api/auth.py`).
- **SMS templates** fit one GSM-7 segment and always end with the STOP
  opt-out (tests: `tests/test_sms_and_training.py`).
- Keep-alive workflow pings `/health` instead of recomputing the full
  alert grid every 14 minutes.

## What to do next — Phase 6 pilot loop

1. Run the live system through the rainy season (April-October) across the
   15 LGAs.
2. After each event, field partners submit `POST /verify` (with
   VERIFY_SECRET) for warned and unwarned locations.
3. `python scripts/recalibrate.py --analyse` -> FP/FN vs dispatched alerts.
4. Label new events properly (SAR + FwDET via `floodsight/labeling/`,
   rows tagged `label_source="sar_fwdet"`), append via
   `scripts/build_event_training_rows.py`, then `--retrain`.
5. Recalibrate `SUSCEPTIBILITY_WEIGHTS` (floodsight/config.py) from
   verified vs flagged locations.
6. The +/-0.3 m deck claim stays retired until
   `metrics.holdout_real_rows_only` supports it on >=3 held-out real events.

P2 items 9-12 are now built (all-clear SMS, STOP/START webhook, inbound
SMS verification, OTP subscribe, briefing->subscribers) and item 8 is
half-built (tidal signal live; dam-release monitoring still open) — see
IMPROVEMENTS.md for what each needs before it is fully live:
run `scripts/sql/04_inbound_otp.sql`, set AT_WEBHOOK_TOKEN, configure the
AT inbound callback URL, and flip REQUIRE_OTP after sandbox testing.
Then work down IMPROVEMENTS.md P3.

## SAR data source chain (unchanged — Planetary Computer is dead for this)

`floodsight/labeling/sar_extent.py` source chain for Sentinel-1 VV:

1. **Element84 Earth Search v1** (`sentinel-1-grd`) — scene discovery by
   date + AOI (asset URLs are requester-pays; direct download fails).
2. **ASF fallback** — `_download_vv_via_asf()` matches by absoluteOrbit +
   AOI WKT + time window.
3. **HyP3 RTC fallback** — submits an RTC job and downloads calibrated
   sigma0; output matched on the shared start timestamp.

One-time setup: pre-authorize the ASF Cumulus app with your Earthdata
account: `https://urs.earthdata.nasa.gov/approve_app?client_id=BO_n7nTIlMljdvU6kRRB3g`

## Known issues / caveats

1. **Copernicus DEM GLO-30 is a DSM** — rooftop heights inflate slope/HAND
   in dense urban cells (documented in `depth_hand.py`).
2. **HAND is NaN for lagoon/creek + DEM edge cells** — imputed with the
   training-set median, which is saved in the model bundle and reused at
   serving time (`hand_impute_median`).
3. **Rainfall feature importance is still low** — the real events span too
   few storm tracks; only more real labeled events fix this.
4. **2024 SAR "during" scene (July 3) was pre-peak** (peak July 4) —
   rain features for those rows are conservative.
5. **Dam-release and tidal floods are undetectable by rainfall alone**
   (2 of 8 back-test misses) — see IMPROVEMENTS.md item 8.
6. **`POST /subscribe` upsert is still unverified** — an attacker who knows
   a phone number can move that subscriber's location. OTP confirmation is
   IMPROVEMENTS.md item 10.

## Environment

- Conda env: `floodsight` (Python 3.11, numpy<2 pinned for pysheds)
- Activate: `conda activate floodsight`
- Run from project root: `cd C:\Users\User\Downloads\floodsight-starter\floodsight-starter`
- Credentials: `.env` in project root (NASA Earthdata + Africa's Talking)
- Render env vars: SUPABASE_URL, SUPABASE_KEY, AT_*, DISPATCH_SECRET,
  VERIFY_SECRET, AT_WEBHOOK_TOKEN (inbound SMS), REQUIRE_OTP (optional,
  default off)
- GitHub Actions secrets (morning briefing): add SUPABASE_URL,
  SUPABASE_KEY so the briefing reaches subscribers
- API locally: `uvicorn api.main:app --reload --port 8080`
- Live deployment: Render (auto-deploys on push to GitHub main)
- Tests: `pytest tests/ -v` (now also covers SMS encoding, trainer
  provenance, phone normalization)
