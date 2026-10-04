# FloodSight blocker remediation — 4 October 2026

Current stage: controlled advisory pilot preparation. The first hardening release is merged and live on Render, but in development mode on a free host. A separately approved Supabase access-restriction migration has been applied and verified. No paid service purchase or public SMS activation has been performed. See `PILOT_ACCEPTANCE.md` for current evidence and rollout gates.

| Blocker | Repository result | Remaining acceptance |
|---|---|---|
| Invalid/outside locations returned Lagos risk | Finite inputs, AOI/cell-coverage rejection, spatial index | Confirm actual pilot boundaries |
| Negative rain/unbounded reports | Constraints, real dates, finite numbers, bounded text/bodies | Field reporting procedures |
| Public PII/open CORS | Protected routes, bearer docs, restricted origins, private reporting API, RLS migration | Apply/test policies on intended database |
| Consent/phone ownership | Missing consent rejected; production OTP; atomic confirmation/upsert | Approved-number delivery and STOP/START tests |
| Ephemeral verification storage | Production requires durable database persistence | Backups, cleanup schedule, restore drill |
| Slow/heavy maps | Compact/precompressed maps, cached responses, street viewport tiles, indexed lookup/loading lock | Production load and target-device tests |
| UI inconsistencies | Same-origin API, live legend/thresholds, one click handler, escaped external text, outage state, mobile layout | Accessibility/device acceptance |
| Geocoder misuse | Local LGA gazetteer replaces third-party autocomplete | Licensed address search only if needed |
| Deployment/dependency drift | Docker/Render files, maintained dependency minimums, expanded CI/security scan | Linux build and PostgreSQL CI execution |
| Map/SMS disagreement | Shared calculation; corrected satellite handling; atomic send reservations | Expert review of replayed events |
| Ambiguous cell IDs / missing deployment LGA tags | Stable IDs for 735 boundary-split records; source-hashed packaged LGA index; shared polygon lookup | Keep historical ambiguous records separate; approve boundary interpretation |
| Unsupported claims | Corrected resolution/method, experimental depth, exact severity matching, cautious No Alert | Approved public copy/pilot scope |
| Weak model validation | Event/provenance normalization; training-only preprocessing; observed-event/baseline report | More independent data, location holdouts, prospective validation |
| Policy/implementation mismatch | Revised retention/region/storage statements, deletion endpoint and cleanup migration | Actual controller/region/agreements/legal review |
| Operations | Readiness, dry-run dispatch, approval flags, incident/rollback runbook | Operators, monitoring, scheduler, rehearsals |

`reports/model_validation.json` records negative R² for both observed events, under both observed-only and augmented training. Infrastructure changes do not resolve that scientific gap. Historical model artifacts remain experimental.

The next defensible release is a scoped pilot with human oversight. An autonomous public warning service or marketed accuracy/lead-time guarantee remains blocked by scientific and operational acceptance evidence.

## Verification receipt

Update: 159 tests now pass locally, including eight real PostgreSQL migration/security/concurrency tests (no database tests skipped). The isolated local test server is PostgreSQL 18; PostgreSQL 17, Linux container checks and a real production restore must still be verified separately. The earlier receipt below describes the first hardening release, not this subsequent fix.

Local automated tests, browser checks and offline request timings are release preparation, not production acceptance. `reports/release_verification.json` records actual local transfers/timings, and `reports/dependency_audit.json` records the deployment dependency scan. Docker/PostgreSQL execution is not available on this laptop; those checks must pass in CI before release. Live provider delivery, target-device/load testing, backup restoration and prospective flood validation remain unverified.

Latest local result: 143 tests passed, four disposable-PostgreSQL tests skipped. Deployment dependency scan: zero known vulnerabilities. The packaged grid loads without raw downloads, with 24,933 unique identifiers and no missing LGA labels. Public pages and interactive API documentation render in the browser; offline weather is visibly unavailable. Point-query alerts are labelled rainfall scenarios, and the displayed hazard score now matches the susceptibility legend rather than the exposure-weighted score.
