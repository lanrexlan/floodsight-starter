BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout='30s';
DO $fs_access_test$
DECLARE original_role text := current_user; client_role text; object_name text; fn_name text;
  denied integer:=0; server_reads integer:=0; fn_checks integer:=0; n bigint;
BEGIN
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
    EXECUTE format('SET LOCAL ROLE %I',client_role);
    FOREACH object_name IN ARRAY ARRAY['prediction_log','verifications','dispatch_cells','briefing_log','subscribers','pending_subscriptions','alert_log','chew_subscribers','health_alerts','chew_responses','mel_events','subscription_attempts','alert_claims','alert_delivery_stats'] LOOP
      BEGIN
        EXECUTE format('SELECT count(*) FROM public.%I',object_name) INTO n;
        RAISE EXCEPTION 'Unexpected effective read by % on %',client_role,object_name;
      EXCEPTION WHEN insufficient_privilege THEN denied := denied+1;
      END;
    END LOOP;
    FOREACH fn_name IN ARRAY ARRAY['public.consume_subscription_attempt(text,text)','public.consume_pending_subscription(text,text)','public.claim_alert(uuid,date,text)','public.release_schema_version()','public.cleanup_personal_data()','public.deactivate_stale_subscribers()'] LOOP
      IF has_function_privilege(current_user,fn_name,'EXECUTE') THEN
        RAISE EXCEPTION 'Unexpected client function permission: %',fn_name;
      END IF;
      fn_checks := fn_checks+1;
    END LOOP;
    EXECUTE format('SET LOCAL ROLE %I',original_role);
  END LOOP;
  SET LOCAL ROLE service_role;
  FOREACH object_name IN ARRAY ARRAY['prediction_log','verifications','dispatch_cells','briefing_log','subscribers','pending_subscriptions','alert_log','chew_subscribers','health_alerts','chew_responses','mel_events','subscription_attempts','alert_claims','alert_delivery_stats'] LOOP
    EXECUTE format('SELECT count(*) FROM public.%I',object_name) INTO n;
    server_reads := server_reads+1;
  END LOOP;
  FOREACH fn_name IN ARRAY ARRAY['public.consume_subscription_attempt(text,text)','public.consume_pending_subscription(text,text)','public.claim_alert(uuid,date,text)','public.release_schema_version()','public.cleanup_personal_data()','public.deactivate_stale_subscribers()'] LOOP
    IF NOT has_function_privilege(current_user,fn_name,'EXECUTE') THEN
      RAISE EXCEPTION 'Missing service function permission: %',fn_name;
    END IF;
    fn_checks := fn_checks+1;
  END LOOP;
  IF public.release_schema_version() <> 7 THEN RAISE EXCEPTION 'Wrong schema version'; END IF;
  EXECUTE format('SET LOCAL ROLE %I',original_role);
  PERFORM set_config('floodsight.access_receipt',jsonb_build_object(
    'actual_private_select_denials',denied,'actual_server_reads',server_reads,
    'function_role_permission_checks',fn_checks,'release_schema_version',7,
    'mutating_functions_invoked',false,'passed',true)::text,true);
END; $fs_access_test$;
SELECT current_setting('floodsight.access_receipt')::jsonb AS access_receipt;
ROLLBACK;
