CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS data_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    adapter_key text NOT NULL UNIQUE,
    source_type text NOT NULL CHECK (
        source_type IN ('official', 'news', 'forum', 'social', 'user_report', 'derived')
    ),
    license text,
    update_frequency text,
    last_success_at timestamptz,
    last_failure_at timestamptz,
    health_status text NOT NULL DEFAULT 'unknown' CHECK (
        health_status IN ('healthy', 'degraded', 'failed', 'disabled', 'unknown')
    ),
    legal_basis text NOT NULL DEFAULT 'L1' CHECK (legal_basis IN ('L1', 'L2', 'L3', 'L4', 'L5')),
    source_timestamp_min timestamptz,
    source_timestamp_max timestamptz,
    is_enabled boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_source_id uuid REFERENCES data_sources(id) ON DELETE SET NULL,
    adapter_key text NOT NULL,
    raw_ref text NOT NULL UNIQUE,
    storage_uri text,
    content_hash text,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    source_timestamp_min timestamptz,
    source_timestamp_max timestamptz,
    retention_expires_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS staging_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_snapshot_id uuid REFERENCES raw_snapshots(id) ON DELETE SET NULL,
    data_source_id uuid REFERENCES data_sources(id) ON DELETE SET NULL,
    source_id text,
    source_type text NOT NULL CHECK (
        source_type IN ('official', 'news', 'forum', 'social', 'user_report', 'derived')
    ),
    event_type text NOT NULL CHECK (
        event_type IN (
            'rainfall',
            'water_level',
            'flood_warning',
            'flood_potential',
            'flood_report',
            'road_closure',
            'discussion'
        )
    ),
    title text NOT NULL,
    summary text NOT NULL,
    url text,
    occurred_at timestamptz,
    observed_at timestamptz,
    geom geometry(Geometry, 4326),
    confidence numeric(6,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    validation_status text NOT NULL DEFAULT 'pending' CHECK (
        validation_status IN ('pending', 'accepted', 'rejected', 'quarantined')
    ),
    rejection_reason text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_source_id uuid REFERENCES data_sources(id) ON DELETE SET NULL,
    source_id text NOT NULL,
    source_type text NOT NULL CHECK (
        source_type IN ('official', 'news', 'forum', 'social', 'user_report', 'derived')
    ),
    event_type text NOT NULL CHECK (
        event_type IN (
            'rainfall',
            'water_level',
            'flood_warning',
            'flood_potential',
            'flood_report',
            'road_closure',
            'discussion'
        )
    ),
    title text NOT NULL,
    summary text NOT NULL,
    url text,
    occurred_at timestamptz,
    observed_at timestamptz,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Geometry, 4326),
    distance_to_query_m numeric(10,2),
    confidence numeric(6,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    freshness_score numeric(6,3) CHECK (
        freshness_score IS NULL OR (freshness_score >= 0 AND freshness_score <= 1)
    ),
    source_weight numeric(6,3) CHECK (source_weight IS NULL OR source_weight >= 0),
    privacy_level text NOT NULL DEFAULT 'public' CHECK (
        privacy_level IN ('public', 'aggregated', 'redacted')
    ),
    raw_ref text,
    ingestion_status text NOT NULL DEFAULT 'accepted' CHECK (
        ingestion_status IN ('accepted', 'rejected', 'expired')
    ),
    properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (distance_to_query_m IS NULL OR distance_to_query_m >= 0)
);

CREATE TABLE IF NOT EXISTS location_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    input_type text NOT NULL CHECK (input_type IN ('address', 'map_click', 'parcel', 'landmark')),
    raw_input text,
    geom geometry(Point, 4326) NOT NULL,
    radius_m integer NOT NULL DEFAULT 500 CHECK (radius_m > 0),
    privacy_bucket text,
    h3_index text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id uuid NOT NULL REFERENCES location_queries(id) ON DELETE CASCADE,
    score_version text NOT NULL,
    realtime_score numeric(6,3),
    historical_score numeric(6,3),
    confidence_score numeric(6,3),
    risk_level_realtime text NOT NULL DEFAULT 'unknown' CHECK (
        risk_level_realtime IN ('low', 'medium', 'high', 'severe', 'unknown')
    ),
    risk_level_historical text NOT NULL DEFAULT 'unknown' CHECK (
        risk_level_historical IN ('low', 'medium', 'high', 'severe', 'unknown')
    ),
    explanation jsonb NOT NULL DEFAULT '{}'::jsonb,
    data_freshness jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    CHECK (realtime_score IS NULL OR (realtime_score >= 0 AND realtime_score <= 100)),
    CHECK (historical_score IS NULL OR (historical_score >= 0 AND historical_score <= 100)),
    CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1))
);

CREATE TABLE IF NOT EXISTS risk_assessment_evidence (
    risk_assessment_id uuid NOT NULL REFERENCES risk_assessments(id) ON DELETE CASCADE,
    evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    relevance_score numeric(6,3),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (risk_assessment_id, evidence_id),
    CHECK (relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1))
);

