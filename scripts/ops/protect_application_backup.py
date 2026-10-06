"""Encrypt a verified SMALL application backup; keep the key outside upload/Git.

Uses cryptography's standard Fernet authenticated format, not a custom cipher.
Only this program's encrypted .zip.fernet output is eligible for cloud upload.
No network calls, source credentials, public database writes or secret printing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile

from cryptography.fernet import Fernet

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_TOKEN_BYTES = 48 * 1024 * 1024
MAX_RECEIPT_BYTES = 32 * 1024
MEMBERS = {'application-public.dump', 'receipt.json', 'RECOVERY.txt'}
RECOVERY = '''FloodSight application backup, standard Fernet-encrypted ZIP.
Keep the matching Fernet key in an independent secure location, NOT Drive/GitHub.
Decrypt with cryptography.fernet.Fernet(key).decrypt(encrypted_bytes), with no TTL.
The authenticated plaintext is a ZIP containing application-public.dump and
receipt.json. Verify archive SHA-256 against the receipt before any restoration.
The receipt is the original export-time record; its restore-unverified flag is
not modified by a later verification drill.
Restore only into a NEW isolated database and verify data, grants, RLS and schema.
Never restore over production or run baseline/consent-backfill/SMS/cleanup here.
Scope: public application schema ONLY, not full Supabase recovery. Managed
schemas, global roles/passwords, migration history, Storage file contents and
platform settings require separate recovery handling. Local tests use PG18.3
against a Supabase PG17.6 source, not a same-version managed-service recovery.
'''


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def create_bundle(archive, receipt_bytes):
    if not archive.startswith(b'PGDMP') or len(archive) > MAX_ARCHIVE_BYTES:
        raise RuntimeError('Unsupported archive format or size; review a streaming solution')
    if len(receipt_bytes) > MAX_RECEIPT_BYTES:
        raise RuntimeError('Receipt exceeds reviewed size limit')
    receipt = json.loads(receipt_bytes.decode('utf-8-sig'))
    if receipt['project_ref'] != 'buwwsplrhsfgnkulhkpc':
        raise RuntimeError('Backup identity mismatch')
    if sha256(archive) != receipt['sha256'].lower() or len(archive) != receipt['bytes']:
        raise RuntimeError('Archive checksum or size mismatch')
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as z:
        z.writestr('application-public.dump', archive)
        z.writestr('receipt.json', receipt_bytes)
        z.writestr('RECOVERY.txt', RECOVERY)
    return stream.getvalue()


def verify_token(token, key, expected_archive_sha256):
    if len(token) > MAX_TOKEN_BYTES:
        raise RuntimeError('Encrypted input exceeds reviewed size limit')
    plaintext = Fernet(key).decrypt(token)  # No TTL: recovery must not expire.
    with zipfile.ZipFile(BytesIO(plaintext)) as z:
        if set(z.namelist()) != MEMBERS or len(z.namelist()) != len(MEMBERS):
            raise RuntimeError('Unexpected encrypted bundle members')
        if sum(i.file_size for i in z.infolist()) > MAX_ARCHIVE_BYTES + 65536:
            raise RuntimeError('Decrypted bundle exceeds reviewed size limit')
        archive, receipt_bytes = z.read('application-public.dump'), z.read('receipt.json')
    # Revalidate authenticated archive and receipt, including expected source hash.
    create_bundle(archive, receipt_bytes)
    if sha256(archive) != expected_archive_sha256.lower():
        raise RuntimeError('Decrypted archive differs from the independently verified source')
    return archive, receipt_bytes


def private_acl(path, *, directory, create=False):
    if os.name != 'nt':
        raise RuntimeError('Private-file operations are configured for Windows only')
    if create:
        path.mkdir(parents=True, exist_ok=False)
    resolved = path.resolve(strict=True)
    if (directory and not resolved.is_dir()) or (not directory and not resolved.is_file()):
        raise RuntimeError('Expected a private directory or regular file')
    pwsh = shutil.which('pwsh.exe')
    if not pwsh:
        raise RuntimeError('PowerShell 7 is required for ACL checks')
    literal = str(resolved).replace("'", "''")
    setup = ''
    if create:
        setup = '''$a=[Security.AccessControl.DirectorySecurity]::new();
$a.SetAccessRuleProtection($true,$false); $a.SetOwner($u);
foreach($s in @($u,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))){
$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
$s,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))};
Set-Acl -LiteralPath $p -AclObject $a;
'''
    command = "$ErrorActionPreference='Stop'; $p='" + literal + "'; " + '''
$u=[Security.Principal.WindowsIdentity]::GetCurrent().User;
''' + setup + '''$i=Get-Item -LiteralPath $p -Force;
if($i.Attributes -band [IO.FileAttributes]::ReparsePoint){exit 4};
$a=Get-Acl -LiteralPath $p;
if($a.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $u.Value){exit 5};
''' + ('if(-not $a.AreAccessRulesProtected){exit 1};\n' if directory else '') + '''
$r=$a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]);
if($r.Count -ne 2){exit 2};
foreach($x in $r){if($x.AccessControlType -ne 'Allow' -or
$x.IdentityReference.Value -notin @($u.Value,'S-1-5-18') -or
$x.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl){exit 3}};
''' + ('''foreach($x in $r){if($x.InheritanceFlags -ne
([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
[Security.AccessControl.InheritanceFlags]::ObjectInherit) -or
$x.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None){exit 6}};
''' if directory else '') + '''
'''
    check = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if check.returncode:
        raise RuntimeError('Owner/SYSTEM-only private path ACL check failed')
    return resolved


def private_directory(path, *, create=False):
    return private_acl(path, directory=True, create=create)


def private_file_bytes(path, max_bytes):
    resolved = private_acl(path, directory=False)
    # Bound the actual read too, rather than trusting a previous size snapshot.
    with resolved.open('rb') as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise RuntimeError('Private input exceeds reviewed size limit')
    return data


def source_directory(path):
    root = (Path(os.environ['LOCALAPPDATA'])/'FloodSightRecovery').resolve()
    resolved = path.resolve(strict=True)
    if resolved == root or root not in resolved.parents:
        raise RuntimeError('Source must be a supplied private recovery run directory')
    return private_directory(resolved)


def checked_key(path):
    # Home is not subject to packaged-app LOCALAPPDATA write redirection. Keep
    # legacy app-cache keys readable for verified, non-destructive relocation.
    key_roots = ((Path.home()/'FloodSightRecoveryKeys').resolve(),
                 (Path(os.environ['LOCALAPPDATA'])/'FloodSightRecoveryKeys').resolve())
    resolved = path.resolve(strict=True)
    if not any(root in resolved.parents for root in key_roots) or not resolved.is_file():
        raise RuntimeError('Key must be the separately protected local recovery key file')
    private_directory(resolved.parent)
    key = private_file_bytes(resolved, 256).strip()
    Fernet(key)  # Validate format without printing its value.
    return key


def main():
    p = argparse.ArgumentParser()
    commands = p.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--backup-directory', type=Path, required=True)
    prepare.add_argument('--drill-receipt', type=Path, required=True)
    relocate = commands.add_parser('relocate-key')
    relocate.add_argument('--key-file', type=Path, required=True)
    for name in ('verify', 'recover'):
        action = commands.add_parser(name)
        action.add_argument('--encrypted-file', type=Path, required=True)
        action.add_argument('--key-file', type=Path, required=True)
        action.add_argument('--cipher-sha256', required=True)
        action.add_argument('--archive-sha256', required=True)
    a = p.parse_args()
    if a.command == 'relocate-key':
        key = checked_key(a.key_file)
        key_dir = private_directory(Path.home()/'FloodSightRecoveryKeys'/uuid.uuid4().hex, create=True)
        key_file = key_dir/'floodsight-recovery.fernet-key'
        with key_file.open('xb') as f:
            f.write(key+b'\n')
        if checked_key(key_file) != key:
            raise RuntimeError('Relocated key verification failed')
        result = {'key_file':str(key_file), 'verified_same_key':True,
                  'original_key_retained':True, 'key_uploaded':False,
                  'key_saved_off_computer':False, 'private_acl_verified':True}
    elif a.command == 'prepare':
        backup = source_directory(a.backup_directory)
        archive = private_file_bytes(backup/'application-public.dump', MAX_ARCHIVE_BYTES)
        receipt_bytes = private_file_bytes(backup/'receipt.json', MAX_RECEIPT_BYTES)
        drill = json.loads(a.drill_receipt.read_text(encoding='utf-8'))
        if not (drill['base_restore_passed'] and drill['restored_release_schema_verified']
                and drill['database_regression_passed'] and drill['local_server_stopped']
                and drill['release_schema_version'] == 7
                and drill['backup_sha256'].lower() == sha256(archive)):
            raise RuntimeError('A matching successful version-7 restore drill is required')
        bundle = create_bundle(archive, receipt_bytes)
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex
        encrypted_dir = private_directory(backup/('offsite-upload-'+run_id), create=True)
        key_dir = private_directory(Path.home()/'FloodSightRecoveryKeys'/run_id,
                                    create=True)
        key_file = key_dir/'floodsight-recovery.fernet-key'
        key = Fernet.generate_key()
        with key_file.open('xb') as f:
            f.write(key+b'\n')
        if checked_key(key_file) != key:
            raise RuntimeError('New key file verification failed')
        token = Fernet(key).encrypt(bundle)
        verify_token(token, key, sha256(archive))
        encrypted = encrypted_dir/('floodsight-application-'+run_id+'.zip.fernet')
        with encrypted.open('xb') as f:
            f.write(token)
        result = {'prepared_at_utc':datetime.now(timezone.utc).isoformat(),
            'format':'standard Fernet authenticated encryption over ZIP',
            'cipher_sha256':sha256(token), 'cipher_bytes':len(token),
            'archive_sha256':sha256(archive), 'archive_bytes':len(archive),
            'local_roundtrip_verified':True, 'source_archive_unchanged':True,
            'private_acl_verified':True, 'key_saved_off_computer':False,
            'encrypted_file':str(encrypted), 'key_file':str(key_file),
            'key_uploaded':False, 'upload_performed':False}
        if sha256(private_file_bytes(backup/'application-public.dump', MAX_ARCHIVE_BYTES)) != sha256(archive):
            raise RuntimeError('Source archive changed during preparation')
        (encrypted_dir/'preparation-receipt.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    else:
        encrypted = a.encrypted_file.resolve(strict=True)
        # Ciphertext is not secret, but its actual read must still be bounded.
        with encrypted.open('rb') as f:
            token = f.read(MAX_TOKEN_BYTES + 1)
        if len(token) > MAX_TOKEN_BYTES:
            raise RuntimeError('Encrypted input exceeds reviewed size limit')
        if sha256(token) != a.cipher_sha256.lower():
            raise RuntimeError('Downloaded encrypted checksum mismatch')
        archive, receipt_bytes = verify_token(token, checked_key(a.key_file), a.archive_sha256)
        result = {'download_cipher_sha256':sha256(token), 'decrypted_archive_sha256':sha256(archive),
                  'decrypted_archive_bytes':len(archive), 'decrypt_and_integrity_verified':True,
                  'plaintext_written':False, 'key_uploaded':False}
        if a.command == 'recover':
            # Only a new private local output; no SQL restore or network calls.
            out = private_directory(Path(os.environ['LOCALAPPDATA'])/'FloodSightRecovery'/
                                    ('decrypted-offsite-'+uuid.uuid4().hex), create=True)
            (out/'application-public.dump').write_bytes(archive)
            (out/'receipt.json').write_bytes(receipt_bytes)
            result.update(recovery_directory=str(out), plaintext_written=True)
    print(json.dumps(result))  # Paths/digests only, NEVER secret key or row values.


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'failed':True, 'error_type':type(exc).__name__,
            'reason':str(exc) if isinstance(exc,RuntimeError) else 'Details withheld; no secrets printed'}))
        raise SystemExit(1)
