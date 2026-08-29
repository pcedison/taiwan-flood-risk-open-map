-- Keep the scheduled retention pass bounded as evidence history grows.
--
-- The evidence index supports the official realtime prune query without
-- changing which event types are eligible for deletion. The raw snapshot
-- index orders rows by their already-persisted per-source-family expiry time.
-- Both indexes are operational only: no row, source gate, or scoring rule is
-- changed by this migration.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_evidence_official_retention_cutoff_event
    ON evidence (
        (COALESCE(observed_at, ingested_at, created_at)),
        event_type
    )
    WHERE source_type = 'official';

CREATE INDEX IF NOT EXISTS idx_raw_snapshots_retention_expires_at
    ON raw_snapshots (retention_expires_at)
    WHERE retention_expires_at IS NOT NULL;

-- The raw-snapshot foreign key uses ON DELETE SET NULL. Cover every retained
-- staging status so expiry never scans the entire staging audit table once per
-- snapshot; the existing accepted-only index remains optimized for promotion.
CREATE INDEX IF NOT EXISTS idx_staging_evidence_raw_snapshot_id
    ON staging_evidence (raw_snapshot_id)
    WHERE raw_snapshot_id IS NOT NULL;

COMMIT;
