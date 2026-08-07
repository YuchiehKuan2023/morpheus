-- Migration 009: Add 'clean' to user_training_events.source check constraint
--
-- Purpose:
--   Below-threshold inference events (mean_abs_z < 2.0) are persisted to
--   user_training_events by ai_orchestrator._handle_clean_event(), using
--   source='clean'.  These are distinct from human-validated 'feedback' events
--   and should be tracked separately for analytics / pruning policies.
--
-- Sources after this migration:
--   'seed'     — events imported from the original azure_ad_train.jsonl
--   'feedback' — events added via the false-positive feedback loop (human label)
--   'clean'    — events auto-persisted from the inference pipeline (below threshold)
--
-- Applied: 2026-05-02
-- Author:  AI Intelligence Layer Team

BEGIN;

ALTER TABLE user_training_events
    DROP CONSTRAINT user_training_events_source_check;

ALTER TABLE user_training_events
    ADD CONSTRAINT user_training_events_source_check
        CHECK (source IN ('seed', 'feedback', 'clean'));

COMMIT;
