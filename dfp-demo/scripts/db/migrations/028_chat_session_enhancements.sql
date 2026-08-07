-- Migration: Enhance chat_sessions with status, user ownership, and pinning
-- Version: 028
-- Date: 2026-05-01
-- Description: Add status (active/archived), user_id, and is_pinned to chat_sessions
--              to support filtering, per-user sessions, and conversation management.

ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    ADD COLUMN IF NOT EXISTS user_id    INTEGER REFERENCES analyst_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS is_pinned  BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_chat_sessions_status  ON chat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id);
