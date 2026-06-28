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
        'Keelung local water level observations',
        'local.keelung.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '基隆市水位站',
            'owner_authority', 'Keelung City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://smartflood.klcg.gov.tw/keelung_web/',
            'resource_url', 'https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/flood/getFloodListData?fields=ascent_rate&filter_ps=true&org_data=ALL&org_id=58&source=ALL&strata=0&type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W&unit=1',
            'notes', 'Disabled by default; reads Keelung smart-flood JSON water-level rows and rejects stale or future observations.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Keelung local flood sensor observations',
        'local.keelung.flood_sensor',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '基隆市淹水感測器',
            'owner_authority', 'Keelung City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://smartflood.klcg.gov.tw/keelung_web/',
            'resource_url', 'https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/flood/getFloodListData?fields=ascent_rate&filter_ps=true&org_data=ALL&org_id=58&source=ALL&strata=0&type=flood&unit=1',
            'notes', 'Disabled by default; interprets type=flood water_inner as flood depth in centimeters.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Keelung local rainfall observations',
        'local.keelung.rainfall',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '基隆市雨量站',
            'owner_authority', 'Keelung City Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://smartflood.klcg.gov.tw/keelung_web/',
            'resource_url', 'https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/rain/getRainFallBaseData?org_id=58&org_data=ALL',
            'notes', 'Disabled by default; preserves rain, min_10, min_30, hour_3, hour_6, hour_12, and hour_24 rainfall windows.',
            'review_status', 'ready',
            'phase', 'local_realtime_sources'
        )
    ),
    (
        'Yunlin local water level observations',
        'local.yunlin.water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L3',
        false,
        jsonb_build_object(
            'label_zh', '雲林縣水位站',
            'owner_authority', 'Yunlin County Government',
            'license_name', 'Government Open Data License',
            'tier', 'L3',
            'source_url', 'https://yliflood.yunlin.gov.tw/ifloodboard/',
            'resource_url', 'https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5',
            'notes', 'Disabled by default; filters stationType=water-level rows with levelHeight/latestUpdateTime. Flood-sensor rows are not normalized because the verified public list does not expose depth values.',
            'review_status', 'needs_review',
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
