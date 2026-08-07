-- Migration 006: Create dfp_retrain_jobs table
-- Purpose: Track per-user DFP model retraining jobs triggered by false positive accumulation.
--
-- A retraining job is queued when a user accumulates >= 300 new clean (false positive)
-- events since the last successful job.  MLflow orchestration polls this table for
-- 'pending' jobs, updates status to 'running' → 'completed' | 'failed', and writes
-- back model version info.
--
-- Rollback: see 006_rollback_dfp_retrain_jobs.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- Table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dfp_retrain_jobs (
    -- Identity
    job_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(255) NOT NULL,

    -- What triggered this job
    false_positive_ids      UUID[]       NOT NULL DEFAULT '{}',   -- anomaly_ids marked FP
    new_clean_events        INTEGER      NOT NULL DEFAULT 0,       -- events added this run
    total_training_events   INTEGER,                               -- total events after append

    -- Lifecycle
    status                  VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at              TIMESTAMP WITH TIME ZONE,
    completed_at            TIMESTAMP WITH TIME ZONE,
    error_message           TEXT,

    -- Model versioning (filled in by MLflow runner on completion)
    old_model_version       VARCHAR(50),
    new_model_version       VARCHAR(50),
    mlflow_run_id           VARCHAR(255),

    -- Audit
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_retrain_user_status
    ON dfp_retrain_jobs (user_id, status);

CREATE INDEX IF NOT EXISTS idx_retrain_status_created
    ON dfp_retrain_jobs (status, created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- updated_at trigger
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_dfp_retrain_jobs_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_dfp_retrain_jobs_updated_at ON dfp_retrain_jobs;
CREATE TRIGGER trg_dfp_retrain_jobs_updated_at
    BEFORE UPDATE ON dfp_retrain_jobs
    FOR EACH ROW EXECUTE FUNCTION update_dfp_retrain_jobs_updated_at();

-- Migration tracking is handled automatically by scripts/db/migrate.py.
