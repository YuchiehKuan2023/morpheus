-- Rollback: Remove processed column and revert event_type constraint
-- Version: 029

ALTER TABLE enriched_anomalies DROP COLUMN IF EXISTS processed;

ALTER TABLE simulation_sessions DROP CONSTRAINT IF EXISTS simulation_sessions_event_type_check;
ALTER TABLE simulation_sessions
    ADD CONSTRAINT simulation_sessions_event_type_check
    CHECK (event_type IN ('clean', 'novel'));
