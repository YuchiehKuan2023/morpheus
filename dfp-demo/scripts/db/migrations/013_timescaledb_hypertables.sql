-- Migration 013: Enable TimescaleDB and convert time-series tables to hypertables
--
-- Purpose:
--   Convert enriched_anomalies, user_training_events, agent_investigations,
--   and agent_findings to TimescaleDB hypertables for time-series optimisation:
--   automatic chunk partitioning, compression, retention policies, and continuous
--   aggregates (hourly + daily).
--
--   This migration is ADDITIVE — it does not alter any column types, drop any
--   data, or modify any existing indexes.  All existing insertions, queries,
--   and updates continue to work without change.
--
-- Prerequisites:
--   - Run against TimescaleDB (port 5433), NOT the native PG18 instance (5432).
--   - Data must already be present (restored via scripts/db/migrate_to_timescaledb.sh).
--   - TimescaleDB extension must be available in the image (timescale/timescaledb-ha:pg17
--     includes it by default).
--
-- Tables converted:
--   enriched_anomalies      — partitioned on timestamp    (1-week chunks)
--   user_training_events    — partitioned on event_time   (4-week chunks)
--   agent_investigations    — partitioned on triggered_at (4-week chunks)
--   agent_findings          — partitioned on started_at   (4-week chunks)
--
-- Applied: 2026-03-27
-- Author:  AI Intelligence Layer Team

BEGIN;

-- ============================================================================
-- 1. Enable TimescaleDB extension
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- 2. Convert enriched_anomalies to a hypertable
--
-- Chunk interval: 1 week — balances query pruning performance against the
-- overhead of many small chunks given roughly ~100-500 anomalies/day.
--
-- migrate_data => TRUE: existing rows are moved into the correct chunks.
-- if_not_exists => TRUE: idempotent; safe to re-run.
-- ============================================================================

SELECT create_hypertable(
    'enriched_anomalies',
    'timestamp',
    chunk_time_interval => INTERVAL '1 week',
    migrate_data        => TRUE,
    if_not_exists       => TRUE
);

-- ============================================================================
-- 3. Convert user_training_events to a hypertable
--
-- Chunk interval: 4 weeks — training events are bulk-loaded infrequently
-- (seed + feedback) so fewer, larger chunks are more efficient.
-- ============================================================================

SELECT create_hypertable(
    'user_training_events',
    'event_time',
    chunk_time_interval => INTERVAL '4 weeks',
    migrate_data        => TRUE,
    if_not_exists       => TRUE
);

-- ============================================================================
-- 4. Convert agent_investigations to a hypertable
--
-- Chunk interval: 4 weeks — one investigation is triggered per confirmed anomaly,
-- so volume tracks enriched_anomalies but is always lower. 4-week chunks
-- keep chunk count manageable while supporting time-range queries on triggered_at.
-- ============================================================================

SELECT create_hypertable(
    'agent_investigations',
    'triggered_at',
    chunk_time_interval => INTERVAL '4 weeks',
    migrate_data        => TRUE,
    if_not_exists       => TRUE
);

-- ============================================================================
-- 5. Convert agent_findings to a hypertable
--
-- Chunk interval: 4 weeks — each investigation produces at most 3 findings
-- (forensics, investigation, remediation), so volume mirrors agent_investigations.
-- ============================================================================

SELECT create_hypertable(
    'agent_findings',
    'started_at',
    chunk_time_interval => INTERVAL '4 weeks',
    migrate_data        => TRUE,
    if_not_exists       => TRUE
);

-- ============================================================================
-- 6. Compression policies
--
-- Chunks older than the threshold are compressed using TimescaleDB's columnar
-- compression.  Compressed chunks are still fully queryable; INSERT/UPDATE/DELETE
-- on compressed chunks is handled automatically by decompressing first.
--
-- enriched_anomalies    — compress after 30 days (anomalies are rarely updated
--                         once validated; dashboard queries ORDER BY timestamp DESC
--                         and hit recent, uncompressed chunks first).
-- user_training_events  — compress after 60 days (written once, read in bulk
--                         during retraining; old chunks are cold).
-- agent_investigations  — compress after 30 days (investigations complete quickly;
--                         historical records are read-only for dashboard/audit).
-- agent_findings        — compress after 30 days (same cadence as investigations).
-- ============================================================================

ALTER TABLE enriched_anomalies SET (
    timescaledb.compress,
    timescaledb.compress_orderby  = 'timestamp DESC',
    timescaledb.compress_segmentby = 'user_id'
);
SELECT add_compression_policy(
    'enriched_anomalies',
    compress_after => INTERVAL '30 days',
    if_not_exists  => TRUE
);

ALTER TABLE user_training_events SET (
    timescaledb.compress,
    timescaledb.compress_orderby  = 'event_time DESC',
    timescaledb.compress_segmentby = 'user_id'
);
SELECT add_compression_policy(
    'user_training_events',
    compress_after => INTERVAL '60 days',
    if_not_exists  => TRUE
);

