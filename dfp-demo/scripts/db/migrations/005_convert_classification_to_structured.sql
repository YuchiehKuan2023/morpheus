-- Migration: Convert anomaly_classification to structured JSONB format
-- Description: Change from simple string to structured object with threat types
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-27

-- ============================================================
-- Migration 005: Structured Anomaly Classification
-- Purpose: Support detailed threat classification with taxonomy
-- ============================================================

-- Step 1: Drop dependent views that reference anomaly_classification
DROP VIEW IF EXISTS vw_latest_llm_explanations CASCADE;
DROP VIEW IF EXISTS vw_llm_explanation_stats CASCADE;

-- Step 2: Drop the CHECK constraint that validates old string values
ALTER TABLE llm_explanations 
DROP CONSTRAINT IF EXISTS valid_classification;

-- Step 2: Add new JSONB column for structured classification
ALTER TABLE llm_explanations 
ADD COLUMN anomaly_classification_jsonb JSONB;

-- Step 3: Migrate existing TEXT data to structured JSONB
-- Convert: "true_positive" → {"positive": true, "threat_types": null}
-- Convert: "false_positive" → {"positive": false, "threat_types": null}
-- Convert: "uncertain" → {"positive": null, "threat_types": null}
UPDATE llm_explanations 
SET anomaly_classification_jsonb = 
    CASE 
        WHEN anomaly_classification = 'true_positive' THEN 
            '{"positive": true, "threat_types": null}'::jsonb
        WHEN anomaly_classification = 'false_positive' THEN 
            '{"positive": false, "threat_types": null}'::jsonb
        WHEN anomaly_classification = 'uncertain' THEN 
            '{"positive": null, "threat_types": null}'::jsonb
        WHEN anomaly_classification = 'benign' THEN 
            '{"positive": false, "threat_types": null}'::jsonb
        WHEN anomaly_classification IS NULL THEN 
            NULL
        ELSE 
            '{"positive": null, "threat_types": null}'::jsonb
    END;

-- Step 4: Drop old TEXT column
ALTER TABLE llm_explanations 
DROP COLUMN anomaly_classification;

-- Step 5: Rename new column to original name
ALTER TABLE llm_explanations 
RENAME COLUMN anomaly_classification_jsonb TO anomaly_classification;

-- Step 6: Add index for JSON queries (GIN index for JSONB)
CREATE INDEX idx_llm_explanations_classification_positive 
ON llm_explanations USING btree ((anomaly_classification->>'positive'));

CREATE INDEX idx_llm_explanations_threat_types 
ON llm_explanations USING gin((anomaly_classification->'threat_types'));

-- Step 7: Add comment explaining new structure
COMMENT ON COLUMN llm_explanations.anomaly_classification IS 
'Structured threat classification in JSONB format:
{
  "positive": true|false|null,  -- true=true_positive, false=false_positive, null=uncertain
  "threat_types": [              -- array of threat type strings (or null for false positives)
    "account_takeover",
    "impossible_travel",
    "credential_stuffing",
    ...
  ]
}

Threat types from taxonomy:
- Identity & Access: account_takeover, compromised_credentials, credential_stuffing, brute_force_attack, session_hijacking
- Movement & Access: impossible_travel, suspicious_location, unusual_time_access, lateral_movement, privilege_escalation
- Application Abuse: unauthorized_application_access, data_exfiltration, api_abuse, resource_abuse
- Insider Threats: insider_threat_behavioral, policy_violation, data_hoarding
- Advanced: reconnaissance, persistence_attempt, malware_indicator, command_and_control
- Device: unknown_device, device_anomaly, browser_automation';

-- Step 8: Recreate views with updated JSONB structure
-- ============================================================
-- View: Latest Explanations (updated for JSONB classification)
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
-- View: Explanation Statistics (updated for JSONB classification)
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
    COUNT(CASE WHEN (anomaly_classification->>'positive')::boolean = true THEN 1 END) as true_positives,
    COUNT(CASE WHEN (anomaly_classification->>'positive')::boolean = false THEN 1 END) as false_positives,
    COUNT(CASE WHEN anomaly_classification->>'positive' IS NULL THEN 1 END) as uncertain,
    COUNT(CASE WHEN human_feedback = 'helpful' THEN 1 END) as helpful_count,
    COUNT(CASE WHEN human_feedback = 'not_helpful' THEN 1 END) as not_helpful_count
FROM llm_explanations
GROUP BY DATE(created_at), explanation_type, model_name
ORDER BY date DESC, explanation_type;

COMMENT ON VIEW vw_llm_explanation_stats IS 'Daily statistics with structured classification support (positive field extraction)';

-- Step 9: Grant permissions on recreated views
GRANT SELECT ON vw_latest_llm_explanations TO dfp_ai;
GRANT SELECT ON vw_llm_explanation_stats TO dfp_ai;

-- Verification query (uncomment to test)
-- SELECT 
--     detection_id,
--     jsonb_pretty(anomaly_classification) as classification,
--     anomaly_classification->>'positive' as is_positive,
--     anomaly_classification->'threat_types' as threats
-- FROM llm_explanations
-- WHERE anomaly_classification IS NOT NULL
-- ORDER BY created_at DESC
-- LIMIT 10;
