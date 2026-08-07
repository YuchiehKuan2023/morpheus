-- Migration: Add avatar_url to monitored_users and analyst_users
-- Version: 011
-- Date: 2026-03-18
-- Description: Adds an optional avatar_url column to both user tables.
--              When populated, the frontend will display the image instead
--              of the generated avatar_initials fallback.

ALTER TABLE monitored_users
    ADD COLUMN IF NOT EXISTS avatar_url TEXT;

ALTER TABLE analyst_users
    ADD COLUMN IF NOT EXISTS avatar_url TEXT;
