-- Migration: Add analyst feedback columns to enriched_anomalies
-- Version: 020
-- Date: 2026-04-28
-- Description: Adds analyst_verdict, analyst_notes, reviewed_by, reviewed_at
--              for the analyst review workflow. Existing resolution_notes and
--              resolved_at columns are retained for resolution summaries.

-- ============================================================================
-- New columns
-- ============================================================================

ALTER TABLE enriched_anomalies
    ADD COLUMN analyst_verdict VARCHAR(20)
        CHECK (analyst_verdict IN ('confirmed', 'false_positive', 'escalated', 'dismissed'));

ALTER TABLE enriched_anomalies
    ADD COLUMN analyst_notes TEXT;

ALTER TABLE enriched_anomalies
    ADD COLUMN reviewed_by INTEGER REFERENCES analyst_users(id);

ALTER TABLE enriched_anomalies
    ADD COLUMN reviewed_at TIMESTAMPTZ;

-- ============================================================================
-- Indexes for review queries
-- ============================================================================

CREATE INDEX idx_enriched_anomalies_reviewed_by
    ON enriched_anomalies (reviewed_by, reviewed_at DESC);

CREATE INDEX idx_enriched_anomalies_verdict
    ON enriched_anomalies (analyst_verdict)
    WHERE analyst_verdict IS NOT NULL;
