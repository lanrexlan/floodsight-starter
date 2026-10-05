# Read-only deployment receipt — 5 October 2026

Owner confirmed workspace: Rankine Innovation Lab Projects
(`tea-d8rbv0ernols73f81rig`). No hosting settings, environment secrets, database
records, messaging approvals or spending were changed during this check.

Render API confirms `floodsight-starter` (`srv-d8s5hnbeo5us73e4q6s0`) is live:

- Deploy `dep-db1dks2vcj2c73a5ha20`, merged main commit
  `38d688416d1db1a7f217ed5a53c960773b623671`.
- URL: https://floodsight-starter.onrender.com
- GitHub main auto-deploys on commits; a feature-branch push is not a release.
- Native Python runtime, one free instance, Ohio region; no health-check path
  configured on the service. Existing service settings do not automatically
  adopt the repository Blueprint.

Bounded public GET checks after an initial 45-second timeout:

| Endpoint | Result | Interpretation |
|---|---|---|
| `/health` | 200, `status=ok` | Application process responds |
| `/ready` | 200, `ready=true`, `mode=development` | Development readiness only; production credential/database gates are not exercised |
| `/product-status` | 200, depth disabled, controlled pilot | Experimental depth remains off; not scientific approval |
| `/dashboard/` and `/dashboard/app.js` | 200 | Previously merged assets served; not the pending UX changes |
| `/risk/point?lat=6.52&lon=3.37` | 200, packaged pipeline cell/risk | Representative static lookup works; not a validation observation |
| `/health/activity`, `/health/mel/events` without token | 401 | Protected reports reject anonymous access |
| `/health/cases` without token | 200 | Deployed main still exposes this aggregate case view; fix branch adds operator protection and nine auth regressions |

The initial timeout is consistent with a cold start but does not prove its cause
or define latency/availability. These are smoke checks, not a load test, paid
weather-provider test, production database/backup test or SMS acceptance.

Next release: review and merge the new fix PR after branch CI passes, then confirm
the new Render commit and repeat asset/health/depth-off/private-route checks.
Production mode, schema 06/07, restoration, approved always-on hosting and live
delivery tests remain separate acceptance gates. No autonomous warning or market
accuracy claim is approved by this receipt.
