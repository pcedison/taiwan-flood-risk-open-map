-- ADR-0006 compliance: stored query history must not contain raw query text
-- or precise user-selected coordinates. New writes are coarsened at the
-- application layer; this migration coarsens rows persisted before the fix.
-- Rounding to 2 decimal places matches the ~1 km privacy bucket. Idempotent:
-- re-running re-rounds already-rounded values into the same result.

UPDATE location_queries
SET
    raw_input = NULL,
    lat = ROUND(lat, 2),
    lng = ROUND(lng, 2),
    geom = ST_SetSRID(
        ST_MakePoint(
            ROUND(ST_X(geom)::numeric, 2)::double precision,
            ROUND(ST_Y(geom)::numeric, 2)::double precision
        ),
        4326
    )
WHERE
    raw_input IS NOT NULL
    OR lat IS DISTINCT FROM ROUND(lat, 2)
    OR lng IS DISTINCT FROM ROUND(lng, 2)
    OR ST_X(geom)::numeric IS DISTINCT FROM ROUND(ST_X(geom)::numeric, 2)
    OR ST_Y(geom)::numeric IS DISTINCT FROM ROUND(ST_Y(geom)::numeric, 2);

-- Stored assessment snapshots duplicated the precise location and the raw
-- query text; blank the text and round the location in place.
UPDATE risk_assessments
SET result_snapshot = result_snapshot
    || jsonb_build_object('location_text', NULL)
    || CASE
        WHEN jsonb_typeof(result_snapshot -> 'location' -> 'lat') = 'number'
            AND jsonb_typeof(result_snapshot -> 'location' -> 'lng') = 'number'
        THEN jsonb_build_object(
            'location',
            jsonb_build_object(
                'lat', ROUND((result_snapshot -> 'location' ->> 'lat')::numeric, 2),
                'lng', ROUND((result_snapshot -> 'location' ->> 'lng')::numeric, 2)
            )
        )
        ELSE '{}'::jsonb
    END
WHERE
    (result_snapshot ? 'location_text'
        AND jsonb_typeof(result_snapshot -> 'location_text') <> 'null')
    OR (
        jsonb_typeof(result_snapshot -> 'location' -> 'lat') = 'number'
        AND (result_snapshot -> 'location' ->> 'lat')::numeric
            IS DISTINCT FROM ROUND((result_snapshot -> 'location' ->> 'lat')::numeric, 2)
    )
    OR (
        jsonb_typeof(result_snapshot -> 'location' -> 'lng') = 'number'
        AND (result_snapshot -> 'location' ->> 'lng')::numeric
            IS DISTINCT FROM ROUND((result_snapshot -> 'location' ->> 'lng')::numeric, 2)
    );

-- Profile-refresh job payloads carried precise coordinates and raw text too.
UPDATE worker_runtime_jobs
SET payload = (payload - 'location_text')
    || CASE
        WHEN jsonb_typeof(payload -> 'lat') = 'number'
            AND jsonb_typeof(payload -> 'lng') = 'number'
        THEN jsonb_build_object(
            'lat', ROUND((payload ->> 'lat')::numeric, 2),
            'lng', ROUND((payload ->> 'lng')::numeric, 2)
        )
        ELSE '{}'::jsonb
    END
WHERE
    payload ? 'location_text'
    OR (
        jsonb_typeof(payload -> 'lat') = 'number'
        AND (payload ->> 'lat')::numeric
            IS DISTINCT FROM ROUND((payload ->> 'lat')::numeric, 2)
    )
    OR (
        jsonb_typeof(payload -> 'lng') = 'number'
        AND (payload ->> 'lng')::numeric
            IS DISTINCT FROM ROUND((payload ->> 'lng')::numeric, 2)
    );
