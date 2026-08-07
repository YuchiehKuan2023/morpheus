-- Migration 024: Consolidate anomaly status model
--
-- OLD statuses: pending, investigating, resolved, false_positive
-- NEW statuses: new, pending, resolved
--
-- Mapping:
--   investigating (no assignee)  → new
--   investigating (has assignee) → pending  (shouldn't exist, but handle it)
--   pending (no assignee)        → new
--   pending (has assignee)       → pending  (no change)
--   false_positive (no verdict)  → resolved (backfill analyst_verdict)
--   false_positive (has verdict) → resolved
--   resolved                     → resolved (no change)
--
-- is_anomaly is NEVER touched — it's the AI's classification.
-- analyst_verdict tracks the human decision independently.

-- Step 1: Drop old CHECK constraint so we can write 'new' values
ALTER TABLE enriched_anomalies
    DROP CONSTRAINT IF EXISTS enriched_anomalies_status_check;

-- Step 2: Remap data

-- investigating without assignee → new
UPDATE enriched_anomalies
SET status     = 'new',
    updated_at = NOW()
WHERE status = 'investigating'
  AND assigned_to IS NULL;

-- investigating with assignee → pending
UPDATE enriched_anomalies
SET status     = 'pending',
    updated_at = NOW()
WHERE status = 'investigating'
  AND assigned_to IS NOT NULL;

-- pending without assignee → new
UPDATE enriched_anomalies
SET status     = 'new',
    updated_at = NOW()
WHERE status = 'pending'
  AND assigned_to IS NULL;

-- false_positive without analyst_verdict → resolved + backfill verdict
UPDATE enriched_anomalies
SET status          = 'resolved',
    analyst_verdict = 'false_positive',
    analyst_notes   = COALESCE(analyst_notes, resolution_notes),
    resolution_notes= COALESCE(resolution_notes, analyst_notes),
    reviewed_by     = COALESCE(reviewed_by, assigned_to),
    reviewed_at     = COALESCE(reviewed_at, resolved_at, updated_at),
    resolved_at     = COALESCE(resolved_at, updated_at),
    updated_at      = NOW()
WHERE status = 'false_positive'
  AND analyst_verdict IS NULL;

-- false_positive with analyst_verdict already set → just fix status
UPDATE enriched_anomalies
SET status     = 'resolved',
    resolved_at= COALESCE(resolved_at, reviewed_at, updated_at),
    updated_at = NOW()
WHERE status = 'false_positive'
  AND analyst_verdict IS NOT NULL;

-- Step 3: Add new CHECK constraint
ALTER TABLE enriched_anomalies
    ADD CONSTRAINT enriched_anomalies_status_check
    CHECK (status IN ('new', 'pending', 'resolved'));

-- Step 4: Change DEFAULT from 'pending' to 'new'
ALTER TABLE enriched_anomalies
    ALTER COLUMN status SET DEFAULT 'new';
