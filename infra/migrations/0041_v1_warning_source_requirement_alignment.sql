-- Align the reviewed flood-warning absence contract with the deployed runtime.
--
-- NCDR CAP is part of the default hosted backbone and remains the required
-- flood-warning source. CWA heavy-rain warning is still a reviewed applicable
-- mapping, but it is disabled at runtime and therefore becomes a redundant
-- subset of NCDR rather than an independent absence requirement. This migration
-- changes no data-source enable flag, credential, or runtime gate.

BEGIN;

UPDATE realtime_source_jurisdictions
SET requirement_role = 'required',
    redundancy_of_adapter_key = NULL,
    mapping_revision = '2026-08-28-v1-warning-alignment',
    reviewed_at = now(),
    review_ref = '0041_v1_warning_source_requirement_alignment'
WHERE adapter_key = 'official.ncdr.cap'
    AND signal_type = 'flood_warning'
    AND coverage_scope = 'national'
    AND jurisdiction_code = 'TW';

UPDATE realtime_source_jurisdictions
SET requirement_role = 'redundant_subset',
    redundancy_of_adapter_key = 'official.ncdr.cap',
    mapping_revision = '2026-08-28-v1-warning-alignment',
    reviewed_at = now(),
    review_ref = '0041_v1_warning_source_requirement_alignment'
WHERE adapter_key = 'official.cwa.heavy_rain_warning'
    AND signal_type = 'flood_warning'
    AND coverage_scope = 'national'
    AND jurisdiction_code = 'TW';

UPDATE realtime_jurisdiction_signal_contracts
SET mapping_revision = '2026-08-28-v1-warning-alignment',
    reviewed_at = now(),
    review_ref = '0041_v1_warning_source_requirement_alignment',
    updated_at = now()
WHERE signal_type = 'flood_warning';

-- Recompute the warning manifest with the same JSONB array, ordering, text
-- encoding, and revision-scoped applicability used by the production read path.
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
    WHERE contract.signal_type = 'flood_warning'
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
    review_ref = '0041_v1_warning_source_requirement_alignment',
    updated_at = now()
FROM manifest
WHERE contract.jurisdiction_code = manifest.jurisdiction_code
    AND contract.signal_type = manifest.signal_type;

-- Fail closed on an incomplete county set, a runtime/contract role drift, or a
-- manifest that differs from what query_realtime_jurisdiction_context proves.
DO $$
DECLARE
    warning_contract_count integer;
    warning_mapping_count integer;
    matching_mapping_count integer;
    bad_contract_count integer;
BEGIN
    SELECT count(*) INTO warning_contract_count
    FROM realtime_jurisdiction_signal_contracts
    WHERE signal_type = 'flood_warning';
    IF warning_contract_count <> 22 THEN
        RAISE EXCEPTION
            '0041: expected 22 flood_warning contracts, found %',
            warning_contract_count;
    END IF;

    SELECT count(*) INTO warning_mapping_count
    FROM realtime_source_jurisdictions
    WHERE signal_type = 'flood_warning';
    IF warning_mapping_count <> 2 THEN
        RAISE EXCEPTION
            '0041: expected exactly two flood_warning mappings, found %',
            warning_mapping_count;
    END IF;

    SELECT count(*) INTO matching_mapping_count
    FROM realtime_source_jurisdictions mapping
    WHERE mapping.signal_type = 'flood_warning'
        AND mapping.coverage_scope = 'national'
        AND mapping.jurisdiction_code = 'TW'
        AND mapping.mapping_revision = '2026-08-28-v1-warning-alignment'
        AND mapping.reviewed_at IS NOT NULL
        AND mapping.review_ref = '0041_v1_warning_source_requirement_alignment'
        AND (
            (
                mapping.adapter_key = 'official.ncdr.cap'
                AND mapping.requirement_role = 'required'
                AND mapping.redundancy_of_adapter_key IS NULL
            )
            OR (
                mapping.adapter_key = 'official.cwa.heavy_rain_warning'
                AND mapping.requirement_role = 'redundant_subset'
                AND mapping.redundancy_of_adapter_key = 'official.ncdr.cap'
            )
        );
    IF matching_mapping_count <> 2 THEN
        RAISE EXCEPTION
            '0041: flood_warning roles or review evidence are inconsistent';
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
            ) AS actual_sha256,
            COALESCE(
                bool_and(
                    CASE
                        WHEN mapping.requirement_role <> 'redundant_subset' THEN true
                        ELSE EXISTS (
                            SELECT 1
                            FROM realtime_source_jurisdictions parent_mapping
                            WHERE parent_mapping.adapter_key
                                    = mapping.redundancy_of_adapter_key
                                AND parent_mapping.signal_type = mapping.signal_type
                                AND parent_mapping.requirement_role = 'required'
                                AND parent_mapping.mapping_revision
                                    = mapping.mapping_revision
                                AND (
                                    parent_mapping.coverage_scope = 'national'
                                    OR parent_mapping.jurisdiction_code
                                        = contract.jurisdiction_code
                                )
                        )
                    END
                ) FILTER (WHERE mapping.adapter_key IS NOT NULL),
                false
            ) AS redundancy_parent_valid
        FROM realtime_jurisdiction_signal_contracts contract
        LEFT JOIN realtime_source_jurisdictions mapping
            ON mapping.signal_type = contract.signal_type
            AND mapping.mapping_revision = contract.mapping_revision
            AND (
                mapping.coverage_scope = 'national'
                OR mapping.jurisdiction_code = contract.jurisdiction_code
            )
        WHERE contract.signal_type = 'flood_warning'
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
        manifest.catalog_status = 'reviewed_complete'
        AND manifest.mapping_revision = '2026-08-28-v1-warning-alignment'
        AND manifest.mapping_manifest_version = 'jurisdiction-source-jsonb-v1'
        AND manifest.actual_count = 2
        AND manifest.approved_mapping_count = manifest.actual_count
        AND manifest.approved_mapping_manifest_sha256 = manifest.actual_sha256
        AND manifest.reviewed_at IS NOT NULL
        AND manifest.review_ref = '0041_v1_warning_source_requirement_alignment'
        AND manifest.redundancy_parent_valid
    );
    IF bad_contract_count > 0 THEN
        RAISE EXCEPTION
            '0041: % flood_warning contracts lack a valid aligned proof',
            bad_contract_count;
    END IF;
END
$$;

COMMIT;
