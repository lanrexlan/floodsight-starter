-- =============================================================================
-- FloodSight Phase 16: Resident Alert Subscriptions
-- Run this once in your Supabase project's SQL Editor.
-- Dashboard → SQL Editor → New query → paste → Run
-- =============================================================================

-- Subscribers: one row per phone number
CREATE TABLE IF NOT EXISTS subscribers (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    name        TEXT,                          -- optional display name
    phone       TEXT        NOT NULL UNIQUE,   -- E.164 format, e.g. +2348012345678
    lat         DOUBLE PRECISION NOT NULL,     -- WGS84 latitude of their location
    lon         DOUBLE PRECISION NOT NULL,     -- WGS84 longitude of their location
    area_name   TEXT,                          -- human-readable (from reverse geocode)
    risk_class  TEXT,                          -- Low / Moderate / High / Very High
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    active      BOOLEAN     DEFAULT TRUE       -- set FALSE to unsubscribe
);

-- Alert log: one row per (subscriber × calendar day × alert level)
-- Prevents sending the same alert twice in a day.
-- If alert escalates from Watch → Warning on the same day, a new row is written.
CREATE TABLE IF NOT EXISTS alert_log (
    id            UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    subscriber_id UUID        NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    alert_level   TEXT        NOT NULL CHECK (alert_level IN ('Watch', 'Warning')),
    sent_at       TIMESTAMPTZ DEFAULT NOW(),
    event_date    DATE        NOT NULL         -- Lagos local date (UTC+1)
);

-- Dedup index: one Watch and one Warning per subscriber per calendar day
CREATE UNIQUE INDEX IF NOT EXISTS alert_log_unique_day
    ON alert_log (subscriber_id, event_date, alert_level);

-- Optional: index for fast active subscriber lookup
CREATE INDEX IF NOT EXISTS subscribers_active_idx
    ON subscribers (active) WHERE active = TRUE;

-- =============================================================================
-- Row Level Security (RLS) — recommended for production
-- The API uses the service-role key (bypasses RLS) so RLS just prevents
-- direct anon-key access to subscriber PII.
-- =============================================================================
ALTER TABLE subscribers  ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_log    ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (your API key does this by default)
-- No anon / authenticated policies needed since the public never reads these tables directly.
