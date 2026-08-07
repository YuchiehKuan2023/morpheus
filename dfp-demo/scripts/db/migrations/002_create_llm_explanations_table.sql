-- Migration: Create LLM Explanations Table
-- Description: Store versioned LLM explanations with detailed metadata
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-20

-- ============================================================
-- Table: llm_explanations
-- Purpose: Store all LLM-generated explanations with versioning
-- ============================================================

CREATE TABLE IF NOT EXISTS llm_explanations (
    -- Primary identifiers
    id SERIAL PRIMARY KEY,
    detection_id UUID NOT NULL,
    version INT NOT NULL DEFAULT 1,
    
    -- Explanation content (structured JSON)
    explanation_type VARCHAR(50) NOT NULL, -- 'summary', 'detailed', 'forensics'
    
    -- Structured analysis fields
    context_analysis TEXT,          -- What happened (factual description)
    pattern_analysis TEXT,           -- Behavioral pattern identified
    anomaly_classification TEXT,     -- Classification result (true_positive, false_positive, uncertain)
    risk_assessment TEXT,            -- Security risk evaluation
    recommendations TEXT,            -- Actionable next steps
    confidence_score DECIMAL(5,4),   -- Model confidence (0.0000-1.0000)
    severity_level VARCHAR(20),      -- LOW, MEDIUM, HIGH, CRITICAL
    
    -- Reasoning and evidence
    reasoning_process TEXT,          -- Step-by-step reasoning (if available)
    evidence_summary TEXT,           -- Key evidence used in analysis
    entities_referenced JSONB,       -- Entities involved in explanation
    similar_cases_cited JSONB,       -- Similar cases referenced
    graph_insights_used JSONB,       -- Graph context utilized
    
    -- Model metadata
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50),
    prompt_template_version VARCHAR(50),
    temperature DECIMAL(3,2),
    max_tokens INT,
    
    -- Token usage and costs
    prompt_tokens INT NOT NULL,
    completion_tokens INT NOT NULL,
    total_tokens INT NOT NULL,
    cost_usd DECIMAL(10,6) NOT NULL,
    
    -- Performance metrics
    latency_ms DECIMAL(10,2) NOT NULL,
    api_response_time_ms DECIMAL(10,2),
    rag_assembly_time_ms DECIMAL(10,2),
    
    -- Quality indicators
    has_reasoning BOOLEAN DEFAULT FALSE,
    has_citations BOOLEAN DEFAULT FALSE,
    grounding_score DECIMAL(5,4),    -- How well grounded in provided data (0-1)
    hallucination_risk VARCHAR(20),  -- LOW, MEDIUM, HIGH
    
    -- RAG context metadata
    rag_context_size INT,            -- Tokens in RAG context
    similar_detections_count INT,
    entities_count INT,
    graph_depth INT,
    cold_start BOOLEAN DEFAULT FALSE,
    
    -- Feedback and validation
    human_feedback VARCHAR(20),      -- 'helpful', 'not_helpful', 'inaccurate', NULL
    human_rating INT CHECK (human_rating BETWEEN 1 AND 5),
    human_notes TEXT,
    validation_status VARCHAR(20),   -- 'pending', 'approved', 'rejected'
    validated_by VARCHAR(100),
    validated_at TIMESTAMP,
    
    -- Error handling
    generation_error TEXT,           -- Error message if generation failed
    retry_count INT DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_detection_version UNIQUE (detection_id, version, explanation_type),
    CONSTRAINT valid_explanation_type CHECK (explanation_type IN ('summary', 'detailed', 'forensics')),
    CONSTRAINT valid_severity CHECK (severity_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', NULL)),
    CONSTRAINT valid_classification CHECK (anomaly_classification IN ('true_positive', 'false_positive', 'uncertain', 'benign', NULL))
);

-- ============================================================
-- Indexes for Performance
-- ============================================================

-- Primary lookup index
CREATE INDEX idx_llm_explanations_detection_id ON llm_explanations(detection_id);

-- Type and version lookups
CREATE INDEX idx_llm_explanations_type ON llm_explanations(explanation_type);
CREATE INDEX idx_llm_explanations_version ON llm_explanations(detection_id, version DESC);

