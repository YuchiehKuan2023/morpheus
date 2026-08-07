-- Migration: Add intent / confidence / sources columns to chat_messages
-- Version: 017
-- Date: 2026-04-24
-- Description: Persists the AI metadata (intent label, confidence score, source
--              category list) returned by Pass 0 intent analysis so that
--              conversation history can re-display the metadata panel on reload.

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS intent     TEXT,
    ADD COLUMN IF NOT EXISTS confidence INTEGER,
    ADD COLUMN IF NOT EXISTS sources    JSONB;   -- ordered list of source category strings
