CREATE TABLE IF NOT EXISTS official_realtime_latest (
    source_id text NOT NULL,
    adapter_key text NOT NULL,
    event_type text NOT NULL,
    station_id text NOT NULL,
    station_name text,
    authority text,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point, 4326) NOT NULL,
    rainfall_mm_1h double precision,
    rainfall_mm_24h double precision,
    water_level_m double precision,
    warning_level_m double precision,
    flood_depth_cm double precision,
    confidence numeric(6,3),
    freshness_score numeric(6,3),
    source_weight numeric(6,3),
    risk_factor numeric(6,3),
    evidence_id uuid REFERENCES evidence(id) ON DELETE SET NULL,
    source_url text,
    attribution text,
    quality_flags jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adapter_key, event_type, station_id),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK (freshness_score IS NULL OR (freshness_score >= 0 AND freshness_score <= 1)),
    CHECK (source_weight IS NULL OR source_weight >= 0),
    CHECK (risk_factor IS NULL OR risk_factor >= 0)
);

CREATE INDEX IF NOT EXISTS idx_official_realtime_latest_geom
    ON official_realtime_latest USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_official_realtime_latest_event_observed
    ON official_realtime_latest (event_type, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_official_realtime_latest_source_observed
    ON official_realtime_latest (source_id, observed_at DESC);

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
        'Civil IoT flood sensor observations (Water Resources Agency)',
        'official.civil_iot.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '經濟部水利署 Civil IoT 淹水感測器',
            'owner_authority', 'Water Resources Agency',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://fhy.wra.gov.tw/fhyv2/',
            'notes', 'Disabled by default pending adapter delivery, schema validation, and legal review.',
            'review_status', 'pending',
            'phase', '2'
        )
    ),
    (
        'Civil IoT river water level observations (Water Resources Agency)',
        'official.civil_iot.river_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '經濟部水利署 Civil IoT 河川水位',
            'owner_authority', 'Water Resources Agency',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://fhy.wra.gov.tw/fhyv2/',
            'notes', 'Disabled by default pending adapter delivery, schema validation, and legal review.',
            'review_status', 'pending',
            'phase', '2'
        )
    ),
    (
        'Civil IoT pond water level observations (Water Resources Agency)',
        'official.civil_iot.pond_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '經濟部水利署 Civil IoT 池塘水位',
            'owner_authority', 'Water Resources Agency',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://fhy.wra.gov.tw/fhyv2/',
            'notes', 'Disabled by default pending adapter delivery, schema validation, and legal review.',
            'review_status', 'pending',
            'phase', '2'
        )
    ),
    (
        'Civil IoT sewer water level observations (Water Resources Agency)',
        'official.civil_iot.sewer_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '經濟部水利署 Civil IoT 下水道水位',
            'owner_authority', 'Water Resources Agency',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://fhy.wra.gov.tw/fhyv2/',
            'notes', 'Disabled by default pending adapter delivery, schema validation, and legal review.',
            'review_status', 'pending',
            'phase', '2'
        )
    ),
    (
        'Civil IoT pump water level observations (Water Resources Agency)',
        'official.civil_iot.pump_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '經濟部水利署 Civil IoT 抽水站水位',
            'owner_authority', 'Water Resources Agency',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://fhy.wra.gov.tw/fhyv2/',
            'notes', 'Disabled by default pending adapter delivery, schema validation, and legal review.',
            'review_status', 'pending',
            'phase', '2'
        )
    ),
    (
        'NCDR CAP alert feed (National Science and Technology Center for Disaster Reduction)',
        'official.ncdr.cap',
        'official',
        'CAP public alert terms pending confirmation',
        'event_driven',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '國家災害防救科技中心 CAP 示警',
            'owner_authority', 'National Science and Technology Center for Disaster Reduction',
            'license_name', 'CAP public alert terms pending confirmation',
            'tier', 'L1',
            'source_url', 'https://alerts.ncdr.nat.gov.tw/',
            'notes', 'Disabled by default pending CAP ingestion adapter, redistribution review, and alert deduplication rules.',
            'review_status', 'pending',
            'phase', '2'
        )
    ),
    (
        'Tainan City flood sensor observations (Tainan City Government)',
        'local.tainan.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '台南市政府淹水感測器',
            'owner_authority', 'Tainan City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://opendata.tainan.gov.tw/',
            'notes', 'Disabled by default pending local adapter delivery, field mapping review, and municipal data-sharing approval.',
            'review_status', 'pending',
            'phase', '2'
        )
    )
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    health_status = EXCLUDED.health_status,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();
