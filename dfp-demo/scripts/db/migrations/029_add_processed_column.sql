-- Migration: Add processed column to enriched_anomalies
-- Version: 029
-- Date: 2026-05-08
-- Description: Track whether an anomaly has been fully processed through the
--              AI pipeline (enrichment, labeling, classification, agents).
--              Synthetic anomalies from heuristic scripts are FALSE; anomalies
--              processed by the AI orchestrator are TRUE.
--              Also widens simulation_sessions.event_type to allow
--              'reorchestration' for on-demand pipeline runs from the UI.

ALTER TABLE enriched_anomalies
    ADD COLUMN IF NOT EXISTS processed BOOLEAN NOT NULL DEFAULT FALSE;

-- Seed: AI-processed anomalies are marked processed
UPDATE enriched_anomalies SET processed = TRUE  WHERE validated_by = 'ai_auto_labeler';
-- Heuristic / unprocessed anomalies remain FALSE (column default)

-- Widen event_type constraint on simulation_sessions to allow reorchestration
ALTER TABLE simulation_sessions DROP CONSTRAINT IF EXISTS simulation_sessions_event_type_check;
ALTER TABLE simulation_sessions
    ADD CONSTRAINT simulation_sessions_event_type_check
    CHECK (event_type IN ('clean', 'novel', 'reorchestration'));
