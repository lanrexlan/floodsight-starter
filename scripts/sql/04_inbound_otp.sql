-- =============================================================================
-- FloodSight — P2 upgrades: all-clear alerts, inbound SMS, OTP subscriptions.
-- Run ONCE in Supabase SQL Editor after 03_logs.sql.
-- =============================================================================

-- 1. Allow 'All Clear' in alert_log (stand-down messages are deduplicated
--    per day exactly like Watch/Warning).
ALTER TABLE alert_log DROP CONSTRAINT IF EXISTS alert_log_alert_level_check;
ALTER TABLE alert_log
    ADD CONSTRAINT alert_log_alert_level_check
    CHECK (alert_level IN ('Watch', 'Warning', 'All Clear'));

-- 2. Pending OTP-confirmed subscriptions (REQUIRE_OTP=true flow).
--    One pending row per phone; confirmed rows are deleted after upsert
--    into subscribers.
CREATE TABLE IF NOT EXISTS pending_subscriptions (
    phone       TEXT PRIMARY KEY,              -- E.164
    code_hash   TEXT NOT NULL,                 -- sha256(code + phone)
    payload     JSONB NOT NULL,                -- lat/lon/name/area_name
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

ALTER TABLE pending_subscriptions ENABLE ROW LEVEL SECURITY;
