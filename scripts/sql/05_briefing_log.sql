-- Migration 05: morning briefing idempotency log
--
-- Tracks each day's morning briefing send so the backup cron
-- (06:00 UTC) can detect that the primary run (05:00 UTC) already
-- succeeded and exit without sending a duplicate SMS.
--
-- Run once in the Supabase SQL editor or via the CLI:
--   supabase db push  (if using the local dev flow)

CREATE TABLE IF NOT EXISTS briefing_log (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sent_date        date        NOT NULL DEFAULT CURRENT_DATE,
    sent_at          timestamptz NOT NULL DEFAULT now(),
    recipient_count  int         NOT NULL DEFAULT 0,
    dry_run          boolean     NOT NULL DEFAULT false,

    -- One real (non-dry-run) send per calendar day in Lagos time
    CONSTRAINT briefing_log_unique_day UNIQUE (sent_date, dry_run)
        DEFERRABLE INITIALLY DEFERRED
);

-- Keep 90 days of history; older rows serve no operational purpose
CREATE INDEX IF NOT EXISTS briefing_log_sent_date_idx ON briefing_log (sent_date DESC);

COMMENT ON TABLE briefing_log IS
    'One row per morning briefing send. Used to prevent the backup cron '
    'from sending a duplicate when the primary GitHub Actions run succeeded.';
