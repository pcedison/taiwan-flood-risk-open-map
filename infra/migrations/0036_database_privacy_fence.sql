-- Close the rolling-deploy privacy race left by application-only scrubbing.
--
-- Trigger DDL takes a table lock that is held until this migration commits.
-- Creating every fence before the repair UPDATE means an old application
-- write either lands before that table is locked and is repaired below, or
-- waits for commit and is scrubbed by the newly-visible trigger.  This keeps
-- the 0033 -> 0036 deployment gap from retaining raw query text or precise
-- coordinates.

CREATE OR REPLACE FUNCTION enforce_location_query_storage_privacy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.raw_input := NULL;

    IF NEW.lat IS NOT NULL THEN
        NEW.lat := ROUND(NEW.lat, 2);
    END IF;
    IF NEW.lng IS NOT NULL THEN
        NEW.lng := ROUND(NEW.lng, 2);
    END IF;
    IF NEW.geom IS NOT NULL THEN
        NEW.geom := ST_SetSRID(
            ST_MakePoint(
                ROUND(ST_X(NEW.geom)::numeric, 2)::double precision,
                ROUND(ST_Y(NEW.geom)::numeric, 2)::double precision
            ),
            4326
        );
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_location_queries_storage_privacy
    ON location_queries;

CREATE TRIGGER trg_location_queries_storage_privacy
BEFORE INSERT OR UPDATE ON location_queries
FOR EACH ROW
EXECUTE FUNCTION enforce_location_query_storage_privacy();

CREATE OR REPLACE FUNCTION scrub_risk_assessment_snapshot_privacy(
    snapshot jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
    scrubbed jsonb := snapshot;
BEGIN
    IF jsonb_typeof(scrubbed) <> 'object' THEN
        RETURN scrubbed;
    END IF;

    -- Retain an existing compatibility key, but never retain its raw text
    -- value. Do not add a new key to snapshots that never carried location
    -- data; that keeps unrelated historical JSON byte-for-byte unchanged.
    IF scrubbed ? 'location_text' THEN
        scrubbed := jsonb_set(scrubbed, '{location_text}', 'null'::jsonb, false);
    END IF;

    -- Change only the coordinate leaves.  Fields such as precision, source,
    -- radius, scores, and evidence metadata must survive the privacy fence.
    IF jsonb_typeof(scrubbed #> '{location,lat}') = 'number' THEN
        scrubbed := jsonb_set(
            scrubbed,
            '{location,lat}',
            to_jsonb(ROUND((scrubbed #>> '{location,lat}')::numeric, 2)),
            false
        );
    END IF;
    IF jsonb_typeof(scrubbed #> '{location,lng}') = 'number' THEN
        scrubbed := jsonb_set(
            scrubbed,
            '{location,lng}',
            to_jsonb(ROUND((scrubbed #>> '{location,lng}')::numeric, 2)),
            false
        );
    END IF;

    RETURN scrubbed;
END
$$;

CREATE OR REPLACE FUNCTION enforce_risk_assessment_storage_privacy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.result_snapshot := scrub_risk_assessment_snapshot_privacy(
        NEW.result_snapshot
    );
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_risk_assessments_storage_privacy
    ON risk_assessments;

CREATE TRIGGER trg_risk_assessments_storage_privacy
BEFORE INSERT OR UPDATE ON risk_assessments
FOR EACH ROW
EXECUTE FUNCTION enforce_risk_assessment_storage_privacy();

CREATE OR REPLACE FUNCTION scrub_worker_runtime_payload_privacy(
    runtime_payload jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
    scrubbed jsonb := runtime_payload;
BEGIN
    IF jsonb_typeof(scrubbed) <> 'object' THEN
        RETURN scrubbed;
    END IF;

    scrubbed := scrubbed - 'location_text';
    IF jsonb_typeof(scrubbed -> 'lat') = 'number' THEN
        scrubbed := jsonb_set(
            scrubbed,
            '{lat}',
            to_jsonb(ROUND((scrubbed ->> 'lat')::numeric, 2)),
            false
        );
    END IF;
    IF jsonb_typeof(scrubbed -> 'lng') = 'number' THEN
        scrubbed := jsonb_set(
            scrubbed,
            '{lng}',
            to_jsonb(ROUND((scrubbed ->> 'lng')::numeric, 2)),
            false
        );
    END IF;

    RETURN scrubbed;
END
$$;

CREATE OR REPLACE FUNCTION enforce_worker_runtime_job_storage_privacy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.payload := scrub_worker_runtime_payload_privacy(NEW.payload);
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_worker_runtime_jobs_storage_privacy
    ON worker_runtime_jobs;

CREATE TRIGGER trg_worker_runtime_jobs_storage_privacy
BEFORE INSERT OR UPDATE ON worker_runtime_jobs
FOR EACH ROW
EXECUTE FUNCTION enforce_worker_runtime_job_storage_privacy();

-- Repair rows written by an old container after migration 0033 completed but
-- before these database fences were installed.  Each UPDATE is idempotent and
-- avoids rewriting rows that already satisfy the privacy contract.
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

UPDATE risk_assessments
SET result_snapshot = scrub_risk_assessment_snapshot_privacy(result_snapshot)
WHERE result_snapshot IS DISTINCT FROM
    scrub_risk_assessment_snapshot_privacy(result_snapshot);

UPDATE worker_runtime_jobs
SET payload = scrub_worker_runtime_payload_privacy(payload)
WHERE payload IS DISTINCT FROM scrub_worker_runtime_payload_privacy(payload);
