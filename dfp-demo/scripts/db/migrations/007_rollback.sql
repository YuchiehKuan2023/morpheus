-- Rollback for Migration 007: remove classified_by column
BEGIN;

DROP INDEX IF EXISTS idx_enriched_anomalies_classified_by;
ALTER TABLE enriched_anomalies DROP COLUMN IF EXISTS classified_by;

COMMIT;
