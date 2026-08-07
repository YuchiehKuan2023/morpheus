-- Rollback: Drop LLM Explanations Table
-- Reverses: 002_create_llm_explanations_table.sql

DROP TABLE IF EXISTS llm_explanations;
