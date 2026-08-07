-- Migration Rollback: Remove user_baseline_used column from LLM Explanations Table
-- Description: Rollback for 003_add_user_baseline_to_llm_explanations.sql
-- Author: AI Intelligence Layer Team
-- Date: 2026-02-24

-- ============================================================
-- Table: llm_explanations
-- Purpose: Revert user_baseline_used column addition
-- ============================================================

-- Drop the GIN index
DROP INDEX IF EXISTS idx_llm_explanations_user_baseline_used;

-- Remove the user_baseline_used column
ALTER TABLE llm_explanations
DROP COLUMN IF EXISTS user_baseline_used;

-- Rollback summary
-- Removed: user_baseline_used JSONB column
-- Removed: GIN index on user_baseline_used
