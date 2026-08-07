-- Migration 008: Create user_training_events table
--
-- Purpose:
--   Store clean Azure AD events that feed DFP model retraining.
--   Replaces the append-only JSONL file approach with a queryable,
--   indexed, source-tagged table.
--
-- Sources:
--   'seed'     — events imported from the original azure_ad_train.jsonl
--   'feedback' — events added via the false-positive feedback loop
--
-- Key queries:
--   Last event for a user (test anchor):
--     SELECT event FROM user_training_events
--     WHERE user_id = $1 ORDER BY event_time DESC LIMIT 1
--
--   Export window for retraining:
--     SELECT event FROM user_training_events
--     WHERE user_id = $1 AND event_time > NOW() - INTERVAL '90 days'
--     ORDER BY event_time ASC
--
--   Prune stale feedback events (seed events are never pruned):
--     DELETE FROM user_training_events
--     WHERE source = 'feedback' AND event_time < NOW() - INTERVAL '180 days'
--
-- Applied: 2026-03-15
-- Author:  AI Intelligence Layer Team

BEGIN;

CREATE TABLE IF NOT EXISTS user_training_events (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     TEXT         NOT NULL,
    event_time  TIMESTAMPTZ  NOT NULL,
    event       JSONB        NOT NULL,
    source      TEXT         NOT NULL CHECK (source IN ('seed', 'feedback')),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Composite index supports per-user chronological queries (most common access pattern).
CREATE INDEX IF NOT EXISTS idx_ute_user_time
    ON user_training_events (user_id, event_time DESC);

-- Single-column index on event_time supports global pruning / time-range scans.
CREATE INDEX IF NOT EXISTS idx_ute_event_time
    ON user_training_events (event_time);

COMMIT;
