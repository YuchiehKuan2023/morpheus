-- 030: Add simulated column to enriched_anomalies
-- Marks which anomalies were detected during simulation vs. real data.
-- Provenance: _simulation_session_id is injected by SimulationScheduler into
-- original_event for every simulated anomaly, making this deterministic and
-- environment-agnostic.

ALTER TABLE enriched_anomalies
    ADD COLUMN simulated BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill from deterministic provenance marker
UPDATE enriched_anomalies
   SET simulated = TRUE
 WHERE original_event->>'_simulation_session_id' IS NOT NULL;
