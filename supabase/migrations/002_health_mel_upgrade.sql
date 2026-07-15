-- ============================================================
-- FloodSight Health — Migration 002: entomology validation +
-- operational MEL upgrade (NEXA PoC rework, July 2026).
--
-- Run ONCE in Supabase SQL Editor AFTER 001_health_layer.sql.
-- All statements are idempotent.
--
-- Purpose:
--   1. Add columns to health_alerts so operational KPIs (alert-to-action
--      time, anticipatory-action rate) can be computed per alert.
--   2. Expand mel_events event_type to include operational + entomology
--      verification events.
--   3. Add entomology_observations — the larval-survey table that TESTS
--      the flood -> Anopheles link (vs urban Culex) directly. The
--      Anopheles-positive fraction of flagged sites is a PRIMARY PoC
--      intermediary outcome.
-- ============================================================

-- 1. health_alerts: carry the risk tier + outbreak window on each alert
ALTER TABLE health_alerts
    ADD COLUMN IF NOT EXISTS risk_tier             text,
    ADD COLUMN IF NOT EXISTS outbreak_window_start date,
    ADD COLUMN IF NOT EXISTS outbreak_window_end   date;

-- 2. mel_events: allow operational + entomology verification event types.
--    (Drop and re-add the CHECK so the enum can grow.)
ALTER TABLE mel_events DROP CONSTRAINT IF EXISTS mel_events_event_type_check;
ALTER TABLE mel_events
    ADD CONSTRAINT mel_events_event_type_check CHECK (event_type IN (
        -- health-system actions
        'NETS_DISTRIBUTED',
        'RDT_KITS_PREPOSITIONED',
        'IRS_CONDUCTED',
        'COMMUNITY_SENSITIZATION',
        'CASE_MANAGEMENT_TRAINING',
        'STOCK_PREPOSITIONING',
        'LARVAL_SOURCE_MANAGEMENT',
        -- operational / verification events
        'ALERT_ACKNOWLEDGED',
        'LARVAL_SURVEY_CONDUCTED',
        'ANOPHELES_CONFIRMED',
        'CULEX_ONLY',
        'NO_LARVAE'
    ));

-- 3. Entomology observations — one row per larval-dip survey at a flagged site.
--    This is how the pilot answers the malaria-epidemiologist's key question:
--    does urban Lagos floodwater actually produce the MALARIA vector
--    (Anopheles gambiae s.l.), or mostly the nuisance vector (Culex)?
CREATE TABLE IF NOT EXISTS entomology_observations (
    id                     bigserial PRIMARY KEY,
    lga_name               text NOT NULL,
    ward                   text,
    lat                    double precision,
    lon                    double precision,
    survey_date            date NOT NULL,
    -- link back to the alert/window that flagged this site
    alert_id               bigint REFERENCES health_alerts(id),
    flood_event_id         text,
    days_since_flood       integer,
    -- habitat characterisation
    water_type             text CHECK (water_type IN (
                               'clean_temporary','turbid','polluted_drain',
                               'tidal','canal','other')),
    habitat_notes          text,
    -- larval dip results (WHO standard 350 ml dipper)
    dips_taken             integer,
    anopheles_larvae       integer DEFAULT 0,
    culex_larvae           integer DEFAULT 0,
    aedes_larvae           integer DEFAULT 0,
    anopheles_confirmed    boolean DEFAULT false,
    species_id_method      text,     -- 'morphological' | 'PCR' | 'field'
    surveyed_by            text,
    recorded_at            timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ento_lga_date
    ON entomology_observations (lga_name, survey_date DESC);
CREATE INDEX IF NOT EXISTS idx_ento_alert
    ON entomology_observations (alert_id);

-- RLS: entomology data is non-PII and dashboard-readable
ALTER TABLE entomology_observations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ento_public_read ON entomology_observations;
CREATE POLICY ento_public_read ON entomology_observations
    FOR SELECT USING (true);
