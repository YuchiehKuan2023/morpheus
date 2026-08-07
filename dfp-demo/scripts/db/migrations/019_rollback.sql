-- Rollback: Migration 019
-- Reverts assigned_to back to VARCHAR(255), drops FK constraint

DROP INDEX IF EXISTS idx_enriched_anomalies_assigned;

ALTER TABLE enriched_anomalies
    DROP CONSTRAINT IF EXISTS fk_enriched_anomalies_assigned_to;

ALTER TABLE enriched_anomalies
    ALTER COLUMN assigned_to TYPE VARCHAR(255) USING assigned_to::TEXT;

CREATE INDEX idx_enriched_anomalies_assigned
    ON enriched_anomalies (assigned_to, status);
