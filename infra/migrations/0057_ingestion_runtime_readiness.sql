-- Persist public-safe ingestion runtime readiness instead of treating API,
-- PostgreSQL, and Redis liveness as proof that the scheduler is operating.

CREATE TABLE IF NOT EXISTS ingestion_scheduler_heartbeats (
    scheduler_key text PRIMARY KEY,
    runtime_status text NOT NULL DEFAULT 'running' CHECK (
        runtime_status IN ('running', 'stopped')
    ),
    last_seen_at timestamptz NOT NULL,
    stale_after_seconds integer NOT NULL CHECK (stale_after_seconds > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_scheduler_heartbeats_last_seen
    ON ingestion_scheduler_heartbeats (last_seen_at DESC);

-- This table is the migrated runtime projection of deployment_default=true in
-- config/source-registry.yaml.  CI rejects key drift between both surfaces.
-- stale_after_seconds is three scheduler intervals for ordinary sources; the
-- reviewed WRA history snapshot is intentionally checked once per day.
CREATE TABLE IF NOT EXISTS ingestion_readiness_sources (
    profile_key text NOT NULL,
    adapter_key text NOT NULL
        REFERENCES data_sources(adapter_key) ON DELETE RESTRICT,
    coverage_kind text NOT NULL CHECK (
        coverage_kind IN ('national_realtime', 'local_realtime', 'nationwide_history')
    ),
    stale_after_seconds integer NOT NULL CHECK (stale_after_seconds > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_key, adapter_key)
);

INSERT INTO ingestion_readiness_sources (
    profile_key,
    adapter_key,
    coverage_kind,
    stale_after_seconds
)
VALUES
    ('production_backbone', 'official.cwa.rainfall', 'national_realtime', 1800),
    ('production_backbone', 'official.cwa.tide_level', 'national_realtime', 1800),
    ('production_backbone', 'official.wra.water_level', 'national_realtime', 1800),
    ('production_backbone', 'official.wra_iow.flood_depth', 'national_realtime', 1800),
    ('production_backbone', 'official.wra.historical_flood', 'nationwide_history', 90000),
    ('production_backbone', 'official.ncdr.cap', 'national_realtime', 1800),
    ('production_backbone', 'official.civil_iot.flood_sensor', 'national_realtime', 1800),
    ('production_backbone', 'official.civil_iot.sewer_water_level', 'national_realtime', 1800),
    ('production_backbone', 'official.civil_iot.pump_water_level', 'national_realtime', 1800),
    ('production_backbone', 'official.civil_iot.gate_water_level', 'national_realtime', 1800),
    ('production_backbone', 'local.tainan.flood_sensor', 'local_realtime', 1800)
ON CONFLICT (profile_key, adapter_key) DO UPDATE SET
    coverage_kind = EXCLUDED.coverage_kind,
    stale_after_seconds = EXCLUDED.stale_after_seconds,
    updated_at = now();

DO $$
DECLARE
    source_count integer;
BEGIN
    SELECT count(*) INTO source_count
    FROM ingestion_readiness_sources
    WHERE profile_key = 'production_backbone';

    IF source_count <> 11 THEN
        RAISE EXCEPTION
            '0057: expected 11 production backbone readiness sources, found %',
            source_count;
    END IF;
END
$$;
