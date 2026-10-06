# FloodSight application-database restore verification

Restore drill completed **5 October 2026, 14:47 Lagos time**. The isolated local
application-database restore and upgrade rehearsal passed without changing live
Supabase. Following explicit owner approval, live upgrades 06/07 were applied at
**16:27 Lagos time** and verified through **16:39**. Full disaster-recovery and
production acceptance remain open. The fresh post-upgrade backup was successfully
restored and verified at **16:52 Lagos time**; details below.

## Evidence

- Owner-created export: 60,139 bytes, public application schema only. SHA-256
  `7FFDD0F3603777151399E7ADF810443887275BFBC4F581DC476B2ED432CCB8C2`
  matched before and after the drill. No source database password was provided to
  Codex, saved in the repository, or used by the local restore.
- Restore: fourteen tables, two subscriber rows and 83 briefing-log rows; twelve
  tables empty. Every archived COPY row was compared with the restored contents
  using sorted, length-delimited SHA-256, without logging individual rows.
- A later read-only source observation also matched the restored table contents,
  columns, ordinary constraints, indexes, sequence values, policies, grants and
  public function definitions/permissions. It was not synchronized to the export
  snapshot; the independent archive comparison supplies the content proof.
- RLS enabled on all fourteen restored tables. Actual SELECT attempts by anon and
  authenticated were denied for eleven private tables (22 checks). Server-role
  reads succeeded. Privileged maintenance function permissions were verified,
  without invoking that function.
- Upgrades `06_delivery_reports.sql` and `07_release_hardening.sql` applied twice
  on the restored copy, in transactions. Version 7 returned; all original columns,
  records and original sequence values remained unchanged after each application.
  The upgrade creates additional fields/objects, so this is not a claim that the
  entire schema or every new-field value stayed unchanged.
- After upgrade: 28 actual anonymous/signed-in private SELECT denials, server
  reads and six private function permission checks passed.
- Eight database regression tests passed in a **second, synthetic-only database**.
  Their fixture truncates data and was never pointed at the recovered database.
  Four synthetic parser/comparison tests also passed.
- Fresh wider suite: 219 passed, eight database tests skipped, ten existing
  dependency warnings. The eight database tests passed separately during the
  isolated drill above. An initial wider run hit the sandbox's TEMP-folder ACL;
  rerunning with a new workspace-contained temporary directory passed, without
  weakening permissions or changing the test assertions.
- Successful drill: 19.938 seconds including local initialization, restore,
  checks, rehearsals, regression and shutdown. Restore command alone: 0.656 seconds.
  These tiny-dataset local measurements are **not a production RTO or SLA**.
- All created test clusters were stopped and checked for absence of their server
  PID files. The existing Windows PostgreSQL service was not changed. No Render,
  public API, SMS provider, webhook or scheduler was connected to recovered data.
