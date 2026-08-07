-- Migration 023: Backfill analyst_verdict, analyst_notes, reviewed_by, reviewed_at
-- for anomalies that were resolved by the seed script (have resolution_notes
-- and assigned_to but no analyst_verdict).
--
-- Sets analyst_verdict = 'confirmed' (they were marked resolved),
-- analyst_notes = resolution_notes, reviewed_by = assigned_to,
-- reviewed_at = resolved_at.

UPDATE enriched_anomalies
SET analyst_verdict = 'confirmed',
    analyst_notes   = resolution_notes,
    reviewed_by     = assigned_to,
    reviewed_at     = resolved_at,
    updated_at      = NOW()
WHERE status = 'resolved'
  AND resolution_notes IS NOT NULL
  AND analyst_verdict IS NULL;
