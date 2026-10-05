# Backup and isolated restoration preflight

Initial preflight: 5 October 2026, 13:45 Lagos time. Update at 14:47: the owner
created an export and the isolated local application restore/upgrade rehearsal
passed. Full disaster-recovery acceptance remains open; see
`BACKUP_RESTORE_VERIFICATION.md`. The drill did not change live database records,
schema, credentials or hosting. Later, at 16:27 Lagos, explicitly approved live
upgrades 06/07 were applied and verified (version 7; original records preserved).
The schema/object inventory and no-backup statements below are historical
preflight evidence, not the later completed drill or current post-upgrade schema.

## Verified live state at initial preflight

- FloodSight project `buwwsplrhsfgnkulhkpc`: ACTIVE_HEALTHY, eu-west-1,
  PostgreSQL 17.6. Database size approximately 12 MB including managed schemas.
- Fourteen public application tables; all have row-level security enabled.
- Exact preflight counts: two subscriber rows and 83 briefing-log rows; the other
  twelve public tables are empty. No phone numbers or individual coordinates were
  displayed or exported by this preflight. Counts may change after this check.
- Auth users, Storage buckets/object metadata and Vault secrets: all zero.
- Seven public policies; one public function; no public views or custom table
  triggers. A restore must preserve grants, RLS, policies and function search path,
  not merely the table rows. Required roles include anon/authenticated/service_role.
- Security advisor: no WARN/ERROR findings; seven INFO notices for intentionally
  deny-by-default tables without policies.
- Release-version/claim functions and alert_claims/subscription_attempts tables
  are absent. Health delivery columns are only partially present. Rehearse the
  corrected 06/07 upgrades on the restored copy before any live application.

This is an inspection of the live database, **not evidence of an existing backup**.
No backup has yet been downloaded, hashed, restored or compared with its source.
The read-only comparison query was successfully executed against the source:
138 columns, 32 constraints, 37 indexes, seven policies and 238 explicit table
grant entries were inventoried, along with contents checksums and the public
function's permissions. Those entry counts are metadata, not additional records.

## Available paths and current access gap

The connected Supabase tools can inspect SQL and migrations, but do not expose
backup listing/download or a backup-to-isolated-project operation. The tool named
restore_project must not be treated as a general backup-restore test.

