-- Persist the official rolling recent-years flood-disaster point source and
-- retain per-source county/year checks before aggregating the public ledger.
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
    'NSTC nationwide recent flood-disaster points',
    'official.nstc.flood_disaster_points',
    'official',
    'Government Open Data License, version 1.0',
    'irregular rolling recent-years snapshot; worker checks daily',
    'unknown',
    'L1',
    true,
    jsonb_build_object(
        'label_zh', '國科會近5年淹水災點資料',
        'owner_authority', 'National Science and Technology Council',
        'data_gov_dataset_id', '130016',
        'source_url', 'https://data.gov.tw/dataset/130016',
        'resource_format', 'CSV',
        'coordinate_reference_system', 'TWD97 / TM2 zone 121',
        'evidence_scope', 'historical',
        'event_time_precision', 'year',
        'coverage_is_complete', false,
        'snapshot_generation_mode', 'complete_replace',
        'raw_snapshot_required', true,
        'review_status', 'ready',
        'limitation_zh', '來源是滾動近期年份點位快照；缺少點位不代表未曾淹水，且年份不可當成精確事件日期。'
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

INSERT INTO ingestion_readiness_sources (
    profile_key,
    adapter_key,
    coverage_kind,
    stale_after_seconds
)
VALUES (
    'production_backbone',
    'official.nstc.flood_disaster_points',
    'nationwide_history',
    90000
)
ON CONFLICT (profile_key, adapter_key) DO UPDATE SET
    coverage_kind = EXCLUDED.coverage_kind,
    stale_after_seconds = EXCLUDED.stale_after_seconds,
    updated_at = now();

CREATE TABLE IF NOT EXISTS historical_coverage_source_checks (
    jurisdiction_code text NOT NULL,
    coverage_year integer NOT NULL,
    adapter_key text NOT NULL,
    status text NOT NULL,
    record_count integer NOT NULL DEFAULT 0,
    attempted_at timestamptz NOT NULL,
    succeeded_at timestamptz,
    review_ref text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (jurisdiction_code, coverage_year, adapter_key),
    FOREIGN KEY (jurisdiction_code, coverage_year)
        REFERENCES historical_coverage_cells(jurisdiction_code, coverage_year)
        ON DELETE CASCADE,
    FOREIGN KEY (adapter_key)
        REFERENCES data_sources(adapter_key)
        ON DELETE RESTRICT,
    CHECK (coverage_year BETWEEN 2018 AND 2100),
    CHECK (status IN ('succeeded', 'failed')),
    CHECK (record_count >= 0),
    CHECK (btrim(review_ref) <> ''),
    CHECK (succeeded_at IS NULL OR succeeded_at <= updated_at),
    CHECK (
        (status = 'succeeded' AND succeeded_at IS NOT NULL)
        OR (status = 'failed' AND succeeded_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_historical_coverage_source_checks_status
    ON historical_coverage_source_checks (
        status,
        coverage_year,
        jurisdiction_code,
        adapter_key
    );

COMMENT ON TABLE historical_coverage_source_checks IS
    'Per-source county/year audit rows used to aggregate the fail-closed historical coverage ledger.';
