-- Stop previously persisted Tainan stations that the official source marks as
-- inactive from remaining public through evidence history or realtime latest.
-- New generations are handled by the worker's station-lifecycle tombstones;
-- this migration repairs rows written before those flags were persisted.

DELETE FROM official_realtime_latest latest
USING evidence e, data_sources ds
WHERE latest.evidence_id = e.id
    AND e.data_source_id = ds.id
    AND ds.adapter_key = 'local.tainan.flood_sensor'
    AND (
        e.properties->>'realtime_station_enabled' = 'false'
        OR e.properties->>'metadata_station_enabled' = 'false'
        OR e.title LIKE '%(停用)%'
    );

-- Some rows created by older promotion code may no longer have an evidence
-- link. The materialized station name still carries the reviewed legacy marker.
DELETE FROM official_realtime_latest
WHERE adapter_key = 'local.tainan.flood_sensor'
    AND station_name LIKE '%(停用)%';

UPDATE evidence e
SET
    ingestion_status = 'rejected',
    properties = e.properties || jsonb_build_object(
        'station_lifecycle_state', 'inactive',
        'station_lifecycle_reason', 'official_source_marked_disabled'
    ),
    updated_at = now()
FROM data_sources ds
WHERE e.data_source_id = ds.id
    AND ds.adapter_key = 'local.tainan.flood_sensor'
    AND e.ingestion_status = 'accepted'
    AND (
        e.properties->>'realtime_station_enabled' = 'false'
        OR e.properties->>'metadata_station_enabled' = 'false'
        OR e.title LIKE '%(停用)%'
    );
