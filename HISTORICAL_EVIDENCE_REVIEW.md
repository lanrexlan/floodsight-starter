# Lagos historical evidence review

Review date: 2026-10-05. **Scientific acceptance is still open.**
The freeze hashes refer to the original local byte-level snapshot, including
line endings and ignored research inputs. Git may normalize text line endings;
a fresh checkout is not a substitute for that retained snapshot. Verification
must reject missing/changed bytes, not silently recreate the proposal after tuning.
This is a research-only desk review. Production settings, depth models, hosting,
real alert dispatch and external accounts were not changed.

## Outcome

Three episodes have community-level corroboration. This does not validate each
Groundsource polygon, confirm a measured peak, or produce depth labels.

| Episode | Evidence and date precision | Suitable next use |
| --- | --- | --- |
| October 2024 river flooding | [NEMA assessment](https://nema.gov.ng/impact-assessment-of-dam-water-release-by-ogun-osun-river-basin-development-authority-orbda/) reports actual inundation; monitoring began October 11, publication October 14. These are assessment dates, not onset/peak. Some communities straddle Lagos/Ogun. | Riverine case review after exact site and observation-time recovery; not numerical depth validation. |
| August 3–4, 2025 rain flood | [Channels contemporary report](https://www.channelstv.com/2025/08/04/lagos-communities-flooded-vehicles-submerged-after-marathon-rainfall/) and [Ohio State fieldwork account](https://oia.osu.edu/news/2025/09/29/documenting-floods-and-building-resilience-lagos/) support occurrence in Ikorodu; the latter identifies August 4. | Reserved new-label historical challenge; measured-depth data request lead. |
| September 23–24, 2025 rain flood | [TheCable report](https://www.thecable.ng/houses-vehicles-submerged-as-flood-ravages-lagos-communities/) has dated resident posts; [Channels resident accounts](https://www.channelstv.com/2025/09/27/flood-ikota-lekki-residents-urge-govt-to-act-against-illegal-structures-on-waterways/) corroborate Ikota/Lekki. Its Tuesday date is inferred as September 23. | Reserved occurrence review; original photos, precise sites and times still needed. File photos and qualitative body-depth descriptions are not instrument measurements. |

[April 2025 Lagos Island pumping](https://punchng.com/lagos-evacuates-water-from-flooded-communities/)
is retained only as a reference. The report confirms flooding, but does not establish
onset or peak. No event date is assigned from its publication date.

## Best lead for actual local depth measurements

Ohio State's account describes Oluwadamilola Salau's team recording rain and depth
with a gauge and measuring staff. No measurement table or reuse permission was
acquired. Her [official professional profile](https://geography.osu.edu/people/salau.2)
lists **salau.2@osu.edu**. No outreach has been sent.

Request site coordinates/IDs, times and timezone, ground-referenced metres,
measurement uncertainty and instrument method/calibration, wet/dry sampling,
quality flags and permission for commercial-product validation. Ask whether
records overlap our old labeling/tuning. A positive response is not automatically
a usable validation dataset; inspect provenance and sampling first. Obtain
specific consent before requesting any restricted resident-level information.

## Contamination audit and proposed reserve

The current training CSV contains 2,536 rows: 1,920 synthetic rows plus 616
SAR/FwDET proxy rows from two events. Synthetic rows count as exposure even
though they are not real measurements. Existing API historical events and the
augmentation event list also count as tuning exposure. These were inspected
without executing the API or fetching weather.

Conservative exclusion uses **whole event months**, not just claimed peak dates.
It cannot detect all adjacent-month storm overlap, external notebooks, deck
development, or undocumented manual tuning. The existing CSV has no coordinates
or site IDs, so spatial/site independence remains unauditable. Known 2025
presentation references also need the owner's history review.

August and September 2025 are reserved in full before computing any predictions:
164 candidate reports, including uncorroborated dates/places. Do not use those
months to select features, thresholds or model variants. Neither absence from
the news nor an uncorroborated reserved row constitutes a dry control.

This is **not a pristine whole-system holdout**. The documented coastal threshold
calibration used sea-level inputs from 2023 through October 2026, including these
months. That is covariate exposure, not necessarily flood-label exposure, but it
must be disclosed. A future prospective shadow test remains necessary.

The coastal calibration's advisory-active-day distribution is not a measured
false-alarm rate: that requires systematically observed negative outcomes.
Similarly, archived observed rainfall cannot establish advance warning lead time.

## Reproducible screening results

| Screening category | Candidate reports |
| --- | ---: |
| All Lagos-bounding-box candidates | 2,870 |
| Quarantined: known training/tuning months | 1,031 |
| Reserved: August–September 2025 historical challenge | 164 |
| Unallocated: review only | 1,675 |
| Reported-place geometry overlaps actual served grid | 2,110 |
| Reported-place geometry outside served grid | 760 |

The first three allocation categories partition the queue; service overlap is a
separate check. Intersecting a service cell does **not** prove that cell flooded.
Overlap fractions concern reported-place area, not inundation extent or coverage
confidence. No severity/risk scores were used to select reports.

There are 2,381 provisional review groups, **not 2,381 verified independent
floods**. Small places (at most 4 km2) are grouped when within 500 m and their date
intervals overlap or are separated by at most one day. Broad places stay separate
and cannot bridge local groups. Connected chains can span longer than one storm;
chains over seven days are flagged. Adjacent storms can merge and the same storm
can split across neighborhoods. Parameters are review heuristics, not scientific
independence criteria; human event resolution remains required.

There are 16, 60 and 33 temporal overlaps with the October 2024, August 2025 and
September 2025 cases respectively. These are **temporal links only**, not verified
spatial matches or independent observations. Individual polygons verified: zero.
Independent measured depths imported: zero. Verified dry observations: zero.

## Files, snapshot and next gate

- `data/validation/reviewed_event_sources.json`: event evidence, precision,
  limitations and measurement-request requirements; no copied full articles.
- `data/raw/scientific/groundsource_review_queue.csv`: local ignored review queue.
  The original GeoJSON is unchanged.
- `reports/historical_evidence_review.json`: allocations, exposure strata,
  reserved source UUIDs and SHA-256 fingerprints of the evidence, script,
  training CSV, current model, served grid, relevant configuration and generated
  review queue. The verification check detects missing or changed inputs/queue.

Optional local research environment: geopandas, shapely and pyogrio; these are not
new production dependencies. Run from the repository root:

```text
python scripts/review_groundsource.py --verify-freeze
```

The default run verifies an existing proposal rather than overwriting it. An
explicit `--refresh-proposal` rebuilds the snapshot and requires renewed review;
retain the previous snapshot in version history. This is a proposal freeze, not
approval or proof that no earlier external exposure occurred. The check is not
yet integrated with model-training/release workflows.

Next: obtain permission and actual measurements from the strongest local lead,
recover original site provenance, and have a qualified local hydrology reviewer
approve test design and decision-relevant error tolerances **before scoring**.
Until then, no independent depth score or scientific clearance can be issued.