CREATE TABLE IF NOT EXISTS query_heat_buckets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    h3_index text NOT NULL,
    period text NOT NULL,
    period_started_at timestamptz NOT NULL,
    query_count integer NOT NULL DEFAULT 0 CHECK (query_count >= 0),
    unique_approx_count integer NOT NULL DEFAULT 0 CHECK (unique_approx_count >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (h3_index, period, period_started_at)
);

CREATE TABLE IF NOT EXISTS map_layers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id text NOT NULL UNIQUE,
    name text NOT NULL,
    description text,
    category text NOT NULL CHECK (
        category IN ('flood_potential', 'rainfall', 'water_level', 'warning', 'evidence', 'query_heat')
    ),
    status text NOT NULL DEFAULT 'disabled' CHECK (status IN ('available', 'degraded', 'disabled')),
    minzoom integer CHECK (minzoom IS NULL OR (minzoom >= 0 AND minzoom <= 24)),
    maxzoom integer CHECK (maxzoom IS NULL OR (maxzoom >= 0 AND maxzoom <= 24)),
    attribution text,
    tilejson_url text NOT NULL,
    updated_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (minzoom IS NULL OR maxzoom IS NULL OR minzoom <= maxzoom)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_key text NOT NULL,
    adapter_key text,
    started_at timestamptz,
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'skipped', 'disabled')
    ),
    items_fetched integer NOT NULL DEFAULT 0 CHECK (items_fetched >= 0),
    items_promoted integer NOT NULL DEFAULT 0 CHECK (items_promoted >= 0),
    items_rejected integer NOT NULL DEFAULT 0 CHECK (items_rejected >= 0),
    error_code text,
    error_message text,
    source_timestamp_min timestamptz,
    source_timestamp_max timestamptz,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS adapter_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_job_id uuid REFERENCES ingestion_jobs(id) ON DELETE SET NULL,
    adapter_key text NOT NULL,
    data_source_id uuid REFERENCES data_sources(id) ON DELETE SET NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'succeeded', 'failed', 'partial')
    ),
    items_fetched integer NOT NULL DEFAULT 0 CHECK (items_fetched >= 0),
    items_promoted integer NOT NULL DEFAULT 0 CHECK (items_promoted >= 0),
    items_rejected integer NOT NULL DEFAULT 0 CHECK (items_rejected >= 0),
    raw_ref text,
    error_code text,
    error_message text,
    source_timestamp_min timestamptz,
    source_timestamp_max timestamptz,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS user_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    geom geometry(Point, 4326) NOT NULL,
    summary text NOT NULL,
    media_ref text,
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'approved', 'rejected', 'spam')
    ),
    privacy_level text NOT NULL DEFAULT 'redacted' CHECK (
        privacy_level IN ('public', 'aggregated', 'redacted')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_ref text,
    action text NOT NULL,
    subject_type text NOT NULL,
    subject_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_data_sources_adapter_key
    ON data_sources (adapter_key);

CREATE INDEX IF NOT EXISTS idx_data_sources_source_type
    ON data_sources (source_type);

CREATE INDEX IF NOT EXISTS idx_raw_snapshots_adapter_key
    ON raw_snapshots (adapter_key);

CREATE INDEX IF NOT EXISTS idx_staging_evidence_geom
    ON staging_evidence USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_staging_evidence_validation_status
    ON staging_evidence (validation_status);

CREATE INDEX IF NOT EXISTS idx_evidence_geom
    ON evidence USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_evidence_occurred_at
    ON evidence (occurred_at);

CREATE INDEX IF NOT EXISTS idx_evidence_source_type
    ON evidence (source_type);

CREATE INDEX IF NOT EXISTS idx_evidence_data_source_id
    ON evidence (data_source_id);

CREATE INDEX IF NOT EXISTS idx_location_queries_geom
    ON location_queries USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_location_queries_h3_index
    ON location_queries (h3_index);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_query_id
    ON risk_assessments (query_id);

CREATE INDEX IF NOT EXISTS idx_risk_assessment_evidence_evidence_id
    ON risk_assessment_evidence (evidence_id);

CREATE INDEX IF NOT EXISTS idx_query_heat_buckets_h3_index
    ON query_heat_buckets (h3_index);

CREATE INDEX IF NOT EXISTS idx_map_layers_status
    ON map_layers (status);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status
    ON ingestion_jobs (status);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_job_key
    ON ingestion_jobs (job_key);

CREATE INDEX IF NOT EXISTS idx_adapter_runs_adapter_key_started_at
    ON adapter_runs (adapter_key, started_at);

CREATE INDEX IF NOT EXISTS idx_user_reports_geom
    ON user_reports USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_audit_logs_subject
    ON audit_logs (subject_type, subject_id);
