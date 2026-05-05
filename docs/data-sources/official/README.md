# Official Data Sources

Phase 2 official ingestion starts with fixture-locked parsers before production network fetchers are enabled. Each adapter preserves source URL, timestamp, source family, event type, attribution, confidence, and raw snapshot key.

As of 2026-04-30, the public risk API also has a live official-data bridge for MVP risk assessment. It reads Central Weather Administration rainfall observations and Water Resources Agency water-level observations directly, joins WRA station metadata for coordinates, and exposes the nearest station evidence plus source health in `/v1/risk/assess`. This removes the former public UI limitation messages for rainfall and water level when the official sources are healthy.

This bridge is not Phase 2 completion by itself. Phase 2 acceptance still requires worker ingestion, raw snapshots, staging/promote, source health, and persisted evidence that can be audited later. It also must not be used to infer that historical home-buying flood risk is low just because current rainfall or water level is normal.

| Adapter key | Source family | Event type | Status |
|---|---|---|---|
| `official.cwa.rainfall` | `official` | `rainfall` | Fixture parser + API bridge + gated worker live client implemented |
| `official.wra.water_level` | `official` | `water_level` | Fixture parser + API bridge + gated worker live client implemented |
| `official.flood_potential.geojson` | `official` | `flood_potential` | Fixture parser implemented |

Current official endpoints used by the MVP bridge:

- CWA automatic rainfall observations: `https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001`
- WRA realtime water level observations: `https://opendata.wra.gov.tw/api/v2/73c4c3de-4045-4765-abeb-89f9f9cd5ff0`
- WRA water-level station metadata: `https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92`

Source mapping notes:

- data.gov.tw dataset 9177 maps to the CWA `O-A0002-001` automatic rainfall
  station endpoint. This is the canonical rainfall source for the current
  adapter and public MVP bridge because it exposes `RainfallElement` values.
- CWA `O-A0003-001` is a 10-minute automatic weather station observation
  endpoint. It is useful as a future supplemental weather source, but it should
  not replace `O-A0002-001` in the rainfall adapter because its current payload
  exposes `WeatherElement`, not `RainfallElement`.
- data.gov.tw dataset 25768 maps to the WRA realtime water-level endpoint used
  by the worker adapter and public MVP bridge.
- DPRC flood-potential SHP packages are handled as planning/reference data, not
  realtime observations. Local all-Taiwan import evidence was recorded on
  2026-05-05 under `tmp/evidence/flood-potential/`.
- Protomaps/PMTiles belongs to the basemap delivery path. It is not an evidence
  source for flood risk by itself, but the web app supports operator-owned
  PMTiles, raster, or MapLibre style URLs through `NEXT_PUBLIC_BASEMAP_*`.

2026-05-05 automated source smoke evidence:

- `tmp/evidence/official-sources/cwa-o-a0002-rainfall-2026-05-05.json`:
  1,303 CWA rainfall stations downloaded and parsed by
  `official.cwa.rainfall`.
- `tmp/evidence/official-sources/cwa-o-a0003-weather-2026-05-05.json`:
  362 CWA weather stations downloaded; rainfall parser correctly produced zero
  records because the payload has no `RainfallElement`.
- `tmp/evidence/official-sources/wra-water-level-2026-05-05.json`: 372 WRA
  water-level rows downloaded, parsed, and normalized by
  `official.wra.water_level`.
- `tmp/evidence/official-sources/wra-water-stations-2026-05-05.json`: 857 WRA
  station metadata rows downloaded for bridge context; it is not a water-level
  observation payload.

Worker live clients are still explicit opt-in paths. CWA uses
`SOURCE_CWA_API_ENABLED=true` plus `CWA_API_AUTHORIZATION`; WRA uses
`SOURCE_WRA_API_ENABLED=true` with optional `WRA_API_TOKEN`. These gates prove a
deployable worker path exists for local/preview acceptance, not production beta
readiness. Flood-potential remains fixture/demo only; adding its worker gate
would prove only a deployable path until the upstream and operations reviews
below are accepted.

Production enablement requirements:

- complete real upstream URL/license review and attribution text;
- complete credential review for every source and environment;
- record retrieval cadence and freshness threshold;
- document hosted cadence and scheduler ownership;
- configure alert routing and source-health ownership;
- complete poison-job quarantine/replay audit before relying on queue replay;
- verify production egress from the deployed environment;
- store raw snapshots before staging normalized evidence;
- keep adapter disablement controlled by configuration;
- fail with structured errors without blocking the public API.
- promote the MVP live bridge into the worker ingestion pipeline so public API reads persisted, auditable snapshots instead of fetching upstream sources on demand.
