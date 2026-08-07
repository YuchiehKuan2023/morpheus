-- Migration: Create simulation sessions table
-- Version: 014
-- Date: 2026-04-16
-- Description: Tracks individual event sessions sent through the DFP pipeline
--              by the Event Simulator. Each row represents one event sent to
--              Kafka and its progression through all pipeline stages.
--              stages_log stores process-level detail (per-agent, per-step)
--              as a JSONB array for SSE streaming to the frontend.

CREATE TABLE simulation_sessions (
    session_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID        NOT NULL,
    user_id              TEXT        NOT NULL,
    event_type           TEXT        NOT NULL
                                     CHECK (event_type IN ('clean', 'novel')),
    scenario             TEXT,                         -- null for clean; 'app'|'browser'|'os'|'device' for novel
    sent_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stage                TEXT        NOT NULL DEFAULT 'sent'
                                     CHECK (stage IN (
                                         'sent', 'clean', 'detected', 'enriched',
                                         'labeled', 'classified', 'agent_running',
                                         'complete', 'failed'
                                     )),
    anomaly_id           UUID,                         -- set when a matching row appears in enriched_anomalies
    anomaly_score        FLOAT,
    severity             TEXT,
    root_cause           TEXT,
    risk_score           FLOAT,
    investigation_id     UUID,                         -- set when agent_investigations row appears
    investigation_status TEXT,
    completed_at         TIMESTAMPTZ,
    stages_log           JSONB       NOT NULL DEFAULT '[]'::JSONB
    -- stages_log entry shape:
    -- {
    --   "group":   "inference" | "ai_orchestrator" | "agent_orchestrator",
    --   "process": "kafka_sent" | "dfp_scoring" | "context_enrichment" |
    --              "llm_classification" | "risk_scoring" |
    --              "forensics_agent" | "investigation_agent" | "remediation_agent",
    --   "status":  "pending" | "running" | "completed" | "error",
    --   "ts":      "<ISO 8601 timestamp or null>",
    --   "detail":  "<human-readable detail or null>"
    -- }
);

-- SSE polling: find rows changed since last poll
CREATE INDEX idx_sim_sessions_updated  ON simulation_sessions(updated_at DESC);

-- Group all sessions belonging to a run, newest first
CREATE INDEX idx_sim_sessions_run      ON simulation_sessions(run_id, sent_at DESC);

-- Efficient tracker query: find in-progress sessions that need polling
CREATE INDEX idx_sim_sessions_stage    ON simulation_sessions(stage)
    WHERE stage NOT IN ('complete', 'clean', 'failed');

-- Per-user history
CREATE INDEX idx_sim_sessions_user     ON simulation_sessions(user_id, sent_at DESC);
