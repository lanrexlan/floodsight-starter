# Scientific validation: external evidence and next gates

Research date: 2026-10-05. Status: **scientific acceptance remains open**.
Hosting upgrades are deferred. This research does not enable experimental depth,
change the deployed model, or authorize public warning dispatch.

## What the existing results actually establish

`reports/model_validation.json` contains 616 satellite/FwDET-derived proxy depths
from just two events, not 616 independent surveyed flood measurements. Observed-only
held-out RMSE is 0.163 m versus a 0.149 m mean baseline for the 2021 event, and
0.274 m versus 0.269 m for 2024. Both held-out R-squared values are negative.
Synthetic augmentation does not repair generalization. Do not advertise depth
accuracy from random row splits or from another researcher's model scores.

The training CSV lacks coordinates and persistent site IDs. Recover these from
the original labeling pipeline before attempting spatial/site holdouts; do not
guess locations from terrain features. FwDET labels and terrain predictors share
DEM errors, so agreement with those labels is not independent depth validation.

## Public sources investigated

The author's subsequently supplied provider list now has a separate
[source and acquisition plan](AUTHOR_SOURCE_PLAN.md), including versioning,
commercial-use restrictions and prioritized extent-versus-depth validation.
No additional validation observations or production inputs were imported from
that list. The frozen historical review remains unchanged.

