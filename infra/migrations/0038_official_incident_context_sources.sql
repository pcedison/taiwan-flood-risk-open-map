-- Register the four official incident/context sources as catalog rows.
-- Every row is inserted disabled. This migration does not enable any adapter,
-- store any credential, approve any spatial review, or create a required
-- realtime coverage mapping. Operators must still turn on each runtime gate
-- and complete the fail-closed source review before a row can be enabled.

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
        'Central Weather Administration heavy-rain CAP warnings',
        'official.cwa.heavy_rain_warning',
        'official',
        '中央氣象署開放資料平臺使用規範',
        'event_driven',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '中央氣象署豪雨特報',
            'owner_authority', 'Central Weather Administration',
            'source_url', 'https://opendata.cwa.gov.tw/dataset/warning/W-C0033-003',
            'resource_url', 'https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/W-C0033-003?format=CAP',
            'license_name', '中央氣象署開放資料平臺使用規範',
            'license_url', 'https://opendata.cwa.gov.tw/about/rules',
            'limitation_zh', '僅保留有界原始快照與來源拒絕稽核；未經審查的行政區與訊息層級幾何永不進入 staging、latest、promotion 或計分。',
            'spatial_review', 'unapproved',
            'evidence_scope', 'audit_only',
            'scoring_use', 'gated',
            'review_status', 'audit_only',
            'phase', 'safe_fast_official_incident_expansion'
        )
    ),
    (
        'NCDR datastore and CAP dump alerts',
        'official.ncdr.cap',
        'official',
        'Government Open Data License, version 1.0',
        'event_driven',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '國家災害防救科技中心 CAP 告警',
            'owner_authority', 'National Science and Technology Center for Disaster Reduction',
            'source_url', 'https://alerts.ncdr.nat.gov.tw/',
            'resource_url', 'https://alerts.ncdr.nat.gov.tw/api/datastore',
            'dump_url', 'https://alerts.ncdr.nat.gov.tw/api/dump/datastore',
            'license_name', 'Government Open Data License, version 1.0',
            'limitation_zh', '僅保留有界原始 CAP 快照與來源拒絕稽核；行政區與 Circle 幾何未經審查前不做正規化。',
            'spatial_review', 'unapproved',
            'evidence_scope', 'audit_only',
            'scoring_use', 'gated',
            'review_status', 'audit_only',
            'phase', 'safe_fast_official_incident_expansion'
        )
    ),
    (
        'Police Broadcasting Service realtime road conditions',
        'official.npa.police_radio_traffic',
        'official',
        'Government Open Data License, version 1.0',
        'near_realtime',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '警廣即時路況積淹水通報',
            'owner_authority', 'Police Broadcasting Service',
            'source_url', 'https://data.gov.tw/dataset/15221',
            'resource_url', 'https://rtr.pbs.gov.tw/NMP103_PbsWS/resources/roadData/opendata',
            'license_name', 'Government Open Data License, version 1.0',
            'limitation_zh', '警廣即時路況通報，尚未由淹水感測器確認；僅作為顯示用脈絡。',
            'evidence_scope', 'context',
            'scoring_use', 'never',
            'verification_status', 'reported_unverified',
            'review_status', 'context_only',
            'phase', 'safe_fast_official_incident_expansion'
        )
    ),
    (
        'Water Resources Agency warning KML context',
        'official.wra.flood_warning',
        'official',
        'Government Open Data License, version 1.0',
        'event_driven',
        'unknown',
        'L1',
        false,
        jsonb_build_object(
            'label_zh', '水利署淹水與水位警戒圖層',
            'owner_authority', 'Water Resources Agency',
            'source_url', 'https://data.gov.tw/dataset/5982',
            'resource_url', 'https://opendata.wra.gov.tw/api/v2/301c0b62-8736-4e03-95ef-55309c1a5e74',
            'license_name', 'Government Open Data License, version 1.0',
            'limitation_zh', '官方警戒範圍為情境背景，尚未經淹水感測器逐點確認；僅作為顯示用脈絡。',
            'evidence_scope', 'context',
            'scoring_use', 'never',
            'verification_status', 'official_reported',
            'active_fixture_reviewed', 'no',
            'review_status', 'context_only',
            'phase', 'safe_fast_official_incident_expansion'
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
