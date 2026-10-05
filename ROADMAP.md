# FloodSight Roadmap — From Susceptibility Map to Flood Depth Platform

> Historical June 2026 roadmap, not current deployment or validation status.
> Current evidence: `RELEASE_STATUS.md`, `UX_OPS_FIXES.md`, `PILOT_ACCEPTANCE.md`
> and `SCIENTIFIC_VALIDATION.md`. The targets below are not achieved claims.

**Status as of June 2026:** Open-data flood *susceptibility* prototype (QGIS-based) for three Lagos LGAs. No flood depth prediction, no trained ML model, no live data pipeline, no deployed application yet.

**Target:** What the pitch deck describes — an AI flood-depth prediction platform (meters of inundation, 72-hour lead time) with a community-facing alert layer, deployed and validated.

This document is deliberately blunt about the current gap so the team can close it credibly, rather than risk it being discovered by a judge, partner, or investor first.

---

## 1. Where we are (honest baseline)

| Component | Pitch deck claim | Repo reality |
|---|---|---|
| Flood depth prediction | LSTM + physics-informed NN, ±0.3m accuracy | Not built. Output is a 4-class risk category, not a depth value. |
| AI model | "AI Depth Prediction" engine | Static weighted-overlay formula with manually set coefficients. No training, no learned parameters. |
| Rainfall alerts | Real-time fusion engine, 72-hr precipitation-to-runoff modelling | Threshold rule on `rain_24h`/`rain_72h` against fixed mm values. CHIRPS pulled manually for demo dates, not automated. |
| Dashboard / app | Mobile-first dashboard, SMS fallback, "SMS gateway integrated" (2025 Q4) | No web app, no mobile app, no SMS integration. Output is static PNG maps and a `.qgz` QGIS project file. |
| Validation | Implied accuracy target (±0.3m) | No historical flood event has been used to check model outputs. |
| Coverage | Roadmap to 5 countries by 2027 | 3 Lagos LGAs, static 30m grid, one scoring run. |

**Why this matters now:** the deck is investor/competition-facing and makes specific, falsifiable technical claims (model architecture, accuracy figure, feature already shipped). The fastest way to lose credibility with technical reviewers is for the repo to visibly contradict the deck. The roadmap below is sequenced so the *credibility gap closes first*, before chasing the harder ML build-out.

---

## 2. What's solid and worth keeping

- Open-data-only sourcing (Copernicus DEM, ESA WorldCover, WorldPop, OSM, CHIRPS) — no licensing dependency, genuinely differentiates you from DHI/IBM/Esri.
- Documented, reproducible methodology (weights, formulas, classification thresholds spelled out in README).
- Static/dynamic layer separation — slow-changing susceptibility baseline + fast-changing rainfall layer is the right architecture to build a depth model on top of.
- Population exposure already joined to risk class — the right unit of impact (people, not pixels).
- Working QGIS model end-to-end from raw rasters to classified output — the GIS plumbing (reprojection, clipping, grid creation, terrain derivatives) is reusable for the depth model; you're not starting from zero.

---

## 3. Known defects to fix immediately (before anything else)

1. **Risk class skew.** Population table shows Moderate (65,978 cells) and High (248,824 cells) absorbing almost everything, while Low (5 cells) and Very High (73 cells) are nearly empty. Check whether normalization of `risk_elev`, `risk_slope`, etc. is min-max scaled per-layer correctly, and whether classification breakpoints (0.25/0.50/0.75) match the actual distribution of `flood_score` rather than an assumed uniform spread. Re-run a histogram of `flood_score` before trusting any class-based statistic publicly.
2. **Deck/repo language alignment.** Until Phase 1 below is done, any external-facing material should describe the current system as a "flood susceptibility and exposure model" with depth prediction "in active development," not as a shipped AI depth engine. This is a one-afternoon fix that removes the single biggest risk to your credibility.

---

## 4. Phased roadmap

### Phase 0 — Align claims with reality (1–2 weeks)
**Goal:** No external document overstates current capability.
- Audit pitch deck, README, and any public materials for depth/AI/SMS claims not yet built.
- Reframe as "susceptibility model (live) + depth prediction (in development, target Q[X])."
- Add a clearly labeled "Current Capability" section to the README (this document can seed it).

### Phase 1 — Physical flood depth via HAND (4–8 weeks)
**Goal:** Produce a real depth-in-meters output without needing a trained ML model yet.
- Compute a Height-Above-Nearest-Drainage (HAND) raster from your existing DEM and flow-accumulation layers (tools: `pysheds`, `WhiteboxTools`, or TauDEM — all open source, scriptable, replace manual QGIS steps).
- Derive synthetic stage/rating curves per HAND class using established hydraulic-geometry relationships (cross-reference USGS/NOAA HAND-based inundation mapping methodology, and the open-source GeoFlood framework as a reference implementation).
- Source a discharge estimate per event: start with GloFAS reanalysis/forecast discharge for the relevant river reaches, or a simple SCS curve-number rainfall-runoff calculation from your rainfall layer if GloFAS resolution is too coarse for Lagos's drainage network.
- Combine: discharge → stage → depth per HAND bin → grid-cell depth raster.
- **Deliverable:** a `flood_depth_m` field alongside `risk_class`, for at least one historical or demo rainfall event. This alone lets you honestly claim depth prediction in the deck.

