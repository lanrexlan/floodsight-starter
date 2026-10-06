"""Synthetic bytes only: no private key files, cloud accounts or real rows."""
import importlib.util
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import pytest

spec = importlib.util.spec_from_file_location('protect_application_backup',
    Path(__file__).resolve().parents[1]/'scripts/ops/protect_application_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def bundle():
    archive = b'PGDMP synthetic-only archive'
    receipt = json.dumps({'project_ref':'buwwsplrhsfgnkulhkpc',
        'sha256':backup.sha256(archive), 'bytes':len(archive)}).encode()
    return archive, backup.create_bundle(archive,receipt)


def test_authenticated_roundtrip_preserves_exact_archive():
    archive, data = bundle()
    key = Fernet.generate_key()
    token = Fernet(key).encrypt(data)
    actual, _ = backup.verify_token(token,key,backup.sha256(archive))
    assert actual == archive
    assert archive not in token


def test_wrong_key_and_tampering_are_rejected():
    archive, data = bundle()
    key = Fernet.generate_key()
    token = Fernet(key).encrypt(data)
    with pytest.raises(InvalidToken):
        backup.verify_token(token,Fernet.generate_key(),backup.sha256(archive))
    modified = token[:50]+(b'A' if token[50:51] != b'A' else b'B')+token[51:]
    with pytest.raises(InvalidToken):
        backup.verify_token(modified,key,backup.sha256(archive))


def test_independent_source_hash_and_receipt_are_checked():
    archive, data = bundle()
    key = Fernet.generate_key()
    with pytest.raises(RuntimeError,match='independently verified source'):
        backup.verify_token(Fernet(key).encrypt(data),key,'0'*64)
    with pytest.raises(RuntimeError,match='checksum or size'):
        backup.create_bundle(archive,json.dumps({'project_ref':'buwwsplrhsfgnkulhkpc',
            'sha256':'0'*64,'bytes':len(archive)}).encode())


def test_unexpected_bundle_members_are_rejected():
    archive, data = bundle()
    stream = backup.BytesIO(data)
    with backup.zipfile.ZipFile(stream,'a') as z:
        z.writestr('../secret-key','synthetic')
    key = Fernet.generate_key()
    with pytest.raises(RuntimeError,match='Unexpected encrypted bundle members'):
        backup.verify_token(Fernet(key).encrypt(stream.getvalue()),key,backup.sha256(archive))


def test_receipt_identity_and_size_limits_are_enforced(monkeypatch):
    archive = b'PGDMP synthetic-only archive'
    receipt = json.dumps({'project_ref':'wrong-project',
        'sha256':backup.sha256(archive), 'bytes':len(archive)}).encode()
    with pytest.raises(RuntimeError, match='identity mismatch'):
        backup.create_bundle(archive, receipt)
    monkeypatch.setattr(backup, 'MAX_RECEIPT_BYTES', 8)
    with pytest.raises(RuntimeError, match='Receipt exceeds'):
        backup.create_bundle(archive, receipt)


def test_archive_and_token_size_limits_are_enforced(monkeypatch):
    archive, data = bundle()
    monkeypatch.setattr(backup, 'MAX_ARCHIVE_BYTES', 8)
    with pytest.raises(RuntimeError, match='Unsupported archive'):
        backup.create_bundle(archive, b'{}')
    monkeypatch.setattr(backup, 'MAX_TOKEN_BYTES', 8)
    key = Fernet.generate_key()
    with pytest.raises(RuntimeError, match='Encrypted input exceeds'):
        backup.verify_token(Fernet(key).encrypt(data), key, backup.sha256(archive))


def test_authenticated_zip_expansion_is_bounded(monkeypatch):
    archive, data = bundle()
    stream = backup.BytesIO()
    with backup.zipfile.ZipFile(backup.BytesIO(data)) as original:
        with backup.zipfile.ZipFile(stream, 'w', compression=backup.zipfile.ZIP_DEFLATED) as z:
            for name in original.namelist():
                z.writestr(name, b'A' * 70000 if name == 'RECOVERY.txt' else original.read(name))
    monkeypatch.setattr(backup, 'MAX_ARCHIVE_BYTES', 32)
    key = Fernet.generate_key()
    with pytest.raises(RuntimeError, match='Decrypted bundle exceeds'):
        backup.verify_token(Fernet(key).encrypt(stream.getvalue()), key, backup.sha256(archive))


def test_private_file_reads_are_bounded(tmp_path, monkeypatch):
    path = tmp_path/'synthetic.bin'
    path.write_bytes(b'synthetic')
    monkeypatch.setattr(backup, 'private_acl', lambda path, **kwargs: path)
    assert backup.private_file_bytes(path, 9) == b'synthetic'
    with pytest.raises(RuntimeError, match='Private input exceeds'):
        backup.private_file_bytes(path, 8)


@pytest.mark.skipif(os.name != 'nt', reason='Windows-only filesystem helper')
def test_windows_private_file_checks_inherited_permissions(tmp_path):
    private = backup.private_directory(tmp_path/'private', create=True)
    path = private/'synthetic.bin'
    path.write_bytes(b'synthetic')
    assert backup.private_file_bytes(path, 9) == b'synthetic'


@pytest.mark.skipif(os.name != 'nt', reason='Windows-only filesystem helper')
def test_windows_rejects_explicit_public_file_access(tmp_path):
    private = backup.private_directory(tmp_path/'private', create=True)
    path = private/'synthetic.bin'
    path.write_bytes(b'synthetic')
    literal = str(path).replace("'", "''")
    command = "$ErrorActionPreference='Stop'; $p='" + literal + "'; " + '''
$a=Get-Acl -LiteralPath $p;
$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
[Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Read','Allow'));
Set-Acl -LiteralPath $p -AclObject $a;
'''
    result = backup.subprocess.run([backup.shutil.which('pwsh.exe'), '-NoProfile',
        '-NonInteractive', '-Command', command], capture_output=True, timeout=20,
        creationflags=backup.subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    with pytest.raises(RuntimeError, match='private path ACL check failed'):
        backup.private_file_bytes(path, 9)
