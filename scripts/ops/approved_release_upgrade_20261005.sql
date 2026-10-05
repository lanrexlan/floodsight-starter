-- Approved, one-time live upgrade. Existing columns/records must be preserved.
-- No baseline replay, consent backfill, SMS, cleanup invocation or scheduling.
-- A single DO statement is atomic; no explicit COMMIT can split its changes.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL TIME ZONE 'UTC';
DO $fs_atomic_upgrade$
DECLARE g record; observed_rows bigint; observed_md5 text; private_name text; client_role text;
BEGIN
  PERFORM set_config('search_path', 'public,pg_catalog', true);
  LOCK TABLE public."alert_log", public."briefing_log", public."chew_responses", public."chew_subscribers", public."dhis2_malaria_cases", public."dispatch_cells", public."entomology_observations", public."health_alerts", public."lga_health_risk", public."mel_events", public."pending_subscriptions", public."prediction_log", public."subscribers", public."verifications" IN SHARE ROW EXCLUSIVE MODE;
  FOR g IN SELECT * FROM jsonb_to_recordset($fs_guard_data$[{"name":"alert_log","columns":"\"id\",\"subscriber_id\",\"alert_level\",\"sent_at\",\"event_date\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"briefing_log","columns":"\"id\",\"sent_date\",\"sent_at\",\"recipient_count\",\"dry_run\"","rows":83,"content_md5":"4e52b6a6fd8250f26ddaa6c7bc6af63f"},{"name":"chew_responses","columns":"\"id\",\"phone\",\"chew_id\",\"raw_message\",\"parsed_action\",\"cases_reported\",\"lga_name\",\"received_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"chew_subscribers","columns":"\"id\",\"phone\",\"name\",\"lga_name\",\"facility_name\",\"role\",\"ward\",\"active\",\"enrolled_at\",\"enrolled_by\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"dhis2_malaria_cases","columns":"\"id\",\"lga_name\",\"period\",\"confirmed_cases\",\"suspected_cases\",\"rdt_positive\",\"treatment_started\",\"data_element_id\",\"org_unit_id\",\"pulled_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"dispatch_cells","columns":"\"id\",\"created_at\",\"event_date\",\"cell_id\",\"lat\",\"lon\",\"alert_level\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"entomology_observations","columns":"\"id\",\"lga_name\",\"ward\",\"lat\",\"lon\",\"survey_date\",\"alert_id\",\"flood_event_id\",\"days_since_flood\",\"water_type\",\"habitat_notes\",\"dips_taken\",\"anopheles_larvae\",\"culex_larvae\",\"aedes_larvae\",\"anopheles_confirmed\",\"species_id_method\",\"surveyed_by\",\"recorded_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"health_alerts","columns":"\"id\",\"chew_id\",\"lga_health_risk_id\",\"lga_name\",\"phone\",\"message_text\",\"at_message_id\",\"at_status\",\"at_cost\",\"sent_at\",\"delivered_at\",\"idempotency_key\",\"risk_tier\",\"outbreak_window_start\",\"outbreak_window_end\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"lga_health_risk","columns":"\"id\",\"lga_name\",\"computed_at\",\"flood_event_id\",\"inundation_area_km2\",\"peak_susceptibility\",\"temp_celsius\",\"breeding_lag_days\",\"outbreak_window_start\",\"outbreak_window_end\",\"outbreak_probability\",\"risk_tier\",\"alert_sent\",\"alert_sent_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"mel_events","columns":"\"id\",\"lga_name\",\"event_type\",\"quantity\",\"unit\",\"reported_by\",\"facility_name\",\"ward\",\"event_date\",\"notes\",\"alert_id\",\"recorded_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"pending_subscriptions","columns":"\"phone\",\"code_hash\",\"payload\",\"attempts\",\"created_at\",\"expires_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"prediction_log","columns":"\"id\",\"ts\",\"lat\",\"lon\",\"cell_id\",\"features\",\"predicted_depth_m\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"subscribers","columns":"\"id\",\"name\",\"phone\",\"lat\",\"lon\",\"area_name\",\"risk_class\",\"created_at\",\"active\",\"consent_at\"","rows":2,"content_md5":"ffefc6981cc94d176b6371beafde3262"},{"name":"verifications","columns":"\"id\",\"verification_id\",\"ts\",\"lat\",\"lon\",\"event_date\",\"observed_flooded\",\"observed_depth_m\",\"reporter\",\"notes\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"}]$fs_guard_data$::jsonb) AS x(name text, columns text, rows bigint, content_md5 text)
