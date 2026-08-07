-- Migration 015: Add anomaly_score to user_training_events
--
-- Purpose:
--   Store the DFP per-user autoencoder reconstruction error (mean_abs_z) for
--   every below-threshold (clean) inference event.  This enables:
--
--     1. Per-user score distribution analysis
--          SELECT user_id,
--                 AVG(anomaly_score)    AS mean_score,
--                 STDDEV(anomaly_score) AS std_score,
--                 PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY anomaly_score)
--                                       AS p95_score
--          FROM user_training_events
--          WHERE source = 'clean' AND anomaly_score IS NOT NULL
--          GROUP BY user_id;
--
--     2. Dynamic per-user threshold calculation
--          SELECT mean_score + 3 * std_score AS dynamic_threshold
--          FROM (above query) t
--          WHERE user_id = $1;
--
--     3. Score drift alerting — catch gradual baseline shifts before they
--        cross the static 2.0 threshold.
--
--   NULL for 'seed' and 'feedback' rows (score not available for historical data).
--
-- Applied: 2026-04-22
-- Author:  Tomasz Zabek <tzabek@deloitte.co.uk>

BEGIN;

ALTER TABLE user_training_events
    ADD COLUMN IF NOT EXISTS anomaly_score FLOAT;

-- Partial index: only index rows that have a score (clean events only).
-- Supports fast per-user score distribution queries without bloating the index
-- with NULLs from the seed/feedback rows.
CREATE INDEX IF NOT EXISTS idx_ute_user_score
    ON user_training_events (user_id, anomaly_score)
    WHERE anomaly_score IS NOT NULL;

COMMENT ON COLUMN user_training_events.anomaly_score IS
    'DFP per-user autoencoder reconstruction error (mean_abs_z) at inference time. '
    'NULL for seed/feedback rows. Populated for source=''clean'' events only.';

COMMIT;