ALTER TABLE agent_investigations SET (
    timescaledb.compress,
    timescaledb.compress_orderby  = 'triggered_at DESC'
);
SELECT add_compression_policy(
    'agent_investigations',
    compress_after => INTERVAL '30 days',
    if_not_exists  => TRUE
);

ALTER TABLE agent_findings SET (
    timescaledb.compress,
    timescaledb.compress_orderby  = 'started_at DESC'
);
SELECT add_compression_policy(
    'agent_findings',
    compress_after => INTERVAL '30 days',
    if_not_exists  => TRUE
);

-- ============================================================================
-- 7. Retention policies
--
-- Raw rows older than the threshold are automatically dropped.
-- enriched_anomalies    — 365 days (1 year of anomaly history)
-- user_training_events  — 730 days (2 years; seed events are long-lived baselines)
-- agent_investigations  — 365 days (aligned with anomaly retention)
-- agent_findings        — 365 days (aligned with investigation retention)
-- ============================================================================

SELECT add_retention_policy(
    'enriched_anomalies',
    drop_after    => INTERVAL '365 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'user_training_events',
    drop_after    => INTERVAL '730 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'agent_investigations',
    drop_after    => INTERVAL '365 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'agent_findings',
    drop_after    => INTERVAL '365 days',
    if_not_exists => TRUE
);

-- ============================================================================
-- 8. Continuous aggregate: hourly anomaly counts per user
--
-- Feeds the Grafana activity heatmap and real-time anomaly trend panels.
-- Refreshed every 30 minutes; stays at most 1 hour behind real-time.
-- All four severity levels included for complete dashboard coverage.
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS anomaly_counts_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp)                          AS bucket,
    user_id,
    COUNT(*)                                                  AS anomaly_count,
    AVG(anomaly_score)                                        AS avg_score,
    MAX(anomaly_score)                                        AS max_score,
    AVG(risk_score)                                           AS avg_risk_score,
    COUNT(*) FILTER (WHERE severity = 'CRITICAL')             AS critical_count,
    COUNT(*) FILTER (WHERE severity = 'HIGH')                 AS high_count,
    COUNT(*) FILTER (WHERE severity = 'MEDIUM')               AS medium_count,
    COUNT(*) FILTER (WHERE severity = 'LOW')                  AS low_count,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE)                 AS confirmed_count,
    COUNT(*) FILTER (WHERE is_anomaly = FALSE)                AS false_positive_count,
    COUNT(*) FILTER (WHERE is_anomaly IS NULL)                AS pending_count
FROM enriched_anomalies
GROUP BY bucket, user_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'anomaly_counts_hourly',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists     => TRUE
);

-- ============================================================================
-- 9. Continuous aggregate: daily anomaly summary (all users)
--
-- Feeds weekly/monthly trend panels in Grafana and long-range analytics.
-- Daily granularity reduces query cost for charts spanning weeks or months.
-- Refreshed every hour; end_offset of 1 day avoids partial-day buckets.
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS anomaly_counts_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp)                           AS bucket,
    user_id,
    root_cause,
    COUNT(*)                                                  AS anomaly_count,
    AVG(anomaly_score)                                        AS avg_score,
    MAX(anomaly_score)                                        AS max_score,
    AVG(risk_score)                                           AS avg_risk_score,
    COUNT(*) FILTER (WHERE severity = 'CRITICAL')             AS critical_count,
    COUNT(*) FILTER (WHERE severity = 'HIGH')                 AS high_count,
    COUNT(*) FILTER (WHERE severity = 'MEDIUM')               AS medium_count,
    COUNT(*) FILTER (WHERE severity = 'LOW')                  AS low_count,
    COUNT(*) FILTER (WHERE is_anomaly = TRUE)                 AS confirmed_count,
    COUNT(*) FILTER (WHERE is_anomaly = FALSE)                AS false_positive_count
FROM enriched_anomalies
GROUP BY bucket, user_id, root_cause
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'anomaly_counts_daily',
    start_offset      => INTERVAL '30 days',
    end_offset        => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);

-- ============================================================================
-- 10. Continuous aggregate: hourly agent investigation throughput
--
-- Tracks how many investigations are triggered, completed, and failed per hour.
-- Useful for SLA monitoring (time-to-investigate) and agent load dashboards.
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS investigation_counts_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', triggered_at)                       AS bucket,
    COUNT(*)                                                  AS total_triggered,
    COUNT(*) FILTER (WHERE status = 'complete')               AS completed_count,
    COUNT(*) FILTER (WHERE status = 'failed')                 AS failed_count,
    COUNT(*) FILTER (WHERE status = 'pending')                AS pending_count,
    AVG(confidence_score)                                     AS avg_confidence,
    AVG(EXTRACT(EPOCH FROM (completed_at - triggered_at)))    AS avg_duration_seconds
FROM agent_investigations
GROUP BY bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'investigation_counts_hourly',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists     => TRUE
);

COMMIT;

