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
        'Civil IoT water gate external water level observations',
        'official.civil_iot.gate_water_level',
        'official',
        'Government Open Data License',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', 'Civil IoT 閘門外水位',
            'owner_authority', 'Water Resources Agency / local governments',
            'license_name', 'Government Open Data License',
            'tier', 'L1',
            'source_url', 'https://ci.taiwan.gov.tw/dsp/Views/dataset/detail.aspx?id=water_15',
            'resource_url', 'https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Things',
            'notes', 'Disabled by default; reads SensorThings Things with Datastreams containing 閘門外水位 and latest Observations for cross-county gate external water-level context.',
            'review_status', 'ready',
            'phase', 'taiwan_realtime_backbone'
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

UPDATE data_sources
SET
    name = 'Civil IoT pump station water level observations',
    metadata = metadata || jsonb_build_object(
        'label_zh', 'Civil IoT 抽水站水位',
        'owner_authority', 'Water Resources Agency / local governments',
        'source_url', 'https://ci.taiwan.gov.tw/dsp/Views/dataset/detail.aspx?id=water_14',
        'resource_url', 'https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Things',
        'notes', 'Disabled by default; reads SensorThings Things where stationName contains 抽水 and Datastreams contain 水位, preferring 外水位 and falling back to generic 水位.',
        'review_status', 'ready',
        'phase', 'taiwan_realtime_backbone'
    ),
    updated_at = now()
WHERE adapter_key = 'official.civil_iot.pump_water_level';
