# Public Source Adapter Attempts - 2026-07-02

## Summary

This pass rechecked public sources for the remaining local signal gaps and attempted adapter work where a source exposed latest-observation fields without credentials.

Completed code changes:

- Added `local.yilan.mobile_pump_status` from Yilan ArcGIS REST layer 1.
- Fixed Yilan ArcGIS HTTPS fetching on Python 3.13/OpenSSL by relaxing strict X.509 verification while keeping CA and hostname verification enabled.
- Fixed Civil IoT county inference for Taoyuan legacy city glyphs, so `official.civil_iot.gate_water_level` now contributes Taoyuan gate-water-level coverage.
- Regenerated signal-gap discovery and official request artifacts.

Current generated gap counts after this pass:

- `pump_or_gate_status`: 11 counties.
- `flood_depth`: 3 counties.
- `sewer_water_level`: 1 county.
- Total signal-gap county-items: 15.

## Adapter Attempts

| # | Source checked | Target gap | Result | Reason |
| --- | --- | --- | --- | --- |
| 1 | Civil IoT Water Resource `water_15` gate water level | Taoyuan `pump_or_gate_status` / gate-water-level backbone | Implemented coverage fix | Live payload included Taoyuan records but the authority string used a legacy `桃園巿` glyph. Added alias normalization and coverage mapping. |
| 2 | Civil IoT Water Resource `water_14` pump water level | Remaining pump/gate counties | No new adapter | Existing adapter already works, but live smoke did not return target-county records for the remaining 11 pump/gate counties. |
| 3 | Yilan ArcGIS REST layer 1 `移動式抽水機_昕傳` | Yilan `pump_or_gate_status` | Implemented `local.yilan.mobile_pump_status` | Layer exposes `id`, `status`, `LogDate`, `operateat`, `voltage`, `lon`, and `lat`; live smoke fetched/normalized 42 rows. |
| 4 | Yilan ArcGIS REST layer 3 `抽水機_昕傳` | Yilan pump status | Deferred | Layer appears usable but overlaps layer 1 and has a narrower tachometer-oriented schema; layer 1 was the cleaner status-only production adapter. |
| 5 | Yilan ArcGIS REST layer 5 `抽水站` | Yilan pump/gate status | Not implemented | Public layer is facility/status metadata without a clear latest observation timestamp equivalent to layer 1. |
| 6 | Keelung smartflood existing APIs | Keelung `pump_or_gate_status` | Not implemented | Existing water/flood/rain endpoints are public and already implemented. Guessed pump/gate routes returned 404 or empty results; no safe public read API was confirmed. |
| 7 | New Taipei open-data water gate and pump datasets | New Taipei `pump_or_gate_status` | Not implemented | Datasets are static or yearly metadata, not latest-operation or latest-observation APIs. |
| 8 | Taoyuan pump and water-gate open datasets | Taoyuan pump/gate status | No local adapter; central coverage fixed | Public datasets describe quantities or gate metadata. The real measurable improvement came from Civil IoT gate water level, not local static datasets. |
| 9 | Penghu ArcGIS SewerNew layers 5/8/9/20 | Penghu `flood_depth` / pump/gate status | Not implemented | Layers are rain-station metadata, static flood-prone-point interviews, or facility metadata; layer 6 water level was already implemented. |
| 10 | data.gov.tw signal-gap catalog refresh | All remaining gaps | No live-read candidates found | Refresh found 9 metadata-only candidates and 0 live-read API candidates for remaining signal gaps. |

## Public Evidence Links

- Civil IoT Water Resource dataset page: <https://ci.taiwan.gov.tw/dsp/Views/_EN/dataset/water.aspx>
- Yilan ArcGIS REST service: <https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer>
- Keelung smartflood platform: <https://smartflood.klcg.gov.tw/keelung_web/>
- New Taipei water-gate dataset: <https://data.ntpc.gov.tw/datasets/bf784279-31aa-44bc-a210-33151d03e7ab>
- Taoyuan pump dataset: <https://data.gov.tw/dataset/152939>
- Taoyuan water-gate dataset: <https://data.gov.tw/en/datasets/46582>
- Penghu ArcGIS SewerNew service: <https://ph3dgis.penghu.gov.tw/server/rest/services/SewerNew/PHSewer_Basemap/MapServer>

## Generated Artifacts

- `docs/reviews/signal-gap-discovery-refresh-2026-07-02-public-source-adapter-attempts/signal-gap-discovery-refresh-summary.json`
- `docs/reviews/signal-gap-discovery-refresh-2026-07-02-public-source-adapter-attempts/signal-gap-discovery-refresh-pump-or-gate-status.json`
- `docs/reviews/signal-gap-discovery-refresh-2026-07-02-public-source-adapter-attempts/signal-gap-discovery-refresh-flood-depth.json`
- `docs/reviews/signal-gap-discovery-refresh-2026-07-02-public-source-adapter-attempts/signal-gap-discovery-refresh-sewer-water-level.json`