The [FloodSight backup dashboard](https://supabase.com/dashboard/project/buwwsplrhsfgnkulhkpc/database/backups/scheduled)
initially required browser sign-in. The owner signed in privately; no passwords,
tokens or keys should be pasted into chat.

Update after owner sign-in on 5 October: the dashboard confirms the organization's
**Free Plan** and explicitly states that it does not include project backups.
There is therefore no scheduled recovery point available for this drill. No plan
upgrade, password reset or restore was initiated. The dashboard's Session pooler
connection is `aws-0-eu-west-1.pooler.supabase.com:5432`, user
`postgres.buwwsplrhsfgnkulhkpc`, database `postgres`; its password remains unknown.

`scripts/ops/export_application_backup.ps1` prepares a Windows-only manual public-
schema export through that verified connection. Run it interactively in the
owner's PowerShell so the existing password is entered into PostgreSQL's hidden
prompt, never chat. It validates TLS, uses a read-only source connection, preserves
public ownership/grants/policies, and writes to a unique ACL-restricted directory
under LOCALAPPDATA outside Git. It checks archive readability and records SHA-256,
but does **not** claim restoration, full-project recovery or off-site encryption.
Its `-CheckOnly` mode passed; script syntax and in-memory ACL construction were
also checked. These do not test the live connection or an actual export. Additional
roles/extension dependencies and source-snapshot comparison must be captured for
the isolated drill before calling this backup accepted. No export has yet run.

Owner's first export attempt failed at TLS certificate verification, before any
usable backup was produced. The helper initially used the system/OpenSSL trust
bundle, which did not trust Supabase's private CA. Corrected on 5 October: the
official dashboard-linked public root CA is bundled and pinned by DER SHA-256,
validity-checked, and used only for this connection. `verify-full` remains enabled;
no operating-system trust store, database password or server setting was changed.
The pooler's certificate chain and hostname passed a password-free TLS 1.3 test
using that CA. The installed PostgreSQL 18 client also reached the expected
password challenge with no password sent, and rejected an intentionally incorrect
hostname. Script syntax and `-CheckOnly` passed. Authentication, export and isolated
restoration remain unverified.

PostgreSQL 18.3 dump/restore tools are installed locally. A PostgreSQL 18 service is
running, but a passwordless local connection is rejected. No database connection
credential was present in the current process environment. Docker's engine is not
running. Do not reset passwords or weaken local authentication as a shortcut.

Options once access is available:

1. If suitable managed backups exist, inspect timestamp/status, then use an
   explicitly approved isolated destination. A restore of the live project is
   prohibited for this drill. A new cloud project may incur charges; quote the
   cost and obtain confirmation before creating it.
2. Otherwise create a logical export using a securely configured direct/session
   database connection and current provider guidance. Preserve schema, data,
   roles/grants, sequences, extensions and relevant migration history. Do not
   use a service-role API key as a PostgreSQL password. Do not put a secret URL
   on a logged command line or reset the live password without owner action.
3. A local isolated application-schema drill can avoid new cloud charges, but
   needs a secured, dedicated target with compatible roles/extensions. It does
   not test Supabase Auth/Storage/Vault/platform services. Those are currently
   empty, but production recovery still requires their configuration inventory.

## Drill acceptance checklist

- Store exports in a private, access-restricted location outside Git and ordinary
  shared folders. Encrypt any retained off-site copy; owner selects destination
  and retention. SHA-256 proves file integrity, not encryption or restorable data.
- Capture source metadata and contents at the export's consistent snapshot, not
  from a later query. Record backup time, bytes, hash, version and scope/exclusions.
- Keep target wholly isolated: no Render connection, provider credentials, SMS
  audience, webhooks, cron jobs or public API exposure. Verify its identity before
  every restore; never use the source project's connection as the restore target.
- Restore into an empty dedicated target; fail on errors. Do not suppress errors,
  skip constraints, replay consent backfills, or invoke cleanup functions.
- Compare exact table counts/content checksums, columns, constraints, indexes,
  sequences/defaults, RLS, policies, grants, function behavior/search paths and
  extension dependencies. Run anonymous/authenticated denial and server-role checks.
- The read-only `scripts/ops/restore_inventory.sql` supplies aggregate public-schema
  comparison metadata without printing individual rows. MD5 here is an accidental-
  change comparison aid, not a cryptographic backup signature or security control.
  Matching counts alone do not prove matching contents. Review every difference;
  source and target platform version differences are not silently ignored.
- Record actual recovery duration and backup-to-recovery data-loss window. The
  owner must approve RTO/RPO limits; no limits or acceptance are invented here.
- Only after base restoration passes: rehearse 06/07 on the isolated copy, verify
  version 7 and row preservation, then obtain approval for the specific live upgrade.
- Retain a private verified backup and a non-sensitive drill receipt. Approve
  disposal/retention of restored personal data; do not leave an unprotected clone.

## Provider/version notes

[Supabase backup guidance](https://supabase.com/docs/guides/platform/backups) describes
daily managed backups for paid plans and recommends exports for free projects.
Database backups do not contain Storage file contents. A development branch's
migrations alone are not restoration of live data. Availability must be verified
on this project rather than inferred from those general features.

[Current restore guidance](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)
requires separate handling of roles, migration history, managed-schema changes,
encryption keys and Storage/Edge configuration where applicable.

The [25 September PostgreSQL update notice](https://supabase.com/changelog/postgres-15-19-17-11-breaking-changes)
announces 17.11 security/correctness fixes. This project's inspected version is
17.6. Add provider-version upgrade review after a verified backup, not an automatic
upgrade during this drill. ltree/btree_gist are not installed in the inspected
project; pgcrypto is installed, but actual legacy-cipher usage has not been audited.
