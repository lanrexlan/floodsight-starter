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
