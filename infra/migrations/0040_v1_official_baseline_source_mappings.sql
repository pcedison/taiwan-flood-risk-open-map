-- Move the jurisdiction source catalog onto the revision the API actually reads.
--
-- `query_realtime_jurisdiction_context` hardcodes `2026-08-24-v1-baseline` in two
-- places: the source-mapping WHERE clause, and the contract proof it must join
-- against. 0035 seeded every mapping and contract at `2026-07-18-v1` and left the
-- contracts `unreviewed`. No migration ever moved them, because the migration that
-- was supposed to do it (see docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md)
-- never landed and slot 0039 went to an unrelated catalog fix.
--
-- The effect is silent and total. A query point that resolves to a home county
-- matches zero mappings, so `adapter_keys` is empty, every evidence read is
-- filtered against nothing, the source health table is never queried, and the
-- public API reports every official signal as "source not configured" while the
-- database holds fresh observations from more than a thousand stations.
--
-- This migration recomputes the approved manifest digest with the exact ordering
-- and encoding the query uses, rather than storing a hand-computed constant, so
-- the stored proof cannot drift from what the query recomputes at read time.

BEGIN;

-- 0035 restricted signal contracts to the three-signal absence proof plus sewer.
-- The v1 baseline adds flood_warning as an operational contract, so the older
-- constraint has to widen before its rows can exist.
ALTER TABLE realtime_jurisdiction_signal_contracts
    DROP CONSTRAINT IF EXISTS realtime_jurisdiction_signal_contracts_signal_type_check;
ALTER TABLE realtime_jurisdiction_signal_contracts
    ADD CONSTRAINT realtime_jurisdiction_signal_contracts_signal_type_check
    CHECK (
        signal_type IN (
            'rainfall',
            'water_level',
            'flood_depth',
            'sewer_water_level',
            'flood_warning'
        )
    );

-- Replace the mapping rows wholesale. Frozen tide/Civil-IoT/other-local candidates
-- carried `requirement_role = 'required'`, which would make nationwide low-risk
-- readiness unreachable. Kaohsiung and Pingtung stay central-only and are surfaced
-- by the explicit local-gap policy in the assessment repository instead.
-- This touches no source, evidence, run, adapter, or module row.
DELETE FROM realtime_source_jurisdictions;

INSERT INTO realtime_source_jurisdictions (
    adapter_key,
    signal_type,
    coverage_scope,
    jurisdiction_code,
    requirement_role,
    redundancy_of_adapter_key,
    mapping_revision,
    reviewed_at,
    review_ref
)
VALUES
    ('official.cwa.rainfall', 'rainfall', 'national', 'TW', 'required', NULL,
     '2026-08-24-v1-baseline', now(), '0040_v1_official_baseline_source_mappings'),
    ('official.wra.water_level', 'water_level', 'national', 'TW', 'required', NULL,
     '2026-08-24-v1-baseline', now(), '0040_v1_official_baseline_source_mappings'),
    ('official.wra_iow.flood_depth', 'flood_depth', 'national', 'TW', 'required', NULL,
     '2026-08-24-v1-baseline', now(), '0040_v1_official_baseline_source_mappings'),
    ('official.cwa.heavy_rain_warning', 'flood_warning', 'national', 'TW', 'required', NULL,
     '2026-08-24-v1-baseline', now(), '0040_v1_official_baseline_source_mappings'),
    ('official.ncdr.cap', 'flood_warning', 'national', 'TW', 'required', NULL,
     '2026-08-24-v1-baseline', now(), '0040_v1_official_baseline_source_mappings'),
    ('local.tainan.flood_sensor', 'flood_depth', 'local', '67000000', 'required', NULL,
     '2026-08-24-v1-baseline', now(), '0040_v1_official_baseline_source_mappings');

-- Every county needs a flood_warning contract row; 0035 only created the four it
-- knew about.
INSERT INTO realtime_jurisdiction_signal_contracts (
    jurisdiction_code,
    signal_type,
    catalog_status,
    mapping_revision
)
SELECT jurisdiction.jurisdiction_code, 'flood_warning', 'unreviewed', '2026-08-24-v1-baseline'
FROM realtime_jurisdictions jurisdiction
ON CONFLICT (jurisdiction_code, signal_type) DO NOTHING;

-- The proof requires the contract revision and the mapping revision to agree, so
-- move the contracts before recomputing anything from them.
UPDATE realtime_jurisdiction_signal_contracts
SET mapping_revision = '2026-08-24-v1-baseline',
    updated_at = now();

