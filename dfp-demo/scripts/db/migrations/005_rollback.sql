-- Rollback: Convert anomaly_classification back to TEXT
-- Description: Revert structured JSONB to simple string format
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-27

-- ============================================================
-- Rollback 005: Revert Structured Classification
-- Purpose: Restore simple string classification if needed
-- ============================================================

-- Step 1: Drop dependent views
DROP VIEW IF EXISTS vw_latest_llm_explanations CASCADE;
DROP VIEW IF EXISTS vw_llm_explanation_stats CASCADE;

-- Step 2: Drop GIN index on threat_types
DROP INDEX IF EXISTS idx_llm_explanations_threat_types;

-- Step 3: Drop btree index on positive field
DROP INDEX IF EXISTS idx_llm_explanations_classification_positive;

-- Step 3: Add new TEXT column
ALTER TABLE llm_explanations 
ADD COLUMN anomaly_classification_text TEXT;

-- Step 4: Convert JSONB back to TEXT
-- {"positive": true, ...} → "true_positive"
-- {"positive": false, ...} → "false_positive"
-- {"positive": null, ...} → "uncertain"
UPDATE llm_explanations 
SET anomaly_classification_text = 
    CASE 
        WHEN anomaly_classification->>'positive' = 'true' THEN 'true_positive'
        WHEN anomaly_classification->>'positive' = 'false' THEN 'false_positive'
        WHEN anomaly_classification IS NULL THEN NULL
        ELSE 'uncertain'
    END;

-- Step 5: Drop JSONB column
ALTER TABLE llm_explanations 
DROP COLUMN anomaly_classification;

-- Step 6: Rename TEXT column back to original name
ALTER TABLE llm_explanations 
RENAME COLUMN anomaly_classification_text TO anomaly_classification;

-- Step 7: Restore CHECK constraint
ALTER TABLE llm_explanations 
ADD CONSTRAINT valid_classification 
CHECK (anomaly_classification IN ('true_positive', 'false_positive', 'uncertain', 'benign', NULL));

-- Step 8: Recreate original index
CREATE INDEX idx_llm_explanations_classification 
ON llm_explanations(anomaly_classification);

-- Step 9: Restore original comment
COMMENT ON COLUMN llm_explanations.anomaly_classification IS 
'LLM assessment: true_positive, false_positive, uncertain, benign';

-- Step 10: Recreate original views with TEXT classification
-- ============================================================
-- View: Latest Explanations (original TEXT format)
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
-- View: Explanation Statistics (original TEXT format)
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

-- Step 11: Grant permissions on recreated views
GRANT SELECT ON vw_latest_llm_explanations TO dfp_ai;
GRANT SELECT ON vw_llm_explanation_stats TO dfp_ai;

-- Verification query (uncomment to test)
-- SELECT 
--     detection_id,
--     anomaly_classification,
--     COUNT(*) as count
-- FROM llm_explanations
-- WHERE anomaly_classification IS NOT NULL
-- GROUP BY anomaly_classification
-- ORDER BY count DESC;
