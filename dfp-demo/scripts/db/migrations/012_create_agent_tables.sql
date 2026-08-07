-- Migration: Create agent investigation tables
-- Version: 012
-- Date: 2026-04-07
-- Description: Persistent store for multi-agent investigation results.
--              agent_investigations: one row per anomaly investigation.
--              agent_findings: one row per agent per investigation.

CREATE TABLE agent_investigations (
    investigation_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    anomaly_id          UUID        NOT NULL
                                    REFERENCES enriched_anomalies(anomaly_id)
                                    ON DELETE CASCADE,
    triggered_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT        NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'running', 'complete', 'failed')),
    severity_at_trigger TEXT,
    agents_invoked      TEXT[],
    confidence_score    FLOAT,
    overall_recommendation TEXT,
    raw_report          JSONB
);

CREATE TABLE agent_findings (
    finding_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id    UUID        NOT NULL
                                    REFERENCES agent_investigations(investigation_id)
                                    ON DELETE CASCADE,
    agent_type          TEXT        NOT NULL
                                    CHECK (agent_type IN ('forensics', 'investigation', 'remediation')),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT        NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'running', 'complete', 'failed', 'skipped')),
    result              JSONB,
    llm_tokens_used     INTEGER,
    latency_ms          INTEGER
);

CREATE INDEX idx_agent_investigations_anomaly  ON agent_investigations(anomaly_id);
CREATE INDEX idx_agent_investigations_status   ON agent_investigations(status);
CREATE INDEX idx_agent_findings_investigation  ON agent_findings(investigation_id);
CREATE INDEX idx_agent_findings_type           ON agent_findings(agent_type);