| Source | What is available | Appropriate use | Limits/access decision |
| --- | --- | --- | --- |
| [Groundsource v1, Google Research](https://zenodo.org/records/18647054) | Global news-derived reported-place polygons and event date intervals; 2,646,302 released rows inspected | Lagos historical event discovery and a manual review queue | CC BY 4.0 verified through the publisher API. No depth, dry controls, article URLs, or measured inundation footprints in the inspected schema. AI extraction and reporting bias require corroboration. |
| [Nkwunonwo, Portsmouth thesis, 2016](https://researchportal.port.ac.uk/en/studentTheses/meeting-the-challenges-of-flood-risk-assessment-developing-countr/) | Table 7-4: 30 Lagos locations with GPS coordinates and mixed eyewitness/media evidence. Table 7-7: six photograph-estimated depth ranges for the historical Lagos case | Older-event occurrence checks; locate original photos and request more precise site/time/method evidence | Depths are photo estimates, NOT gauge readings. Geographic names are not sufficient to assign six precise depth points. Rights for dataset redistribution/commercial training not verified; tables not imported. PDF pages 234 and 249 (printed 206 and 221); limitations on PDF page 267 (printed 239). |
| [Nwaokoro, Portsmouth thesis, 2024](https://researchportal.port.ac.uk/en/studentTheses/social-vulnerability-and-flood-resilience-in-lagos-state-nigeria/) | Table 3.4: Lagos flood-location/date inventory for 2016-2023 | Additional event discovery and independent source cross-checking | Occurrence only. Mixed month/day precision, repeated entries and some questionable coordinates need review. Rights for reuse not verified; not imported. |
| [NEMA Oshodi-Isolo post-flood assessment, published 2025-10-20](https://nema.gov.ng/post-flood-assessment-in-oshodi-isolo-federal-constituency-lagos-state/) | Agency assessment identifies past flooding in Ejigbo, Okota and Ilasamaja | Official community-level corroboration and a lead for requesting original field records | No precise event date, coordinates or measured depth in the public page. Publication date is NOT an observation date. Reference only; no reusable data license verified. |
| [NEMA/Lagos assessment coordination, published 2023-04-05](https://nema.gov.ng/nema-collaborates-with-lagos-state-on-2022-2023-flood-assessment-and-preparedness/) | Confirms that NEMA shared prior-year flood-hotspot assessments with Lagos authorities | Concrete institutional lead for original 2022 assessment data | Page mixes prior flooding and future preparedness; its entire place list must not be labeled as observed flooding on publication day. No underlying measurement file supplied. |
| [UNOSAT Nigeria, 2024 web map](https://unosat.org/products/3961) and [Mokwa, 2025](https://unosat.org/products/4137) | Downloadable satellite water extents (SHP/GDB); Mokwa analysis from Sentinel-2 | Independent-provider extent comparisons where imagery actually overlaps the test area | Not measured depth; provider explicitly describes preliminary, field-unvalidated analysis. Mokwa is outside Lagos. Check resource-specific terms and permanent-water/valid-observation masks before ingestion. |
| [HAD-FCDR25, Hadejia, 2025](https://zenodo.org/records/15204588) | EO and participatory flood/crop evidence for 2020/2022; 142.8 MB archive | Potential out-of-region extent/method stress test | CC BY 4.0 verified through the publisher API; archive contents not inspected. Northern agricultural/riverine setting is not a Lagos coastal/pluvial acceptance set. |
| [Global Flood Database v1](https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_DB_MODIS_EVENTS_V1) | MODIS flood extent, duration, permanent-water and cloud-observation information for 2000-2018 | Potential coarse research cross-checks after verifying Lagos event coverage and permissions | Publisher catalog lists CC BY-NC 4.0: excluded from commercial-product training without permission. Satellite extent, not street depth; effective MODIS resolution is 250 m even where grids are resampled. Missing/cloud-covered observations are not dry labels. |
| [Lagos Climate data set, Aasa, 2022](https://data.mendeley.com/datasets/z6yk7j624s/1) | Lagos climate dataset listing | Possible meteorological covariates once files/units/stations/time coverage are inspected | CC BY 4.0 listed; file contents have not been verified. Climate data alone is not flood ground truth. |
| [FloodNet NYC sensor archive, 2020-2023](https://zenodo.org/records/10211443) | Ultrasonic, ground-referenced depth time series; filtered depth in millimetres | Potential external sensor-method benchmark with separately approved permissions | Zenodo API reports CC BY-NC-SA 4.0 and the record points to a non-commercial access agreement. Excluded from commercial-product training. NYC transfer would not validate Lagos anyway. |
| [USGS Flood Event Viewer](https://www.usgs.gov/tools/flood-event-viewer) | Downloadable US storm/high-water-mark/sensor records | External surveyed-measurement benchmark after inspecting datum, ground reference, quality and uncertainty | US observations are not local Lagos validation. Gauge elevation or a mark above a vertical datum must not be mislabeled as inundation depth above ground. |

This search has **not found an immediately usable, sufficiently precise, independently
measured Lagos depth dataset**. That is a search finding, not a claim that none exists.
The next-step [historical evidence review](HISTORICAL_EVIDENCE_REVIEW.md) found a
specific local measured-depth research lead at Ohio State, but no measurement
table or reuse permission has been acquired. It also records three corroborated
community-level episodes and a proposed, explicitly non-pristine historical
challenge reserve. This does not change the zero-depth/zero-dry intake counts.
The [2026 Lagos modeling paper](https://www.nature.com/articles/s41598-026-38544-1)
also states that derived study data are available by request rather than providing
an open measured-depth download. Published performance for runoff or land-cover
classification is not evidence for FloodSight's street-depth model.

Selected factual values from Tables 6-8 are now recorded separately in
`data/validation/lagos_paper_benchmark.json`, with explicit simulation labels,
units and pending dataset-specific reuse rights. They are used by
`scripts/check_paper_benchmark.py` for dimensional and numerical consistency
screening only, producing `reports/lagos_paper_benchmark_checks.json`. No matched
storm/catchment observations exist for a FloodSight error score, and no rows were
added to depth training. Two small rainfall/loss/excess identity residuals are
preserved for clarification rather than automatically corrected. These are QC
queries, not evidence that the paper's model is invalid.

The article is marked CC BY-NC-ND 4.0; no commercial dataset-use or adapted-map
redistribution permission has been acquired. On 2026-10-05 the owner supplied the
author's response to the sent request: underlying-data sharing was declined due
to institutional/ethical restrictions, third-party agreements and confidential
research commitments. See [AUTHOR_DATA_REQUEST.md](AUTHOR_DATA_REQUEST.md).
This route is unavailable for the present intake, not pending approval. The reply
does not grant additional reuse rights or provide validation observations.

Public-source replication is a separate route: the paper identifies USGS Landsat,
Copernicus Sentinel-2 and SRTM terrain inputs, but its rainfall and streamflow
records came from NiMet and Ogun-Oshun River Basin Development Authority. Public
imagery and terrain are useful inputs, not independently measured street depths.
Availability and permitted uses of agency records must be established directly
with those providers. Reproducing a method or agreeing with its simulated outputs
does not establish FloodSight's forecasting or depth accuracy. Prioritize the
independent local measurement lead and prospective wet/dry pilot described above;
do not use another coauthor to circumvent the refusal. No additional outreach has
been sent. This intake does not change the historical reserve or any production
acceptance decision; independent measured-depth and dry-control additions remain
zero.

## Reproducible Groundsource research queue

Pinned source: DOI `10.5281/zenodo.18647054`, file `groundsource_2026.parquet`,
667,122,400 bytes, publisher MD5 `cd1b5de6508f7aad8e1d1d0dd4cecea6`.
Attribution: Mayo, Zlydenko et al. (2026), Groundsource v1, Google Research,
[publisher record](https://zenodo.org/records/18647054), CC BY 4.0.

The optional local reader requires `pyarrow`. It is not added to production
dependencies. Download from the publisher file link to
`data/raw/scientific/groundsource_2026.parquet`, then run:

```text
python scripts/download_groundsource.py
python scripts/extract_groundsource.py
```

The extractor verifies file length, checksum and CRS before reading bounded batches.
It selects reported-place polygons intersecting the current Lagos bounding box,
preserves dates/UUIDs/full geometry and creates:

- `data/raw/scientific/groundsource_lagos_candidates.geojson` (local, ignored by Git).
- `reports/groundsource_lagos_inventory.json` (small, shareable provenance/quality summary).

Completed intake on 2026-10-05: the full archive matched the publisher checksum.
All 2,646,302 rows were scanned; 2,870 reported-place polygons intersect the Lagos
bounding box, with start dates from 2001-02-01 to 2026-01-20. Of these, 1,190
exceed the 4 km2 broad-place review threshold, 329 have date intervals longer than
one day, and 72 have place centroids outside the bounding box. These flags overlap.
All individual polygons remain unreviewed; community-level corroboration is
recorded separately in the historical review. There were no identical normalized geometry/date groups,
but overlapping reports can still describe the same event. Independent measured
Lagos depths and verified dry controls added: **zero**.

These are **unreviewed reported places**, not flood footprints, measured depths,
independent event counts, or validation acceptance. A bounding-box intersection
does not establish a flood inside one of the actual 15-LGA service cells. A place
area above 4 km2 is flagged as a review heuristic, not an uncertainty measurement.
Identical place/date report groups are flagged; other overlapping reports may
still describe the same flood. Do not interpret report-count trends as flood trends.

[Google's methodology](https://www.research.google/blog/introducing-groundsource-turning-news-reports-into-data-with-gemini/)
reports imperfect temporal/spatial extraction in manual review. Verify local
records rather than adopting the publisher's aggregate quality percentages as
FloodSight's own accuracy.

## Work needed to convert candidates into defensible evidence

1. Review each candidate against original articles, official situation reports or
   independent observers. Keep evidence URLs, event interval, precise location,
   spatial uncertainty, reviewer, review date and inclusion reason. Reject warnings
   about future flooding, incorrect geocodes and unrelated mentions.
2. Cluster overlapping reports into actual events; retain source IDs. Check overlap
   with existing training events and known manually curated validation locations.
   An external publisher is not independent if its observations were already used
   to tune FloodSight. Freeze an event/site holdout before model development.
3. Match reviewed evidence to actual service cells only at defensible spatial
   precision. A district polygon cannot assert that every enclosed cell flooded.
   Wet-only points can provide case coverage diagnostics, not specificity, false
   alarm rates, precision, or overall accuracy. Do not create random dry controls
   from places absent from the news.
4. Obtain systematic wet AND dry observations at fixed sites during monitored
   intervals. For depth, require ground-referenced metres, measurement method,
   uncertainty, exact time/site and independent review. Ask thesis authors and
   relevant Lagos/NIHSA/local research institutions for existing measured records
   and permission before importing; no outreach has been sent by this work.
5. Recover geospatial provenance for existing proxy labels; rebuild features for
   any genuine new depth measurements using versioned input sources. Keep sensor,
   photograph-estimated, satellite/FwDET and synthetic labels in separate strata.
6. Evaluate new events and new sites against mean/terrain/rainfall baselines.
   Report MAE/RMSE/bias by event and depth range, threshold errors relevant to
   intended decisions, and event/site-cluster uncertainty intervals. Thousands of
   neighboring pixels or minute readings are not thousands of independent trials.
7. Run prospective shadow validation with archived issued forecasts, issue times,
   source freshness, fixed thresholds, and systematic outcomes including misses
   and non-events. Estimate false alarms, missed floods, lead time and availability.
   Historical observed rainfall is unsuitable evidence of advance warning skill.

## Acceptance decision

Before testing the locked holdout, a qualified local flood/hydrology reviewer and
the response owner must approve the intended use, site/event sample design,
measurement tolerances and acceptable missed/false-alert tradeoff. Numeric launch
thresholds must be justified by that use and uncertainty, not selected after seeing
the score. A minimum row count alone is not scientific acceptance.

Depth remains off until held-out independent local measurements support its
claimed resolution/use and prospective performance is accepted. Rule-based
rainfall advisories, susceptibility ranking and health estimates require separate
evidence; this archive does not validate those claims automatically.
