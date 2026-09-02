-- Keep one durable staging decision for each evidence identity in a raw
-- snapshot. Replaying the exact same content-addressed revision must not grow
-- staging_evidence indefinitely.
WITH ranked_staging AS MATERIALIZED (
    SELECT
        staging.id,
        row_number() OVER (
            PARTITION BY
                staging.raw_snapshot_id,
                staging.payload->>'evidence_id'
            ORDER BY
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM evidence promoted
                        WHERE promoted.properties->>'staging_evidence_id'
                            = staging.id::text
                    ) THEN 0
                    ELSE 1
                END,
                staging.created_at,
                staging.id
        ) AS duplicate_rank
    FROM staging_evidence staging
    WHERE staging.raw_snapshot_id IS NOT NULL
      AND NULLIF(staging.payload->>'evidence_id', '') IS NOT NULL
)
DELETE FROM staging_evidence duplicate
USING ranked_staging ranked
WHERE duplicate.id = ranked.id
  AND ranked.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_staging_evidence_snapshot_evidence_id
    ON staging_evidence (
        raw_snapshot_id,
        (payload->>'evidence_id')
    )
    WHERE raw_snapshot_id IS NOT NULL
      AND NULLIF(payload->>'evidence_id', '') IS NOT NULL;
