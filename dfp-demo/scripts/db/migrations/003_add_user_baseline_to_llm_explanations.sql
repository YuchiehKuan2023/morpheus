-- Migration: Add user_baseline_used column to LLM Explanations Table
-- Description: Add JSONB column to store user training baseline data used in LLM analysis
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-24

-- ============================================================
-- Table: llm_explanations
-- Purpose: Add user_baseline_used to store training profile context
-- ============================================================

-- Add user_baseline_used column to store training baseline (normal behavior profile)
ALTER TABLE llm_explanations
ADD COLUMN IF NOT EXISTS user_baseline_used JSONB;

-- Add comment explaining the column purpose
COMMENT ON COLUMN llm_explanations.user_baseline_used IS 
'User training baseline data used in LLM analysis. Contains: total_events, baseline_strength, 
apps_count, devices_count, locations_count, top_apps, top_devices, top_locations. 
This represents the user''s NORMAL behavior profile from training data, used for comparison 
against anomalous behavior.';

-- Create index for JSONB queries (if needed for filtering/searching)
CREATE INDEX IF NOT EXISTS idx_llm_explanations_user_baseline_used 
ON llm_explanations USING GIN (user_baseline_used);

-- Migration summary
-- Added: user_baseline_used JSONB column
-- Added: Comment documentation
-- Added: GIN index for efficient JSONB queries
