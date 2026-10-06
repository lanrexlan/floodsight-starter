# Encrypted off-site application backup — 5 October 2026

With explicit owner approval, a private `FloodSight Backups` folder was created
in the connected Google Drive account. Only a 104,312-byte encrypted backup was
uploaded. Folder and file metadata readback show one owner permission, no public
sharing, the expected folder parent and matching size. No key, password, readable
database archive, personal row or private recovery log was uploaded.

The encryption uses the installed cryptography 50.0.2 library's standard Fernet
authenticated format over a ZIP, with a fresh random key. The ZIP contains only
the verified public-schema archive, its original export receipt and recovery
instructions. No custom cipher or password-derived key was introduced. Fernet
requires preserving its secret key; losing it prevents decryption. See the
[library documentation](https://cryptography.io/en/50.0.2/fernet/).

## Verification

- Local encrypt/decrypt round trip passed. Synthetic tests reject a wrong key,
  altered ciphertext, wrong source checksum and unexpected ZIP members.
- The uploaded ciphertext was downloaded through the authenticated file reference
  returned by Drive, without requesting inline base64. The transient signed
  download reference is not stored in the repository or verification receipt.
- Its SHA-256 matched `34dfbb0440aaccf3356d5edb98b5cf95a9dd180b27c9cc3d161bf8c026fec792`.
- Downloaded bytes decrypted in memory and matched the original 75,900-byte
  restore-tested archive SHA-256:
  `84f906d1c42044f6fc6ad79454d9b6949220707cdd88f1d1c37d05ca96ddc05e`.
  No readable downloaded data was written to disk. This step did not perform a
  new SQL restore; matching bytes link it to the successful 16-table/85-record
  restore in `reports/backup_restore_postupgrade_drill_20261005.json`.
- The key is outside Drive/GitHub in an owner/SYSTEM-only local folder. Windows
  initially redirected it into packaged-app local storage; a verified copy is now
  in the stable home-folder `FloodSightRecoveryKeys` directory. Both private key
  copies contain the same key; its contents were never printed. Decryption was
  rechecked using the stable copy.
- The original plaintext backups remain unchanged. No live database, hosting,
  scheduler, SMS configuration or billing was changed.
- Fresh wider suite: 225 passed, eight database tests skipped, ten existing
  dependency warnings. Four new crypto tests and six parser tests passed. The
  eight database tests passed separately in the earlier isolated restore drill;
  this cloud/decryption step did not run or connect a database.

Aggregate receipt: `reports/encrypted_offsite_backup_20261005.json`. Private Drive
IDs, signed download URLs, source/key paths and key values are not in that receipt.
The encryption helper and aggregate evidence are included on the
`codex/floodsight-encrypted-offsite-backup` review branch. Merge and GitHub CI
acceptance are separate from the completed one-off backup verification.

### Helper review — 6 October 2026

The review tightened owner/SYSTEM-only checks on files as well as folders,
including owner, full-control permissions and directory inheritance. Existing
files are checked without changing their permissions; unexpected permissions
fail closed. Archive, receipt and ciphertext reads have explicit size limits.
New synthetic regressions check these limits and reject explicit public file
access even inside a private directory. No real key or backup was accessed by
these tests, and no cloud verification or SQL restore was repeated in this review.

The targeted suite passed all sixteen checks (ten encryption/helper checks,
including two Windows filesystem checks, and six restore-parser checks). The full
local suite passed 231 tests, skipped eight database checks, and emitted ten
existing dependency warnings. All 21 hermetic UI checks passed; CI YAML parsed.
The direct vulnerability check found none for the two pinned recovery packages;
it did not resolve transitive dependencies. The requirements-based resolved audit
could not initialize its temporary environment. GitHub CI installs the optional
operations requirements and runs the full installed-dependency audit, PostgreSQL
17 checks and container checks; its result must be reviewed before merging.

## Recovery-key custody and remaining actions

On 2026-10-06, the owner confirmed the recovery key was safely saved separately.
This is owner-attested custody: the external copy has not been inspected or used
in a recovery test. Keep that copy in a secure, independently recoverable place,
such as your password manager or an offline USB kept safely. Do not put it
in the backup's Google Drive account, GitHub, email or this chat. Do not delete the
local copies until the independent copy is confirmed and tested. The backup cannot
protect against computer loss if all key copies are lost with that computer.

Key custody is **owner-confirmed**, but recovery using that external key copy is
not yet tested. Only a one-off encrypted copy is verified;
no recurring backup schedule or retention/deletion procedure is configured. Full
Supabase/same-version recovery and owner-approved recovery-time/data-loss limits
remain open. This does not establish market or scientific acceptance.

## Recovery format and tooling

`scripts/ops/protect_application_backup.py` supports `prepare`, `verify`, `recover`
and verified `relocate-key`. Key values are never command arguments or output.
`requirements-ops.txt` pins the optional local recovery dependencies; it does not
change deployment requirements. The wrapper's filesystem/ACL handling is Windows-
specific, but the Fernet token/ZIP format is standard and independently decryptable
with the matching key and cryptography. Do not apply a TTL when decrypting backups.
The in-memory helper is bounded to 32 MB archives; larger backups require a reviewed
streaming approach, not increasing limits without assessing memory/security.

`recover` writes only a newly created private LOCALAPPDATA/FloodSightRecovery run,
never over an existing archive. Recheck the resulting SHA-256, then use the
isolated restore checker with a matching source inventory. Do not restore over
production, send SMS, run cleanup, or replay baseline/consent-backfill scripts as
part of recovery.
