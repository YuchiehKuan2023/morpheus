-- Rollback: Remove authentication columns from analyst_users
-- Version: 018

ALTER TABLE analyst_users
    DROP COLUMN IF EXISTS password_hash,
    DROP COLUMN IF EXISTS last_login_at,
    DROP COLUMN IF EXISTS last_logout_at,
    DROP COLUMN IF EXISTS failed_login_count,
    DROP COLUMN IF EXISTS locked_until,
    DROP COLUMN IF EXISTS password_changed_at;
