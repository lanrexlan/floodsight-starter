-- Run after scripts/sql/01..06 and supabase/migrations/001..002.
-- Service-role only: public clients must never read reports or activity PII.
ALTER TABLE prediction_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE dispatch_cells ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON prediction_log, verifications, dispatch_cells FROM anon, authenticated;
ALTER VIEW alert_delivery_stats SET (security_invoker = true);

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
