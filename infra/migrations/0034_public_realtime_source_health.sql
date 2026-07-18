-- Public realtime source health reads the latest ingestion attempt by adapter
-- on every risk assessment. Keep that lookup bounded as ingestion_jobs grows.
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_adapter_created
    ON ingestion_jobs (adapter_key, created_at DESC, id DESC)
    WHERE adapter_key IS NOT NULL;

-- A later-started cycle remains authoritative even if an older overlapping
-- cycle finishes and writes after it.
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_adapter_started
    ON ingestion_jobs (
        adapter_key,
        (COALESCE(started_at, created_at)) DESC,
        created_at DESC,
        id DESC
    )
    WHERE adapter_key IS NOT NULL;

-- A non-empty latest table is not proof that a national station inventory is
-- complete.  These gates stay false/null until an adapter has a reviewed full-
-- snapshot contract and a conservative minimum station baseline.  The public
-- API additionally requires a clean, non-partial latest run before exposing
-- inventory_complete=true.
ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS station_inventory_reviewed boolean NOT NULL DEFAULT false;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS station_inventory_min_count integer;

-- The persisted is_enabled flag is deployment metadata, not proof of the
-- worker's current environment selection.  Workers refresh these public-safe
-- snapshots every scheduler/producer tick so disabled and stalled remain
-- distinguishable without exposing environment values.
ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_enabled boolean;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_enabled_checked_at timestamptz;

-- Fetch/staging success is recorded before promotion.  Keep the final
-- fetch-to-latest-read-model outcome separately so a promotion/queue failure
-- cannot be reported as a healthy source.
ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_pipeline_status text;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_pipeline_checked_at timestamptz;

-- Correlate the final outcome to the exact ingestion attempt.  Pre-fetch
-- failures use their cycle generation timestamp because they have no
-- ingestion_jobs row. checked_at alone is insufficient when overlapping
-- workers finish out of order.
ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_pipeline_run_at timestamptz;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS runtime_pipeline_complete boolean NOT NULL DEFAULT false;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'data_sources_station_inventory_min_count_check'
    ) THEN
        ALTER TABLE data_sources
            ADD CONSTRAINT data_sources_station_inventory_min_count_check
            CHECK (
                station_inventory_min_count IS NULL
                OR station_inventory_min_count > 0
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'data_sources_runtime_pipeline_status_check'
    ) THEN
        ALTER TABLE data_sources
            ADD CONSTRAINT data_sources_runtime_pipeline_status_check
            CHECK (
                runtime_pipeline_status IS NULL
                OR runtime_pipeline_status IN ('succeeded', 'failed')
            );
    END IF;
END
$$;

-- The token-gated Kinmen KWIS adapter exists in the worker registry but must
-- stay disabled until county authorization and redistribution approval exist.
-- Registering it here lets the public health contract report that honest
-- disabled state instead of silently omitting the source.
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
VALUES
    (
        'Kinmen KWIS pump station status',
        'local.kinmen.kwis_pump_station',
        'official',
        'County authorization required before production use',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '金門縣水情系統抽水站狀態',
            'owner_authority', 'Kinmen County Government',
            'license_name', 'County authorization required before production use',
            'tier', 'L3',
            'source_url', 'https://kwis.kinmen.gov.tw/',
            'notes', 'Disabled by default; the read API requires a county-reviewed token and redistribution approval.',
            'review_status', 'needs_authorization_request',
            'phase', 'local_realtime_sources'
        )
    )
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    legal_basis = EXCLUDED.legal_basis,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();
