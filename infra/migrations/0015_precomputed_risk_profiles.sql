CREATE TABLE IF NOT EXISTS admin_area_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    area_key text NOT NULL UNIQUE,
    scope text NOT NULL CHECK (scope IN ('county', 'town', 'village')),
    county_name text NOT NULL,
    town_name text,
    village_name text,
    geom geometry(Geometry, 4326) NOT NULL,
    centroid geometry(Point, 4326),
    profile_radius_m integer NOT NULL DEFAULT 2000 CHECK (profile_radius_m > 0),
    score_version text NOT NULL,
    realtime_level text NOT NULL DEFAULT 'unknown' CHECK (
        realtime_level IN ('low', 'medium', 'high', 'severe', 'unknown')
    ),
    historical_level text NOT NULL DEFAULT 'unknown' CHECK (
        historical_level IN ('low', 'medium', 'high', 'severe', 'unknown')
    ),
    confidence_level text NOT NULL DEFAULT 'unknown' CHECK (
        confidence_level IN ('low', 'medium', 'high', 'unknown')
    ),
    evidence_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    top_evidence_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    latest_observed_at timestamptz,
    latest_occurred_at timestamptz,
    latest_ingested_at timestamptz,
    coverage_gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'stale' CHECK (
        status IN ('healthy', 'stale', 'missing', 'disabled')
    ),
    computed_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at IS NULL OR expires_at > computed_at)
);

CREATE TABLE IF NOT EXISTS risk_grid_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    grid_key text NOT NULL UNIQUE,
    grid_system text NOT NULL CHECK (grid_system IN ('h3', 'geohash')),
    grid_resolution text NOT NULL,
    geom geometry(Geometry, 4326) NOT NULL,
    centroid geometry(Point, 4326),
    profile_radius_m integer NOT NULL DEFAULT 1000 CHECK (profile_radius_m > 0),
    score_version text NOT NULL,
    realtime_level text NOT NULL DEFAULT 'unknown' CHECK (
        realtime_level IN ('low', 'medium', 'high', 'severe', 'unknown')
    ),
    historical_level text NOT NULL DEFAULT 'unknown' CHECK (
        historical_level IN ('low', 'medium', 'high', 'severe', 'unknown')
    ),
    confidence_level text NOT NULL DEFAULT 'unknown' CHECK (
        confidence_level IN ('low', 'medium', 'high', 'unknown')
    ),
    evidence_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    top_evidence_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    latest_observed_at timestamptz,
    latest_occurred_at timestamptz,
    latest_ingested_at timestamptz,
    coverage_gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'stale' CHECK (
        status IN ('healthy', 'stale', 'missing', 'disabled')
    ),
    computed_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at IS NULL OR expires_at > computed_at)
);

CREATE TABLE IF NOT EXISTS profile_evidence_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_kind text NOT NULL CHECK (profile_kind IN ('admin_area', 'risk_grid')),
    profile_key text NOT NULL,
    evidence_id uuid NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    relevance_score numeric(6,3) CHECK (
        relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)
    ),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (profile_kind, profile_key, evidence_id)
);

CREATE TABLE IF NOT EXISTS profile_refresh_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_kind text NOT NULL CHECK (profile_kind IN ('admin_area', 'risk_grid')),
    profile_key text NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')
    ),
    priority integer NOT NULL DEFAULT 0,
    reason text NOT NULL DEFAULT 'scheduled_refresh',
    run_after timestamptz NOT NULL DEFAULT now(),
    leased_by text,
    lease_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    started_at timestamptz,
    finished_at timestamptz,
    last_error text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS evidence_embeddings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_id uuid REFERENCES evidence(id) ON DELETE CASCADE,
    staging_evidence_id uuid REFERENCES staging_evidence(id) ON DELETE CASCADE,
    model_name text NOT NULL,
    model_version text NOT NULL,
    content_scope text NOT NULL DEFAULT 'title_summary_metadata' CHECK (
        content_scope IN ('title_summary_metadata', 'metadata_only')
    ),
    embedding double precision[] NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'hidden', 'deleted')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (evidence_id IS NOT NULL AND staging_evidence_id IS NULL)
        OR (evidence_id IS NULL AND staging_evidence_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_admin_area_profiles_area_key
    ON admin_area_profiles (area_key);

CREATE INDEX IF NOT EXISTS idx_admin_area_profiles_scope
    ON admin_area_profiles (scope);

CREATE INDEX IF NOT EXISTS idx_admin_area_profiles_geom
    ON admin_area_profiles USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_admin_area_profiles_centroid
    ON admin_area_profiles USING gist (centroid);

CREATE INDEX IF NOT EXISTS idx_admin_area_profiles_status_expires_at
    ON admin_area_profiles (status, expires_at);

CREATE INDEX IF NOT EXISTS idx_risk_grid_profiles_grid_key
    ON risk_grid_profiles (grid_key);

CREATE INDEX IF NOT EXISTS idx_risk_grid_profiles_grid_system
    ON risk_grid_profiles (grid_system, grid_resolution);

CREATE INDEX IF NOT EXISTS idx_risk_grid_profiles_geom
    ON risk_grid_profiles USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_risk_grid_profiles_centroid
    ON risk_grid_profiles USING gist (centroid);

CREATE INDEX IF NOT EXISTS idx_risk_grid_profiles_status_expires_at
    ON risk_grid_profiles (status, expires_at);

CREATE INDEX IF NOT EXISTS idx_profile_evidence_links_evidence_id
    ON profile_evidence_links (evidence_id);

CREATE INDEX IF NOT EXISTS idx_profile_evidence_links_profile
    ON profile_evidence_links (profile_kind, profile_key);

CREATE INDEX IF NOT EXISTS idx_profile_refresh_jobs_status_priority
    ON profile_refresh_jobs (status, priority DESC, run_after, created_at);

CREATE INDEX IF NOT EXISTS idx_profile_refresh_jobs_profile
    ON profile_refresh_jobs (profile_kind, profile_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_refresh_jobs_active_unique
    ON profile_refresh_jobs (profile_kind, profile_key)
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_profile_refresh_jobs_lease_expires_at
    ON profile_refresh_jobs (lease_expires_at)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_evidence_id
    ON evidence_embeddings (evidence_id);

CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_staging_evidence_id
    ON evidence_embeddings (staging_evidence_id);

CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_model
    ON evidence_embeddings (model_name, model_version);

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_embeddings_evidence_model_unique
    ON evidence_embeddings (evidence_id, model_name, model_version)
    WHERE evidence_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_embeddings_staging_model_unique
    ON evidence_embeddings (staging_evidence_id, model_name, model_version)
    WHERE staging_evidence_id IS NOT NULL;
