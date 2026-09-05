-- Realtime freshness windows were left at the ten-minute repository default,
-- but CWA rainfall, WRA water level and the Civil IoT water-level networks all
-- publish ten-minute observations several minutes after the observation time,
-- and ingestion polls every five minutes. A query therefore almost always sees
-- observations aged 10-20 minutes, so the public health view reported
-- "fresh 0" for every station on every backbone source while the data was in
-- fact current. Thirty minutes covers one publication cycle plus ingestion and
-- query lag. The WRA IoW flood-depth network publishes hourly, so it gets the
-- same 90-minute window already used by the CWA tide observations (0051).
--
-- Idempotent: re-running rewrites the same metadata key with the same value.

BEGIN;

UPDATE data_sources
SET metadata = jsonb_set(
        COALESCE(metadata, '{}'::jsonb),
        '{freshness_threshold_seconds}',
        to_jsonb(1800),
        true
    ),
    updated_at = now()
WHERE adapter_key IN (
    'official.cwa.rainfall',
    'official.wra.water_level',
    'official.civil_iot.sewer_water_level',
    'official.civil_iot.flood_sensor',
    'official.civil_iot.pump_water_level',
    'official.civil_iot.gate_water_level',
    'official.civil_iot.river_water_level',
    'official.civil_iot.pond_water_level'
);

UPDATE data_sources
SET metadata = jsonb_set(
        COALESCE(metadata, '{}'::jsonb),
        '{freshness_threshold_seconds}',
        to_jsonb(5400),
        true
    ),
    updated_at = now()
WHERE adapter_key = 'official.wra_iow.flood_depth';

COMMIT;
