-- =============================================================================
-- FloodSight Phase 18 Track 5: NDPR Compliance Migration
-- Run ONCE in Supabase SQL Editor after 01_subscribers.sql has been applied.
-- Dashboard → SQL Editor → New query → paste → Run
-- =============================================================================

-- 1. Add consent_at column to record when explicit NDPR consent was given
--    (back-fills existing rows with their created_at timestamp — they implicitly
--    consented by subscribing and we cannot retroactively re-request consent
--    for a pilot-scale subscriber base)
ALTER TABLE subscribers
    ADD COLUMN IF NOT EXISTS consent_at TIMESTAMPTZ DEFAULT NOW();

UPDATE subscribers
    SET consent_at = created_at
    WHERE consent_at IS NULL;

-- 2. Index for efficient retention policy lookups
CREATE INDEX IF NOT EXISTS subscribers_consent_at_idx
    ON subscribers (consent_at);


-- =============================================================================
-- RETENTION POLICY
-- =============================================================================
-- Deactivate subscribers who have been inactive for 12+ consecutive months.
-- "Inactive" = no alert has been sent to them in the last 12 months.
-- Newly subscribed accounts within 12 months are never deactivated.
--
-- This function is designed to be called monthly by a Supabase scheduled job
-- (Database → Extensions → pg_cron) or from an external cron hitting the
-- Supabase API.
-- =============================================================================

CREATE OR REPLACE FUNCTION deactivate_stale_subscribers()
RETURNS TABLE(deactivated_count INTEGER) AS $$
DECLARE
    _count INTEGER;
BEGIN
    UPDATE subscribers
    SET    active = FALSE
    WHERE  active = TRUE
      -- Account is older than 12 months
      AND  created_at < NOW() - INTERVAL '12 months'
      -- No alerts sent in the last 12 months
      AND  id NOT IN (
               SELECT DISTINCT subscriber_id
               FROM   alert_log
               WHERE  sent_at > NOW() - INTERVAL '12 months'
           );

    GET DIAGNOSTICS _count = ROW_COUNT;
    deactivated_count := _count;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Test the function returns cleanly (won't deactivate anything in a fresh db)
-- SELECT * FROM deactivate_stale_subscribers();


-- =============================================================================
-- OPTIONAL: Schedule via pg_cron (run on the 1st of each month at 02:00 UTC)
-- Only enable this if you have activated the pg_cron extension in Supabase:
--   Database → Extensions → pg_cron → Enable
-- =============================================================================

-- SELECT cron.schedule(
--     'monthly-ndpr-cleanup',
--     '0 2 1 * *',
--     $$SELECT deactivate_stale_subscribers()$$
-- );


-- =============================================================================
-- REFERENCE: what the full subscribers table looks like after this migration
-- =============================================================================
--
--  Column       | Type             | Notes
--  -------------|------------------|-------------------------------------------
--  id           | UUID             | primary key
--  name         | TEXT             | optional
--  phone        | TEXT (UNIQUE)    | E.164 format
--  lat          | DOUBLE PRECISION |
--  lon          | DOUBLE PRECISION |
--  area_name    | TEXT             | optional
--  risk_class   | TEXT             | Low / Moderate / High / Very High
--  created_at   | TIMESTAMPTZ      | subscription date
--  consent_at   | TIMESTAMPTZ      | ← NEW: NDPR explicit consent timestamp
--  active       | BOOLEAN          | FALSE = unsubscribed / stale
-- =============================================================================
