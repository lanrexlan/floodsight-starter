-- FloodSight Health Intelligence Layer — Supabase Migrations
-- Run these in order in Supabase SQL Editor (or via supabase db push).
-- Each block is idempotent — safe to re-run.

-- ============================================================
-- 001: LGA health risk scores (daily outbreak probability)
-- ============================================================
CREATE TABLE IF NOT EXISTS lga_health_risk (
    id                    bigserial PRIMARY KEY,
    lga_name              text NOT NULL,
    computed_at           timestamptz NOT NULL DEFAULT now(),
    flood_event_id        text,
    inundation_area_km2   numeric(8,3),
    peak_susceptibility   numeric(6,4),
    temp_celsius          numeric(5,2),
    breeding_lag_days     integer,
    outbreak_window_start date,
    outbreak_window_end   date,
    outbreak_probability  numeric(5,4),
    risk_tier             text CHECK (risk_tier IN ('Low','Moderate','High','Critical')),
    alert_sent            boolean DEFAULT false,
    alert_sent_at         timestamptz
);

CREATE INDEX IF NOT EXISTS idx_lga_health_risk_lga  ON lga_health_risk (lga_name);
CREATE INDEX IF NOT EXISTS idx_lga_health_risk_date ON lga_health_risk (computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_lga_health_risk_win  ON lga_health_risk (outbreak_window_start);

-- ============================================================
-- 002: CHEW subscriber registry
-- ============================================================
CREATE TABLE IF NOT EXISTS chew_subscribers (
    id             bigserial PRIMARY KEY,
    phone          text UNIQUE NOT NULL,
    name           text,
    lga_name       text NOT NULL,
    facility_name  text,
    role           text DEFAULT 'CHEW'
                   CHECK (role IN ('CHEW','PHC_MANAGER','LGA_OFFICER','SPHCDA')),
    ward           text,
    active         boolean DEFAULT true,
    enrolled_at    timestamptz DEFAULT now(),
    enrolled_by    text
);

CREATE INDEX IF NOT EXISTS idx_chew_lga ON chew_subscribers (lga_name)
    WHERE active = true;

-- ============================================================
-- 003: Health alert log (one row per SMS sent to a CHEW)
-- ============================================================
CREATE TABLE IF NOT EXISTS health_alerts (
    id                   bigserial PRIMARY KEY,
    chew_id              bigint REFERENCES chew_subscribers(id),
    lga_health_risk_id   bigint REFERENCES lga_health_risk(id),
    lga_name             text NOT NULL,
    phone                text NOT NULL,
    message_text         text NOT NULL,
    at_message_id        text,
    at_status            text,
    at_cost              text,
    sent_at              timestamptz DEFAULT now(),
    delivered_at         timestamptz,
    idempotency_key      text UNIQUE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_health_alerts_chew ON health_alerts (chew_id);
CREATE INDEX IF NOT EXISTS idx_health_alerts_lga  ON health_alerts (lga_name, sent_at DESC);

-- ============================================================
-- 004: CHEW SMS reply log
-- ============================================================
CREATE TABLE IF NOT EXISTS chew_responses (
    id              bigserial PRIMARY KEY,
    phone           text NOT NULL,
    chew_id         bigint REFERENCES chew_subscribers(id),
    raw_message     text NOT NULL,
    parsed_action   text,
    cases_reported  integer,
    lga_name        text,
    received_at     timestamptz DEFAULT now()
);

-- ============================================================
-- 005: MEL events (health-system actions taken in response)
-- ============================================================
CREATE TABLE IF NOT EXISTS mel_events (
    id             bigserial PRIMARY KEY,
    lga_name       text NOT NULL,
    event_type     text NOT NULL CHECK (event_type IN (
                       'NETS_DISTRIBUTED',
                       'RDT_KITS_PREPOSITIONED',
                       'IRS_CONDUCTED',
                       'COMMUNITY_SENSITIZATION',
                       'CASE_MANAGEMENT_TRAINING',
                       'STOCK_PREPOSITIONING'
                   )),
    quantity       integer,
    unit           text,
    reported_by    text,
    facility_name  text,
    ward           text,
    event_date     date NOT NULL,
    notes          text,
    alert_id       bigint REFERENCES health_alerts(id),
    recorded_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mel_lga_date ON mel_events (lga_name, event_date DESC);

-- ============================================================
-- 006: DHIS2 malaria case data cache (monthly pull)
-- ============================================================
CREATE TABLE IF NOT EXISTS dhis2_malaria_cases (
    id                 bigserial PRIMARY KEY,
    lga_name           text NOT NULL,
    period             text NOT NULL,
    confirmed_cases    integer,
    suspected_cases    integer,
    rdt_positive       integer,
    treatment_started  integer,
    data_element_id    text,
    org_unit_id        text,
    pulled_at          timestamptz DEFAULT now(),
    UNIQUE (lga_name, period)
);

-- ============================================================
-- 007: Row Level Security
-- Public tables (dashboard-readable): lga_health_risk, dhis2_malaria_cases
-- Private tables (service_role only): chew_subscribers, health_alerts,
--                                      chew_responses, mel_events
-- ============================================================

-- Public-read tables
ALTER TABLE lga_health_risk       ENABLE ROW LEVEL SECURITY;
ALTER TABLE dhis2_malaria_cases   ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "public read lga_health_risk"     ON lga_health_risk;
DROP POLICY IF EXISTS "public read dhis2_malaria_cases" ON dhis2_malaria_cases;
CREATE POLICY "public read lga_health_risk"     ON lga_health_risk     FOR SELECT USING (true);
CREATE POLICY "public read dhis2_malaria_cases" ON dhis2_malaria_cases FOR SELECT USING (true);

-- Service-role-only tables (CHEW phone numbers are PII)
ALTER TABLE chew_subscribers ENABLE ROW LEVEL SECURITY;
ALTER TABLE health_alerts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE chew_responses   ENABLE ROW LEVEL SECURITY;
ALTER TABLE mel_events       ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service only chew_subscribers" ON chew_subscribers;
DROP POLICY IF EXISTS "service only health_alerts"    ON health_alerts;
DROP POLICY IF EXISTS "service only chew_responses"   ON chew_responses;
DROP POLICY IF EXISTS "service only mel_events"       ON mel_events;

CREATE POLICY "service only chew_subscribers" ON chew_subscribers TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service only health_alerts"    ON health_alerts    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service only chew_responses"   ON chew_responses   TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service only mel_events"       ON mel_events       TO service_role USING (true) WITH CHECK (true);

-- Done
SELECT 'FloodSight Health Intelligence Layer migrations complete' AS status;