-- No reviewed sewer source exists yet. Record that as a gap rather than an
-- unreviewed catalog, and clear any approved digest so the proof cannot pass on
-- stale numbers. Doing this first keeps the reviewed_complete CHECK satisfiable.
UPDATE realtime_jurisdiction_signal_contracts
SET catalog_status = 'known_gap',
    approved_mapping_count = NULL,
    approved_mapping_manifest_sha256 = NULL,
    reviewed_at = now(),
    review_ref = '0040_v1_official_baseline_source_mappings',
    updated_at = now()
WHERE signal_type = 'sewer_water_level';

-- Recompute count and digest with the same expression the read path uses.
WITH manifest AS (
    SELECT
        contract.jurisdiction_code,
        contract.signal_type,
        count(mapping.adapter_key)::integer AS actual_count,
        COALESCE(
            jsonb_agg(
                jsonb_build_array(
                    mapping.adapter_key,
                    contract.signal_type,
                    mapping.coverage_scope,
                    mapping.jurisdiction_code,
                    mapping.requirement_role,
                    mapping.redundancy_of_adapter_key,
                    mapping.mapping_revision
                )
                ORDER BY
                    mapping.adapter_key,
                    mapping.coverage_scope,
                    mapping.jurisdiction_code,
                    mapping.requirement_role,
                    mapping.redundancy_of_adapter_key,
                    mapping.mapping_revision
            ) FILTER (WHERE mapping.adapter_key IS NOT NULL),
            '[]'::jsonb
        ) AS mapping_manifest
    FROM realtime_jurisdiction_signal_contracts contract
    LEFT JOIN realtime_source_jurisdictions mapping
        ON mapping.signal_type = contract.signal_type
        AND (
            mapping.coverage_scope = 'national'
            OR mapping.jurisdiction_code = contract.jurisdiction_code
        )
    WHERE contract.signal_type IN ('rainfall', 'water_level', 'flood_depth', 'flood_warning')
    GROUP BY contract.jurisdiction_code, contract.signal_type
)
UPDATE realtime_jurisdiction_signal_contracts contract
SET catalog_status = 'reviewed_complete',
    approved_mapping_count = manifest.actual_count,
    approved_mapping_manifest_sha256 = encode(
        digest(convert_to(manifest.mapping_manifest::text, 'UTF8'), 'sha256'),
        'hex'
    ),
    reviewed_at = now(),
    review_ref = '0040_v1_official_baseline_source_mappings',
    updated_at = now()
FROM manifest
WHERE contract.jurisdiction_code = manifest.jurisdiction_code
    AND contract.signal_type = manifest.signal_type;

-- Fail closed. A silently omitted CAP key, a county without both warning keys, or
-- a contract left short of a valid proof would restore the exact failure this
-- migration exists to end, and would do it invisibly.
DO $$
DECLARE
    jurisdiction_count integer;
    bad_count integer;
BEGIN
    SELECT count(*) INTO jurisdiction_count FROM realtime_jurisdictions;

    SELECT count(*) INTO bad_count
    FROM realtime_jurisdiction_signal_contracts
    WHERE signal_type IN ('rainfall', 'water_level', 'flood_depth', 'flood_warning')
        AND NOT (
            catalog_status = 'reviewed_complete'
            AND mapping_revision = '2026-08-24-v1-baseline'
            AND approved_mapping_count > 0
            AND approved_mapping_manifest_sha256 IS NOT NULL
            AND reviewed_at IS NOT NULL
            AND review_ref IS NOT NULL
        );
    IF bad_count > 0 THEN
        RAISE EXCEPTION
            '0040: % reviewed signal contracts did not reach a valid v1 proof',
            bad_count;
    END IF;

    SELECT count(*) INTO bad_count
    FROM (
        SELECT contract.jurisdiction_code
        FROM realtime_jurisdiction_signal_contracts contract
        LEFT JOIN realtime_source_jurisdictions mapping
            ON mapping.signal_type = contract.signal_type
            AND (
                mapping.coverage_scope = 'national'
                OR mapping.jurisdiction_code = contract.jurisdiction_code
            )
        WHERE contract.signal_type = 'flood_warning'
        GROUP BY contract.jurisdiction_code
        HAVING array_agg(mapping.adapter_key ORDER BY mapping.adapter_key)
            <> ARRAY['official.cwa.heavy_rain_warning', 'official.ncdr.cap']
    ) AS offenders;
    IF bad_count > 0 THEN
        RAISE EXCEPTION
            '0040: % jurisdictions are missing a reviewed flood_warning key',
            bad_count;
    END IF;

    SELECT count(*) INTO bad_count
    FROM realtime_jurisdiction_signal_contracts
    WHERE signal_type = 'flood_warning';
    IF bad_count <> jurisdiction_count THEN
        RAISE EXCEPTION
            '0040: expected % flood_warning contracts, found %',
            jurisdiction_count, bad_count;
    END IF;
END
$$;

COMMIT;
