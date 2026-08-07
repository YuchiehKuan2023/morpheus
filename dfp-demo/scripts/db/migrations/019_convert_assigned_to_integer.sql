-- Migration: Convert assigned_to from VARCHAR(255) to INTEGER FK
-- Version: 019
-- Date: 2026-04-28
-- Description: Updates email-format assigned_to values to integer IDs via
--              analyst_users lookup, then alters column type to INTEGER with FK.

-- ============================================================================
-- Step 1: Convert email-format values to integer IDs
-- ============================================================================

UPDATE enriched_anomalies ea
SET assigned_to = CAST(au.id AS TEXT)
FROM analyst_users au
WHERE ea.assigned_to = au.username
  AND ea.assigned_to !~ '^\d+$';

-- ============================================================================
-- Step 2: Drop the old index (uses VARCHAR type)
-- ============================================================================

DROP INDEX IF EXISTS idx_enriched_anomalies_assigned;

-- ============================================================================
-- Step 3: Alter column type from VARCHAR(255) to INTEGER
-- ============================================================================

ALTER TABLE enriched_anomalies
    ALTER COLUMN assigned_to TYPE INTEGER USING assigned_to::INTEGER;

-- ============================================================================
-- Step 4: Add foreign key constraint
-- ============================================================================

ALTER TABLE enriched_anomalies
    ADD CONSTRAINT fk_enriched_anomalies_assigned_to
    FOREIGN KEY (assigned_to) REFERENCES analyst_users(id);

-- ============================================================================
-- Step 5: Recreate index with proper INTEGER type
-- ============================================================================

CREATE INDEX idx_enriched_anomalies_assigned
    ON enriched_anomalies (assigned_to, status);
