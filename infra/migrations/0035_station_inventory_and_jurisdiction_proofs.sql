-- A station-count floor cannot prove that an upstream response was not
-- truncated.  The reviewed checksum below pins a source to an explicitly
-- approved station-ID manifest; every live run must independently prove the
-- upstream total and terminal page before the public API may conclude that a
-- query point has no station in range.
ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS approved_station_manifest_sha256 text;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS approved_station_manifest_version text;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS station_inventory_reviewed_at timestamptz;

ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS station_inventory_review_ref text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'data_sources_station_manifest_sha256_check'
    ) THEN
        ALTER TABLE data_sources
            ADD CONSTRAINT data_sources_station_manifest_sha256_check
            CHECK (
                approved_station_manifest_sha256 IS NULL
                OR approved_station_manifest_sha256 ~ '^[0-9a-f]{64}$'
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'data_sources_station_inventory_review_check'
    ) THEN
        ALTER TABLE data_sources
            ADD CONSTRAINT data_sources_station_inventory_review_check
            CHECK (
                NOT station_inventory_reviewed
                OR (
                    station_inventory_min_count IS NOT NULL
                    AND approved_station_manifest_sha256 IS NOT NULL
                    AND approved_station_manifest_version IS NOT NULL
                    AND station_inventory_reviewed_at IS NOT NULL
                    AND station_inventory_review_ref IS NOT NULL
                )
            );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS station_inventory_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ingestion_job_id uuid NOT NULL UNIQUE
        REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    adapter_key text NOT NULL,
    captured_at timestamptz NOT NULL,
    upstream_total integer,
    pages_fetched integer NOT NULL DEFAULT 0,
    pagination_complete boolean NOT NULL DEFAULT false,
    source_items_seen integer NOT NULL DEFAULT 0,
    station_ids_seen integer NOT NULL DEFAULT 0,
    missing_station_id_count integer NOT NULL DEFAULT 0,
    duplicate_station_id_count integer NOT NULL DEFAULT 0,
    manifest_version text NOT NULL DEFAULT 'station-id-json-v1',
    manifest_sha256 text,
    station_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    inventory_complete boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (upstream_total IS NULL OR upstream_total >= 0),
    CHECK (pages_fetched >= 0),
    CHECK (source_items_seen >= 0),
    CHECK (station_ids_seen >= 0),
    CHECK (missing_station_id_count >= 0),
    CHECK (duplicate_station_id_count >= 0),
    CHECK (manifest_version = 'station-id-json-v1'),
    CHECK (jsonb_typeof(station_ids) = 'array'),
    CHECK (manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (
        NOT inventory_complete
        OR (
            upstream_total IS NOT NULL
            AND pages_fetched > 0
            AND pagination_complete
            AND source_items_seen = upstream_total
            AND station_ids_seen = upstream_total
            AND missing_station_id_count = 0
            AND duplicate_station_id_count = 0
            AND jsonb_array_length(station_ids) = upstream_total
            AND manifest_sha256 IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_station_inventory_snapshots_adapter_captured
    ON station_inventory_snapshots (adapter_key, captured_at DESC, id DESC);

-- Canonical 8-digit county/city codes.  Geometry is deliberately kept in a
-- separately reviewed snapshot: names/codes may be seeded safely, but centroid
-- or client-provided administrative hints must never authorize no-station.
CREATE TABLE IF NOT EXISTS realtime_jurisdictions (
    jurisdiction_code text PRIMARY KEY,
    jurisdiction_name text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jurisdiction_code ~ '^[0-9]{8}$')
);

INSERT INTO realtime_jurisdictions (jurisdiction_code, jurisdiction_name)
VALUES
    ('63000000', '臺北市'),
    ('65000000', '新北市'),
    ('68000000', '桃園市'),
    ('66000000', '臺中市'),
    ('67000000', '臺南市'),
    ('64000000', '高雄市'),
    ('10017000', '基隆市'),
    ('10018000', '新竹市'),
    ('10020000', '嘉義市'),
    ('10004000', '新竹縣'),
    ('10005000', '苗栗縣'),
    ('10007000', '彰化縣'),
    ('10008000', '南投縣'),
    ('10009000', '雲林縣'),
    ('10010000', '嘉義縣'),
    ('10013000', '屏東縣'),
    ('10002000', '宜蘭縣'),
    ('10015000', '花蓮縣'),
    ('10014000', '臺東縣'),
    ('10016000', '澎湖縣'),
    ('09020000', '金門縣'),
    ('09007000', '連江縣')
ON CONFLICT (jurisdiction_code) DO UPDATE SET
    jurisdiction_name = EXCLUDED.jurisdiction_name;

CREATE TABLE IF NOT EXISTS realtime_jurisdiction_boundary_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name text NOT NULL,
    source_url text NOT NULL,
    source_revision text NOT NULL,
    expected_count integer NOT NULL DEFAULT 22,
    imported_count integer NOT NULL DEFAULT 0,
    manifest_sha256 text,
    approved_manifest_sha256 text,
    is_complete boolean NOT NULL DEFAULT false,
    reviewed_at timestamptz,
    review_ref text,
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expected_count = 22),
    CHECK (imported_count >= 0),
    CHECK (manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (
        approved_manifest_sha256 IS NULL
        OR approved_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CHECK (
        NOT is_complete
        OR (
            imported_count = expected_count
            AND manifest_sha256 IS NOT NULL
        )
    ),
    CHECK (
        NOT is_active
        OR (
            is_complete
            AND reviewed_at IS NOT NULL
            AND review_ref IS NOT NULL
            AND manifest_sha256 = approved_manifest_sha256
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_realtime_boundary_snapshot_active
    ON realtime_jurisdiction_boundary_snapshots (is_active)
    WHERE is_active;

CREATE OR REPLACE FUNCTION prevent_reviewed_realtime_boundary_snapshot_rewrite()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT (OLD.is_complete OR OLD.is_active) THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'reviewed realtime jurisdiction boundary snapshots are immutable';
    END IF;

    -- Activation may be toggled to revoke or atomically switch snapshots, but
    -- the reviewed source, counts, checksum, and review evidence are permanent.
    IF (to_jsonb(NEW) - 'is_active')
        IS DISTINCT FROM (to_jsonb(OLD) - 'is_active') THEN
        RAISE EXCEPTION
            'reviewed realtime jurisdiction boundary snapshots are immutable';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_realtime_boundary_snapshot_immutable
    ON realtime_jurisdiction_boundary_snapshots;

CREATE TRIGGER trg_realtime_boundary_snapshot_immutable
BEFORE UPDATE OR DELETE ON realtime_jurisdiction_boundary_snapshots
FOR EACH ROW
EXECUTE FUNCTION prevent_reviewed_realtime_boundary_snapshot_rewrite();

CREATE TABLE IF NOT EXISTS realtime_jurisdiction_boundaries (
    snapshot_id uuid NOT NULL
        REFERENCES realtime_jurisdiction_boundary_snapshots(id) ON DELETE CASCADE,
    jurisdiction_code text NOT NULL
        REFERENCES realtime_jurisdictions(jurisdiction_code) ON DELETE RESTRICT,
    geom geometry(MultiPolygon, 4326) NOT NULL,
    geom_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, jurisdiction_code),
    CHECK (NOT ST_IsEmpty(geom)),
    CHECK (ST_IsValid(geom)),
    CHECK (geom_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (
        geom_sha256 = encode(digest(ST_AsEWKB(geom), 'sha256'), 'hex')
    )
);

CREATE INDEX IF NOT EXISTS idx_realtime_jurisdiction_boundaries_geom
    ON realtime_jurisdiction_boundaries USING gist (geom);

-- Once a snapshot is marked complete, its geometry rows are immutable.  A new
-- official revision must use a new snapshot so an approved checksum cannot be
-- retained while county boundaries are edited in place.
CREATE OR REPLACE FUNCTION prevent_reviewed_realtime_boundary_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_snapshot_ids uuid[];
    snapshot_locked boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        target_snapshot_ids := ARRAY[NEW.snapshot_id];
    ELSIF TG_OP = 'DELETE' THEN
        target_snapshot_ids := ARRAY[OLD.snapshot_id];
    ELSE
        -- UPDATE may move a row between snapshots.  Lock both the source and
        -- destination so an incomplete donor cannot be moved into an already
        -- reviewed snapshot after its manifest was approved.
        target_snapshot_ids := ARRAY[OLD.snapshot_id, NEW.snapshot_id];
    END IF;

    -- Serialize child-row mutations with the parent transition to complete or
    -- active.  Without this lock, a boundary write and the review UPDATE could
    -- both observe an incomplete snapshot and commit in the opposite order.
    PERFORM snapshot.id
    FROM realtime_jurisdiction_boundary_snapshots snapshot
    WHERE snapshot.id = ANY(target_snapshot_ids)
    ORDER BY snapshot.id
    FOR SHARE;

    SELECT COALESCE(bool_or(snapshot.is_complete OR snapshot.is_active), false)
    INTO snapshot_locked
    FROM realtime_jurisdiction_boundary_snapshots snapshot
    WHERE snapshot.id = ANY(target_snapshot_ids);

    IF COALESCE(snapshot_locked, false) THEN
        RAISE EXCEPTION
            'reviewed realtime jurisdiction boundary snapshots are immutable';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_realtime_boundary_immutable
    ON realtime_jurisdiction_boundaries;

CREATE TRIGGER trg_realtime_boundary_immutable
BEFORE INSERT OR UPDATE OR DELETE ON realtime_jurisdiction_boundaries
FOR EACH ROW
EXECUTE FUNCTION prevent_reviewed_realtime_boundary_mutation();

CREATE TABLE IF NOT EXISTS realtime_jurisdiction_signal_contracts (
    jurisdiction_code text NOT NULL
        REFERENCES realtime_jurisdictions(jurisdiction_code) ON DELETE CASCADE,
    signal_type text NOT NULL,
    catalog_status text NOT NULL DEFAULT 'unreviewed',
    mapping_revision text NOT NULL,
    mapping_manifest_version text NOT NULL DEFAULT 'jurisdiction-source-jsonb-v1',
    approved_mapping_count integer,
    approved_mapping_manifest_sha256 text,
    reviewed_at timestamptz,
    review_ref text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (jurisdiction_code, signal_type),
    CHECK (
        signal_type IN ('rainfall', 'water_level', 'flood_depth', 'sewer_water_level')
    ),
    CHECK (catalog_status IN ('reviewed_complete', 'known_gap', 'unreviewed')),
    CHECK (mapping_manifest_version = 'jurisdiction-source-jsonb-v1'),
    CHECK (approved_mapping_count IS NULL OR approved_mapping_count > 0),
    CHECK (
        approved_mapping_manifest_sha256 IS NULL
        OR approved_mapping_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CHECK (
        catalog_status <> 'reviewed_complete'
        OR (
            approved_mapping_count IS NOT NULL
            AND approved_mapping_manifest_sha256 IS NOT NULL
            AND reviewed_at IS NOT NULL
            AND review_ref IS NOT NULL
        )
    )
);

INSERT INTO realtime_jurisdiction_signal_contracts (
    jurisdiction_code,
    signal_type,
    catalog_status,
    mapping_revision
)
SELECT
    jurisdiction.jurisdiction_code,
    signal.signal_type,
    'unreviewed',
    '2026-07-18-v1'
FROM realtime_jurisdictions jurisdiction
CROSS JOIN (
    VALUES
        ('rainfall'),
        ('water_level'),
        ('flood_depth'),
        ('sewer_water_level')
) AS signal(signal_type)
ON CONFLICT (jurisdiction_code, signal_type) DO NOTHING;

CREATE TABLE IF NOT EXISTS realtime_source_jurisdictions (
    adapter_key text NOT NULL
        REFERENCES data_sources(adapter_key) ON DELETE CASCADE,
    signal_type text NOT NULL,
    coverage_scope text NOT NULL,
    jurisdiction_code text NOT NULL,
    requirement_role text NOT NULL DEFAULT 'required',
    redundancy_of_adapter_key text
        REFERENCES data_sources(adapter_key) ON DELETE RESTRICT,
    mapping_revision text NOT NULL,
    reviewed_at timestamptz,
    review_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adapter_key, signal_type, jurisdiction_code),
    CHECK (
        signal_type IN (
            'rainfall',
            'water_level',
            'flood_depth',
            'sewer_water_level',
            'pump_or_gate_status',
            'flood_warning',
            'status_only'
        )
    ),
    CHECK (coverage_scope IN ('national', 'local')),
    CHECK (
        (coverage_scope = 'national' AND jurisdiction_code = 'TW')
        OR (coverage_scope = 'local' AND jurisdiction_code ~ '^[0-9]{8}$')
    ),
    CHECK (requirement_role IN ('required', 'redundant_subset')),
    CHECK (
        redundancy_of_adapter_key IS NULL
        OR redundancy_of_adapter_key <> adapter_key
    ),
    CHECK (
        requirement_role = 'required'
        OR (
            redundancy_of_adapter_key IS NOT NULL
            AND reviewed_at IS NOT NULL
            AND review_ref IS NOT NULL
        )
    )
);

-- National sources are applicable to every resolved county.  Local sources
-- are mapped explicitly; adapter-key parsing is intentionally not trusted at
-- runtime because a typo or renamed adapter could otherwise silently escape
-- the absence proof.
INSERT INTO realtime_source_jurisdictions (
    adapter_key,
    signal_type,
    coverage_scope,
    jurisdiction_code,
    requirement_role,
    mapping_revision
)
VALUES
    ('official.cwa.rainfall', 'rainfall', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.cwa.tide_level', 'water_level', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.wra.water_level', 'water_level', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.wra_iow.flood_depth', 'flood_depth', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.civil_iot.flood_sensor', 'flood_depth', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.civil_iot.river_water_level', 'water_level', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.civil_iot.pond_water_level', 'water_level', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.civil_iot.sewer_water_level', 'sewer_water_level', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.civil_iot.pump_water_level', 'pump_or_gate_status', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.civil_iot.gate_water_level', 'pump_or_gate_status', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('official.ncdr.cap', 'flood_warning', 'national', 'TW', 'required', '2026-07-18-v1'),
    ('local.taipei.sewer_water_level', 'sewer_water_level', 'local', '63000000', 'required', '2026-07-18-v1'),
    ('local.taipei.river_water_level', 'water_level', 'local', '63000000', 'required', '2026-07-18-v1'),
    ('local.taipei.pump_station', 'pump_or_gate_status', 'local', '63000000', 'required', '2026-07-18-v1'),
    ('local.new_taipei.water_level', 'water_level', 'local', '65000000', 'required', '2026-07-18-v1'),
    ('local.new_taipei.flood_sensor', 'flood_depth', 'local', '65000000', 'required', '2026-07-18-v1'),
    ('local.new_taipei.rainfall', 'rainfall', 'local', '65000000', 'required', '2026-07-18-v1'),
    ('local.new_taipei.drainage_water_level', 'sewer_water_level', 'local', '65000000', 'required', '2026-07-18-v1'),
    ('local.keelung.water_level', 'water_level', 'local', '10017000', 'required', '2026-07-18-v1'),
    ('local.keelung.flood_sensor', 'flood_depth', 'local', '10017000', 'required', '2026-07-18-v1'),
    ('local.keelung.rainfall', 'rainfall', 'local', '10017000', 'required', '2026-07-18-v1'),
    ('local.taoyuan.flood_sensor', 'flood_depth', 'local', '68000000', 'required', '2026-07-18-v1'),
    ('local.taoyuan.water_level', 'water_level', 'local', '68000000', 'required', '2026-07-18-v1'),
    ('local.taoyuan.rainfall', 'rainfall', 'local', '68000000', 'required', '2026-07-18-v1'),
    ('local.hsinchu_city.sewer_water_level', 'sewer_water_level', 'local', '10018000', 'required', '2026-07-18-v1'),
    ('local.hsinchu_city.flood_sensor', 'flood_depth', 'local', '10018000', 'required', '2026-07-18-v1'),
    ('local.hsinchu_county.flood_sensor', 'flood_depth', 'local', '10004000', 'required', '2026-07-18-v1'),
    ('local.miaoli.flood_sensor', 'flood_depth', 'local', '10005000', 'required', '2026-07-18-v1'),
    ('local.taichung.water_level', 'water_level', 'local', '66000000', 'required', '2026-07-18-v1'),
    ('local.changhua.flood_sensor', 'flood_depth', 'local', '10007000', 'required', '2026-07-18-v1'),
    ('local.nantou.sewer_water_level', 'sewer_water_level', 'local', '10008000', 'required', '2026-07-18-v1'),
    ('local.yunlin.water_level', 'water_level', 'local', '10009000', 'required', '2026-07-18-v1'),
    ('local.chiayi_city.water_level', 'water_level', 'local', '10020000', 'required', '2026-07-18-v1'),
    ('local.chiayi_city.rainfall', 'rainfall', 'local', '10020000', 'required', '2026-07-18-v1'),
    ('local.chiayi_county.flood_sensor', 'flood_depth', 'local', '10010000', 'required', '2026-07-18-v1'),
    ('local.tainan.flood_sensor', 'flood_depth', 'local', '67000000', 'required', '2026-07-18-v1'),
    ('local.kaohsiung.sewer_water_level', 'sewer_water_level', 'local', '64000000', 'required', '2026-07-18-v1'),
    ('local.kaohsiung.flood_sensor', 'flood_depth', 'local', '64000000', 'required', '2026-07-18-v1'),
    ('local.kaohsiung.rainfall', 'rainfall', 'local', '64000000', 'required', '2026-07-18-v1'),
    ('local.pingtung.flood_sensor', 'flood_depth', 'local', '10013000', 'required', '2026-07-18-v1'),
    ('local.yilan.flood_sensor', 'flood_depth', 'local', '10002000', 'required', '2026-07-18-v1'),
    ('local.yilan.water_level', 'water_level', 'local', '10002000', 'required', '2026-07-18-v1'),
    ('local.hualien.flood_sensor', 'flood_depth', 'local', '10015000', 'required', '2026-07-18-v1'),
    ('local.taitung.flood_sensor', 'flood_depth', 'local', '10014000', 'required', '2026-07-18-v1'),
    ('local.penghu.water_level', 'water_level', 'local', '10016000', 'required', '2026-07-18-v1'),
    ('local.kinmen.kwis_pump_station', 'pump_or_gate_status', 'local', '09020000', 'required', '2026-07-18-v1')
ON CONFLICT (adapter_key, signal_type, jurisdiction_code) DO UPDATE SET
    coverage_scope = EXCLUDED.coverage_scope,
    requirement_role = EXCLUDED.requirement_role,
    mapping_revision = EXCLUDED.mapping_revision;

CREATE INDEX IF NOT EXISTS idx_realtime_source_jurisdictions_lookup
    ON realtime_source_jurisdictions (
        coverage_scope,
        jurisdiction_code,
        signal_type,
        requirement_role
    );
