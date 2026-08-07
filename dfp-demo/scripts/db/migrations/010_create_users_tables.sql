-- Migration: Create monitored_users and analyst_users tables
-- Version: 010
-- Date: 2026-03-16
-- Description: Two tables to support the frontend Users page and anomaly
--              assignment features. monitored_users holds the 50 trained
--              users enriched from profile JSON + user_baselines.yaml.
--              analyst_users holds the SOC team seed rows (~10).

-- ============================================================================
-- CREATE TABLE: monitored_users
-- ============================================================================

CREATE TABLE IF NOT EXISTS monitored_users (
    id                       SERIAL PRIMARY KEY,
    username                 TEXT UNIQUE NOT NULL,  -- email, matches user_id in enriched_anomalies
    user_guid                UUID,                  -- from profile meta.user_id_guid
    display_name             TEXT,
    first_name               TEXT,
    last_name                TEXT,
    email                    TEXT,
    company                  TEXT,                  -- derived from email domain
    department               TEXT,                  -- Engineering / HR / Finance / etc.
    user_role                TEXT,                  -- engineering / hr / sales_marketing / general
    job_title                TEXT,                  -- derived by rule engine in populate script
    seniority                TEXT,                  -- Junior / Mid / Senior / Principal
    primary_location_city    TEXT,                  -- most frequent city from profile
    primary_location_country TEXT,
    home_location_lat        NUMERIC,
    home_location_lon        NUMERIC,
    all_locations            JSONB,                 -- [{city, country, lat, lon, frequency}]
    primary_os               TEXT,
    primary_browser          TEXT,
    primary_device           TEXT,
    devices                  JSONB,                 -- [{name, count}]
    apps                     JSONB,                 -- [{app, count}]
    work_hours_start         INT,
    work_hours_end           INT,
    active_days              TEXT[],                -- ['Monday','Tuesday',...]
    total_events             INT,
    avatar_color             TEXT,                  -- CSS hex, deterministic from user_role
    avatar_initials          TEXT,                  -- e.g. 'AG' for Andrew Gonzalez
    corp_vpn                 BOOLEAN DEFAULT FALSE,
    created_at               TIMESTAMPTZ DEFAULT NOW(),
    updated_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monitored_users_username
    ON monitored_users (username);

CREATE INDEX IF NOT EXISTS idx_monitored_users_user_role
    ON monitored_users (user_role);

CREATE INDEX IF NOT EXISTS idx_monitored_users_company
    ON monitored_users (company);

CREATE INDEX IF NOT EXISTS idx_monitored_users_department
    ON monitored_users (department);

-- ============================================================================
-- CREATE TABLE: analyst_users
-- ============================================================================

CREATE TABLE IF NOT EXISTS analyst_users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,  -- e.g. j.smith@soc.internal
    display_name    TEXT,
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    analyst_role    TEXT NOT NULL,         -- soc_analyst_l1/l2/l3 / soc_manager / compliance_officer
    level           INT  NOT NULL,         -- 1 / 2 / 3
    avatar_color    TEXT,
    avatar_initials TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analyst_users_username
    ON analyst_users (username);

CREATE INDEX IF NOT EXISTS idx_analyst_users_analyst_role
    ON analyst_users (analyst_role);

-- ============================================================================
-- Foreign key hook — add assignment column to enriched_anomalies if it exists
-- (tolerates running before enriched_anomalies exists)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'enriched_anomalies'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'enriched_anomalies' AND column_name = 'assigned_to'
    ) THEN
        ALTER TABLE enriched_anomalies
            ADD COLUMN assigned_to INT REFERENCES analyst_users(id);
    END IF;
END $$;
