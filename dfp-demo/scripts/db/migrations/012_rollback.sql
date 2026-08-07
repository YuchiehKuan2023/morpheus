-- Rollback: Drop agent investigation tables
-- Reverses: 012_create_agent_tables.sql

DROP TABLE IF EXISTS agent_findings;
DROP TABLE IF EXISTS agent_investigations;
