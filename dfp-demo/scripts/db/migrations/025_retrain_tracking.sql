-- Migration 025: Add retrain_type to dfp_retrain_jobs + classifier_retrain_log
-- Purpose: Extend retraining infrastructure to support DFP autoencoder AND
--          classifier retraining (XGBoost risk scorer, DistilBERT root cause).

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Add retrain_type column to dfp_retrain_jobs
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE dfp_retrain_jobs
    ADD COLUMN IF NOT EXISTS retrain_type VARCHAR(20) NOT NULL DEFAULT 'dfp'
        CHECK (retrain_type IN ('dfp', 'risk_scorer', 'root_cause'));

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Classifier retrain log — tracks XGBoost / DistilBERT retrain history
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS classifier_retrain_log (
    id                  SERIAL PRIMARY KEY,
    classifier_type     VARCHAR(50) NOT NULL,          -- 'risk_scorer' | 'root_cause'
    anomalies_at_retrain INTEGER NOT NULL DEFAULT 0,   -- total classified anomalies at time of retrain
    model_path          TEXT,                           -- e.g. data/models/risk_scorer/
    mlflow_run_id       VARCHAR(255),
    started_at          TIMESTAMP WITH TIME ZONE,
    completed_at        TIMESTAMP WITH TIME ZONE,
    duration_seconds    FLOAT,
    status              VARCHAR(20) NOT NULL DEFAULT 'completed'
                            CHECK (status IN ('running', 'completed', 'failed')),
    error_message       TEXT,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_classifier_retrain_type
    ON classifier_retrain_log (classifier_type, created_at DESC);
