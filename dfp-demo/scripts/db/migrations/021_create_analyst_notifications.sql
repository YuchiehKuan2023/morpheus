-- Migration: Create analyst_notifications table
-- Version: 021
-- Date: 2026-04-28
-- Description: Stores notifications for analyst users (e.g. anomaly assigned).
--              Unread = seen_at IS NULL; marking as seen sets the timestamp.

CREATE TABLE IF NOT EXISTS analyst_notifications (
    id          SERIAL PRIMARY KEY,
    analyst_id  INTEGER NOT NULL REFERENCES analyst_users(id),
    anomaly_id  UUID REFERENCES enriched_anomalies(anomaly_id),
    type        VARCHAR(50) NOT NULL,
    title       TEXT NOT NULL,
    message     TEXT,
    seen_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Fast lookup: unread notifications for a user
CREATE INDEX idx_notifications_analyst_unseen
    ON analyst_notifications (analyst_id, seen_at)
    WHERE seen_at IS NULL;

-- Listing: all notifications for a user, newest first
CREATE INDEX idx_notifications_analyst_created
    ON analyst_notifications (analyst_id, created_at DESC);
