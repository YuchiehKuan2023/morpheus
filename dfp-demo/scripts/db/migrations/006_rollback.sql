-- Rollback 006: Drop dfp_retrain_jobs table

DROP TRIGGER IF EXISTS trg_dfp_retrain_jobs_updated_at ON dfp_retrain_jobs;
DROP FUNCTION IF EXISTS update_dfp_retrain_jobs_updated_at();
DROP TABLE IF EXISTS dfp_retrain_jobs;

DELETE FROM schema_migrations WHERE version = '006';
