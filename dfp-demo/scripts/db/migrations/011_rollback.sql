-- Migration: 011 Rollback — Drop avatar_url columns
-- Version: 011
-- Date: 2026-03-18

ALTER TABLE monitored_users DROP COLUMN IF EXISTS avatar_url;
ALTER TABLE analyst_users   DROP COLUMN IF EXISTS avatar_url;
