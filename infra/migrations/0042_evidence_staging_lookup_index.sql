-- Keep promotion idempotency lookups bounded as the public evidence table grows.
--
-- Every promotion candidate checks whether its staging row was already consumed.
-- Without this expression index, that per-candidate check scans the full evidence
-- table and can starve both ingestion and public risk requests under hosted load.
-- The index changes no evidence, source gate, or public contract semantics.

CREATE INDEX IF NOT EXISTS idx_evidence_staging_evidence_id
    ON evidence ((properties ->> 'staging_evidence_id'))
    WHERE properties ? 'staging_evidence_id';
