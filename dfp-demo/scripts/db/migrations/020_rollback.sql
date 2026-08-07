-- Rollback: Migration 020
-- Removes analyst feedback columns from enriched_anomalies

DROP INDEX IF EXISTS idx_enriched_anomalies_verdict;
DROP INDEX IF EXISTS idx_enriched_anomalies_reviewed_by;

ALTER TABLE enriched_anomalies DROP COLUMN IF EXISTS reviewed_at;
ALTER TABLE enriched_anomalies DROP COLUMN IF EXISTS reviewed_by;
ALTER TABLE enriched_anomalies DROP COLUMN IF EXISTS analyst_notes;
ALTER TABLE enriched_anomalies DROP COLUMN IF EXISTS analyst_verdict;
