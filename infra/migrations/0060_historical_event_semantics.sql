-- Make historical event time semantics explicit.  Some official datasets only
-- publish a year, while realtime sensors publish repeated instant observations
-- that the read path later groups into flood episodes.  Do not force either
-- shape into one misleading timestamp.

ALTER TABLE staging_evidence
    ADD COLUMN IF NOT EXISTS event_year integer,
    ADD COLUMN IF NOT EXISTS temporal_precision text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS event_start_at timestamptz,
    ADD COLUMN IF NOT EXISTS event_end_at timestamptz,
    ADD COLUMN IF NOT EXISTS source_record_key text;

ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS event_year integer,
    ADD COLUMN IF NOT EXISTS temporal_precision text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS event_start_at timestamptz,
    ADD COLUMN IF NOT EXISTS event_end_at timestamptz,
    ADD COLUMN IF NOT EXISTS source_record_key text;

ALTER TABLE staging_evidence
    DROP CONSTRAINT IF EXISTS staging_evidence_event_year_check,
    DROP CONSTRAINT IF EXISTS staging_evidence_temporal_precision_check,
    DROP CONSTRAINT IF EXISTS staging_evidence_event_range_check,
    DROP CONSTRAINT IF EXISTS staging_evidence_year_precision_check;

ALTER TABLE staging_evidence
    ADD CONSTRAINT staging_evidence_event_year_check
        CHECK (event_year IS NULL OR event_year BETWEEN 1900 AND 2100),
    ADD CONSTRAINT staging_evidence_temporal_precision_check
        CHECK (temporal_precision IN ('instant', 'day', 'month', 'year', 'unknown')),
    ADD CONSTRAINT staging_evidence_event_range_check
        CHECK (
            event_start_at IS NULL
            OR event_end_at IS NULL
            OR event_start_at <= event_end_at
        ),
    ADD CONSTRAINT staging_evidence_year_precision_check
        CHECK (
            temporal_precision <> 'year'
            OR (
                event_year IS NOT NULL
                AND occurred_at IS NULL
                AND observed_at IS NULL
                AND event_start_at IS NULL
                AND event_end_at IS NULL
            )
        );

ALTER TABLE evidence
    DROP CONSTRAINT IF EXISTS evidence_event_year_check,
    DROP CONSTRAINT IF EXISTS evidence_temporal_precision_check,
    DROP CONSTRAINT IF EXISTS evidence_event_range_check,
    DROP CONSTRAINT IF EXISTS evidence_year_precision_check;

ALTER TABLE evidence
    ADD CONSTRAINT evidence_event_year_check
        CHECK (event_year IS NULL OR event_year BETWEEN 1900 AND 2100),
    ADD CONSTRAINT evidence_temporal_precision_check
        CHECK (temporal_precision IN ('instant', 'day', 'month', 'year', 'unknown')),
    ADD CONSTRAINT evidence_event_range_check
        CHECK (
            event_start_at IS NULL
            OR event_end_at IS NULL
            OR event_start_at <= event_end_at
        ),
    ADD CONSTRAINT evidence_year_precision_check
        CHECK (
            temporal_precision <> 'year'
            OR (
                event_year IS NOT NULL
                AND occurred_at IS NULL
                AND observed_at IS NULL
                AND event_start_at IS NULL
                AND event_end_at IS NULL
            )
        );

UPDATE staging_evidence
SET
    event_year = EXTRACT(YEAR FROM COALESCE(occurred_at, observed_at))::integer,
    temporal_precision = CASE
        WHEN COALESCE(occurred_at, observed_at) IS NULL THEN 'unknown'
        ELSE 'instant'
    END,
    event_start_at = COALESCE(occurred_at, observed_at),
    event_end_at = COALESCE(observed_at, occurred_at),
    source_record_key = source_id
WHERE event_year IS NULL
   OR temporal_precision = 'unknown'
   OR source_record_key IS NULL;

UPDATE evidence
SET
    event_year = EXTRACT(YEAR FROM COALESCE(occurred_at, observed_at))::integer,
    temporal_precision = CASE
        WHEN COALESCE(occurred_at, observed_at) IS NULL THEN 'unknown'
        ELSE 'instant'
    END,
    event_start_at = COALESCE(occurred_at, observed_at),
    event_end_at = COALESCE(observed_at, occurred_at),
    source_record_key = source_id
WHERE event_year IS NULL
   OR temporal_precision = 'unknown'
   OR source_record_key IS NULL;

