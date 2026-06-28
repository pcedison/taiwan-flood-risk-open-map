# Official Data Sources

Phase 2 official ingestion starts with fixture-locked parsers before production network fetchers are enabled. Each adapter preserves source URL, timestamp, source family, event type, attribution, confidence, and raw snapshot key.

As of 2026-04-30, the public risk API also has a live official-data bridge for MVP risk assessment. It reads Central Weather Administration rainfall observations and Water Resources Agency water-level observations directly, joins WRA station metadata for coordinates, and exposes the nearest station evidence plus source health in `/v1/risk/assess`. This removes the former public UI limitation messages for rainfall and water level when the official sources are healthy.

This bridge is not Phase 2 completion by itself. Phase 2 acceptance still requires worker ingestion, raw snapshots, staging/promote, source health, and persisted evidence that can be audited later. It also must not be used to infer that historical home-buying flood risk is low just because current rainfall or water level is normal.

| Adapter key | Source family | Event type | Status |
|---|---|---|---|
| `official.cwa.rainfall` | `official` | `rainfall` | Fixture parser + API bridge + gated worker live client implemented |
| `official.wra.water_level` | `official` | `water_level` | Fixture parser + API bridge + gated worker live client implemented |
| `official.wra_iow.flood_depth` | `official` | `flood_report` | Gated worker live client implemented; joins latest flood depth with station metadata |
| `official.flood_potential.geojson` | `official` | `flood_potential` | Fixture parser implemented |
| `official.nstc.flood_disaster_points` | `official` | `flood_report` | API bundled historical snapshot fallback implemented; not a rolling current-year source |

Current official endpoints used by the MVP bridge:

- CWA automatic rainfall observations: `https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001`
- WRA realtime water level observations: `https://opendata.wra.gov.tw/api/v2/73c4c3de-4045-4765-abeb-89f9f9cd5ff0`
- WRA water-level station metadata: `https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92`
- WRA IoW latest flood depth observations: `https://opendata.wra.gov.tw/api/v2/1b991bbb-ad85-4e7a-b931-06ce8749d3ed`
- WRA IoW flood sensor metadata: `https://opendata.wra.gov.tw/api/v2/21c50be1-7c4a-4fdf-a386-790625e984e7`

Latest data.gov.tw review:

- `docs/data-sources/official/data-gov-tw-source-review-2026-05-12.md`
  records the 2026-05-12 source comparison requested for public beta. It keeps
  CWA rainfall dataset 9177, WRA water-level dataset 25768, and WRA
  flood-potential dataset 25766 as preferred official sources. It now also
  tracks dataset 130016 as an official observed flood-disaster point snapshot,
  while noting that all-Taiwan doorplates are not solved by data.gov.tw.
- `docs/data-sources/official/official-source-catalog.yaml` is the
  machine-readable source catalog. Worker official adapter metadata is tested
  against it so data.gov.tw remains the primary public catalog reference while
  raw snapshots can still retain concrete resource URLs.
- `docs/data-sources/geocoding/geocoding-data-manifest.yaml` now carries the
  matching data.gov.tw dataset IDs, landing URLs, resource URLs, and source
  catalog keys for the primary geocoder inputs: village boundaries dataset 7438,
  national road names dataset 35321, and shelter points dataset 73242. The
  closed doorplate suggestion 136942 is explicitly tracked as unavailable.

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
- data.gov.tw dataset 130016 maps to an official observed historical
  flood-disaster point CSV snapshot. A direct 2026-05-13 resource download
  returned 5,923 rows covering 2018-2022 only; it does not currently include
  2023-2026 events. The API labels it as a snapshot and marks it degraded when
  the coverage end year is older than the current Taiwan year. Recent flood
  facts must be corroborated through public news/wiki metadata or other
  separately modeled official sources, not mixed into this official snapshot.
- DPRC flood-potential SHP packages are handled as planning/reference data, not
  realtime observations. Local all-Taiwan import evidence was recorded on
  2026-05-05 under `tmp/evidence/flood-potential/`; `tmp/` is local scratch and
  should promote only curated summaries into tracked docs.
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
