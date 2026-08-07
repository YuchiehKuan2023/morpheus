-- Rollback 015: Remove anomaly_score from user_training_events

BEGIN;

DROP INDEX IF EXISTS idx_ute_user_score;

ALTER TABLE user_training_events
    DROP COLUMN IF EXISTS anomaly_score;

COMMIT;
