-- Rollback 009: Revert source check constraint to seed/feedback only
--
-- NOTE: Any rows with source='clean' must be removed (or re-sourced)
--       before this rollback can succeed, because the new constraint
--       disallows that value.  Drop those rows if you don't need them:
--
--   DELETE FROM user_training_events WHERE source = 'clean';
--
-- Then apply this rollback.

BEGIN;

ALTER TABLE user_training_events
    DROP CONSTRAINT user_training_events_source_check;

ALTER TABLE user_training_events
    ADD CONSTRAINT user_training_events_source_check
        CHECK (source IN ('seed', 'feedback'));

COMMIT;