LOOP
  EXECUTE format('SELECT count(*), md5(coalesce(string_agg(md5(to_jsonb(r)::text), '','' ORDER BY md5(to_jsonb(r)::text)), '''')) FROM (SELECT %s FROM public.%I) r', g.columns, g.name)
    INTO observed_rows, observed_md5;
  IF observed_rows IS DISTINCT FROM g.rows OR observed_md5 IS DISTINCT FROM g.content_md5 THEN
    RAISE EXCEPTION 'Original-record preservation guard failed for %', g.name;
  END IF;
END LOOP;
  EXECUTE $fs_upgrade06$
-- =============================================================================
-- FloodSight — Africa's Talking delivery reports for resident alerts.
--
-- Run after scripts/sql/01..05 and supabase/migrations/001..002.
--
-- Why
-- ---
-- alert_log recorded only that an SMS was HANDED TO the gateway. "Submitted to
-- Africa's Talking" and "arrived on the handset" are different events, and on
-- Nigerian mobile networks the gap between them is material — handsets are off,
-- out of coverage, or the number has been recycled.
--
-- Without delivery reports the operator dashboard could report a delivery rate
-- only from synthetic fallback data, and the pilot had no defensible way to
-- state what fraction of residents actually received a warning. For a
-- life-safety system that number is the headline metric, and for the UNICEF
-- PoC it is reportable evidence, so it needs to come from measurement rather
-- than assumption.
--
-- Africa's Talking POSTs a delivery report per message to a callback URL once
-- the network reports a final state. These columns store that callback.
-- =============================================================================

-- 1. Delivery-tracking columns on alert_log ---------------------------------

ALTER TABLE alert_log
    ADD COLUMN IF NOT EXISTS at_message_id   TEXT,
    ADD COLUMN IF NOT EXISTS at_status       TEXT,
    ADD COLUMN IF NOT EXISTS at_cost         TEXT,
    ADD COLUMN IF NOT EXISTS delivered_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failure_reason  TEXT;

COMMENT ON COLUMN alert_log.at_message_id  IS
    'Africa''s Talking messageId returned at submission. Correlation key for delivery reports.';
COMMENT ON COLUMN alert_log.at_status      IS
    'Latest AT status: Sent/Submitted at handoff, then Success/Failed/Rejected from the delivery report.';
COMMENT ON COLUMN alert_log.delivered_at   IS
    'Timestamp of the delivery report confirming handset receipt. NULL until confirmed.';
COMMENT ON COLUMN alert_log.failure_reason IS
    'AT failureReason for non-delivery, e.g. UserInBlackList, InsufficientCredit, UserDoesNotExist.';

-- messageId is the lookup key for every incoming delivery report.
CREATE UNIQUE INDEX IF NOT EXISTS alert_log_at_message_id_idx
    ON alert_log (at_message_id)
    WHERE at_message_id IS NOT NULL;

-- Dashboard queries filter on delivery state.
CREATE INDEX IF NOT EXISTS alert_log_at_status_idx
    ON alert_log (at_status)
    WHERE at_status IS NOT NULL;


-- 2. Same treatment for CHEW health alerts ----------------------------------
-- health_alerts already stores at_message_id / at_status / at_cost from
-- migration 001, but had nowhere to record the delivery outcome.

ALTER TABLE health_alerts
    ADD COLUMN IF NOT EXISTS delivered_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failure_reason TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS health_alerts_at_message_id_idx
    ON health_alerts (at_message_id)
    WHERE at_message_id IS NOT NULL;


-- 3. Delivery-rate view for the operator dashboard --------------------------
-- Counts only messages we can actually adjudicate: a message with no delivery
-- report yet is 'pending', and is excluded from the rate rather than being
-- silently counted as a failure (which would understate performance during
-- the reporting lag) or as a success (which would overstate it).

CREATE OR REPLACE VIEW alert_delivery_stats AS
SELECT
    event_date,
    alert_level,
    COUNT(*)                                                   AS submitted,
    COUNT(*) FILTER (WHERE delivered_at IS NOT NULL)           AS delivered,
    COUNT(*) FILTER (WHERE at_status IN ('Failed', 'Rejected')) AS failed,
    COUNT(*) FILTER (WHERE delivered_at IS NULL
                       AND COALESCE(at_status, '') NOT IN ('Failed', 'Rejected')) AS pending,
    ROUND(
        COUNT(*) FILTER (WHERE delivered_at IS NOT NULL)::numeric
        / NULLIF(COUNT(*) FILTER (
              WHERE delivered_at IS NOT NULL
                 OR at_status IN ('Failed', 'Rejected')
          ), 0),
        4
    ) AS delivery_rate
FROM alert_log
GROUP BY event_date, alert_level
ORDER BY event_date DESC, alert_level;

COMMENT ON VIEW alert_delivery_stats IS
    'Per-day, per-level SMS delivery outcomes. delivery_rate is computed over '
    'adjudicated messages only (delivered + failed); pending messages are '
    'excluded so the rate is not distorted by delivery-report lag.';
$fs_upgrade06$;
  EXECUTE $fs_upgrade07$
-- Run after scripts/sql/01..06 and supabase/migrations/001..002.
-- Service-role only: public clients must never read reports or activity PII.
ALTER TABLE prediction_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE dispatch_cells ENABLE ROW LEVEL SECURITY;
ALTER TABLE briefing_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON prediction_log, verifications, dispatch_cells, briefing_log,
    subscribers, pending_subscriptions, alert_log,
    chew_subscribers, health_alerts, chew_responses, mel_events FROM PUBLIC, anon, authenticated;
GRANT ALL ON prediction_log, verifications, dispatch_cells, briefing_log,
    subscribers, pending_subscriptions, alert_log,
    chew_subscribers, health_alerts, chew_responses, mel_events TO service_role;
ALTER VIEW alert_delivery_stats SET (security_invoker = true);
REVOKE ALL ON alert_delivery_stats FROM PUBLIC, anon, authenticated;
GRANT SELECT ON alert_delivery_stats TO service_role;

-- Harden the pre-release privileged function without running it or changing
-- subscribers. Absence of a flood warning is not withdrawal of consent.
ALTER FUNCTION deactivate_stale_subscribers() SET search_path = public;
REVOKE EXECUTE ON FUNCTION deactivate_stale_subscribers() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION deactivate_stale_subscribers() TO service_role;

-- Also repair policies on databases where health migration 001 already ran.
DROP POLICY IF EXISTS "service only chew_subscribers" ON chew_subscribers;
DROP POLICY IF EXISTS "service only health_alerts" ON health_alerts;
DROP POLICY IF EXISTS "service only chew_responses" ON chew_responses;
DROP POLICY IF EXISTS "service only mel_events" ON mel_events;
CREATE POLICY "service only chew_subscribers" ON chew_subscribers TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service only health_alerts" ON health_alerts TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service only chew_responses" ON chew_responses TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service only mel_events" ON mel_events TO service_role USING (true) WITH CHECK (true);

-- Shared, atomic limits survive restarts and serialize concurrent requests.
CREATE TABLE IF NOT EXISTS subscription_attempts (
    key TEXT PRIMARY KEY, starts_at TIMESTAMPTZ NOT NULL, attempts INTEGER NOT NULL
);
ALTER TABLE subscription_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON subscription_attempts FROM anon, authenticated;

CREATE OR REPLACE FUNCTION consume_subscription_attempt(phone_key TEXT, ip_key TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE p subscription_attempts; i subscription_attempts;
BEGIN
    PERFORM pg_advisory_xact_lock(72419831);
    DELETE FROM subscription_attempts WHERE starts_at < now() - interval '1 day';
    INSERT INTO subscription_attempts VALUES ('phone:' || phone_key, now(), 0) ON CONFLICT DO NOTHING;
    INSERT INTO subscription_attempts VALUES ('ip:' || ip_key, now(), 0) ON CONFLICT DO NOTHING;
    UPDATE subscription_attempts SET starts_at=now(), attempts=0
      WHERE key='phone:' || phone_key AND starts_at < now() - interval '10 minutes';
    UPDATE subscription_attempts SET starts_at=now(), attempts=0
      WHERE key='ip:' || ip_key AND starts_at < now() - interval '1 minute';
    SELECT * INTO p FROM subscription_attempts WHERE key='phone:' || phone_key;
    SELECT * INTO i FROM subscription_attempts WHERE key='ip:' || ip_key;
    IF p.attempts >= 8 OR i.attempts >= 15 THEN RETURN false; END IF;
    UPDATE subscription_attempts SET attempts=attempts+1 WHERE key IN ('phone:' || phone_key, 'ip:' || ip_key);
    RETURN true;
END; $$;
REVOKE EXECUTE ON FUNCTION consume_subscription_attempt(TEXT,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION consume_subscription_attempt(TEXT,TEXT) TO service_role;

-- Atomically validate one OTP. Concurrent submissions cannot use a code twice.
CREATE OR REPLACE FUNCTION consume_pending_subscription(p_phone TEXT, p_hash TEXT)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE p pending_subscriptions; saved subscribers;
BEGIN
    SELECT * INTO p FROM pending_subscriptions WHERE phone=p_phone FOR UPDATE;
    IF NOT FOUND THEN RETURN jsonb_build_object('status','not_found'); END IF;
    IF p.expires_at < now() THEN
        DELETE FROM pending_subscriptions WHERE phone=p_phone;
        RETURN jsonb_build_object('status','expired');
    END IF;
    IF p.attempts >= 5 THEN RETURN jsonb_build_object('status','limited'); END IF;
    IF p.code_hash <> p_hash THEN
        UPDATE pending_subscriptions SET attempts=attempts+1 WHERE phone=p_phone;
        RETURN jsonb_build_object('status','wrong');
    END IF;
    INSERT INTO subscribers(phone,lat,lon,name,area_name,risk_class,consent_at,active)
    VALUES(p_phone, (p.payload->>'lat')::double precision, (p.payload->>'lon')::double precision,
           p.payload->>'name', p.payload->>'area_name', p.payload->>'risk_class', now(), true)
    ON CONFLICT(phone) DO UPDATE SET lat=excluded.lat,lon=excluded.lon,name=excluded.name,
       area_name=excluded.area_name,risk_class=excluded.risk_class,consent_at=excluded.consent_at,active=true
    RETURNING * INTO saved;
    DELETE FROM pending_subscriptions WHERE phone=p_phone;
    RETURN jsonb_build_object('status','confirmed','subscriber',row_to_json(saved));
END; $$;
REVOKE EXECUTE ON FUNCTION consume_pending_subscription(TEXT,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION consume_pending_subscription(TEXT,TEXT) TO service_role;

-- Reserve BEFORE contacting the SMS provider. An ambiguous timeout keeps its
-- reservation for manual review: automatic retry could send a duplicate SMS.
CREATE TABLE IF NOT EXISTS alert_claims (
    subscriber_id UUID REFERENCES subscribers(id) ON DELETE CASCADE,
    event_date DATE NOT NULL, alert_level TEXT NOT NULL,
    reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subscriber_id,event_date,alert_level)
);
ALTER TABLE alert_claims ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON alert_claims FROM anon, authenticated;
CREATE OR REPLACE FUNCTION claim_alert(p_subscriber UUID, p_date DATE, p_level TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE inserted_rows INTEGER;
BEGIN
    INSERT INTO alert_claims(subscriber_id,event_date,alert_level)
      VALUES(p_subscriber,p_date,p_level) ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS inserted_rows=ROW_COUNT;
    RETURN inserted_rows=1;
END; $$;
REVOKE EXECUTE ON FUNCTION claim_alert(UUID,DATE,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION claim_alert(UUID,DATE,TEXT) TO service_role;

CREATE OR REPLACE FUNCTION release_schema_version() RETURNS INTEGER
LANGUAGE sql SET search_path=public AS $$ SELECT 7; $$;
REVOKE EXECUTE ON FUNCTION release_schema_version() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION release_schema_version() TO service_role;

-- Mark opt-out time; do not infer inactivity from absence of severe weather.
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
CREATE OR REPLACE FUNCTION mark_deactivation() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
    IF NEW.active THEN NEW.deactivated_at = NULL;
    ELSIF OLD.active IS DISTINCT FROM NEW.active OR NEW.deactivated_at IS NULL THEN NEW.deactivated_at=now();
    END IF;
    RETURN NEW;
END; $$;
DROP TRIGGER IF EXISTS subscriber_deactivation ON subscribers;
CREATE TRIGGER subscriber_deactivation BEFORE UPDATE ON subscribers
FOR EACH ROW EXECUTE FUNCTION mark_deactivation();
UPDATE subscribers SET deactivated_at=now() WHERE NOT active AND deactivated_at IS NULL;

CREATE OR REPLACE FUNCTION cleanup_personal_data() RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    DELETE FROM pending_subscriptions WHERE expires_at < now();
    DELETE FROM subscription_attempts WHERE starts_at < now() - interval '1 day';
    DELETE FROM subscribers WHERE NOT active AND deactivated_at < now() - interval '30 days';
    DELETE FROM prediction_log WHERE ts < now() - interval '90 days';
    DELETE FROM verifications WHERE ts < now() - interval '24 months';
    DELETE FROM alert_log WHERE sent_at < now() - interval '24 months';
    DELETE FROM dispatch_cells WHERE created_at < now() - interval '24 months';
    DELETE FROM alert_claims WHERE reserved_at < now() - interval '24 months';
END; $$;
REVOKE EXECUTE ON FUNCTION cleanup_personal_data() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION cleanup_personal_data() TO service_role;
-- Enable pg_cron in Supabase, then schedule daily (do not schedule duplicates):
-- SELECT cron.schedule('floodsight-retention', '0 2 * * *', $$SELECT cleanup_personal_data();$$);
$fs_upgrade07$;
  FOR g IN SELECT * FROM jsonb_to_recordset($fs_guard_data$[{"name":"alert_log","columns":"\"id\",\"subscriber_id\",\"alert_level\",\"sent_at\",\"event_date\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"briefing_log","columns":"\"id\",\"sent_date\",\"sent_at\",\"recipient_count\",\"dry_run\"","rows":83,"content_md5":"4e52b6a6fd8250f26ddaa6c7bc6af63f"},{"name":"chew_responses","columns":"\"id\",\"phone\",\"chew_id\",\"raw_message\",\"parsed_action\",\"cases_reported\",\"lga_name\",\"received_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"chew_subscribers","columns":"\"id\",\"phone\",\"name\",\"lga_name\",\"facility_name\",\"role\",\"ward\",\"active\",\"enrolled_at\",\"enrolled_by\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"dhis2_malaria_cases","columns":"\"id\",\"lga_name\",\"period\",\"confirmed_cases\",\"suspected_cases\",\"rdt_positive\",\"treatment_started\",\"data_element_id\",\"org_unit_id\",\"pulled_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"dispatch_cells","columns":"\"id\",\"created_at\",\"event_date\",\"cell_id\",\"lat\",\"lon\",\"alert_level\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"entomology_observations","columns":"\"id\",\"lga_name\",\"ward\",\"lat\",\"lon\",\"survey_date\",\"alert_id\",\"flood_event_id\",\"days_since_flood\",\"water_type\",\"habitat_notes\",\"dips_taken\",\"anopheles_larvae\",\"culex_larvae\",\"aedes_larvae\",\"anopheles_confirmed\",\"species_id_method\",\"surveyed_by\",\"recorded_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"health_alerts","columns":"\"id\",\"chew_id\",\"lga_health_risk_id\",\"lga_name\",\"phone\",\"message_text\",\"at_message_id\",\"at_status\",\"at_cost\",\"sent_at\",\"delivered_at\",\"idempotency_key\",\"risk_tier\",\"outbreak_window_start\",\"outbreak_window_end\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"lga_health_risk","columns":"\"id\",\"lga_name\",\"computed_at\",\"flood_event_id\",\"inundation_area_km2\",\"peak_susceptibility\",\"temp_celsius\",\"breeding_lag_days\",\"outbreak_window_start\",\"outbreak_window_end\",\"outbreak_probability\",\"risk_tier\",\"alert_sent\",\"alert_sent_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"mel_events","columns":"\"id\",\"lga_name\",\"event_type\",\"quantity\",\"unit\",\"reported_by\",\"facility_name\",\"ward\",\"event_date\",\"notes\",\"alert_id\",\"recorded_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"pending_subscriptions","columns":"\"phone\",\"code_hash\",\"payload\",\"attempts\",\"created_at\",\"expires_at\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"prediction_log","columns":"\"id\",\"ts\",\"lat\",\"lon\",\"cell_id\",\"features\",\"predicted_depth_m\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"},{"name":"subscribers","columns":"\"id\",\"name\",\"phone\",\"lat\",\"lon\",\"area_name\",\"risk_class\",\"created_at\",\"active\",\"consent_at\"","rows":2,"content_md5":"ffefc6981cc94d176b6371beafde3262"},{"name":"verifications","columns":"\"id\",\"verification_id\",\"ts\",\"lat\",\"lon\",\"event_date\",\"observed_flooded\",\"observed_depth_m\",\"reporter\",\"notes\"","rows":0,"content_md5":"d41d8cd98f00b204e9800998ecf8427e"}]$fs_guard_data$::jsonb) AS x(name text, columns text, rows bigint, content_md5 text)
LOOP
  EXECUTE format('SELECT count(*), md5(coalesce(string_agg(md5(to_jsonb(r)::text), '','' ORDER BY md5(to_jsonb(r)::text)), '''')) FROM (SELECT %s FROM public.%I) r', g.columns, g.name)
    INTO observed_rows, observed_md5;
  IF observed_rows IS DISTINCT FROM g.rows OR observed_md5 IS DISTINCT FROM g.content_md5 THEN
    RAISE EXCEPTION 'Original-record preservation guard failed for %', g.name;
  END IF;
END LOOP;
  IF public.release_schema_version() <> 7 THEN
    RAISE EXCEPTION 'Release schema verification failed';
  END IF;
  FOREACH private_name IN ARRAY ARRAY['prediction_log','verifications','dispatch_cells','briefing_log','subscribers','pending_subscriptions','alert_log','chew_subscribers','health_alerts','chew_responses','mel_events','subscription_attempts','alert_claims','alert_delivery_stats']
  LOOP
    FOREACH client_role IN ARRAY ARRAY['anon','authenticated']
    LOOP
      IF has_table_privilege(client_role, 'public.' || quote_ident(private_name),
          'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN
        RAISE EXCEPTION 'Unexpected private access for % on %', client_role, private_name;
      END IF;
    END LOOP;
    IF NOT has_table_privilege('service_role', 'public.' || quote_ident(private_name), 'SELECT') THEN
      RAISE EXCEPTION 'Server SELECT access missing on %', private_name;
    END IF;
  END LOOP;
END;
$fs_atomic_upgrade$;