- Fresh live security advisor at 14:51 Lagos: no WARN/ERROR findings; seven INFO
  notices identify intentionally deny-by-default tables without policies. No
  permissive policies were added to silence these notices. See the
  [provider explanation](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

Aggregate machine-readable receipt: `reports/backup_restore_drill_20261005.json`.
The archive, copied personal records and private operational logs remain in the
owner's ACL-restricted LOCALAPPDATA/FloodSightRecovery directory, outside Git.
Neither archive nor private logs are attached to this report.

## Compatibility handling reviewed

Source is Supabase PostgreSQL 17.6; the available local target is PostgreSQL 18.3.
This is not a same-version or full Supabase project-recovery test.

- Standard anon/authenticated/service_role/supabase_admin role names and the
  inspected SQL definition of `auth.role()` were reconstructed locally. No Auth
  server, JWT verification, role passwords or full managed schemas were cloned.
  Local supabase_admin is deliberately NOLOGIN, unlike the managed source role.
- The newly created empty default public namespace was reused; only its redundant
  CREATE SCHEMA archive entry was skipped. Every table/data/grant/policy/function
  entry remained included, preserving PostgreSQL's initial PUBLIC USAGE privilege.
- PostgreSQL 18 adds NOT NULL entries to pg_constraint. Each added entry was
  validated against the unchanged source column nullability; ordinary constraints
  matched exactly. See the [PostgreSQL release note](https://www.postgresql.org/docs/18/release-18.html).
- Diagnostic sequence bigint values are encoded as strings to prevent JSON/
  JavaScript rounding. The corrected source/target limits match exactly. This
  diagnostic problem did not affect the binary backup or PostgreSQL data.

## Acceptance still open

1. Same-version/Supabase-target recovery, managed role/configuration/migration
   history inventory, provider-version review and managed-service acceptance.
   Auth/Storage/Vault were empty at preflight, not a guarantee they remain empty.
   [Provider recovery guidance](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)
   requires separate handling of those recovery components where applicable.
2. Recovery testing with the independently saved key, a recurring backup schedule, retention/
   disposal decision, and owner-approved recovery-time/data-loss limits. A one-off
   encrypted Drive copy has now passed download/decryption verification; see
   `OFFSITE_BACKUP_VERIFICATION.md`. The owner confirmed independent key custody
   on 2026-10-06; recovery using that external key copy is not yet tested, so
   recovery after computer loss is not fully accepted.
3. Real approved-number SMS/OTP/STOP/START, production configuration/load checks,
   operator procedures and scientific validation. This drill does not close them.

## Post-upgrade backup — restored and verified

The owner created a separate current-schema export at 16:47 Lagos. Its 75,900-byte
archive SHA-256 is `84F906D1C42044F6FC6AD79454D9B6949220707CDD88F1D1C37D05CA96DDC05E`.
The original pre-upgrade archive remains unchanged and private.

- A fresh isolated local cluster restored all sixteen application tables, all
  85 records and the version-7 functions, trigger, view, policies and grants.
  Every archived COPY row matched the restored contents using sorted,
  length-delimited SHA-256. No personal row values or credentials were logged.
- A later source observation at 16:49 Lagos matched table contents, columns,
  ordinary constraints, indexes, sequences, triggers, views, roles, policies,
  grants and function definitions/permissions. This observation was not
  synchronized to the export; archive-to-restored-row comparisons establish
  backup content fidelity independently.
- All sixteen restored tables have RLS. Twenty-eight actual private SELECT
  denials, fourteen server reads and eighteen function/role permission checks
  passed. The delivery view retains security-invoker protection.
- Version 7 was verified directly from the restored archive: **no upgrade,
  baseline or consent-backfill scripts were replayed** on this recovered copy.
  No maintenance/OTP/claim function or provider endpoint was invoked.
- Eight database regression tests passed in a separate synthetic-only database.
  Six synthetic parser/comparison tests passed, including exact checks for both
  pre-upgrade and version-7 table sets; wrong names are rejected even if the table
  count is correct.
- Fresh wider suite with the updated checker: 221 passed, eight database tests
  skipped, ten existing dependency warnings. Those eight database tests passed
  separately in the isolated drill; the wider run did not use its stopped server.
- The drill finished in 15.594 seconds; restoration alone took 0.703 seconds.
  These local tiny-dataset measurements are not a production RTO/SLA. The new
  local cluster was stopped and its server PID file is absent. Both backup
  archive hashes still match; live Supabase and existing local services were not
  modified. Private copied data/logs remain in the private recovery folder.

Receipt: `reports/backup_restore_postupgrade_drill_20261005.json`; source comparison
inventory: `reports/backup_restore_postupgrade_source_inventory_20261005.json`.
The backup receipt remains marked restore-unverified because it is an immutable
export-time record; the separate drill receipt supplies subsequent verification.

At completion of this drill, this closed the fresh version-7 application-export/local-restore step, **not full
Supabase disaster recovery**. The same managed-schema, migration-history,
PostgreSQL 17 target, encrypted off-site, recurring-backup and owner-approved
recovery-limit gaps listed above remain. Backups and copied personal records
had not been uploaded to GitHub or any off-site destination. The subsequent
encrypted Drive verification is recorded below; plaintext backups and keys
remain excluded from GitHub and Drive.

### What off-site storage means

The two original private backups live on this computer. If it is lost, stolen
or damaged, those originals may be lost with it. Off-site storage is a second copy
kept somewhere independent, such as an approved private cloud-storage account.
Encrypt that copy before uploading it, keep its recovery key separately, and
verify that it can be downloaded, decrypted and restored. Agree on a recurring
schedule and how long copies are kept. The owner-approved one-off encrypted copy
is now verified in a private Drive folder. Independent key custody was owner-confirmed
on 2026-10-06, but that external key copy has not been recovery-tested. No recurring
schedule or purchase has been completed. GitHub holds code and aggregate evidence, not the
database backups, encryption keys or copied personal records.

## Approved live upgrade — completed

The owner approved only the rehearsed 06/07 upgrades. Before applying them, the
backup SHA-256 was checked again and a fresh source inventory matched the restored
copy exactly. The provider recorded migration `20261005152719`, named
`approved_delivery_tracking_and_release_hardening`.

- A single atomic DO statement applied the unchanged reviewed scripts. Original-
  record guards ran before and after under table locks; a failure would abort the
  statement. Lock timeout was five seconds; statement timeout sixty seconds.
- All 138 original columns, all original records across fourteen tables, eleven
  sequences, existing indexes and ordinary constraints remained unchanged. The
  two subscribers and 83 briefing rows were preserved; aggregate comparisons did
  not expose personal records. Whole-row subscriber hashes change when the new
  field is added, so preservation was checked using original columns only.
- Version 7, sixteen RLS-protected tables, delivery fields/three indexes, the
  security-invoker delivery view, four service-role-only health policies and the
  deactivation trigger were verified. No inactive subscriber lacks its opt-out
  timestamp.
- Actual anonymous/authenticated SELECT attempts were denied for fourteen private
  objects (28 checks). Fourteen service-role reads and eighteen role/function
  permission checks passed. Only the non-mutating version function was called;
  maintenance, OTP and alert-claim functions were not invoked by verification.
- Security advisor: no WARN/ERROR findings; nine INFO deny-by-default notices,
  including the two new private tables. No public policies were added to silence
  them. [Provider explanation](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).
- Deployed health/readiness returned HTTP 200 after an initial forty-second read
  timeout. Readiness still reports development mode, which does not test the
  app's production database connection. Protected health routes returned 401;
  experimental depth remains disabled (503). This is not production acceptance.

Aggregate receipt: `reports/live_database_upgrade_20261005.json`. The exact applied
one-time SQL is `scripts/ops/approved_release_upgrade_20261005.sql`; its guards are
specific to this pre-upgrade snapshot, not a general deployment script. The
read-only role test is `scripts/ops/verify_release_access.sql`. Helpers and aggregate
receipts are included on `codex/floodsight-backup-recovery-verification` for GitHub
review. They contain no database archives, personal rows or private recovery logs.

These scripts add delivery tracking, private rate-limit/OTP/alert-reservation
functions and tables, an opt-out timestamp/trigger, and a retention function.
The opt-out timestamp backfill affects only inactive subscribers missing it.
No baseline/consent backfill was replayed, no retention/stale-subscriber routine
was invoked, and no cleanup was scheduled (pg_cron remains absent). No SMS was
sent and no hosting, credentials, messaging settings or experimental-depth gate
was changed. Upgrading the schema does not itself enable production messaging.
Restoring over the live project or buying a platform upgrade was not authorized.
