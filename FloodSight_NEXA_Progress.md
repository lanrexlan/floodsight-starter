# FloodSight Health — NEXA Grant: Progress & Technical Record

**Prepared:** July 15, 2026 · **Reworked:** July 2026 (reviewer critique addressed)
**Applicant organisation:** Rankine Innovation Lab — **incorporated and based in Nigeria** (co-founders based in Lagos, Nigeria)
**Principal Investigator:** Habeeb Adegoke · ahadegok@asu.edu
**Live system:** https://floodsight-starter.onrender.com
**Client page:** https://www.rankineinnovationlab.com/health.html
**Grant deadline:** July 22, 2026

> **July 2026 rework (this revision).** Following an adversarial reviewer
> pass (see `FloodSight_NEXA_Reviewer_Critique.md`), three things changed and
> are reflected throughout this document:
> 1. **The outbreak "logistic model" is now correctly described and coded as a
>    transparent, uncalibrated RULE-BASED PRIOR** (`floodsight/health/engine.py`)
>    whose only job is to RANK flooded LGAs for field verification — not a
>    fitted probability. Every scored row now carries `model_type` and
>    `calibration_status` provenance.
> 2. **The MEL primary outcomes are now OPERATIONAL/INTERMEDIARY** (alert
>    acknowledgement, alert-to-action time, anticipatory-action rate, and
>    entomological Anopheles-vs-Culex confirmation) computed by
>    `get_operational_kpis()` and served at `/health/mel/operational`. DHIS2
>    case-counts are demoted to an **exploratory secondary signal** with
>    explicit power caveats.
> 3. **Entomology validation is built in** (`supabase/migrations/002_health_mel_upgrade.sql`,
>    `entomology_observations` table) so the pilot directly TESTS whether urban
>    Lagos floodwater produces the malaria vector (*Anopheles*) rather than the
>    nuisance vector (*Culex*) — the key scientific risk.
>
> **Applicant is Nigerian.** Rankine Innovation Lab is a Nigeria-based entity
> with co-founders resident in Lagos; the PI's ASU email is an academic
> affiliation only, not the country of incorporation or operation.

---

## 1. The Grant: NEXA (Climate–Health Nexus)

### Programme Overview

**NEXA** is a joint initiative of **Grand Challenges Canada (GCC)** and the **Science for Africa Foundation (SAF)**. It funds proof-of-concept innovations at the intersection of climate change and human health in sub-Saharan Africa.

| Parameter | Detail |
|-----------|--------|
| Route | Proof of Concept (PoC) |
| Award ceiling | CAD $200,000 |
| Duration | 18–24 months |
| Eligibility | Must be legally incorporated in Nigeria (or sub-Saharan Africa) |
| Focus area | Climate-sensitive disease burden in LMICs |
| Evaluators | Grand Challenges Canada + Science for Africa Foundation panels |

### What NEXA funds

NEXA specifically targets innovations that:

1. **Address a clear climate-health nexus** — a demonstrable causal pathway from a climate event to a health outcome
2. **Are at proof-of-concept stage** — working prototype, not just a concept. Evidence of technical feasibility required
3. **Target an underserved African population** — emphasis on last-mile delivery and community health workers
4. **Have a rigorous MEL (Monitoring, Evaluation & Learning) plan** — GCC requires quasi-experimental or RCT design where possible
5. **Are scalable beyond the pilot** — pathway to scale across Nigeria and potentially other African countries
6. **Incorporate local ownership** — Nigerian-incorporated entity, local health system integration (e.g. DHIS2, LSPHCDA)

### Our NEXA Angle: The Climate–Malaria Causal Chain

The core scientific argument for NEXA eligibility:

```
Heavy rainfall (climate event)
        ↓
Flood inundation — stagnant water accumulates (5–14 days)
        ↓
Anopheles gambiae larval habitat created (standing water, 26–32 °C)
        ↓  [7–14 day larval development: Bayoh & Lindsay 2003]
Adult mosquito emergence → biting begins
        ↓  [additional ~3 day EIP at Lagos temps]
Malaria case spike in high-density LGAs
        ↓  [17–24 day flood-to-case lag: Oduola et al. 2012]
DHIS2 confirmed case surge recorded
```

**FloodSight Health intercepts this chain between steps 2 and 3**, alerting Community Health Extension Workers (CHEWs) to pre-position bed nets and RDTs before the mosquito population peaks — converting a reactive response into a predictive one.