### Phase 2 — Automate the data pipeline (4–6 weeks, can run in parallel with Phase 1)
**Goal:** Replace manual CHIRPS pulls with a real ingestion loop.
- Script the rainfall fetch (CHIRPS now, GPM IMERG near-real-time as the upgrade path) on a daily cron/Airflow job.
- Automate steps 2–5 of your existing README workflow (sample at grid centroids → join → recalculate `alert_level`) so it runs unattended.
- Stand up a lightweight tile-serving layer (e.g. `titiler` or GeoServer) so outputs are queryable by URL instead of static PNGs — this is also the foundation for Phase 3's dashboard.

### Phase 3 — Minimum viable web dashboard + alerting (6–10 weeks)
**Goal:** Match the "community alert layer" claim with something deployed.
- Web map (Leaflet/Mapbox GL) showing current risk class + live depth/alert layer for the 3 pilot LGAs.
- SMS integration via a regional gateway (e.g. Africa's Talking, which has direct Nigeria coverage) triggered when `alert_level` crosses Watch/Warning for a community.
- Basic auth-gated admin view for partner agencies (SEMA, NiHSA) to see underlying data, not just alerts — supports the "explainable AI" claim in the deck even before real ML exists.

### Phase 4 — Build the labeled dataset for ML depth prediction (8–12 weeks)
**Goal:** Create the training data the LSTM/physics-informed NN actually needs — this doesn't exist yet and is the real bottleneck to the deck's headline claim.
- Identify historical Lagos flood events (2022, 2024, 2025 events referenced in your own deck) with approximate dates.
- For each event: derive flood extent from Sentinel-1 SAR imagery (free, regularly revisits Lagos), then estimate depth from extent + DEM using FwDET (Floodwater Depth Estimation Tool, open source) as your labeling method.
- Cross-check labeled events against any available ground reports (news, NEMA/SEMA situation reports, community reports) for sanity, not full validation.
- **Deliverable:** a labeled dataset of (terrain features, rainfall sequence, soil/land cover, HAND-derived prior) → (observed depth) for as many historical events as you can reconstruct — even 10–20 well-labeled events is enough to start.

### Phase 5 — Train and validate the ML model (8–12 weeks, depends on Phase 4)
**Goal:** Earn the "AI" claim with an actual trained model.
- Baseline first: gradient-boosted regression (XGBoost/LightGBM) on static + rainfall features predicting depth. Cheap to train, easy to interpret, gives you a real accuracy number to report instead of an aspirational ±0.3m.
- Only move to LSTM once you can show the baseline's errors have temporal structure the static model can't capture (i.e., sequential rainfall matters more than the snapshot).
- Physics-informed NN (shallow-water-equation constraints) is the last step, not the first — justify it once a plain LSTM's physically-implausible errors (e.g., depth predictions on ridgelines) show you need the constraint.
- Validate against held-out historical events from Phase 4, and report a real, defensible accuracy figure — replace the deck's ±0.3m placeholder with whatever the model actually achieves.

### Phase 6 — Pilot, calibrate, scale (ongoing from here)
- Run the live system through one full rainy season in the 3 pilot LGAs.
- Collect community/field verification reports to catch false positives/negatives the satellite-derived labels missed.
- Use that feedback to recalibrate both the susceptibility weights (fixing the Phase 0 skew issue with real ground truth) and the ML model.
- Only after this loop has run at least once is "5 countries by 2027" a credible claim rather than a deck projection.

---

## 5. Suggested sequencing summary

| Phase | Focus | Rough duration | Unlocks |
|---|---|---|---|
| 0 | Align claims with reality | 1–2 wks | Removes credibility risk immediately |
| 1 | HAND-based physical depth | 4–8 wks | Real depth-in-meters output |
| 2 | Automated data pipeline | 4–6 wks (parallel w/ 1) | Live system instead of manual demo |
| 3 | Web dashboard + SMS | 6–10 wks | Matches "community alert layer" claim |
| 4 | Labeled historical dataset | 8–12 wks | Enables real ML, not just rules |
| 5 | Train/validate ML depth model | 8–12 wks | Earns the "AI" claim with real numbers |
| 6 | Pilot season + recalibration | Ongoing | Makes scale claims credible |

Phases 1 and 2 can run in parallel. Phase 5 cannot start meaningfully before Phase 4 produces labeled data — resist the urge to jump to LSTM before there's anything to train it on.

---

## 6. Open questions to resolve early

- Who owns the discharge data sourcing for Phase 1 (GloFAS access, or building the rainfall-runoff fallback)?
- Which historical flood events have enough corroborating information (news, agency reports) to anchor Phase 4 labeling?
- Is SEMA/NiHSA partnership far enough along to get any ground-truth flood reports, even informally, to validate against?
- What's the actual minimum viable accuracy bar for a "Warning" to be operationally trustworthy — this should be decided before training, not after.
