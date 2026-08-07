-- Rollback 013: Remove TimescaleDB hypertables, policies, and continuous aggregates
--
-- WARNING: This drops all TimescaleDB-specific objects but leaves the underlying
-- tables and data intact.  After rolling back, the tables revert to plain
-- PostgreSQL tables — all existing application code continues to work.
--
-- This does NOT restore the tables to the native PG18 instance on port 5432.
-- To fully roll back you must also repoint POSTGRES_PORT=5432 in .env and
-- restart all services.
--
-- Author:  AI Intelligence Layer Team

BEGIN;

-- Drop continuous aggregates (must come before removing hypertable policies)
DROP MATERIALIZED VIEW IF EXISTS investigation_counts_hourly CASCADE;
DROP MATERIALIZED VIEW IF EXISTS anomaly_counts_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS anomaly_counts_hourly CASCADE;

-- Remove retention policies
SELECT remove_retention_policy('agent_findings',        if_not_exists => TRUE);
SELECT remove_retention_policy('agent_investigations',  if_not_exists => TRUE);
SELECT remove_retention_policy('user_training_events',  if_not_exists => TRUE);
SELECT remove_retention_policy('enriched_anomalies',    if_not_exists => TRUE);

-- Remove compression policies
SELECT remove_compression_policy('agent_findings',       if_not_exists => TRUE);
SELECT remove_compression_policy('agent_investigations', if_not_exists => TRUE);
SELECT remove_compression_policy('user_training_events', if_not_exists => TRUE);
SELECT remove_compression_policy('enriched_anomalies',   if_not_exists => TRUE);

-- Decompress any already-compressed chunks before reverting
SELECT decompress_chunk(c) FROM show_chunks('agent_findings') c;
SELECT decompress_chunk(c) FROM show_chunks('agent_investigations') c;
SELECT decompress_chunk(c) FROM show_chunks('user_training_events') c;
SELECT decompress_chunk(c) FROM show_chunks('enriched_anomalies') c;

-- Revert to plain PostgreSQL tables
SELECT revert_owned_to_plain_table('agent_findings');
SELECT revert_owned_to_plain_table('agent_investigations');
SELECT revert_owned_to_plain_table('user_training_events');
SELECT revert_owned_to_plain_table('enriched_anomalies');

-- Drop TimescaleDB extension (only safe if no other hypertables exist)
DROP EXTENSION IF EXISTS timescaledb;

COMMIT;

