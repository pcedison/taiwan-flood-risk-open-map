-- Register and enable the reviewed WRA historical flood-footprint source.
--
-- The adapter and complete-replace snapshot contract were shipped before its
-- persisted source-catalog row. That allowed a run to fetch and normalize the
-- official KML while promotion resolved a NULL data_source_id, leaving the
-- public API unable to join the rows back to an enabled source. Keep this row
-- idempotent and preserve the active snapshot marker managed by ingestion.

INSERT INTO data_sources (
    name,
    adapter_key,
    source_type,
    license,
    update_frequency,
    health_status,
    legal_basis,
    is_enabled,
    metadata
)
VALUES (
    'WRA historical flood footprints',
    'official.wra.historical_flood',
    'official',
    'Government Open Data License, version 1.0',
    'daily_checked_static',
    'unknown',
    'L1',
    true,
    jsonb_build_object(
        'label_zh', '經濟部水利署歷史淹水範圍',
        'owner_authority', 'Water Resources Agency',
        'source_url', 'https://data.gov.tw/dataset/25770',
        'resource_url', 'https://opendata.wra.gov.tw/api/v2/72d7aee9-e29b-49a2-bd0b-54acc8e3b75c',
        'license_name', 'Government Open Data License, version 1.0',
        'license_url', 'https://data.gov.tw/license',
        'dataset_id', '25770',
        'snapshot_generation_mode', 'complete_replace',
        'evidence_scope', 'historical',
        'scoring_use', 'historical_context',
        'spatial_review', 'reviewed',
        'review_status', 'ready',
        'limitation_zh', '歷史淹水範圍僅供背景風險參考，不代表目前正在淹水或官方即時警報。',
        'phase', 'historical_context_recovery'
    )
)
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();

-- Repair evidence written by the pre-fix promotion path. Those rows were
-- accepted with a NULL data_source_id, so the public repository's required
-- catalog join made all 1,075 production footprints invisible.
UPDATE evidence orphan
SET data_source_id = source.id,
    updated_at = now()
FROM data_sources source
WHERE source.adapter_key = 'official.wra.historical_flood'
    AND orphan.data_source_id IS NULL
    AND orphan.properties->>'adapter_key' = source.adapter_key;

-- A complete-replace source is public only through its active snapshot marker.
-- Select the newest repaired official snapshot deterministically; do nothing on
-- a clean install where the scheduler has not ingested a snapshot yet.
WITH latest_snapshot AS (
    SELECT evidence.raw_ref
    FROM evidence
    JOIN data_sources source ON source.id = evidence.data_source_id
    WHERE source.adapter_key = 'official.wra.historical_flood'
        AND evidence.ingestion_status = 'accepted'
        AND evidence.raw_ref IS NOT NULL
    GROUP BY evidence.raw_ref
    ORDER BY max(evidence.ingested_at) DESC, evidence.raw_ref DESC
    LIMIT 1
)
UPDATE data_sources source
SET metadata = jsonb_set(
        source.metadata,
        '{active_snapshot_raw_ref}',
        to_jsonb(latest_snapshot.raw_ref),
        true
    ),
    updated_at = now()
FROM latest_snapshot
WHERE source.adapter_key = 'official.wra.historical_flood';

-- Consume the already-promoted staging backlog using the same terminal reason
-- as the normal idempotent promotion path. This prevents every later cycle from
-- reconsidering the 1,075 repaired rows indefinitely.
UPDATE staging_evidence staging
SET validation_status = 'rejected',
    rejection_reason = 'idempotent_existing_evidence'
FROM raw_snapshots snapshot
WHERE staging.raw_snapshot_id = snapshot.id
    AND staging.validation_status = 'accepted'
    AND staging.payload->>'adapter_key' = 'official.wra.historical_flood'
    AND EXISTS (
        SELECT 1
        FROM evidence promoted
        JOIN data_sources source ON source.id = promoted.data_source_id
        WHERE source.adapter_key = 'official.wra.historical_flood'
            AND promoted.source_id = staging.source_id
            AND promoted.raw_ref IS NOT DISTINCT FROM snapshot.raw_ref
    );
