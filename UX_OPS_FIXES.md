# UX and operational fixes — 5 October 2026

Status: reviewed and prepared for the fix branch, not deployed. No paid resources, live
database mutations, real SMS, author outreach or public messaging activation.

## Implemented

- Scenario sliders, map colours and the scenario banner remain consistent during
  background/manual refresh. Explicit return-to-live restores the latest stored
  forecast; failed refresh stays visibly stale. Missing, old or future timestamps
  cannot leave a forecast labelled live. Static fallback is not an all-clear.
- Refresh is a keyboard-operable button. Status no longer changes every second.
  LGA search supports arrows/Enter/Escape, accessible options and clear errors.
  Older search/location responses cannot overwrite a newer choice. Rainfall edits
  invalidate old point results; point scenarios do not change the city beacon.
- Dependency/WebGL startup failure has an explicit unavailable state. Experimental
  depth controls are hidden until the server authorises them; popups escape data
  and no longer describe the 150 mm scenario as a validated 100-year storm.
- Signup requires explicit LGA selection or GPS and successful coverage checks.
  Location changes clear consent. OTP confirmation is inline, context-locked and
  keyboard-operable, with duplicate-submission protection, cancellation and wrong-
  code retries without another SMS request. Only `subscribed` confirms success.
- Operator tokens use an inline password field, stay only in memory and are
  cleared from the field. Changed/cleared access discards old private responses.
  Health values are labelled uncalibrated research scores, not outbreak probabilities.
  Case reports now require server-side operator authentication as well; deployed
  main's public case-view gap was found in the read-only verification.
- All three messaging schedules have explicit pause/read-only/live gates; manual
  runs default to read-only. Sending approval and credentials remain separate.
  Dry-run resident checks no longer require a dispatch secret. Job concurrency
  prevents overlapping runs, and aggregate receipts omit provider/phone payloads.
- Morning briefings fail closed on ledger/subscriber lookup failures and missing
  consent; no fallback recipient list. Existing release-7 RPC claims reserve each
  subscriber/day in a separate `Briefing` namespace before provider contact and
  remain after uncertain outcomes. Messages do not promise an all-clear or infer
  affected neighbourhoods from cell counts. Health grid mismatches fail closed.
- Readiness documents separate historical development notes from current gates.
  Supabase security guidance informed server-only database access, consent-only
  recipient selection and keeping credentials out of browser storage.

## Verification

Local full Python suite: 215 passed, eight isolated-database tests skipped; that
database was not running for this run. Earlier PostgreSQL evidence is historical,
not a new execution of these changes. Hermetic JavaScript suite: 20 passed.
All five workflows parsed successfully as YAML. Scientific freeze verification
passed; no research holdout or experimental model settings were changed.

`reports/ux_browser_verification.json` records seven successful headless browser
checks: scenario refresh/reset, keyboard search, 390px dashboard/signup layout,
inline OTP retry, operator token clearing and unavailable-map startup. API/provider/database boundaries
and the map renderer were mocked; external requests were blocked. This does not
establish real map rendering, target-device accessibility, load performance or
live delivery. Browser smoke can be repeated against a loopback static server
using `tests/browser_ux_smoke.cjs` with an installed Playwright runtime/browser.
The hermetic UI tests are included in CI; these changes still require CI execution
after review and push.

## Still open

Production hosting/configuration, release schema 06/07, verified backup restoration,
paid-provider authentication/freshness, real OTP/SMS/STOP/START and delivery callbacks,
approved load/low-bandwidth/target-device testing, and named operator procedures/
rehearsals. Missing dispatch credentials are not repaired by pausing a scheduler.
Atomic claims prevent blind retries but do not prove delivery, resolve partial
provider failures or remove the need for operational review. No scientific or
market-deployment approval has been granted. Experimental depth remains off.
