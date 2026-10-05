# Run interactively in your own PowerShell window. Never paste passwords into chat.
# This exports the public application schema ONLY, not a full Supabase project.
[CmdletBinding()]
param(
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$pgDump = 'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe'
$pgRestore = 'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe'
if (-not (Test-Path -LiteralPath $pgDump -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pgRestore -PathType Leaf)) {
    throw 'PostgreSQL 18 dump/restore tools are required at the configured paths.'
}
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
$rootCertificate = Join-Path $PSScriptRoot 'certs/prod-ca-2021.crt'
if (-not (Test-Path -LiteralPath $rootCertificate -PathType Leaf)) {
    throw 'The official Supabase root certificate is missing; do not disable TLS verification.'
}
# The system/OpenSSL trust bundle need not include Supabase's private root CA.
# Use the public CA from the authenticated dashboard, scoped to this connection.
$pem = (Get-Content -LiteralPath $rootCertificate -Raw).Trim()
$match = [regex]::Match($pem, '\A-----BEGIN CERTIFICATE-----\s*(?<body>[A-Za-z0-9+/=\s]+?)\s*-----END CERTIFICATE-----\z')
if (-not $match.Success) { throw 'Expected exactly one PEM root certificate.' }
$der = [Convert]::FromBase64String($match.Groups['body'].Value)
$sha = [Security.Cryptography.SHA256]::Create()
try { $fingerprint = ([BitConverter]::ToString($sha.ComputeHash($der))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
$expectedFingerprint = '807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa'
if ($fingerprint -ne $expectedFingerprint) { throw 'Supabase root certificate fingerprint mismatch.' }
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($der)
try {
    $now = [DateTime]::UtcNow
    if ($now -lt $certificate.NotBefore.ToUniversalTime() -or $now -ge $certificate.NotAfter.ToUniversalTime()) {
        throw 'Supabase root certificate is outside its validity period.'
    }
} finally { $certificate.Dispose() }
if ($CheckOnly) {
    & $pgDump --version
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump version check failed.' }
    & $pgRestore --version
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore version check failed.' }
    Write-Host 'Tools and pinned root certificate passed. No connection, export, directory or credential was created.'
    return
}

# Unique, private local destination outside the repository. Not an encrypted
# off-site backup; owner-approved encrypted retention is still required.
$runId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N')
$destination = Join-Path (Join-Path $env:LOCALAPPDATA 'FloodSightRecovery') $runId
[void][IO.Directory]::CreateDirectory($destination)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
$system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner($identity)
foreach ($sid in @($identity, $system)) {
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    [void]$acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $destination -AclObject $acl
$actualAcl = Get-Acl -LiteralPath $destination
if (-not $actualAcl.AreAccessRulesProtected) { throw 'Private directory ACL verification failed.' }
$rules = $actualAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
if ($rules.Count -ne 2) { throw 'Private directory must have exactly the owner and SYSTEM access rules.' }
foreach ($rule in $rules) {
    $sid = $rule.IdentityReference.Value
    if ($rule.AccessControlType -eq 'Allow' -and $sid -notin @($identity.Value, $system.Value)) {
        throw 'Unexpected principal has access to the export directory.'
    }
}

$archive = Join-Path $destination 'application-public.dump'
$savedEnvironment = @{}
foreach ($name in @('PGSSLMODE', 'PGSSLROOTCERT', 'PGOPTIONS', 'PGPASSWORD', 'PGCONNECT_TIMEOUT')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$started = [DateTime]::UtcNow
try {
    $env:PGSSLMODE = 'verify-full'
    $env:PGSSLROOTCERT = $rootCertificate
    $env:PGCONNECT_TIMEOUT = '15'
    $env:PGOPTIONS = '-c default_transaction_read_only=on -c statement_timeout=120000'
    # Native hidden password prompt, with no secret in arguments/files/logs.
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Write-Host 'Enter the EXISTING Supabase database password at the hidden prompt.'
    Write-Host 'Do not reset it here. TLS validation failures must be investigated, not bypassed.'
    & $pgDump --host=aws-0-eu-west-1.pooler.supabase.com --port=5432 `
        --username=postgres.buwwsplrhsfgnkulhkpc --dbname=postgres --password `
        --format=custom --schema=public --strict-names --lock-wait-timeout=15s `
        --file=$archive
    if ($LASTEXITCODE -ne 0) {
        throw 'Export failed. Any partial archive is NOT a usable backup; do not share it.'
    }
    # Listing validates archive readability, not successful database restoration.
    & $pgRestore --list $archive > $null
    if ($LASTEXITCODE -ne 0) { throw 'Archive listing failed; backup acceptance remains open.' }
    $receipt = [ordered]@{
        project_ref = 'buwwsplrhsfgnkulhkpc'
        scope = 'public application schema only; NOT full Supabase recovery'
        started_at_utc = $started.ToString('o')
        finished_at_utc = [DateTime]::UtcNow.ToString('o')
        bytes = (Get-Item -LiteralPath $archive).Length
        sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
        tls_mode = 'verify-full'
        root_certificate_der_sha256 = $fingerprint
        archive_readable = $true
        isolated_restore_verified = $false
        excluded = @('global roles/passwords', 'managed schemas', 'Storage file contents',
            'platform configuration', 'Edge functions', 'migration history outside public',
            'dependencies in other schemas')
    }
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $destination 'receipt.json') -Encoding UTF8
    Write-Host ('Export created in: ' + $destination)
    Write-Host 'Restore is NOT verified. Keep this private; share only this directory path with Codex.'
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
