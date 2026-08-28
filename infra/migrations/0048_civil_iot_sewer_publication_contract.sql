-- Publish the reviewed Civil IoT sewer-water-level read model to public queries.
--
-- 0040 deliberately recorded this signal as a known gap because its observations
-- were not yet projected into official_realtime_latest. The reviewed projection
-- shipped in PR #240 and now preserves current scope, station geometry, observed
-- time, and water-level metrics. This migration opens only that proven source; it
-- does not enable or map the still-empty flood-sensor, pump, gate, pond, river, or
-- tide feeds.

BEGIN;

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
VALUES (
    'official.civil_iot.sewer_water_level',
    'sewer_water_level',
    'national',
    'TW',
    'required',
    NULL,
    '2026-08-29-sewer-publication',
    now(),
    '0048_civil_iot_sewer_publication_contract'
)
ON CONFLICT (adapter_key, signal_type, jurisdiction_code) DO UPDATE SET
    coverage_scope = EXCLUDED.coverage_scope,
    requirement_role = EXCLUDED.requirement_role,
    redundancy_of_adapter_key = EXCLUDED.redundancy_of_adapter_key,
    mapping_revision = EXCLUDED.mapping_revision,
    reviewed_at = EXCLUDED.reviewed_at,
    review_ref = EXCLUDED.review_ref;

UPDATE realtime_jurisdiction_signal_contracts
SET mapping_revision = '2026-08-29-sewer-publication',
    reviewed_at = now(),
    review_ref = '0048_civil_iot_sewer_publication_contract',
    updated_at = now()
WHERE signal_type = 'sewer_water_level';

-- Recompute the exact JSONB manifest used by
-- query_realtime_jurisdiction_context. A hand-written digest would allow the
-- stored review proof to drift from the public read path.
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
        AND mapping.mapping_revision = contract.mapping_revision
        AND (
            mapping.coverage_scope = 'national'
            OR mapping.jurisdiction_code = contract.jurisdiction_code
        )
    WHERE contract.signal_type = 'sewer_water_level'
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
    review_ref = '0048_civil_iot_sewer_publication_contract',
    updated_at = now()
FROM manifest
WHERE contract.jurisdiction_code = manifest.jurisdiction_code
    AND contract.signal_type = manifest.signal_type;

-- Fail closed if any county cannot prove the one reviewed national mapping with
-- the exact revision and digest the API verifies at request time.
DO $$
DECLARE
    contract_count integer;
    mapping_count integer;
    bad_contract_count integer;
BEGIN
    SELECT count(*) INTO contract_count
    FROM realtime_jurisdiction_signal_contracts
    WHERE signal_type = 'sewer_water_level';
    IF contract_count <> 22 THEN
        RAISE EXCEPTION
            '0048: expected 22 sewer_water_level contracts, found %',
            contract_count;
    END IF;

    SELECT count(*) INTO mapping_count
    FROM realtime_source_jurisdictions
    WHERE signal_type = 'sewer_water_level'
        AND adapter_key = 'official.civil_iot.sewer_water_level'
        AND coverage_scope = 'national'
        AND jurisdiction_code = 'TW'
        AND requirement_role = 'required'
        AND redundancy_of_adapter_key IS NULL
        AND mapping_revision = '2026-08-29-sewer-publication'
        AND reviewed_at IS NOT NULL
        AND review_ref = '0048_civil_iot_sewer_publication_contract';
    IF mapping_count <> 1 THEN
        RAISE EXCEPTION
            '0048: reviewed Civil IoT sewer mapping is missing or inconsistent';
    END IF;

    WITH manifest AS (
        SELECT
            contract.jurisdiction_code,
            contract.catalog_status,
            contract.mapping_revision,
            contract.mapping_manifest_version,
            contract.approved_mapping_count,
            contract.approved_mapping_manifest_sha256,
            contract.reviewed_at,
            contract.review_ref,
            count(mapping.adapter_key)::integer AS actual_count,
            encode(
                digest(
                    convert_to(
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
                        )::text,
                        'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            ) AS actual_sha256
        FROM realtime_jurisdiction_signal_contracts contract
        LEFT JOIN realtime_source_jurisdictions mapping
            ON mapping.signal_type = contract.signal_type
            AND mapping.mapping_revision = contract.mapping_revision
            AND (
                mapping.coverage_scope = 'national'
                OR mapping.jurisdiction_code = contract.jurisdiction_code
            )
        WHERE contract.signal_type = 'sewer_water_level'
        GROUP BY
            contract.jurisdiction_code,
            contract.catalog_status,
            contract.mapping_revision,
            contract.mapping_manifest_version,
            contract.approved_mapping_count,
            contract.approved_mapping_manifest_sha256,
            contract.reviewed_at,
            contract.review_ref
    )
    SELECT count(*) INTO bad_contract_count
    FROM manifest
    WHERE NOT (
        catalog_status = 'reviewed_complete'
        AND mapping_revision = '2026-08-29-sewer-publication'
        AND mapping_manifest_version = 'jurisdiction-source-jsonb-v1'
        AND approved_mapping_count = 1
        AND actual_count = approved_mapping_count
        AND approved_mapping_manifest_sha256 = actual_sha256
        AND reviewed_at IS NOT NULL
        AND review_ref = '0048_civil_iot_sewer_publication_contract'
    );
    IF bad_contract_count > 0 THEN
        RAISE EXCEPTION
            '0048: % sewer-water-level contracts failed their publication proof',
            bad_contract_count;
    END IF;
END
$$;

COMMIT;
