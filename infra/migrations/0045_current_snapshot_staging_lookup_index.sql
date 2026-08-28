-- Managed ingestion promotes only rows attached to the raw snapshot fetched by
-- the current source cycle.  The raw snapshot is found by its unique raw_ref;
-- this partial index lets PostgreSQL reach that snapshot's accepted staging
-- rows without scanning every historical accepted row first.
--
-- The index changes no staging status, evidence, source gate, or public result.

CREATE INDEX IF NOT EXISTS idx_staging_evidence_accepted_raw_snapshot_id
    ON staging_evidence (raw_snapshot_id)
    WHERE validation_status = 'accepted'
        AND raw_snapshot_id IS NOT NULL;
