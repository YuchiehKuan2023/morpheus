-- Rollback: Remove status, user_id, and is_pinned from chat_sessions
-- Version: 028

DROP INDEX IF EXISTS idx_chat_sessions_user_id;
DROP INDEX IF EXISTS idx_chat_sessions_status;

ALTER TABLE chat_sessions
    DROP COLUMN IF EXISTS is_pinned,
    DROP COLUMN IF EXISTS user_id,
    DROP COLUMN IF EXISTS status;
