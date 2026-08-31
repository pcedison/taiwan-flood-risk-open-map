-- A declared government publisher does not make an aggregator redirect a
-- durable official citation. Keep previously collected rows for audit, but
-- prevent unreadable/non-government links from remaining public evidence.

WITH citation_rows AS (
    SELECT
        e.id,
        lower(
            coalesce(
                substring(e.url from '^https://([^/?#:]+)'),
                ''
            )
        ) AS citation_host
    FROM evidence e
    JOIN data_sources ds ON ds.id = e.data_source_id
    WHERE ds.adapter_key = 'official.gov_tw.flood_citation'
)
UPDATE evidence e
SET
    ingestion_status = 'rejected',
    properties = e.properties || jsonb_build_object(
        'quality_gate', 'direct_official_citation_url_required',
        'exclusion_reason', 'Aggregator or non-government citation URL is not a readable official source page.',
        'excluded_at_migration', '0055'
    ),
    updated_at = now()
FROM citation_rows c
WHERE e.id = c.id
  AND NOT (
      c.citation_host = 'gov.tw'
      OR c.citation_host LIKE '%.gov.tw'
      OR c.citation_host = 'gov.taipei'
      OR c.citation_host LIKE '%.gov.taipei'
  );

UPDATE data_sources
SET
    metadata = metadata || jsonb_build_object(
        'direct_official_citation_url_required', true,
        'publisher_tag_is_not_citation', true,
        'aggregator_only_rows_retained_as', 'rejected'
    ),
    updated_at = now()
WHERE adapter_key = 'official.gov_tw.flood_citation';
