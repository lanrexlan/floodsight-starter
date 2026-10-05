# FloodSight blocker remediation — 5 October 2026

Current stage: controlled advisory pilot preparation, not a market-approved autonomous warning product. Merged main commit `38d688416d1db1a7f217ed5a53c960773b623671` passed GitHub Python/PostgreSQL 17, dependency, container build and packaged-asset smoke checks. Render now confirms that commit is live on the free service; public health/assets/point lookup respond successfully, but readiness reports development mode, not production acceptance. See `DEPLOYMENT_VERIFICATION.md`. Approved Supabase access restrictions were verified previously, but release schema 06/07 and backup restoration remain open. No paid purchase or public SMS activation occurred.

The UX/scheduler changes in `UX_OPS_FIXES.md` are reviewed on the fix branch and not yet deployed. GitHub checks for that branch must pass before merge; Render follows main, not the fix branch. See `PILOT_ACCEPTANCE.md` for acceptance gates and `SCIENTIFIC_VALIDATION.md` and `AUTHOR_SOURCE_PLAN.md` for evidence and source decisions, including the declined underlying-data request.

| Blocker | Repository result | Remaining acceptance |
|---|---|---|
| Invalid/outside locations returned Lagos risk | Finite inputs, AOI/cell-coverage rejection, spatial index | Confirm actual pilot boundaries |
| Negative rain/unbounded reports | Constraints, real dates, finite numbers, bounded text/bodies | Field reporting procedures |
| Public PII/open CORS | Protected routes, bearer docs, restricted origins, private reporting API, RLS migration | Apply/test policies on intended database |
| Consent/phone ownership | Missing consent rejected; production OTP; atomic confirmation/upsert | Approved-number delivery and STOP/START tests |
| Ephemeral verification storage | Production requires durable database persistence | Backups, cleanup schedule, restore drill |
| Slow/heavy maps | Compact/precompressed maps, cached responses, street viewport tiles, indexed lookup/loading lock | Production load and target-device tests |
| UI inconsistencies | Scenario/live reset and refresh consistency, keyboard search/refresh, inline OTP/operator access, request-race protection, cautious static/stale states | Local checks pass; reviewed deployment and real-device/accessibility acceptance pending |
| Geocoder misuse | Local LGA gazetteer replaces third-party autocomplete | Licensed address search only if needed |
| Deployment/dependency drift | Docker/Render files, expanded CI/security scan; merged main passed Linux/PostgreSQL 17/container CI | New local changes need CI and deployment verification |
| Map/SMS disagreement | Shared calculation; corrected satellite handling; atomic send reservations | Expert review of replayed events |
| Ambiguous cell IDs / missing deployment LGA tags | Stable IDs for 735 boundary-split records; source-hashed packaged LGA index; shared polygon lookup | Keep historical ambiguous records separate; approve boundary interpretation |
| Unsupported claims | Corrected resolution/method, experimental depth, exact severity matching, cautious No Alert | Approved public copy/pilot scope |
| Weak model validation | Event/provenance normalization; training-only preprocessing; observed-event/baseline report | More independent data, location holdouts, prospective validation |
| Policy/implementation mismatch | Revised retention/region/storage statements, deletion endpoint and cleanup migration | Actual controller/region/agreements/legal review |
| Operations | Readiness, dry-run dispatch, paused channel gates, consent-only briefing lookup and atomic pre-send claims | Credentials, live delivery, restoration, operators and rehearsals |

`reports/model_validation.json` records negative R² for both observed events, under both observed-only and augmented training. Infrastructure changes do not resolve that scientific gap. Historical model artifacts remain experimental.

The next defensible release is a scoped pilot with human oversight. An autonomous public warning service or marketed accuracy/lead-time guarantee remains blocked by scientific and operational acceptance evidence.

## Verification receipt

- Merged main CI: [successful run](https://github.com/lanrexlan/floodsight-starter/actions/runs/37242113178), commit `38d688416d1db1a7f217ed5a53c960773b623671`. This predates the new local UX/scheduler edits.
- The last inspected resident scheduler failed for a missing GitHub `DISPATCH_SECRET`: [run](https://github.com/lanrexlan/floodsight-starter/actions/runs/37261468287). New pause/read-only gates handle disabled schedules explicitly; they do not install credentials or establish delivery.
- Local full suite for the current changes: 215 passed, eight database tests skipped because the isolated database was not running. Earlier PostgreSQL 18 evidence (159 passed, including eight database checks) is a separate historical receipt, not a fresh run of these edits.
- Hermetic UI behavior: 21 passed. Seven headless browser checks passed with APIs/providers/map rendering mocked; see `reports/ux_browser_verification.json`. YAML parsing and scientific freeze verification passed.
- Real SMS/OTP/STOP/START, deployment/paid-provider checks, production load, actual-device/map acceptance, live backup restoration, approved procedures and prospective flood validation remain open. Existing automated tests do not replace these gates.