-- Classification and severity filtering
CREATE INDEX idx_llm_explanations_classification ON llm_explanations(anomaly_classification);
CREATE INDEX idx_llm_explanations_severity ON llm_explanations(severity_level);

-- Feedback and validation
CREATE INDEX idx_llm_explanations_feedback ON llm_explanations(human_feedback);
CREATE INDEX idx_llm_explanations_validation ON llm_explanations(validation_status);

-- Model analytics
CREATE INDEX idx_llm_explanations_model ON llm_explanations(model_name, created_at DESC);

-- Cost and performance analytics
CREATE INDEX idx_llm_explanations_cost ON llm_explanations(created_at, cost_usd);
CREATE INDEX idx_llm_explanations_latency ON llm_explanations(latency_ms);

-- Timestamp range queries
CREATE INDEX idx_llm_explanations_created_at ON llm_explanations(created_at DESC);

-- ============================================================
-- Trigger: Auto-update timestamp
-- ============================================================

CREATE OR REPLACE FUNCTION update_llm_explanations_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_llm_explanations_timestamp
BEFORE UPDATE ON llm_explanations
FOR EACH ROW
EXECUTE FUNCTION update_llm_explanations_timestamp();

-- ============================================================
-- View: Latest Explanations
-- ============================================================

CREATE OR REPLACE VIEW vw_latest_llm_explanations AS
SELECT DISTINCT ON (detection_id, explanation_type)
    id,
    detection_id,
    version,
    explanation_type,
    context_analysis,
    pattern_analysis,
    anomaly_classification,
    risk_assessment,
    recommendations,
    confidence_score,
    severity_level,
    model_name,
    total_tokens,
    cost_usd,
    latency_ms,
    human_feedback,
    validation_status,
    created_at
FROM llm_explanations
ORDER BY detection_id, explanation_type, version DESC, created_at DESC;

-- ============================================================
-- View: Explanation Statistics
-- ============================================================

CREATE OR REPLACE VIEW vw_llm_explanation_stats AS
SELECT
    DATE(created_at) as date,
    explanation_type,
    model_name,
    COUNT(*) as total_explanations,
    COUNT(DISTINCT detection_id) as unique_detections,
    AVG(total_tokens) as avg_tokens,
    SUM(cost_usd) as total_cost_usd,
    AVG(latency_ms) as avg_latency_ms,
    AVG(confidence_score) as avg_confidence,
    COUNT(CASE WHEN anomaly_classification = 'true_positive' THEN 1 END) as true_positives,
    COUNT(CASE WHEN anomaly_classification = 'false_positive' THEN 1 END) as false_positives,
    COUNT(CASE WHEN human_feedback = 'helpful' THEN 1 END) as helpful_count,
    COUNT(CASE WHEN human_feedback = 'not_helpful' THEN 1 END) as not_helpful_count
FROM llm_explanations
GROUP BY DATE(created_at), explanation_type, model_name
ORDER BY date DESC, explanation_type;

-- ============================================================
-- Comments
-- ============================================================

COMMENT ON TABLE llm_explanations IS 'Versioned storage of LLM-generated anomaly explanations';
COMMENT ON COLUMN llm_explanations.detection_id IS 'References enriched_anomalies.detection_id';
COMMENT ON COLUMN llm_explanations.version IS 'Explanation version for same detection (increments when regenerated)';
COMMENT ON COLUMN llm_explanations.anomaly_classification IS 'LLM assessment: true_positive, false_positive, uncertain, benign';
COMMENT ON COLUMN llm_explanations.grounding_score IS 'How well explanation is grounded in provided data (0-1)';
COMMENT ON COLUMN llm_explanations.hallucination_risk IS 'Risk of hallucinated information: LOW, MEDIUM, HIGH';

-- ============================================================
-- Grant Permissions
-- ============================================================

GRANT SELECT, INSERT, UPDATE ON llm_explanations TO dfp_ai;
GRANT USAGE, SELECT ON SEQUENCE llm_explanations_id_seq TO dfp_ai;
GRANT SELECT ON vw_latest_llm_explanations TO dfp_ai;
GRANT SELECT ON vw_llm_explanation_stats TO dfp_ai;
