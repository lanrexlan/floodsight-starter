-- Read-only application-schema restore comparison. Never applies migrations,
-- activates messaging, changes permissions or invokes maintenance functions.
-- Run with a privileged operator connection on source and isolated restored
-- target. Capture a matching source snapshot at the backup's snapshot time;
-- a later preflight inventory is NOT proof that a backup contains these rows.
-- Counts and whole-table checksums only: no individual phone/location/OTP rows.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL TIME ZONE 'UTC';

WITH table_data AS (
  SELECT t.tablename, t.rowsecurity,
         query_to_xml(format(
           'SELECT count(*) AS row_count, '
           'md5(coalesce(string_agg(md5(to_jsonb(r)::text), '','' '
           'ORDER BY md5(to_jsonb(r)::text)), '''')) AS content_md5 '
           'FROM %I.%I r', t.schemaname, t.tablename),
           false, true, '') AS checks
  FROM pg_tables t WHERE t.schemaname = 'public'
)
SELECT jsonb_build_object(
  'scope', 'public application schema; not a full Supabase project backup',
  'database', current_database(),
  'postgres_version', current_setting('server_version'),
  'captured_at', current_timestamp,
  'tables', (SELECT jsonb_agg(jsonb_build_object(
    'name', tablename, 'rls', rowsecurity,
    'rows', (xpath('/row/row_count/text()', checks))[1]::text::bigint,
    'content_md5', (xpath('/row/content_md5/text()', checks))[1]::text
  ) ORDER BY tablename) FROM table_data),
  'columns', (SELECT jsonb_agg(jsonb_build_object(
    'table', table_name, 'column', column_name, 'ordinal', ordinal_position,
    'type', udt_schema || '.' || udt_name, 'nullable', is_nullable,
    'default', column_default, 'identity', is_identity, 'generated', is_generated
  ) ORDER BY table_name, ordinal_position)
  FROM information_schema.columns WHERE table_schema = 'public'),
  'constraints', (SELECT jsonb_agg(jsonb_build_object(
    'table', c.relname, 'name', k.conname, 'kind', k.contype,
    'definition', pg_get_constraintdef(k.oid), 'validated', k.convalidated
  ) ORDER BY c.relname, k.conname)
  FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public'),
  'indexes', (SELECT jsonb_agg(jsonb_build_object(
    'table', tablename, 'name', indexname, 'definition', indexdef
  ) ORDER BY tablename, indexname) FROM pg_indexes WHERE schemaname = 'public'),
  'sequences', (SELECT jsonb_agg(jsonb_build_object(
    'name', sequencename, 'owner', sequenceowner, 'type', data_type::text,
    -- Encode 64-bit values as strings: JSON/JavaScript would round bigint limits.
    'start', start_value::text, 'minimum', min_value::text, 'maximum', max_value::text,
    'increment', increment_by::text, 'cycle', cycle, 'cache', cache_size::text,
    'last_value', last_value::text
  ) ORDER BY sequencename) FROM pg_sequences WHERE schemaname = 'public'),
  'triggers', (SELECT jsonb_agg(jsonb_build_object(
    'table', c.relname, 'name', t.tgname, 'enabled', t.tgenabled,
    'definition', pg_get_triggerdef(t.oid)
  ) ORDER BY c.relname, t.tgname)
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND NOT t.tgisinternal),
  'views', (SELECT jsonb_agg(jsonb_build_object(
    'name', viewname, 'owner', viewowner, 'definition', definition
  ) ORDER BY viewname) FROM pg_views WHERE schemaname = 'public'),
  'schema_acl', (SELECT nspacl::text FROM pg_namespace WHERE nspname = 'public'),
  'role_flags', (SELECT jsonb_agg(jsonb_build_object(
    'name', rolname, 'login', rolcanlogin, 'bypass_rls', rolbypassrls
  ) ORDER BY rolname) FROM pg_roles
  WHERE rolname IN ('anon', 'authenticated', 'service_role')),
  'policies', (SELECT jsonb_agg(jsonb_build_object(
    'table', tablename, 'name', policyname, 'roles', roles,
    'command', cmd, 'using', qual, 'with_check', with_check
  ) ORDER BY tablename, policyname) FROM pg_policies WHERE schemaname = 'public'),
  'table_grants', (SELECT jsonb_agg(jsonb_build_object(
    'table', table_name, 'role', grantee, 'privilege', privilege_type
  ) ORDER BY table_name, grantee, privilege_type)
  FROM information_schema.table_privileges WHERE table_schema = 'public'),
  'functions', (SELECT jsonb_agg(jsonb_build_object(
    'name', p.proname, 'arguments', pg_get_function_identity_arguments(p.oid),
    'definition_md5', md5(pg_get_functiondef(p.oid)),
    'security_definer', p.prosecdef, 'configuration', p.proconfig,
    'anon_execute', has_function_privilege('anon', p.oid, 'EXECUTE'),
    'authenticated_execute', has_function_privilege('authenticated', p.oid, 'EXECUTE'),
    'service_role_execute', has_function_privilege('service_role', p.oid, 'EXECUTE')
  ) ORDER BY p.proname, pg_get_function_identity_arguments(p.oid))
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.prokind = 'f')
) AS restore_inventory;

COMMIT;
