-- Migration: Create enriched_anomalies table
-- Version: 001
-- Date: 2026-02-19
-- Description: Main table for storing enriched anomaly detections with AI metadata

-- ============================================================================
-- CREATE TABLE: enriched_anomalies
-- ============================================================================

CREATE TABLE IF NOT EXISTS enriched_anomalies (
    -- Primary Identification
    anomaly_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    
    -- Detection Metadata
    anomaly_score FLOAT NOT NULL,
    mean_abs_z FLOAT,
    
    -- CRITICAL: Raw Event Data for Future Retraining
    -- This stores the original event that triggered the detection
    -- Required for DFP feedback loop (Week 9-10) to append false positives
    -- to training cache for model retraining
    original_event JSONB NOT NULL,
    
    -- DFP Detection Results
    -- Contains: z_scores (all detected features), mean_abs_z, feature values
    raw_detection JSONB NOT NULL,
    
    -- AI Enrichment Results
    -- Contains: extracted entities, similar detections, graph context,
    -- cold start status, feature availability
    ai_enrichment JSONB,
    
    -- Stage 1: Anomaly Validation (Week 9-10)
    -- Multi-method ensemble: LLM + similarity + baseline + pattern analysis
    -- NULL: Pending validation (default for new detections)
    -- FALSE: False positive (should be added to training cache for retraining)
    -- TRUE: Real anomaly (excluded from training cache permanently)
    is_anomaly BOOLEAN DEFAULT NULL,
    validation_confidence FLOAT,
    validation_reasoning TEXT,
    validated_at TIMESTAMP,
    validated_by VARCHAR(50), -- 'ai_auto_labeler' or 'analyst_{id}'
    
    -- DFP Feedback Loop Status
    -- Tracks whether this detection has been fed back to DFP for retraining
    feedback_to_dfp BOOLEAN DEFAULT FALSE,
    
    -- Retraining status:
    -- 'pending': Validation pending, not yet processed
    -- 'queued': False positive added to training cache, counting toward 300 threshold
    -- 'completed': Model retrained with this false positive included
    -- 'excluded': Real anomaly, permanently excluded from training
    dfp_retrain_status VARCHAR(20) CHECK (dfp_retrain_status IN ('pending', 'queued', 'completed', 'excluded')),
    dfp_retrained_at TIMESTAMP,
    
    -- Stage 2: Root Cause Classification (Week 11-14)
    -- Only applied to validated TRUE anomalies (is_anomaly=true)
    -- Categories: Account Takeover, Credential Stuffing, Privilege Escalation,
    --            Data Exfiltration, Insider Threat, Geographic Anomaly, etc.
    root_cause VARCHAR(100),
    sub_category VARCHAR(100),
    severity VARCHAR(20) CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    classification_confidence FLOAT,
    classification_reasoning TEXT,
    classified_at TIMESTAMP,
    
    -- Risk Scoring (Week 11-14)
    risk_score FLOAT, -- 0.0 to 100.0
    risk_factors JSONB, -- Key risk contributors
    
    -- Audit Fields
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Data Source Tracking
    source VARCHAR(50) DEFAULT 'dfp_inference', -- 'dfp_inference', 'synthetic', 'manual'
    
    -- Analyst Workflow
    assigned_to VARCHAR(255), -- Analyst user ID
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'investigating', 'resolved', 'false_positive')),
    resolution_notes TEXT,
    resolved_at TIMESTAMP
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Primary query patterns
CREATE INDEX idx_enriched_anomalies_user_timestamp 
    ON enriched_anomalies(user_id, timestamp DESC);

CREATE INDEX idx_enriched_anomalies_timestamp 
    ON enriched_anomalies(timestamp DESC);

-- Anomaly validation queries
CREATE INDEX idx_enriched_anomalies_is_anomaly 
    ON enriched_anomalies(is_anomaly) 
    WHERE is_anomaly IS NOT NULL;

CREATE INDEX idx_enriched_anomalies_validation_pending 
    ON enriched_anomalies(created_at DESC) 
    WHERE is_anomaly IS NULL;

-- DFP feedback loop queries
CREATE INDEX idx_enriched_anomalies_feedback_status 
    ON enriched_anomalies(feedback_to_dfp, dfp_retrain_status);

CREATE INDEX idx_enriched_anomalies_false_positives 
    ON enriched_anomalies(user_id, validated_at DESC) 
    WHERE is_anomaly = FALSE AND feedback_to_dfp = FALSE;

-- Root cause classification queries
CREATE INDEX idx_enriched_anomalies_root_cause 
    ON enriched_anomalies(root_cause, severity);

-- Analyst workflow
CREATE INDEX idx_enriched_anomalies_status 
    ON enriched_anomalies(status, created_at DESC);

CREATE INDEX idx_enriched_anomalies_assigned 
    ON enriched_anomalies(assigned_to, status);

-- JSONB GIN indexes for fast nested queries
CREATE INDEX idx_enriched_anomalies_original_event_gin 
    ON enriched_anomalies USING GIN (original_event);

CREATE INDEX idx_enriched_anomalies_ai_enrichment_gin 
    ON enriched_anomalies USING GIN (ai_enrichment);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_enriched_anomalies_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_enriched_anomalies_updated_at
    BEFORE UPDATE ON enriched_anomalies
    FOR EACH ROW
    EXECUTE FUNCTION update_enriched_anomalies_updated_at();

-- Auto-set dfp_retrain_status based on is_anomaly
CREATE OR REPLACE FUNCTION set_dfp_retrain_status()
RETURNS TRIGGER AS $$
BEGIN
    -- When anomaly is validated
    IF NEW.is_anomaly IS NOT NULL AND OLD.is_anomaly IS NULL THEN
        IF NEW.is_anomaly = FALSE THEN
            -- False positive: queued for training cache appending
            NEW.dfp_retrain_status = 'queued';
        ELSIF NEW.is_anomaly = TRUE THEN
            -- Real anomaly: excluded from training
            NEW.dfp_retrain_status = 'excluded';
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_set_dfp_retrain_status
    BEFORE UPDATE ON enriched_anomalies
    FOR EACH ROW
    WHEN (NEW.is_anomaly IS DISTINCT FROM OLD.is_anomaly)
    EXECUTE FUNCTION set_dfp_retrain_status();

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE enriched_anomalies IS 
'Main table for storing DFP anomaly detections enriched with AI intelligence layer. Supports two-stage labeling (validation → classification) and DFP feedback loop for continuous learning.';

COMMENT ON COLUMN enriched_anomalies.original_event IS 
'CRITICAL: Raw event data required for DFP feedback loop. False positives are appended to training cache for model retraining.';

COMMENT ON COLUMN enriched_anomalies.is_anomaly IS 
'Stage 1 validation: NULL=pending, FALSE=false positive (add to training), TRUE=real anomaly (exclude from training)';

COMMENT ON COLUMN enriched_anomalies.dfp_retrain_status IS 
'Tracks DFP retraining workflow: pending → queued → completed (for false positives) OR excluded (for real anomalies)';

COMMENT ON COLUMN enriched_anomalies.root_cause IS 
'Stage 2 classification: Only applied to validated TRUE anomalies (is_anomaly=true)';

-- ============================================================================
-- GRANTS
-- ============================================================================

-- Grant permissions to dfp_ai user
GRANT SELECT, INSERT, UPDATE ON enriched_anomalies TO dfp_ai;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dfp_ai;
