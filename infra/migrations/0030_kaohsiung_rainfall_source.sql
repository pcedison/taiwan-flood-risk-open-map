INSERT INTO data_sources (
    name,
    adapter_key,
    source_type,
    license,
    update_frequency,
    health_status,
    legal_basis,
    is_enabled,
    metadata
)
VALUES (
    'Kaohsiung rainfall observations',
    'local.kaohsiung.rainfall',
    'official',
    'Government Open Data License',
    'near_realtime',
    'unknown',
    'L3',
    false,
    jsonb_build_object(
        'label_zh', '高雄市雨量站',
        'owner_authority', 'Kaohsiung City Water Resources Bureau',
        'license_name', 'Government Open Data License',
        'tier', 'L3',
        'source_url', 'https://wrb.kcg.gov.tw/WRInfo/',
        'resource_url', 'https://wrbswi.kcg.gov.tw/SFC/api/rain/rt',
        'metadata_url', 'https://wrbswi.kcg.gov.tw/SFC/api/rain/base',
        'notes', 'Disabled by default; joins SFC rain/rt latest rainfall rows with rain/base WGS84 station metadata. This local rainfall source supplements CWA and must not replace CWA.',
        'review_status', 'ready',
        'phase', 'local_realtime_sources'
    )
)
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    health_status = EXCLUDED.health_status,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();