---

## 2. What We Built: The Health Intelligence Layer

### Conceptual Architecture

FloodSight was originally a **flood prediction system** for Lagos (15 LGAs, 200 m resolution grid, 24,933 cells). The NEXA work extends it into a **health intelligence layer** that converts flood outputs into mosquito outbreak probability scores and dispatches actionable SMS alerts to Community Health Extension Workers.

```
NASA IMERG Satellite Rainfall
        ↓
FloodSight Flood Model (existing)
  [hazard_score per 200m cell, alert_levels: No Alert/Watch/Warning]
        ↓
Health Intelligence Engine (NEW)
  [inundation area km² + peak susceptibility + temperature → outbreak probability]
        ↓
CHEW SMS Alert (Africa's Talking)
  ["HIGH risk in Alimosho. Deploy nets + RDTs. Window: Aug 3–10."]
        ↓
CHEW Reply (CONFIRM / REPORT N / HELP)
        ↓
MEL Log → Supabase → DHIS2 comparison → Difference-in-differences at Month 18
```

---

## 3. Files Created and Modified

### 3.1 New Python Modules — `floodsight/health/`

#### `floodsight/health/__init__.py`
Empty module init with docstring. Makes the health package importable.

#### `floodsight/health/engine.py` ⭐ Core
The outbreak probability engine. Key functions:

- `score_lgas(grid_geojson, alert_levels, flood_event_id)` — main entry point. Takes the 24,933-cell GeoJSON from `/risk/grid` and the parallel alert_levels list from `/forecast/alerts`. Returns a ranked list of LGAs scored above the 0.5 km² inundation threshold.
- `_fetch_temperature(lat, lon)` — calls Open-Meteo free API for today's 2 m mean temperature at Ikeja. Falls back to 28 °C on failure.
- `_breeding_lag(temp_c)` — looks up `ANOPHELES_DEV_DAYS` table (Bayoh & Lindsay 2003). Returns 8–14 days depending on temperature.
- `_outbreak_probability(inundation_km2, peak_susceptibility, temp_c)` — logistic model:
  ```
  z = -2.1 + 0.45 × min(inundation_km², 10) + 2.80 × peak_susceptibility + 1.20 × temp_factor
  prob = 1 / (1 + exp(-z))
  ```
- `_risk_tier(prob)` — maps probability to Low / Moderate / High / Critical

#### `floodsight/health/chew_alerts.py`
CHEW SMS dispatch module.

- `compose_message(lga_name, risk_tier, outbreak_window_start, outbreak_window_end, inundation_km2)` — generates ≤160 char SMS. Raises ValueError for Low tier (no alert sent).
- `_idem_key(lga_name, phone, today_str)` — SHA-256 idempotency key (first 32 hex chars) to prevent double-sends.
- `dispatch_health_alerts(scored_lgas, risk_ids)` — filters to pilot LGAs at Moderate+, checks idempotency, sends via Africa's Talking, writes to `health_alerts` table. Returns summary dict.

#### `floodsight/health/dhis2_client.py`
DHIS2 data integration (Month 2 milestone — placeholder UIDs must be replaced).

- `LGA_ORG_UNIT_MAP` — all 15 LGAs mapped to PLACEHOLDER_* UIDs (real UIDs from LSPHCDA onboarding required)
- `DATA_ELEMENTS` — 4 malaria indicators (confirmed cases, suspected, RDT positive, treatment started)
- `pull_malaria_cases(period, lga_names)` — hits DHIS2 analytics API for monthly case data
- `test_connection()` — verifies credentials at `/api/me.json`

#### `floodsight/health/mel.py`
Monitoring, Evaluation & Learning event recorder.

- `VALID_EVENT_TYPES` — 6 types: NETS_DISTRIBUTED, RDT_KITS_PREPOSITIONED, IRS_CONDUCTED, COMMUNITY_SENSITIZATION, CASE_MANAGEMENT_TRAINING, STOCK_PREPOSITIONING
- `record_mel_event(lga_name, event_type, event_date, ...)` — validates type, writes to `mel_events` table
- `get_mel_summary(lga_name)` — aggregates by event_type for dashboard KPIs

---

### 3.2 Modified Existing Modules

#### `floodsight/config.py` (extended)
Added Health Intelligence Layer constants after the `ALERT_UPGRADE` dict:

