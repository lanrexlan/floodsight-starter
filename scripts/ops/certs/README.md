# Supabase server root certificate

This is a **public CA certificate**, not a private key or database credential.
Retrieved on 5 October 2026 from the Download certificate link in FloodSight's
authenticated Supabase Database Settings dashboard:

https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt

Certificate DER SHA-256:
`807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa`

The export helper checks that fingerprint and its validity window before use.
PEM newline normalization does not affect the DER fingerprint. The certificate
is scoped to this PostgreSQL connection; it is NOT installed in Windows trust
stores. Keep `verify-full` enabled so both chain and hostname are checked.

The pooler's TLS 1.3 handshake and hostname were verified using this certificate
without submitting database credentials. This is NOT an authenticated database
check, export or restore test. The installed PostgreSQL 18 client also passed the
TLS check and rejected an intentionally incorrect hostname without sending a
password. If Supabase rotates this CA, retrieve the replacement
from its authenticated dashboard over HTTPS and review/update the pin; do not
download an arbitrary server leaf and declare it trusted.

Provider instructions: https://supabase.com/docs/guides/database/psql
