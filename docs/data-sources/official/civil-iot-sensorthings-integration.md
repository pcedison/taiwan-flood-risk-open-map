# Civil IoT Taiwan SensorThings Integration

Date: 2026-06-15
Status: adapters landed (disabled by default); live enablement gated on API keys
and hosted memory headroom.

## Goal

Strengthen realtime water-situation evidence by ingesting Taiwan's dense official
sensor networks. The earlier "即時資料不足" finding showed realtime risk goes
"未知" when no realtime observation falls inside the query radius; denser station
coverage (especially road flood sensors) directly reduces that gap.

## Why Civil IoT SensorThings, not per-sensor scraping

`ci.taiwan.gov.tw/dsp` (民生公共物聯網) publishes WRA flood sensors, river/
drainage water levels, agricultural pond levels, sewer levels, pump stations, and
CWA rainfall through one **OGC SensorThings API (STA)**. Integrating the STA hub
covers most requested networks with one client instead of 2,000+ per-sensor
connectors.

- Water-resource STA base: `https://sta.ci.taiwan.gov.tw/STA_WaterResource_v2/v1.0/`
- Shape: `Things` → `Locations` (GeoJSON Point, WGS84 `[lng, lat]`) →
  `Datastreams` → `Observations` (`phenomenonTime`, `result`).
- License: Government Open Data License v1.0 (compatible per SDD OQ-003).

## What landed (2026-06-15)

All adapters follow the existing `DataSourceAdapter` contract (live API variant +
fixture-backed variant), are registered in `app/adapters/registry.py`, and are
**disabled by default**.

| Adapter key | Dataset | Event type | Notes |
|---|---|---|---|
| `official.civil_iot.flood_sensor` | 淹水感測器 (`water_12`) | `flood_report` | Road surface flood depth. |
| `official.civil_iot.river_water_level` | 河川水位站 (`iow01`) | `water_level` | Overlaps `official.wra.water_level`. |
| `official.civil_iot.pond_water_level` | 埤塘水位 (`iow12`) | `water_level` | Agricultural; indirect signal. |
| `official.civil_iot.sewer_water_level` | 雨水下水道 (國土署) | `water_level` | Urban drainage loading. |
| `official.civil_iot.pump_water_level` | 抽水站 (`pump_taipei`) | `water_level` | Reads external (外水位) level. |

Shared STA client: `app/adapters/civil_iot/sta_client.py`
(`parse_sta_things_payload`, `fetch_sta_json`). Pond/sewer/pump share one
configurable adapter in `app/adapters/civil_iot/sta_water_level.py`.

### CWA full station network is already integrated

The full CWA automatic rainfall network (`O-A0002-001`, ~570 stations) is
**already** ingested by the existing `official.cwa.rainfall` adapter via
`opendata.cwa.gov.tw`; it only needs an API key and live enablement, not a new
adapter.

### Modeling decision — flood sensor event type

A road flood sensor reading at or above `FLOOD_SENSOR_MIN_DEPTH_CM` (default
3 cm) is treated as an observed flood event (`flood_report`); lower/dry readings
are rejected so routine no-flood telemetry does not become evidence noise. This
makes a genuine flooding reading strengthen both the realtime layer (recent
`flood_report` weight) and the historical record (a road that actually flooded is
a real historical event). The threshold is a module constant and can be tuned by
the domain team before live enablement.

### River water level overlap

`official.civil_iot.river_water_level` is an alternative STA-sourced path to the
existing `official.wra.water_level` (which reads `opendata.wra.gov.tw`). Enable
only one, or dedup by station id, to avoid double-counting.

## Live enablement gates (NOT yet enabled)

Both adapters are off until two external prerequisites are met:

1. **API keys / access.** Civil IoT STA endpoints are largely public, but the
   full CWA station network (follow-up below) needs a free `opendata.cwa.gov.tw`
   key and WRA's IoT platform needs membership. These must be supplied by the
   operator; they are read from env, never committed.
2. **Hosted memory headroom.** The Zeabur node is 2C/2GB with PostGIS OOM
   history. Ingesting 2,000+ flood sensors plus river levels every few minutes
   multiplies evidence volume and can pressure the node. Before live enablement,
   decide on a station/geography subset, retention/pruning, and cadence — or wait
   for a 4 GB upgrade.

Enable (after the gates above) with, e.g.:

```bash
SOURCE_FLOOD_SENSOR_ENABLED=true
SOURCE_FLOOD_SENSOR_API_ENABLED=true
# optional override; blank uses the built-in default STA query
CIVIL_IOT_FLOOD_SENSOR_URL=
CIVIL_IOT_API_TIMEOUT_SECONDS=8
```

## Follow-up sources

Pond (`iow12`), sewer (國土署), and pump (`pump_taipei`) adapters landed
2026-06-15 (above). Remaining optional networks on the same STA client when
prioritized: CWA automatic weather stations (`O-A0001-001`, which also report
rainfall and would complement `O-A0002-001`), CCTV-derived signals, and other
agency water datastreams. The full CWA rainfall network itself is already
covered by `official.cwa.rainfall`.