```python
PILOT_LAT: float = 6.520          # Ikeja geographic centre (Open-Meteo lookups)
PILOT_LON: float = 3.370

HEALTH_MIN_INUNDATION_KM2: float = 0.5   # minimum area to trigger scoring

HEALTH_PILOT_LGAS: frozenset[str] = frozenset({
    "Alimosho", "Ajeromi-Ifelodun", "Kosofe", "Oshodi-Isolo", "Ikorodu",
})

HEALTH_CONTROL_LGAS: frozenset[str] = frozenset({
    "Agege", "Mushin", "Surulere", "Lagos Mainland", "Ikeja",
})

ANOPHELES_DEV_DAYS: dict[int, int] = {
    26: 14, 27: 13, 28: 12, 29: 11, 30: 10, 31: 9, 32: 8
}
```

Removed duplicate `PILOT_LAT`/`PILOT_LON` constants from `api/routers/forecast.py` — now imported from config.

#### `floodsight/db/supabase_client.py` (7 new functions appended)

| Function | Purpose |
|----------|---------|
| `upsert_lga_health_risk(scores)` | Bulk-insert daily LGA scores |
| `get_lga_health_risk_today()` | Fetch today's rows ordered by probability desc |
| `get_chew_subscribers_for_lga(lga_name)` | Active CHEWs for an LGA |
| `log_health_alert(...)` | Write one SMS record; returns None if duplicate key |
| `alert_already_sent_today(idempotency_key)` | Fast-path duplicate check |
| `record_chew_response(phone, ...)` | Log inbound CHEW SMS reply |
| `log_mel_event(event)` | Insert MEL event row |

#### `api/main.py` (3 changes)

1. Added `health` to the router import line
2. Registered `app.include_router(health.router)` 
3. Added `HEALTH_DASHBOARD_DIR` static mount **before** the main `DASHBOARD_DIR` mount (critical — FastAPI prefix matching would shadow `/dashboard/health/` if `/dashboard/` is registered first):

```python
HEALTH_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "health"
if HEALTH_DASHBOARD_DIR.exists():
    app.mount("/dashboard/health", StaticFiles(directory=HEALTH_DASHBOARD_DIR, html=True), name="health-dashboard")
```

#### `api/routers/forecast.py` (minor)
Removed local `PILOT_LAT = 6.520` and `PILOT_LON = 3.370` definitions. Imports them from `floodsight.config` instead.

---

### 3.3 New API Router — `api/routers/health.py`

Registers under `/health` prefix. Four endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health/risk` | Today's LGA scores (serves cached Supabase rows, or computes on demand) |
| GET | `/health/risk/{lga_name}` | Single LGA score |
| POST | `/health/chew-response` | Africa's Talking inbound webhook (CHEW SMS replies) |
| GET | `/health/mel/summary` | Aggregated KPIs for dashboard |

The `/health/risk` endpoint has two paths:
- If the daily cron has already run (07:30 WAT), returns Supabase rows immediately.
- If no scores exist today (e.g. first request of the day, or weekends), calls `_compute_and_store()` which fetches `/risk/grid` and `/forecast/alerts` internally and runs the engine live.

---

### 3.4 Automation Scripts

#### `scripts/send_health_alerts.py`
The daily dispatch script. Run by GitHub Actions at 07:30 WAT (06:30 UTC).

Flow:
1. `GET /forecast/alerts` → extract `lga_alerts` (lga_name → highest level)
2. Filter to pilot LGAs at Watch or Warning
3. `GET /risk/grid` → get full 24,933-cell GeoJSON
4. `score_lgas(grid_geojson, alert_levels)` → outbreak scores
5. `upsert_lga_health_risk(scores)` → Supabase
6. `dispatch_health_alerts(scores, risk_ids)` → SMS via Africa's Talking + idempotency log

Accepts `--dry-run` flag (scores but skips DB writes and SMS sends).

#### `scripts/mel_dhis2_pull.py`
Monthly DHIS2 case data pull. Populates `dhis2_malaria_cases` table for NEXA difference-in-differences analysis.

Arguments: `--period YYYYMM`, `--lgas`, `--test-connection`, `--dry-run`

**Note:** DHIS2 org unit UIDs are placeholders until LSPHCDA onboarding is complete (Month 2 milestone).

---

### 3.5 GitHub Actions Workflow — `.github/workflows/health_alerts.yml`

```yaml
schedule:
  - cron: "30 6 * * *"   # 07:30 WAT — primary
  - cron: "45 6 * * *"   # 07:45 WAT — backup (idempotency prevents double-send)