-- Dataset 130016 supplies a year but no event date. Remove the legacy 12/31
-- synthetic timestamps and use event_year as the only public ordering key.
UPDATE staging_evidence staging
SET
    event_year = COALESCE(
        CASE
            WHEN staging.payload->>'event_year' ~ '^[0-9]{4}$'
                THEN (staging.payload->>'event_year')::integer
        END,
        substring(staging.source_id FROM '^data-gov-130016:([0-9]{4}):')::integer
    ),
    temporal_precision = 'year',
    occurred_at = NULL,
    observed_at = NULL,
    event_start_at = NULL,
    event_end_at = NULL,
    source_record_key = COALESCE(
        NULLIF(staging.payload->>'source_record_key', ''),
        CASE
            WHEN jsonb_typeof(staging.payload->'location_payload'->'geometry') = 'object'
            THEN concat(
                COALESCE(
                    CASE
                        WHEN staging.payload->>'event_year' ~ '^[0-9]{4}$'
                            THEN staging.payload->>'event_year'
                    END,
                    substring(staging.source_id FROM '^data-gov-130016:([0-9]{4}):')
                ),
                ':',
                substring(
                    encode(
                        digest(
                            convert_to(
                                concat(
                                    COALESCE(
                                        CASE
                                            WHEN staging.payload->>'event_year' ~ '^[0-9]{4}$'
                                                THEN staging.payload->>'event_year'
                                        END,
                                        substring(
                                            staging.source_id
                                            FROM '^data-gov-130016:([0-9]{4}):'
                                        )
                                    ),
                                    '|',
                                    lower(regexp_replace(
                                        btrim(COALESCE(
                                            NULLIF(staging.payload->>'source', ''),
                                            substring(
                                                staging.source_id
                                                FROM '^data-gov-130016:[0-9]{4}:(.*):[^:]+$'
                                            ),
                                            'unknown'
                                        )),
                                        '[[:space:]]+',
                                        ' ',
                                        'g'
                                    )),
                                    '|',
                                    to_char(
                                        ST_X(ST_GeomFromGeoJSON(
                                            (staging.payload->'location_payload'->'geometry')::text
                                        )),
                                        'FM999990.000000'
                                    ),
                                    '|',
                                    to_char(
                                        ST_Y(ST_GeomFromGeoJSON(
                                            (staging.payload->'location_payload'->'geometry')::text
                                        )),
                                        'FM999990.000000'
                                    )
                                ),
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                    FROM 1 FOR 24
                )
            )
        END,
        staging.source_id
    )
FROM data_sources source
WHERE staging.data_source_id = source.id
  AND source.adapter_key = 'official.nstc.flood_disaster_points';

UPDATE evidence promoted
SET
    event_year = COALESCE(
        CASE
            WHEN promoted.properties->>'event_year' ~ '^[0-9]{4}$'
                THEN (promoted.properties->>'event_year')::integer
        END,
        substring(promoted.source_id FROM '^data-gov-130016:([0-9]{4}):')::integer
    ),
    temporal_precision = 'year',
    occurred_at = NULL,
    observed_at = NULL,
    event_start_at = NULL,
    event_end_at = NULL,
    source_record_key = COALESCE(
        NULLIF(promoted.properties->>'source_record_key', ''),
        CASE
            WHEN promoted.geom IS NOT NULL THEN concat(
                COALESCE(
                    CASE
                        WHEN promoted.properties->>'event_year' ~ '^[0-9]{4}$'
                            THEN promoted.properties->>'event_year'
                    END,
                    substring(promoted.source_id FROM '^data-gov-130016:([0-9]{4}):')
                ),
                ':',
                substring(
                    encode(
                        digest(
                            convert_to(
                                concat(
                                    COALESCE(
                                        CASE
                                            WHEN promoted.properties->>'event_year' ~ '^[0-9]{4}$'
                                                THEN promoted.properties->>'event_year'
                                        END,
                                        substring(
                                            promoted.source_id
                                            FROM '^data-gov-130016:([0-9]{4}):'
                                        )
                                    ),
                                    '|',
                                    lower(regexp_replace(
                                        btrim(COALESCE(
                                            NULLIF(promoted.properties->>'source', ''),
                                            substring(
                                                promoted.source_id
                                                FROM '^data-gov-130016:[0-9]{4}:(.*):[^:]+$'
                                            ),
                                            'unknown'
                                        )),
                                        '[[:space:]]+',
                                        ' ',
                                        'g'
                                    )),
                                    '|',
                                    to_char(
                                        ST_X(ST_PointOnSurface(promoted.geom)),
                                        'FM999990.000000'
                                    ),
                                    '|',
                                    to_char(
                                        ST_Y(ST_PointOnSurface(promoted.geom)),
                                        'FM999990.000000'
                                    )
                                ),
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                    FROM 1 FOR 24
                )
            )
        END,
        promoted.source_id
    ),
    properties = promoted.properties || jsonb_build_object(
        'event_year', COALESCE(
            CASE
                WHEN promoted.properties->>'event_year' ~ '^[0-9]{4}$'
                    THEN (promoted.properties->>'event_year')::integer
            END,
            substring(promoted.source_id FROM '^data-gov-130016:([0-9]{4}):')::integer
        ),
        'temporal_precision', 'year'
    )
FROM data_sources source
WHERE promoted.data_source_id = source.id
  AND source.adapter_key = 'official.nstc.flood_disaster_points';

UPDATE raw_snapshots raw
SET
    source_timestamp_min = NULL,
    source_timestamp_max = NULL,
    metadata = raw.metadata || jsonb_build_object(
        'temporal_precision', 'year',
        'exact_event_timestamps_available', false
    )
WHERE raw.adapter_key = 'official.nstc.flood_disaster_points';

CREATE INDEX IF NOT EXISTS idx_evidence_historical_event_order
    ON evidence (event_year DESC, event_end_at DESC, id DESC)
    WHERE ingestion_status = 'accepted'
      AND properties->>'evidence_scope' = 'historical';

CREATE INDEX IF NOT EXISTS idx_evidence_flood_station_episode_time
    ON evidence (
        data_source_id,
        (COALESCE(NULLIF(properties->>'station_id', ''), source_id)),
        observed_at
    )
    WHERE ingestion_status = 'accepted'
      AND source_type = 'official'
      AND event_type = 'flood_report'
      AND properties->>'evidence_scope' = 'current'
      AND observed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_source_record_key_year
    ON evidence (data_source_id, source_record_key, event_year DESC)
    WHERE source_record_key IS NOT NULL;

COMMENT ON COLUMN evidence.temporal_precision IS
    'Precision of the upstream event time; year precision must not be rendered as an exact date.';
COMMENT ON COLUMN evidence.source_record_key IS
    'Stable upstream record identity independent of a raw snapshot revision.';
