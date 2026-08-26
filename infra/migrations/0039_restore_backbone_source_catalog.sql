-- Restore the catalog enablement of the realtime backbone sources.
--
-- Migration 0038 registered catalog rows for the official incident sources and
-- asserted `is_enabled = false` on every row it touched. That is correct for the
-- newly registered sources, but `official.ncdr.cap` was already part of the
-- production realtime backbone and was ingesting before this release.
--
-- This release also introduces the persisted source-catalog gate, which checks
-- `data_sources.is_enabled` before any upstream work. Without this migration the
-- gate would silently stop the seven backbone sources below, which were all
-- ingesting through their runtime gates before the gate existed. Enabling them
-- here restores the pre-release behavior; it does not turn on anything new.
--
-- Deliberately NOT enabled here:
--   official.cwa.heavy_rain_warning  - registered by 0038, never ingested
--   official.npa.police_radio_traffic - new non-scoring context source
--   official.wra.flood_warning        - new non-scoring context source
--   official.wra.historical_flood     - static/slow cadence, operator-driven
--
-- Each source's independent runtime gates still apply. This migration only
-- restores the catalog row, which is the outermost fence, to the state the
-- deployed service was already running with.

UPDATE data_sources
SET is_enabled = true,
    updated_at = now()
WHERE adapter_key IN (
        'official.ncdr.cap',
        'official.wra_iow.flood_depth',
        'official.civil_iot.flood_sensor',
        'official.civil_iot.sewer_water_level',
        'official.civil_iot.pump_water_level',
        'official.civil_iot.gate_water_level',
        'local.tainan.flood_sensor'
    )
    AND is_enabled = false;
