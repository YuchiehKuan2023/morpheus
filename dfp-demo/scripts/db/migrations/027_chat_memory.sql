-- Migration 027: Chat Memory for Episodic Memory (Week 28)
-- Stores per-turn summaries so the agent can recall what was discussed
-- in earlier turns of the same session.

CREATE TABLE IF NOT EXISTS chat_memory (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    turn_number     INTEGER NOT NULL,
    query_summary   TEXT NOT NULL,
    answer_summary  TEXT,
    tools_used      TEXT[],
    entities_referenced TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (session_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_chat_memory_session
    ON chat_memory(session_id);

CREATE INDEX IF NOT EXISTS idx_chat_memory_entities
    ON chat_memory USING GIN(entities_referenced);
