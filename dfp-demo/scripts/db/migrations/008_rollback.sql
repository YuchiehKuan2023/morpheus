-- Rollback 008: Drop user_training_events table
--
-- WARNING: This permanently deletes all seeded and feedback training events.
-- Export data first if it needs to be preserved.
--
-- Author:  AI Intelligence Layer Team

BEGIN;
DROP TABLE IF EXISTS user_training_events;
COMMIT;
