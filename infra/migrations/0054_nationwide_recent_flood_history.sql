-- Replace the request-time Tainan-only recovery path with a nationwide,
-- official-domain citation lookup, and register the fail-closed WRA latest
-- flood-incident adapter used to accumulate future multi-year history.

UPDATE data_sources
SET
    is_enabled = false,
    metadata = metadata || jsonb_build_object(
        'review_status', 'superseded',
        'superseded_by', 'official.gov_tw.flood_citation',
        'superseded_reason', 'Nationwide official-domain lookup replaces the single-city request path.'
    ),
    updated_at = now()
WHERE adapter_key = 'official.tainan.disaster_news';

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
    'Taiwan government recent flood citation lookup',
    'official.gov_tw.flood_citation',
    'official',
    'Citation metadata only; source-page terms remain authoritative',
    'on_demand_bounded_query',
    'unknown',
    'L1',
    true,
    jsonb_build_object(
        'label_zh', '全臺政府機關近期積淹水紀錄',
        'owner_authority', 'Taiwan central and local government agencies',
        'source_scope', 'HTTPS Taiwan government domains only',
        'accepted_domain_suffixes', jsonb_build_array('.gov.tw', '.gov.taipei'),
        'citation_required', true,
        'full_text_stored', false,
        'stored_fields', jsonb_build_array('title', 'publication_date', 'url', 'publisher_domain', 'location_match'),
        'rolling_lookback_years', 7,
        'coverage_is_complete', false,
        'evidence_scope', 'historical',
        'scoring_use', 'historical_context',
        'location_precision', 'admin_area_or_road',
        'review_status', 'ready',
        'limitation_zh', '官方頁面索引用於補查近七年事件，但搜尋索引並非完整事件清冊；無結果不能解讀為未曾淹水。',
        'kill_switch', 'OFFICIAL_NATIONWIDE_HISTORY_CITATIONS_ENABLED=false',
        'supersedes', 'official.tainan.disaster_news',
        'phase', 'nationwide_recent_official_history_recovery'
    )
)
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();

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
    'WRA nationwide reported flood incidents',
    'official.wra.flood_incident',
    'official',
    'Official API contract review required before production activation',
    'worker_poll_latest_disaster_event',
    'disabled',
    'L1',
    false,
    jsonb_build_object(
        'label_zh', '水利署全臺最後事件淹水災情',
        'owner_authority', 'Water Resources Agency',
        'source_url', 'https://fhy.wra.gov.tw/OpenApiv3/v2/Disaster/Flooding?$top=100',
        'documentation_url', 'https://fhy.wra.gov.tw/openapiv3',
        'coverage', 'all_22_counties_in_latest_event_response',
        'upstream_semantics', 'latest_disaster_event_only',
        'durable_history_start', 'after_production_scheduler_activation',
        'raw_snapshot_required', true,
        'evidence_scope', 'historical',
        'coverage_is_complete', false,
        'depth_unit', 'upstream_schema_unspecified',
        'pointless_row_policy', 'raw_audit_rejection_until_reviewed_geometry_resolver',
        'review_status', 'credential_and_contract_required',
        'required_gates', jsonb_build_array(
            'SOURCE_WRA_FLOOD_INCIDENT_ENABLED',
            'SOURCE_WRA_FLOOD_INCIDENT_API_ENABLED',
            'SOURCE_WRA_FLOOD_INCIDENT_CONTRACT_ENABLED',
            'WRA_FLOOD_INCIDENT_API_KEY'
        ),
        'limitation_zh', '上游僅回傳最後災害事件；正式排程啟用前不能宣稱已完成跨年度回補。'
    )
)
ON CONFLICT (adapter_key) DO UPDATE SET
    name = EXCLUDED.name,
    source_type = EXCLUDED.source_type,
    license = EXCLUDED.license,
    update_frequency = EXCLUDED.update_frequency,
    legal_basis = EXCLUDED.legal_basis,
    is_enabled = EXCLUDED.is_enabled,
    metadata = data_sources.metadata || EXCLUDED.metadata,
    updated_at = now();
