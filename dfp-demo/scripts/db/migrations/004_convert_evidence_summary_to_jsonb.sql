-- Migration: Convert evidence_summary to JSONB
-- Description: Change evidence_summary from TEXT to JSONB for structured evidence
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-27

-- ============================================================
-- Migration 004: Convert evidence_summary to JSONB
-- Purpose: Support structured evidence with JSON schema
-- ============================================================

-- Step 1: Add new JSONB column
ALTER TABLE llm_explanations 
ADD COLUMN evidence_summary_jsonb JSONB;

-- Step 2: Migrate existing TEXT data to JSONB
-- (Handle both NULL values and existing text entries)
UPDATE llm_explanations 
SET evidence_summary_jsonb = 
    CASE 
        WHEN evidence_summary IS NULL THEN NULL
        WHEN evidence_summary::text ~ '^\s*\[' THEN evidence_summary::jsonb  -- Already JSON array
        ELSE jsonb_build_array(
            jsonb_build_object(
                'type', 'legacy_text',
                'description', evidence_summary
            )
        )  -- Convert plain text to structured format
    END;

-- Step 3: Drop old TEXT column
ALTER TABLE llm_explanations 
DROP COLUMN evidence_summary;

-- Step 4: Rename new column to original name
ALTER TABLE llm_explanations 
RENAME COLUMN evidence_summary_jsonb TO evidence_summary;

-- Step 5: Add index for JSON queries (optional but recommended)
CREATE INDEX idx_llm_explanations_evidence_summary 
ON llm_explanations USING gin(evidence_summary);

-- Step 6: Add comment explaining structure
COMMENT ON COLUMN llm_explanations.evidence_summary IS 
'Structured evidence array in JSONB format. Each evidence item contains:
- type: metric_anomaly, baseline_mismatch, baseline_match, anomaly_score, historical_pattern, entity_risk, physical_impossibility, insufficient_data
- description (required): Human-readable evidence description
- Optional fields: metric, value, z_score, severity, category, threshold, threshold_ratio, reference_count, reference_scores';

-- Verification query (uncomment to test)
-- SELECT 
--     detection_id,
--     jsonb_pretty(evidence_summary) as formatted_evidence,
--     jsonb_array_length(evidence_summary) as evidence_count
-- FROM llm_explanations
-- WHERE evidence_summary IS NOT NULL
-- LIMIT 5;