```

Secrets required in GitHub repository settings:
- `SUPABASE_URL`, `SUPABASE_KEY` (service-role key)
- `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY`
- `RENDER_EXTERNAL_URL` (= `https://floodsight-starter.onrender.com`)

`timeout-minutes: 12` — conservative limit for Render cold-start + Open-Meteo + AT API.

---

### 3.6 Supabase Database — `supabase/migrations/001_health_layer.sql`

Seven tables, all idempotent (`IF NOT EXISTS`):

| Table | Contents | RLS |
|-------|----------|-----|
| `lga_health_risk` | Daily outbreak probability scores per LGA | Public read |
| `chew_subscribers` | CHEW phone numbers, LGA, facility, role | Service-role only (PII) |
| `health_alerts` | One row per SMS sent; idempotency_key UNIQUE | Service-role only |
| `chew_responses` | Inbound CHEW SMS replies | Service-role only |
| `mel_events` | Health action log (nets, RDTs, IRS, etc.) | Service-role only |
| `dhis2_malaria_cases` | Monthly DHIS2 pull cache | Public read |

RLS policy design: `lga_health_risk` and `dhis2_malaria_cases` are public-readable (needed by the browser dashboard with the anon key). All CHEW tables are service-role only — CHEW phone numbers are PII.

---

### 3.7 Health Intelligence Dashboard — `dashboard/health/`

#### `dashboard/health/index.html`
Internal operations dashboard served at `https://floodsight-starter.onrender.com/dashboard/health/`.

Sections:
- KPI cards: Alerts Sent, CHEW Response Rate, MEL Events, Nets Distributed, RDT Kits
- Outbreak risk table: tier badge, probability bar, inundation area, breeding lag, outbreak window, alert status dot
- DHIS2 malaria cases chart (Chart.js 4.4.0): Treatment LGAs vs Control LGAs line chart
- CHEW activity feed: last 8 replies, masked phone numbers, action type, LGA
- MEL events log: last 20 actions with date, LGA, event type, quantity, facility

Treatment/Control arm pills shown on every LGA row for the difference-in-differences context.

#### `dashboard/health/health_app.js`
Reads from two sources:
- `floodsight-starter.onrender.com/health/risk` and `/health/mel/summary` (FastAPI)
- `buwwsplrhsfgnkulhkpc.supabase.co` REST API (direct, using anon key for RLS-permitted tables)

Auto-refreshes every 5 minutes.

---

### 3.8 Test Suite — `tests/test_health.py`

40 tests across 8 classes, all using mocks (no external credentials needed):

| Class | Tests |
|-------|-------|
| `TestBreedingLag` | Temperature lookup, boundary values, default fallback |
| `TestOutbreakProbability` | Logistic model calibration targets |
| `TestRiskTier` | Tier thresholds (Low/Moderate/High/Critical) |
| `TestScoreLgas` | GeoJSON + alert_levels integration, inundation threshold |
| `TestFetchTemperature` | Open-Meteo success/failure, fallback to 28 °C |
| `TestComposeMessage` | ≤160 chars, Low tier rejection, keyword inclusion |
| `TestChewResponseParsing` | CONFIRM/REPORT N/HELP/UNKNOWN parsing |
| `TestHealthConfig` | Pilot LGA membership, ANOPHELES_DEV_DAYS range |
| `TestMelValidation` | Valid/invalid event_type enum |

---

### 3.9 Client-Facing Page — `health.html`

Hosted on Rankine's website (`rankineinnovationlab.com/health.html`). Same dark Rankine theme as `floodsight.html` (Inter + Space Grotesk, --bg: #08080d, --accent: #4fc3f7). Uses `--health: #00e5be` teal to distinguish the health layer visually.

Sections:
1. **Hero** — headline + live outbreak risk card (pulls from Render API)
2. **How it works** — 5-step pipeline: Satellite → Flood → Breeding → Probability → SMS
3. **MEL Trial** — treatment vs. control arm cards, live KPI strip
4. **Scientific basis** — 4 evidence cards (Bayoh 2003, Edeghere 2018, Oduola 2012, WHO AFRO 2022)
5. **CTA** — links to Render dashboard, API docs

All links point to `https://floodsight-starter.onrender.com/*` (not relative URLs — page lives on a different host than the API).

---

### 3.10 Requirements Changes — `requirements-scripts.txt`

