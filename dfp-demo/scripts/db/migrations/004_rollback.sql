-- Rollback: Convert evidence_summary back to TEXT
-- Description: Revert evidence_summary from JSONB to TEXT format
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-27

-- ============================================================
-- Rollback 004: Revert evidence_summary to TEXT
-- Purpose: Rollback structured evidence migration if needed
-- ============================================================

-- Step 1: Drop GIN index if exists
DROP INDEX IF EXISTS idx_llm_explanations_evidence_summary;

-- Step 2: Add new TEXT column
ALTER TABLE llm_explanations 
ADD COLUMN evidence_summary_text TEXT;

-- Step 3: Convert JSONB back to TEXT
-- (Extract descriptions from structured evidence objects)
UPDATE llm_explanations 
SET evidence_summary_text = 
    CASE 
        WHEN evidence_summary IS NULL THEN NULL
        ELSE (
            SELECT string_agg(item->>'description', E'\n')
            FROM jsonb_array_elements(evidence_summary) AS item
        )
    END;

-- Step 4: Drop JSONB column
ALTER TABLE llm_explanations 
DROP COLUMN evidence_summary;

-- Step 5: Rename TEXT column back to original name
ALTER TABLE llm_explanations 
RENAME COLUMN evidence_summary_text TO evidence_summary;

-- Step 6: Restore original comment
COMMENT ON COLUMN llm_explanations.evidence_summary IS 
'Key evidence used in analysis';

-- Verification query (uncomment to test)
-- SELECT 
--     detection_id,
--     evidence_summary,
--     length(evidence_summary) as text_length
-- FROM llm_explanations
-- WHERE evidence_summary IS NOT NULL
-- LIMIT 5;
