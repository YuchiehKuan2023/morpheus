-- Migration: Add authentication columns to analyst_users
-- Version: 018
-- Date: 2026-04-28
-- Description: Extends analyst_users with password hash, login tracking, and
--              session metadata to support JWT-based authentication.
--              Only analyst_users can log in — monitored_users are data subjects,
--              not platform users.

ALTER TABLE analyst_users
    ADD COLUMN IF NOT EXISTS password_hash      TEXT,
    ADD COLUMN IF NOT EXISTS last_login_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_logout_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failed_login_count INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;
