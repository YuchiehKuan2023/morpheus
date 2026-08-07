-- Migration: Create conversational AI chat tables
-- Version: 016
-- Date: 2026-04-23
-- Description: Persistent store for Conversational AI chat sessions and messages.
--              chat_sessions: one row per conversation.
--              chat_messages: one row per user/assistant turn.

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'New Conversation',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          SERIAL  PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT    NOT NULL,
    tools_used  JSONB,   -- list of tool names invoked to answer this turn
    data        JSONB,   -- raw tool result payloads (capped per tool)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id  ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at  ON chat_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at  ON chat_sessions(updated_at DESC);
