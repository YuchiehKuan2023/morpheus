-- Migration Rollback: Drop enriched_anomalies table
-- Version: 001
-- Date: 2026-02-19
-- Description: Rollback script to safely remove enriched_anomalies table

-- ============================================================================
-- DROP TRIGGERS
-- ============================================================================

DROP TRIGGER IF EXISTS trigger_set_dfp_retrain_status ON enriched_anomalies;
DROP TRIGGER IF EXISTS trigger_enriched_anomalies_updated_at ON enriched_anomalies;

-- ============================================================================
-- DROP FUNCTIONS
-- ============================================================================

DROP FUNCTION IF EXISTS set_dfp_retrain_status();
DROP FUNCTION IF EXISTS update_enriched_anomalies_updated_at();

-- ============================================================================
-- DROP INDEXES
-- ============================================================================

DROP INDEX IF EXISTS idx_enriched_anomalies_ai_enrichment_gin;
DROP INDEX IF EXISTS idx_enriched_anomalies_original_event_gin;
DROP INDEX IF EXISTS idx_enriched_anomalies_assigned;
DROP INDEX IF EXISTS idx_enriched_anomalies_status;
DROP INDEX IF EXISTS idx_enriched_anomalies_root_cause;
DROP INDEX IF EXISTS idx_enriched_anomalies_false_positives;
DROP INDEX IF EXISTS idx_enriched_anomalies_feedback_status;
DROP INDEX IF EXISTS idx_enriched_anomalies_validation_pending;
DROP INDEX IF EXISTS idx_enriched_anomalies_is_anomaly;
DROP INDEX IF EXISTS idx_enriched_anomalies_timestamp;
DROP INDEX IF EXISTS idx_enriched_anomalies_user_timestamp;

-- ============================================================================
-- DROP TABLE
-- ============================================================================

DROP TABLE IF EXISTS enriched_anomalies CASCADE;

-- ============================================================================
-- CONFIRMATION
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration 001 rolled back successfully';
END $$;
