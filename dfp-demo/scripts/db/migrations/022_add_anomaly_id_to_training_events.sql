-- Migration 022: Add anomaly_id to user_training_events
--
-- Purpose:
--   Link feedback training events back to their source anomaly so they can be
--   removed if an analyst overrides the AI's false-positive verdict.
--
--   Without this column, the only link is buried in the JSONB event field
--   (event->'_dfp_feedback'->>'source_anomaly_id'), which is not indexable
--   and not reliable for deletion.
--
-- Usage:
--   Remove feedback event when analyst confirms a true anomaly:
--     DELETE FROM user_training_events
--     WHERE anomaly_id = $1 AND source = 'feedback';
--
-- Applied: 2026-04-29
-- Author:  Tomasz Zabek <tzabek@deloitte.co.uk>

ALTER TABLE user_training_events
    ADD COLUMN IF NOT EXISTS anomaly_id UUID;

-- Partial index on anomaly_id for feedback rows only (seed/clean rows are always NULL).
CREATE INDEX IF NOT EXISTS idx_ute_anomaly_id
    ON user_training_events (anomaly_id)
    WHERE anomaly_id IS NOT NULL;

-- Also update the COMMENT on anomaly_score to reflect it's now populated for feedback too.
COMMENT ON COLUMN user_training_events.anomaly_score IS
    'DFP per-user autoencoder reconstruction error (mean_abs_z) at inference time. '
    'Populated for source=''clean'' and source=''feedback'' events.';
