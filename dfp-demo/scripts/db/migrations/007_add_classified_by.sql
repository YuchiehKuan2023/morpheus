-- Migration 007: Add classified_by column to enriched_anomalies
--
-- Purpose:
--   Track who (or what system) wrote the root_cause / sub_category
--   classification so we can distinguish heuristic bootstrap labels from
--   DistilBERT ML predictions and future LLM-derived labels.
--
-- Values:
--   'heuristic'   — assigned by scripts/heuristic_label.py
--   'distilbert'  — assigned by modules/ai/root_cause/labeling_worker.py
--   'llm'         — assigned by a future LLM-based classifier
--   NULL          — no classification yet (is_anomaly=FALSE or unclassified TRUE)
--
-- Backfill:
--   All existing TPs already have classified_at set by heuristic_label.py,
--   so we backfill them to 'heuristic'.  FALSE_POSITIVEs are left NULL.
--
-- Applied: 2026-03-09
-- Author:  AI Intelligence Layer Team

BEGIN;

ALTER TABLE enriched_anomalies
    ADD COLUMN IF NOT EXISTS classified_by VARCHAR(64);

-- Backfill: records that already have a classification came from heuristic_label.py
UPDATE enriched_anomalies
SET    classified_by = 'heuristic'
WHERE  classified_at IS NOT NULL
  AND  classified_by IS NULL;

-- Index for efficient filtering (e.g. "all heuristic-labeled TPs")
CREATE INDEX IF NOT EXISTS idx_enriched_anomalies_classified_by
    ON enriched_anomalies (classified_by)
    WHERE classified_by IS NOT NULL;

COMMENT ON COLUMN enriched_anomalies.classified_by IS
    'Source of the root_cause/sub_category classification: '
    '''heuristic'' | ''distilbert'' | ''llm'' | NULL';

COMMIT;
