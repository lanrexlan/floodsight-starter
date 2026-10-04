# FloodSight deployment and operations

This release prepares a controlled advisory pilot. Public SMS and experimental depth output are disabled by default in production. `/ready` checks infrastructure; it does not certify forecast accuracy.

## Deployment

1. Run CI: tests, disposable PostgreSQL migration/concurrency checks, dependency scan, and Docker build. Local tests explicitly skip database checks without the test service.
2. Provision an always-on paid host using `render.yaml`, or build `Dockerfile` on a Docker host. These files do not create or bill an account. The build prepares compact maps and street viewport tiles. Use one application worker; SMS limits and reservations are shared in PostgreSQL.
3. Back up the intended Supabase database and inspect existing policies. Apply `scripts/sql/01_subscribers.sql` through `07_release_hardening.sql` in order. Apply both `supabase/migrations/` files for the health research pilot. The release migration restricts anonymous access to personal logs and reports.
4. Configure `.env.example` settings privately. Production requires Supabase, Africa's Talking, dispatch/webhook secrets, exact CORS origins, `REQUIRE_OTP=true`, a paid Open-Meteo key, and confirmed provider agreements. Set `DATA_PROVIDER_LICENSES_CONFIRMED=true` only after reviewing actual data/basemap/provider rights. Never put service-role or dispatch keys into HTML.
5. Configure `/at/incoming?token=...` and `/at/delivery?token=...` callbacks. The legacy health callback also requires a token. Callback query strings contain secrets: the container disables access logs; the ingress proxy must redact these strings. Test confirmation, STOP, START, and delivery reports on approved numbers.
6. Enable Supabase pg_cron and schedule `cleanup_personal_data()` daily using the migration's example. Verify the actual hosting region, privacy contact, processor agreements, deletion procedures, backups, and restore process. The operator must implement the described policy.
7. Verify `/ready`, public pages, coverage rejection, private-route authentication, mobile layout, forecast freshness, and approved test-message delivery before activating public SMS.

## Pilot activation

Boundary-split source records had duplicate cell IDs, including conflicting LGA labels. The API preserves their geometry/order but assigns stable `@row=` suffixes to duplicate IDs. The packaged LGA index is tied to the source grid hash. Keep pre-release historical alert records separately identified; do not silently join old ambiguous IDs to new field reports. Regenerate assets and the index together after a grid change.

Production bulk force-send tests are disabled. Single-message tests require the exact phone number in `APPROVED_TEST_PHONES` (comma separated).

Authenticated `POST /alerts/dispatch?dry_run=true` reviews alerts without messaging residents. Map and dispatch use the same rainfall/coastal/river calculation. Record the responsible operator and review. Set `ALERT_DISPATCH_ENABLED=true` only for an approved pilot audience and escalation procedure. `HEALTH_DISPATCH_ENABLED` separately approves research messages; health probabilities remain uncalibrated. Keep `ENABLE_EXPERIMENTAL_DEPTH=false` unless the pilot specifically needs experimental output.

The repository dispatch workflow runs every three hours. GitHub schedules may be delayed; this is not a promised lead time. Operational warnings need a monitored scheduler at the agreed cadence, verified actual runs, and protected credentials. Morning briefing and health workflows have separate settings and audiences.

OTP confirmation and subscriber creation are one database transaction. Shared cost limits allow eight combined requests per phone per ten minutes and fifteen per IP per minute. The bounded API traffic limiter is process-local; also configure ingress traffic/connection limits. Trust forwarded client IP headers only from the intended proxy.

## Incidents

- Monitor readiness, forecast freshness, job completion, database failures, SMS failures, callback lag, and final delivery outcomes. A quiet warning feed is not proof that upstream data is healthy.
- Weather outage: show static susceptibility and forecast unavailable. Do not interpret unavailable data as No Alert. Pause dispatch when upstream data fails the pilot freshness/coverage requirements.
- SMS timeout: reconcile provider records and `alert_claims`. Sends are reserved beforehand to avoid concurrent duplicates. A timeout may still mean acceptance; there is no automatic resend. Confirm the provider result before removing a reservation or retrying.
- Storage outage: verification returns 503 rather than acknowledging an ephemeral write. Experimental prediction audit failures are logged and require attention.
- Opt-out: check callback authentication and the subscriber active flag. A message already handed to the network may still arrive. Verify the requester before authenticated `DELETE /subscribe/{phone}/erase`.
- Rollback: disable public dispatch, redeploy the last tested image, and preserve the database. Back up before schema changes. Do not retrain automatically during an incident.

## Scientific acceptance

`python scripts/evaluate_model.py` writes `reports/model_validation.json`, testing each observed event separately with observed-only and augmented training. Synthetic labels never count as observed test evidence. Only two observed events are supplied; all current observed-event folds have negative R². More independent flood and non-flood observations, location holdouts, uncertainty calibration, prospective lead times, and sensitivity/false-alarm measurements are needed before public performance claims.

Stored model/design-storm artifacts remain experimental historical outputs and are not automatically promoted. A 150 mm rainfall scenario is not a validated 100-year return period. Agree acceptable model and warning errors with the pilot customer and domain experts before collecting acceptance evidence.

## References

Paid endpoint configuration follows [Open-Meteo documentation](https://open-meteo.com/en/docs/marine-weather-api) and [pricing](https://open-meteo.com/en/pricing). Direct public Nominatim calls were replaced with local LGA search; licensed address search can be added if required.

Dependency updates address [Starlette form parsing](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq) and [python-multipart parsing](https://github.com/Kludex/python-multipart/security/advisories/GHSA-5rvq-cxj2-64vf). CI scans the full deployment dependency set.
