-- Retire the request-time government citation lookup (#326, audit 2026-09-03).
-- The lookup ran on the /v1/risk/assess path (4-13 s per query) and admitted
-- non-incident pages such as dengue notices and FAQs as flood evidence.
--
-- Rows already written by this source stay in `evidence` for audit: the API
-- filters them out of assessment reads and scoring, so no row rewrite is
-- needed here and none is performed. Only the catalog row is flipped, which
-- keeps `data_sources.is_enabled` consistent with
-- `config/source-registry.yaml` (catalog_state: disabled, audit_only).
UPDATE data_sources
SET
    is_enabled = false,
    metadata = metadata || jsonb_build_object(
        'review_status', 'retired',
        'retired_on', '2026-09-04',
        'retired_reason', 'Request-time citation search removed from the assessment path; persisted rows remain auditable but are excluded from scoring.'
    ),
    updated_at = now()
WHERE adapter_key = 'official.gov_tw.flood_citation';