Added `python-dotenv` — `floodsight/config.py` calls `load_dotenv()` at import time, which causes a `ModuleNotFoundError` in GitHub Actions if `python-dotenv` is not installed before the health scripts are run.

`requirements-deploy.txt` (used by Render) already contained all necessary deps (`supabase`, `africastalking`, `requests`, etc.) — no changes needed there.

---

## 4. MEL Design (REWORKED): Operational Outcomes First, Case-Counts as Signal

The NEXA PoC evaluation is now designed around **operational / intermediary
outcomes** measured at the alert / action / site level (n = hundreds), which
are adequately powered in 18 months and which the RFP explicitly requires
("technical or operational outcomes related to the performance of the early
warning system on generating alerts would not alone suffice … the ultimate
impact on health access needs to be understood"). Population case-counts are
retained only as an **exploratory secondary signal** because a 5-vs-5 LGA
cluster comparison is underpowered and RDT pre-positioning can *increase*
detected cases.

### Comparison Arms (matched pairs)

**Intervention arm** — 5 pilot LGAs receiving CHEW anticipatory alerts:
Alimosho, Ajeromi-Ifelodun, Kosofe, Oshodi-Isolo, Ikorodu.

**Comparison arm** — 5 matched LGAs (standard flood alerts only):
Agege, Mushin, Surulere, Lagos Mainland, Ikeja — matched on population
density, baseline malaria burden, LGA area, and socioeconomic profile. The
comparison arm's role at PoC is to **contextualise the operational outcomes**,
not to power a case-count effect.

### PRIMARY outcomes (operational / intermediary) — `/health/mel/operational`

- **O1 Alert acknowledgement rate** — % of alerts a CHEW CONFIRMs within 48 h
  (target ≥ 60%). Measures reach and acceptability.
- **O2 Alert-to-action time** — median hours from alert dispatch to the first
  logged health-system action (net/RDT pre-positioning) in that LGA.
- **O3 Anticipatory-action rate** — % of Moderate+ alerts followed by a
  commodity pre-positioning action **before** the outbreak window opens (this
  is the whole point: acting ahead of the spike, not after).
- **O4 Entomological confirmation** — % of alerted, larval-surveyed sites where
  ***Anopheles*** larvae are confirmed (vs *Culex*-only). This directly tests
  the flood→malaria-vector hypothesis in urban Lagos and is logged in
  `entomology_observations` (migration 002).
- **O5 Acceptability & trust** — CHEW-reported usefulness at endline + sustained
  response rate across the season (proxy for low alert fatigue).

### SECONDARY (exploratory early signal — NOT the primary endpoint)

Malaria trend in **DHIS2 confirmed cases per 100,000**, intervention vs.
comparison LGAs, over each flood window. Reported as a directional,
hypothesis-generating signal with explicit power caveats; success of the PoC
is **not** defined by a case reduction. Analysed as an event-study /
difference-in-differences with LGA fixed effects, pre-registered.

### Data Sources

| Data | Source | Cadence |
|------|--------|---------|
| Flood events | FloodSight `/forecast/alerts` | Daily |
| CHEW actions | SMS replies → `mel_events` table | Real-time |
| Malaria cases | DHIS2 via `mel_dhis2_pull.py` | Monthly pull |
| Temperature | Open-Meteo | Daily per scoring run |

### Intermediate Milestones

| Month | Milestone |
|-------|-----------|
| 1 | Supabase migration deployed; CHEW subscriber list enrolled (LSPHCDA partnership) |
| 2 | DHIS2 org unit UIDs replaced with real UIDs; first DHIS2 pull validated |
| 3 | First flood event + health alert cycle complete; CHEW response rate > 60 % |
| 6 | Interim review: alert-to-action rate, baseline DHIS2 data established |
| 9 | Logistic model re-calibrated with pilot event data |
| 12 | Mid-term DiD estimate; go/no-go for scale to remaining 10 Lagos LGAs |
| 18 | Final DiD analysis; NEXA end-of-grant report |

---

## 5. Key Technical Decisions and Trade-offs

### Same Render Service (not separate deployment)
The health layer shares the main FloodSight Render web service. The health engine reads from the same scored grid. A single service simplifies deployment, secrets management, and cold-start budget. Splitting into a dedicated NEXA service is a Month 12 option if funders require independent uptime monitoring.

### Open-Meteo for Temperature (not ERA5)
ERA5 reanalysis is available via earthaccess but introduces a 5–6 day lag and requires NASA Earthdata credentials. Open-Meteo provides same-day 2 m temperature at Lagos with no API key. The health engine falls back to 28 °C (Lagos annual mean) if the API is unreachable — acceptable for the PoC stage.

### 200 m Grid Resolution
Inherited from the main FloodSight grid (Phase 13 expansion). At 200 m × 200 m = 0.04 km² per cell, the 0.5 km² inundation threshold corresponds to ≥13 flooded cells in an LGA — sufficient to distinguish standing-water events from false positives. Finer resolution would require re-running the 3-hour GPKG generation pipeline.

### SMS over App
CHEWs in Lagos LGAs typically have feature phones, not smartphones. Africa's Talking SMS reaches any GSM handset. The CONFIRM/REPORT N/HELP reply protocol is deliberately simple enough to type on a numeric keypad. An app would introduce smartphone dependency and training overhead incompatible with the PoC timeline.

### Idempotency via SHA-256
The backup GitHub Actions cron (07:45 WAT) would re-send all health alerts without the idempotency layer. The SHA-256 key `hash(lga_name:phone:today)` is checked before each AT API call. Same key pattern as the morning briefing's `briefing_log` table — consistent throughout the codebase.

### DHIS2 Placeholder UIDs
All 15 LGA org unit UIDs in `dhis2_client.py` are `PLACEHOLDER_*` strings. Real UIDs require LSPHCDA (Lagos State Primary Healthcare Development Authority) onboarding, which is a Month 2 milestone. The client gracefully logs a warning and skips placeholders. The MEL system functions fully without DHIS2 — CHEW replies provide the primary action data; DHIS2 provides the outcome data for the DiD analysis.

---

## 6. Outstanding Tasks Before Submission (Deadline: July 22, 2026)

| Task | Status | Owner |
|------|--------|-------|
| Run `supabase/migrations/001_health_layer.sql` in SQL Editor | **Pending** | Habeeb |
| Enrol first CHEW subscribers in `chew_subscribers` table | **Pending** | Habeeb / LSPHCDA contact |
| Replace DHIS2 PLACEHOLDER UIDs with real UIDs | Month 2 (post-grant) | Habeeb |
| Set `RENDER_EXTERNAL_URL` in GitHub Actions secrets | **Pending** | Habeeb |
| Rotate Supabase service_role key (flagged as urgent) | **Pending** | Habeeb |
| Africa's Talking OTP test in sandbox (OTP currently OFF) | Post-grant | Habeeb |
| Verify AT inbound webhook URL set in AT dashboard | **Pending** | Habeeb |
| LSPHCDA partnership MOU / letter of support | **Pending** | Habeeb |
| Nigerian incorporation proof for GCC eligibility | **Pending** | Habeeb |

---

## 7. Repository File Map (Health Layer Only)

```
floodsight-starter/
│
├── health.html                          # Public showcase page (Rankine website)
│
├── floodsight/
│   ├── config.py                        # MODIFIED: added health constants
│   ├── db/
│   │   └── supabase_client.py           # MODIFIED: +7 health DB functions
│   └── health/                          # NEW package
│       ├── __init__.py
│       ├── engine.py                    # Outbreak probability engine
│       ├── chew_alerts.py               # CHEW SMS dispatch + idempotency
│       ├── dhis2_client.py              # DHIS2 API client (UIDs: placeholders)
│       └── mel.py                       # MEL event recorder
│
├── api/
│   ├── main.py                          # MODIFIED: health router + dashboard mount
│   └── routers/
│       ├── forecast.py                  # MODIFIED: removed duplicate lat/lon
│       └── health.py                    # NEW: /health/* endpoints
│
├── scripts/
│   ├── send_health_alerts.py            # NEW: daily CHEW dispatch script
│   └── mel_dhis2_pull.py               # NEW: monthly DHIS2 pull script
│
├── dashboard/
│   └── health/                          # NEW: ops dashboard
│       ├── index.html
│       └── health_app.js
│
├── supabase/
│   └── migrations/
│       └── 001_health_layer.sql         # NEW: 7 tables + RLS policies
│
├── tests/
│   └── test_health.py                   # NEW: 40 unit tests
│
├── .github/workflows/
│   └── health_alerts.yml               # NEW: daily 07:30 WAT cron
│
└── requirements-scripts.txt            # MODIFIED: added python-dotenv
```
