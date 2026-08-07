-- Rollback: Drop conversational AI chat tables
-- Version: 016
DROP TABLE IF EXISTS chat_messages CASCADE;
DROP TABLE IF EXISTS chat_sessions CASCADE;
