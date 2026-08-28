-- Reviewed township geometry for NCDR CAP areas using the official
-- Taiwan_Geocode_103 profile.  This is deliberately separate from the 22-row
-- county jurisdiction snapshot: a township alert must never be widened to its
-- whole county merely because county geometry is already available.

CREATE TABLE IF NOT EXISTS ncdr_alert_area_boundary_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    adapter_key text NOT NULL DEFAULT 'official.ncdr.cap',
    geocode_profile text NOT NULL DEFAULT 'Taiwan_Geocode_103',
    source_name text NOT NULL,
    source_url text NOT NULL,
    source_revision text NOT NULL,
    archive_sha256 text NOT NULL,
    approved_archive_sha256 text,
    manifest_version text NOT NULL DEFAULT 'ncdr-alert-area-jsonb-v1',
    expected_count integer NOT NULL DEFAULT 368,
    imported_count integer NOT NULL DEFAULT 0,
    manifest_sha256 text,
    approved_manifest_sha256 text,
    is_complete boolean NOT NULL DEFAULT false,
    reviewed_at timestamptz,
    review_ref text,
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (adapter_key = 'official.ncdr.cap'),
    CHECK (geocode_profile = 'Taiwan_Geocode_103'),
    CHECK (manifest_version = 'ncdr-alert-area-jsonb-v1'),
    CHECK (expected_count = 368),
    CHECK (imported_count >= 0),
    CHECK (archive_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (
        approved_archive_sha256 IS NULL
        OR approved_archive_sha256 ~ '^[0-9a-f]{64}$'
    ),
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
            AND length(btrim(review_ref)) BETWEEN 1 AND 1024
            AND archive_sha256 = approved_archive_sha256
            AND manifest_sha256 = approved_manifest_sha256
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ncdr_alert_area_boundary_active
    ON ncdr_alert_area_boundary_snapshots (adapter_key, geocode_profile)
    WHERE is_active;

CREATE TABLE IF NOT EXISTS ncdr_alert_area_boundaries (
    snapshot_id uuid NOT NULL
        REFERENCES ncdr_alert_area_boundary_snapshots(id) ON DELETE CASCADE,
    geocode_value text NOT NULL,
    county_name text NOT NULL,
    town_name text NOT NULL,
    english_name text NOT NULL,
    geom geometry(MultiPolygon, 4326) NOT NULL,
    geom_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, geocode_value),
    CHECK (geocode_value ~ '^[0-9]{7}$'),
    CHECK (length(btrim(county_name)) BETWEEN 1 AND 64),
    CHECK (length(btrim(town_name)) BETWEEN 1 AND 64),
    CHECK (length(btrim(english_name)) BETWEEN 1 AND 128),
    CHECK (NOT ST_IsEmpty(geom)),
    CHECK (ST_IsValid(geom)),
    CHECK (geom_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (
        geom_sha256 = encode(digest(ST_AsEWKB(geom), 'sha256'), 'hex')
    )
);

CREATE INDEX IF NOT EXISTS idx_ncdr_alert_area_boundaries_geom
    ON ncdr_alert_area_boundaries USING gist (geom);

CREATE OR REPLACE FUNCTION prevent_reviewed_ncdr_alert_snapshot_rewrite()
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
        RAISE EXCEPTION 'reviewed NCDR alert boundary snapshots are immutable';
    END IF;
    IF (to_jsonb(NEW) - 'is_active')
        IS DISTINCT FROM (to_jsonb(OLD) - 'is_active') THEN
        RAISE EXCEPTION 'reviewed NCDR alert boundary snapshots are immutable';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_ncdr_alert_boundary_snapshot_immutable
    ON ncdr_alert_area_boundary_snapshots;

CREATE TRIGGER trg_ncdr_alert_boundary_snapshot_immutable
BEFORE UPDATE OR DELETE ON ncdr_alert_area_boundary_snapshots
FOR EACH ROW
EXECUTE FUNCTION prevent_reviewed_ncdr_alert_snapshot_rewrite();

CREATE OR REPLACE FUNCTION prevent_reviewed_ncdr_alert_boundary_mutation()
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
        target_snapshot_ids := ARRAY[OLD.snapshot_id, NEW.snapshot_id];
    END IF;

    PERFORM snapshot.id
    FROM ncdr_alert_area_boundary_snapshots snapshot
    WHERE snapshot.id = ANY(target_snapshot_ids)
    ORDER BY snapshot.id
    FOR SHARE;

    SELECT COALESCE(bool_or(snapshot.is_complete OR snapshot.is_active), false)
    INTO snapshot_locked
    FROM ncdr_alert_area_boundary_snapshots snapshot
    WHERE snapshot.id = ANY(target_snapshot_ids);

    IF COALESCE(snapshot_locked, false) THEN
        RAISE EXCEPTION 'reviewed NCDR alert boundaries are immutable';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_ncdr_alert_boundary_immutable
    ON ncdr_alert_area_boundaries;

CREATE TRIGGER trg_ncdr_alert_boundary_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ncdr_alert_area_boundaries
FOR EACH ROW
EXECUTE FUNCTION prevent_reviewed_ncdr_alert_boundary_mutation();
