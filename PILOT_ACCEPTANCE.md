# FloodSight pilot acceptance

Infrastructure access is not scientific or operational acceptance. This checklist does not approve autonomous public warnings or market accuracy guarantees.

## Evidence — 4 October 2026

- Render serves merged commit `7906fd0bc4c1c6b482ed7eb14f20492deee1e706` on the free Python service in development mode, not the production Blueprint configuration.
- Supabase project: `buwwsplrhsfgnkulhkpc`. The owner-approved access restriction was applied and verified. Four exposed tables now have RLS, private tables deny anonymous/signed-in access, and the maintenance function is server-only with a fixed search path. The security advisor has no WARN/ERROR findings. INFO notices for intentional deny-by-default tables remain.
- The release schema upgrade is NOT applied. A live backup is not verified. Do not run cleanup or baseline consent backfills on live records as a shortcut.
- Local tests: 159 passed, including eight real database migration/security/concurrency tests on an isolated PostgreSQL 18 instance. PostgreSQL 17 CI/container checks and production restoration remain separate gates.
- The owner confirmed provider key and agreement availability. Key installation and live-provider behavior are unverified. Never put credentials in this document.
- Depth model acceptance remains blocked: only two SAR/FwDET-derived events, both observed-only holdouts have negative R² and worse RMSE than the mean baseline.

## Rollout order

1. Pass GitHub tests, PostgreSQL 17 checks, dependency audit, container build and packaged-asset container smoke tests for the fix branch.
2. Verify a recent live backup/export and restore it to an isolated target. Compare row counts, schema, constraints and permissions; record recovery time/data loss against operator-approved objectives. Never restore over the active database as a test.
3. Inspect live schema, then apply corrected delivery/release upgrades 06/07 without replaying baseline consent backfills or unrelated health-table resets. Verify schema version 7, delivery columns, RPC permissions and atomic OTP behavior.
4. Merge the reviewed fix and configure Render privately. Obtain separate spending approval for an always-on plan. Set production mode, exact origins, OTP, provider key/agreements, callback/dispatch credentials and `/ready` health checks. Keep all SMS channels and depth off. The existing Python service does not automatically adopt `render.yaml`.
5. Recheck deployed commit, readiness, private-route rejection and weather freshness. Review ingress logging because callback query strings carry secrets.
6. Complete operational tests below before enabling each approved audience/channel separately.

## Scientific evidence plan

Name the field partner, hydrologist and accountable pilot owner. Agree target geography, forecast horizon, acceptable errors and uncertainty reporting before collecting outcomes or tuning models.

Collect independent flood AND dry-control observations across new events and locations. Record observation/event IDs, coordinates, timestamp/timezone, wet/dry status, measured depth/units, method/instrument, uncertainty, evidence reference, reviewer and quality decision. Keep reporter identities private. Satellite proxy depths and synthetic labels must remain separately labelled, not counted as independently measured truth. Never ask residents to enter floodwater.

Freeze dataset, preprocessing, model and configuration versions. Hold out complete events AND spatial groups to prevent neighboring-cell leakage. Report per-event/area MAE/RMSE, wet/dry discrimination, baseline comparisons, uncertainty/calibration and sample counts. Domain experts must approve the complete evidence, not one favorable split.

Register prospective sites, thresholds and success criteria before the next events. Archive forecasts/alerts with issue time and source freshness before outcomes are known. Capture floods and non-events systematically, including missed events. Measure hit rate, false alarms, lead time and coverage by event/site; correlated cells are not independent events. Preserve prediction versions when retraining.

Depth stays off until scientific approval. Rule-based advisories and health research scores also need their own validation; disabling depth does not validate them.

## Operational acceptance

For each test record date, release SHA, environment, operator, expected/actual outcome, evidence reference and acceptance decision.

| Gate | Required evidence | Status |
|---|---|---|
| Test SMS | Approved consenting numbers, sender/shortcode and budget; provider ID AND final handset delivery | Not run |
| OTP | Wrong/expired/replayed codes rejected; one confirmed subscription; live provider receipt | Local database checks pass; live pending |
| STOP/START | Real inbound reply reaches authenticated callback; opted-out number excluded from every sender; START consent/ownership checked | Provider inbound-capability test pending |
| Delivery callbacks | Correct audience updated; storage failures retried instead of falsely acknowledged | Local regressions pass; real callback pending |
| Weather | Paid authentication, freshness, coverage and degraded behavior | Key available; installation/live behavior unverified |
| Load/devices | Approved workload/duration; p95/p99, errors, CPU/RAM, transfers; mobile/low-bandwidth/accessibility checks | Pending; do not stress current free live service |
| Restore | Real backup restored to isolated target, integrity/permissions checked, recovery objectives measured | Backup confirmation/target pending |
| Operations | Named on-call owner; monitoring/scheduler; weather/SMS/storage outage, opt-out, escalation and rollback rehearsal | Procedures documented; approval/rehearsal pending |

Agree numerical acceptance limits and recovery objectives with the owner/customer before testing, not after observing favorable results.
