"""Restore a supplied private public-schema archive into a NEW local PG cluster.

Never connects to Supabase/Render or sends SMS. No database credentials/rows are
printed. Local test credentials exist only for this run in a private directory.
The source archive and receipt are read-only; no existing database is reused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
PG = Path(r"C:\Program Files\PostgreSQL\18\bin")
AUTH_ROLE = """
CREATE SCHEMA auth;
CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS $$
SELECT coalesce(nullif(current_setting('request.jwt.claim.role',true),''),
  (nullif(current_setting('request.jwt.claims',true),'')::jsonb ->> 'role'))::text;
$$;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
"""
PRIVATE_TABLES = (
    'subscribers', 'pending_subscriptions', 'alert_log', 'prediction_log',
    'verifications', 'dispatch_cells', 'briefing_log', 'chew_subscribers',
    'health_alerts', 'chew_responses', 'mel_events',
)
BASE_TABLES = frozenset((*PRIVATE_TABLES, 'dhis2_malaria_cases',
                        'entomology_observations', 'lga_health_risk'))
RELEASE_TABLES = BASE_TABLES | {'subscription_attempts', 'alert_claims'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest_file(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(args, *, env=None, timeout=90, log=None):
    if log:
        # Windows pg_ctl descendants can inherit a captured pipe, preventing
        # communicate() from returning after the launcher has exited. Private
        # file handles + closed stdin keep background-server startup bounded.
        with log.open('wb') as output:
            result = subprocess.run([str(a) for a in args], env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        result = subprocess.run([str(a) for a in args], env=env, capture_output=True,
                                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        # Errors can contain SQL/data. They remain in private logs, never chat.
        raise RuntimeError(f'{Path(str(args[0])).name} failed with code {result.returncode}; inspect private log')
    return result.stdout if not log else b''


def inventory(conn):
    with conn.cursor() as cur:
        cur.execute((ROOT / 'scripts/ops/restore_inventory.sql').read_text(encoding='utf-8'))
        while True:
            if cur.description and cur.description[0].name == 'restore_inventory':
                result = cur.fetchone()[0]
                break
            if not cur.nextset():
                raise RuntimeError('Inventory result was not returned')
        while cur.nextset():
            pass
    return result


def archive_rows(text, *, expected_tables=None):
    """Keep private COPY data in memory; compare raw rows without displaying them."""
    expected = BASE_TABLES if expected_tables is None else frozenset(expected_tables)
    if expected not in (BASE_TABLES, RELEASE_TABLES):
        raise RuntimeError('Source table set differs from reviewed application schemas')
    result = {}
    # Split only on literal LF. Unicode separators may legitimately occur in
    # private text columns and must not be mistaken for COPY row boundaries.
    lines = iter(text.split('\n'))
    for line in lines:
        match = re.fullmatch(r'COPY public\.([a-z_][a-z_0-9]*) \(([^)]+)\) FROM stdin;\r?', line)
        if not match:
            continue
        table, columns = match.groups()
        columns = tuple(c.strip(' "') for c in columns.split(','))
        if not all(re.fullmatch(r'[a-z_][a-z_0-9]*', c) for c in columns):
            raise RuntimeError('Unexpected COPY column identifier')
        rows = []
        for row in lines:
            if row.rstrip('\r\n') == r'\.':
                break
            rows.append(row.rstrip('\r\n').encode('utf-8'))
        else:
            raise RuntimeError('Unterminated COPY section')
        if table in result:
            raise RuntimeError('Duplicate COPY table section')
        result[table] = (columns, rows)
    if set(result) != expected:
        raise RuntimeError('Archived table set differs from the expected application schema')
    return result


def rows_digest(rows):
    # Length delimiters avoid ambiguity when hashing sorted raw COPY rows.
    digest = hashlib.sha256()
    for row in sorted(rows):
        digest.update(len(row).to_bytes(8, 'big'))
        digest.update(row)
    return digest.hexdigest()


def constraint_equivalence(source, target):
    if source['constraints'] == target['constraints']:
        return True
    # PostgreSQL 18 records NOT NULL in pg_constraint; PostgreSQL 17 records it
    # only as a column flag. Check EACH added constraint against the unchanged
    # source nullability, not a blanket dismissal of constraint differences.
    if not (source['postgres_version'].startswith('17.') and target['postgres_version'].startswith('18.')):
        return False
    if any(c['kind'] == 'n' for c in source['constraints']):
        return False
    ordinary = [c for c in target['constraints'] if c['kind'] != 'n']
    if source['constraints'] != ordinary:
        return False
    expected = {(c['table'], c['column']) for c in source['columns'] if c['nullable'] == 'NO'}
    actual = set()
    for c in target['constraints']:
        if c['kind'] != 'n':
            continue
        match = re.fullmatch(r'NOT NULL ([a-z_][a-z_0-9]*)', c['definition'])
        if not c['validated'] or not match:
            return False
        actual.add((c['table'], match[1]))
    return actual == expected


def compare_archive(conn, archived):
    result = []
    conn.execute("SET TIME ZONE 'UTC'")
    conn.execute("SET DateStyle = 'ISO, MDY'")
    for table, (columns, expected) in sorted(archived.items()):
        query = sql.SQL('COPY (SELECT {} FROM public.{}) TO STDOUT').format(
            sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table))
        with conn.cursor().copy(query) as copy:
            actual = b''.join(bytes(chunk) for chunk in copy).splitlines()
        if len(actual) != len(expected) or rows_digest(actual) != rows_digest(expected):
            raise RuntimeError(f'Archive contents mismatch for {table}; raw rows are not logged')
        result.append({'table': table, 'rows': len(actual), 'copy_sha256': rows_digest(actual), 'match': True})
    return result


def private_access_checks(conn, *, upgraded=False):
    tables = (*PRIVATE_TABLES, *(('subscription_attempts', 'alert_claims', 'alert_delivery_stats') if upgraded else ()))
    checks = 0
    for role in ('anon', 'authenticated'):
        for table in tables:
            with conn.transaction():
                conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                try:
                    # A savepoint keeps the parent transaction valid after denial.
                    with conn.transaction():
                        conn.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
                except psycopg.errors.InsufficientPrivilege:
                    checks += 1
                else:
                    raise RuntimeError(f'Unexpected private SELECT access: {role}/{table}')
    with conn.transaction():
        conn.execute('SET LOCAL ROLE service_role')
        for table in tables:
            conn.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table))).fetchone()
    functions = ('deactivate_stale_subscribers()',)
    if upgraded:
        functions += ('consume_subscription_attempt(text,text)', 'consume_pending_subscription(text,text)',
                      'claim_alert(uuid,date,text)', 'release_schema_version()', 'cleanup_personal_data()')
    for function in functions:
        for role in ('anon', 'authenticated'):
            if conn.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')', (role, function)).fetchone()[0]:
                raise RuntimeError(f'Unexpected private function access: {role}/{function}')
        if not conn.execute('SELECT has_function_privilege(\'service_role\',%s,\'EXECUTE\')', (function,)).fetchone()[0]:
            raise RuntimeError(f'Server role cannot execute {function}')
    return {'effective_private_select_denials': checks, 'server_reads': len(tables),
            'function_permissions_checked': len(functions),
            'function_role_permission_checks': len(functions)*3, 'passed': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup-directory', type=Path, required=True)
    parser.add_argument('--source-inventory', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('This drill is configured for Windows PostgreSQL 18 only')
    backup = args.backup_directory.resolve(strict=True)
    allowed = (Path(os.environ['LOCALAPPDATA']) / 'FloodSightRecovery').resolve()
    if backup == allowed or allowed not in backup.parents:
        raise RuntimeError('Backup must be a private run directory under LOCALAPPDATA/FloodSightRecovery')
    # Confirm protections inherited by all generated private artifacts.
    escaped_backup = str(backup).replace("'", "''")
    acl_command = ("$ErrorActionPreference='Stop'; $a=Get-Acl -LiteralPath '" + escaped_backup + "'; "
        '$u=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; '
        '$r=$a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]); '
        'if(-not $a.AreAccessRulesProtected){exit 1}; '
        'foreach($x in $r){if($x.AccessControlType -eq "Allow" -and '
        '$x.IdentityReference.Value -notin @($u,"S-1-5-18")){exit 2}}')
    powershell = shutil.which('pwsh.exe')
    if not powershell:
        raise RuntimeError('PowerShell 7 is required for the private ACL check')
    acl_probe = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', acl_command],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if acl_probe.returncode:
        raise RuntimeError('Private backup-directory ACL verification failed')
    receipt = json.loads((backup / 'receipt.json').read_text(encoding='utf-8-sig'))
    archive = backup / 'application-public.dump'
    if receipt['project_ref'] != 'buwwsplrhsfgnkulhkpc' or digest_file(archive) != receipt['sha256'].lower():
        raise RuntimeError('Source backup identity or SHA-256 mismatch')
    source = json.loads(args.source_inventory.read_text(encoding='utf-8'))
    source_tables = frozenset(t['name'] for t in source['tables'])
    if source_tables not in (BASE_TABLES, RELEASE_TABLES):
        raise RuntimeError('Source inventory does not describe a reviewed application schema')
    already_upgraded = source_tables == RELEASE_TABLES
    # Native dump output is private in memory. No row values are sent to tools/chat.
    archived = archive_rows(run([PG/'pg_restore.exe', '--file=-', archive]).decode('utf-8'),
                            expected_tables=source_tables)
    schema = run([PG/'pg_restore.exe', '--schema-only', '--file=-', archive]).decode('utf-8')
    toc = run([PG/'pg_restore.exe', '--list', archive]).decode('utf-8')
    schema_entries = [line for line in toc.splitlines() if re.search(r'; \d+ \d+ SCHEMA - public pg_database_owner$',line)]
    if len(schema_entries) != 1:
        raise RuntimeError('Expected one reviewed default public-schema archive entry')
    observed_roles = set(re.findall(r'(?:TO|FOR ROLE) (anon|authenticated|service_role|supabase_admin|postgres)\b', schema))
    if observed_roles != {'anon','authenticated','service_role','supabase_admin','postgres'}:
        raise RuntimeError('Archive roles differ from reviewed dependencies')
    private = backup / ('restore-drill-' + uuid.uuid4().hex)
    private.mkdir()
    # Reuse the newly created database's EMPTY default public namespace. This
    # retains PostgreSQL's initial PUBLIC USAGE grant, which pg_dump represents
    # as initial/default privileges rather than emitting it as an extra GRANT.
    # No tables/data/ACL/policy/function archive entries are filtered out.
    toc_file = private/'restore-toc.list'
    toc_file.write_text('\n'.join('; '+line if line == schema_entries[0] else line
        for line in toc.splitlines())+'\n',encoding='utf-8')
    data = private / 'pgdata'
    password = secrets.token_urlsafe(48)
    password_file = private / 'init-password.txt'
    password_file.write_text(password, encoding='ascii')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith('PG'):
            del env[key]
    env['PGPASSWORD'] = password  # Only ephemeral LOCAL credentials, never source credentials.
    env['PGCONNECT_TIMEOUT'] = '10'
    started = time.monotonic()
    report = {'scope':'isolated local public-application restore; NOT full Supabase recovery',
              'started_at_utc':utc(), 'backup_sha256':receipt['sha256'], 'backup_bytes':receipt['bytes'],
              'live_database_changed':False, 'messaging_connected':False,
              'source_postgres':source['postgres_version'], 'target_postgres':'18.3',
              'backup_already_release_version_7':already_upgraded,
              'application_tables_expected':len(source_tables),
              'reconstructed_dependencies':['anon/authenticated/service_role/supabase_admin role names',
                  'auth.role() SQL helper read from source; Auth server NOT replicated'],
              'supabase_admin_local_login':False,
              'restore_adjustments':['reuse empty default public namespace; skip only its CREATE SCHEMA TOC entry'],
              'base_restore_passed':False, 'migration_rehearsal_passed':False}
    server_started = False
    try:
        run([PG/'initdb.exe', '-D', data, '--username=postgres', '--auth-host=scram-sha-256',
             '--auth-local=scram-sha-256', '--pwfile='+str(password_file), '--no-locale', '--encoding=UTF8',
             '-c', 'shared_buffers=32MB', '-c', 'max_connections=30'], env=env, log=private/'initdb.log')
        password_file.unlink()  # Generated one-use file only, not a source credential.
        options = f'-h 127.0.0.1 -p {port} -c log_statement=none -c log_min_error_statement=panic'
        run([PG/'pg_ctl.exe', 'start', '-D', data, '-l', private/'postgres.log', '-w', '-t', '30', '-o', options],
            env=env, timeout=45, log=private/'start.log')
        server_started = True
        connargs = dict(host='127.0.0.1', port=port, user='postgres', password=password,
                        dbname='postgres', sslmode='disable', connect_timeout=10, autocommit=True)
        with psycopg.connect(**connargs) as admin:
            observed = Path(admin.execute("SELECT current_setting('data_directory')").fetchone()[0]).resolve()
            if observed != data.resolve():
                raise RuntimeError('Target cluster identity mismatch; refusing restore')
            admin.execute('CREATE ROLE anon NOLOGIN NOBYPASSRLS')
            admin.execute('CREATE ROLE authenticated NOLOGIN NOBYPASSRLS')
            admin.execute('CREATE ROLE service_role NOLOGIN BYPASSRLS')
            admin.execute('CREATE ROLE supabase_admin NOLOGIN BYPASSRLS')
            admin.execute('CREATE DATABASE floodsight_restore TEMPLATE template0')
            admin.execute('CREATE DATABASE floodsight_test TEMPLATE template0')
        connargs['dbname'] = 'floodsight_restore'
        with psycopg.connect(**connargs) as conn:
            # This is a newly created, empty target. No existing application schema is dropped.
            if conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]:
                raise RuntimeError('New restore database is unexpectedly non-empty')
            conn.execute(AUTH_ROLE)
        target = f'host=127.0.0.1 port={port} user=postgres dbname=floodsight_restore sslmode=disable connect_timeout=10'
        restore_started = time.monotonic()
        run([PG/'pg_restore.exe', '--dbname='+target, '--single-transaction', '--exit-on-error',
             '--no-password', '--use-list='+str(toc_file), archive], env=env, log=private/'restore.log')
        report['restore_seconds'] = round(time.monotonic()-restore_started, 3)
        with psycopg.connect(**connargs) as conn:
            report['archive_content_comparison'] = compare_archive(conn, archived)
            base = inventory(conn)
            (private/'base-inventory.json').write_text(json.dumps(base, indent=2), encoding='utf-8')
            mismatches = [key for key in ('tables','columns','indexes','sequences',
                'triggers','views','schema_acl','role_flags','policies','table_grants','functions')
                if source[key] != base[key]]
            if not constraint_equivalence(source,base):
                mismatches.append('constraints')
            report['source_comparison'] = {'source_observed_at':source['captured_at'],
                'export_synchronized':False, 'mismatched_sections':mismatches,
                'expected_differences':['database name', 'PostgreSQL 17.6 versus 18.3', 'observation time',
                    'PG18 NOT NULL catalog entries individually checked against source column nullability']}
            if mismatches:
                raise RuntimeError('Source inventory differs in sections: '+', '.join(mismatches))
            report['base_access_checks'] = private_access_checks(conn, upgraded=already_upgraded)
            report['base_restore_passed'] = True
            # Never execute baseline/consent-backfill scripts against recovered rows.
            before_sequence = base['sequences']
            repetitions = 0 if already_upgraded else 2
            for repetition in range(repetitions):
                with conn.transaction():
                    for name in ('06_delivery_reports.sql','07_release_hardening.sql'):
                        conn.execute((ROOT/'scripts/sql'/name).read_text(encoding='utf-8'))
                if conn.execute('SELECT release_schema_version()').fetchone()[0] != 7:
                    raise RuntimeError('Rehearsed schema version is not 7')
                compare_archive(conn, archived)  # Compare every original column, not just row counts.
                after = inventory(conn)
                if before_sequence != after['sequences']:
                    raise RuntimeError('Upgrade changed original sequence values')
                private_access_checks(conn, upgraded=True)
            report['upgrade_access_checks'] = private_access_checks(conn, upgraded=True)
            if already_upgraded:
                if conn.execute('SELECT release_schema_version()').fetchone()[0] != 7:
                    raise RuntimeError('Restored post-upgrade schema is not version 7')
                options = conn.execute("SELECT reloptions FROM pg_class WHERE oid='public.alert_delivery_stats'::regclass").fetchone()[0]
                if 'security_invoker=true' not in (options or []):
                    raise RuntimeError('Restored delivery view lacks security-invoker protection')
                report['delivery_view_security_invoker'] = True
                after = base
            report['migration_rehearsal_passed'] = True if repetitions else None
            report['migration_repetitions'] = repetitions
            report['restored_release_schema_verified'] = True
            report['release_schema_version'] = 7
            report['original_columns_and_rows_preserved'] = True
            (private/'upgraded-inventory.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
        # Existing regression fixture truncates synthetic data; NEVER run it on the restored DB.
        testargs = dict(connargs, dbname='floodsight_test')
        with psycopg.connect(**testargs) as conn:
            conn.execute(AUTH_ROLE)
        testenv = dict(env)
        testenv['TEST_DATABASE_URL'] = f'postgresql://postgres:{password}@127.0.0.1:{port}/floodsight_test'
        result = subprocess.run([str(ROOT/'.release-venv/Scripts/python.exe'), '-m', 'pytest',
            str(ROOT/'tests/test_database_release.py'), '-q', '--tb=no'], env=testenv,
            capture_output=True, timeout=90, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        (private/'regression.log').write_bytes(result.stdout+result.stderr)
        report['database_regression_passed'] = result.returncode == 0
        # Only report pass counts, never private logs or connection parameters.
        passed = re.search(rb'(\d+) passed',result.stdout)
        report['database_regression_tests_passed'] = int(passed[1]) if passed else 0
        if result.returncode:
            raise RuntimeError('Synthetic database regression failed; inspect private log')
        if digest_file(archive) != receipt['sha256'].lower():
            raise RuntimeError('Source archive changed during drill')
        report['source_archive_unchanged'] = True
    finally:
        if server_started or (data/'postmaster.pid').exists():
            with (private/'stop.log').open('wb') as output:
                stop = subprocess.run([str(PG/'pg_ctl.exe'), 'stop', '-D', str(data), '-m', 'fast', '-w', '-t', '30'],
                    env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                    timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
            report['local_server_stopped'] = stop.returncode == 0 and not (data/'postmaster.pid').exists()
        if password_file.exists():
            password_file.unlink()
        report['elapsed_seconds'] = round(time.monotonic()-started,3)
        report['finished_at_utc'] = utc()
        report['private_artifact_directory'] = str(private)
        (private/'drill-receipt.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
    if not report.get('local_server_stopped'):
        raise RuntimeError('Local server shutdown is unverified')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Avoid printing exception details: PostgreSQL errors can include private rows.
        print(json.dumps({'drill_failed':True,'error_type':type(exc).__name__,
            'reason':str(exc) if isinstance(exc,RuntimeError) else 'Details withheld to protect private data',
            'next_step':'Inspect private drill logs; no live database writes were attempted.'}))
        raise SystemExit(1)
