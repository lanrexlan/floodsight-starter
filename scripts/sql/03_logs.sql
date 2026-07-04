-- =============================================================================
-- FloodSight — Feedback-loop log tables (predictions, verifications,
-- dispatch cell snapshots).
--
-- Run ONCE in Supabase SQL Editor after 01_subscribers.sql / 02_ndpr_migration.sql.
--
-- Why: these logs previously lived in data/logs/*.jsonl on Render's
-- EPHEMERAL filesystem and were wiped on every deploy/restart — destroying
-- the Phase 6 recalibration feedback loop. Supabase persists them.
-- =============================================================================

-- 1. Every /depth/predict call (features + prediction)
CREATE TABLE IF NOT EXISTS prediction_log (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lat                DOUBLE PRECISION,
    lon                DOUBLE PRECISION,
    cell_id            TEXT,
    features           JSONB,
    predicted_depth_m  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS prediction_log_ts_idx ON prediction_log (ts DESC);

-- 2. Field verification reports (POST /verify)
CREATE TABLE IF NOT EXISTS verifications (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    verification_id    TEXT UNIQUE NOT NULL,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lat                DOUBLE PRECISION NOT NULL,
    lon                DOUBLE PRECISION NOT NULL,
    event_date         DATE NOT NULL,
    observed_flooded   BOOLEAN NOT NULL,
    observed_depth_m   DOUBLE PRECISION,
    reporter           TEXT,        -- PII: only exposed to authorized operators
    notes              TEXT
);
CREATE INDEX IF NOT EXISTS verifications_event_date_idx ON verifications (event_date);

-- 3. Snapshot of Watch/Warning grid cells at dispatch time.
--    Recalibration compares field verifications against THIS (what the
--    system dispatched), not against dashboard clicks in prediction_log.
CREATE TABLE IF NOT EXISTS dispatch_cells (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_date   DATE NOT NULL,
    cell_id      TEXT NOT NULL,
    lat          DOUBLE PRECISION NOT NULL,
    lon          DOUBLE PRECISION NOT NULL,
    alert_level  TEXT NOT NULL CHECK (alert_level IN ('Watch', 'Warning'))
);
-- One row per cell per day; hourly cron upserts against this
-- (last write wins — level reflects the most recent dispatch run that day).
CREATE UNIQUE INDEX IF NOT EXISTS dispatch_cells_event_cell_idx
    ON dispatch_cells (event_date, cell_id);
CREATE INDEX IF NOT EXISTS dispatch_cells_event_date_idx
    ON dispatch_cells (event_date);
