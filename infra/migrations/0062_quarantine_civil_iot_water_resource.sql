-- Quarantine Civil IoT sources whose shared WaterResource entity service is
-- unavailable. On 2026-09-02 the official sta.colife.org.tw service root was
-- HTTP 200, but the minimal Things, Datastreams, Observations, and Sensors
-- entity queries all returned HTTP 500. STA_RainSewer remained healthy and is
-- deliberately kept in the production backbone.
--
-- This is an availability decision, not a deletion: adapter code, historical
-- evidence, source rows, and readiness history remain auditable. A future
-- reviewed migration must explicitly re-enable these catalog rows after a
-- replacement endpoint or restored entity service passes live acceptance.

BEGIN;

UPDATE data_sources
SET is_enabled = false,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'availability_status', 'upstream_unavailable',
        'availability_reviewed_at', '2026-09-02T13:45:00+08:00',
        'availability_incident_ref',
            'docs/reviews/civil-iot-source-recovery-2026-09-02.md',
        'availability_reason',
            'Official STA_WaterResource_v2 entity queries returned HTTP 500.'
    ),
    updated_at = now()
WHERE adapter_key IN (
    'official.civil_iot.flood_sensor',
    'official.civil_iot.pump_water_level',
    'official.civil_iot.gate_water_level'
);

DELETE FROM ingestion_readiness_sources
WHERE profile_key = 'production_backbone'
  AND adapter_key IN (
      'official.civil_iot.flood_sensor',
      'official.civil_iot.pump_water_level',
      'official.civil_iot.gate_water_level'
  );

DO $$
DECLARE
    quarantined_count integer;
    readiness_count integer;
    sewer_enabled boolean;
BEGIN
    SELECT count(*) INTO quarantined_count
    FROM data_sources
    WHERE adapter_key IN (
        'official.civil_iot.flood_sensor',
        'official.civil_iot.pump_water_level',
        'official.civil_iot.gate_water_level'
    )
      AND is_enabled = false
      AND metadata->>'availability_status' = 'upstream_unavailable'
      AND metadata->>'availability_incident_ref'
          = 'docs/reviews/civil-iot-source-recovery-2026-09-02.md';

    IF quarantined_count <> 3 THEN
        RAISE EXCEPTION
            '0062: expected 3 quarantined WaterResource sources, found %',
            quarantined_count;
    END IF;

    SELECT is_enabled INTO sewer_enabled
    FROM data_sources
    WHERE adapter_key = 'official.civil_iot.sewer_water_level';

    IF sewer_enabled IS DISTINCT FROM true THEN
        RAISE EXCEPTION
            '0062: healthy Civil IoT sewer source must remain catalog enabled';
    END IF;

    SELECT count(*) INTO readiness_count
    FROM ingestion_readiness_sources
    WHERE profile_key = 'production_backbone';

    IF readiness_count <> 9 THEN
        RAISE EXCEPTION
            '0062: expected 9 production readiness sources, found %',
            readiness_count;
    END IF;
END
$$;

COMMIT;
