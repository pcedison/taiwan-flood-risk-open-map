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
VALUES
    (
        'WRA IoW flood depth observations',
        'official.wra_iow.flood_depth',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '經濟部水利署 IoW 淹水深度',
            'owner_authority', 'Water Resources Agency',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://data.gov.tw/dataset/142980',
            'metadata_source_url', 'https://data.gov.tw/dataset/142979',
            'notes', 'Disabled by default; joins WRA IoW latest flood-depth readings with basic station metadata before normalization.',
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
