-- Migration: 010 Rollback — Drop users tables
-- Version: 010
-- Date: 2025-01-01
-- Description: Reverse migration 010_create_users_tables.sql

-- Remove the assigned_to FK column added to enriched_anomalies (if it exists)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'enriched_anomalies' AND column_name = 'assigned_to'
    ) THEN
        ALTER TABLE enriched_anomalies DROP COLUMN assigned_to;
    END IF;
END $$;

-- Drop tables (CASCADE removes indexes and FK constraints automatically)
DROP TABLE IF EXISTS monitored_users CASCADE;
DROP TABLE IF EXISTS analyst_users CASCADE;
