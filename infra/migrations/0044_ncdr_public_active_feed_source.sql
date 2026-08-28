-- Keep the persisted source catalog aligned with the reviewed no-credential
-- NCDR transport. Runtime source gates and the existing audit-only spatial
-- policy are intentionally unchanged.

UPDATE data_sources
SET
    name = 'NCDR public active-warning Atom and CAP alerts',
    update_frequency = 'event_driven',
    metadata = metadata || jsonb_build_object(
        'resource_url', 'https://alerts.ncdr.nat.gov.tw/RssAtomFeeds.ashx',
        'resource_format', 'public active-warning Atom index to CAP XML',
        'public_feed_authentication', 'none',
        'member_datastore_url', 'https://alerts.ncdr.nat.gov.tw/api/datastore',
        'member_dump_url', 'https://alerts.ncdr.nat.gov.tw/api/dump/datastore',
        'member_api_key', 'optional',
        'feed_scope', 'active_warnings',
        'feed_category', '淹水',
        'feed_refresh_seconds', 60
    ),
    updated_at = now()
WHERE adapter_key = 'official.ncdr.cap';
