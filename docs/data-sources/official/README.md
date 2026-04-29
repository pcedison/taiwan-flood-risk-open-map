# Official Data Sources

Phase 2 official ingestion starts with fixture-locked parsers before production network fetchers are enabled. Each adapter preserves source URL, timestamp, source family, event type, attribution, confidence, and raw snapshot key.

As of 2026-04-29, the public risk API also has a live official-data bridge for MVP risk assessment. It reads Central Weather Administration rainfall observations and Water Resources Agency water-level observations directly, joins WRA station metadata for coordinates, and exposes the nearest station evidence plus source health in `/v1/risk/assess`. This removes the former public UI limitation messages for rainfall and water level when the official sources are healthy.

This bridge is not Phase 2 completion by itself. Phase 2 acceptance still requires worker ingestion, raw snapshots, staging/promote, source health, and persisted evidence that can be audited later. It also must not be used to infer that historical home-buying flood risk is low just because current rainfall or water level is normal.

| Adapter key | Source family | Event type | Status |
|---|---|---|---|
| `official.cwa.rainfall` | `official` | `rainfall` | Fixture parser + live API bridge implemented |
| `official.wra.water_level` | `official` | `water_level` | Fixture parser + live API bridge implemented |
| `official.flood_potential.geojson` | `official` | `flood_potential` | Fixture parser implemented |

Current official endpoints used by the MVP bridge:

- CWA automatic rainfall observations: `https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001`
- WRA realtime water level observations: `https://opendata.wra.gov.tw/api/v2/73c4c3de-4045-4765-abeb-89f9f9cd5ff0`
- WRA water-level station metadata: `https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92`

Production enablement requirements:

- confirm upstream license and attribution text;
- record retrieval cadence and freshness threshold;
- store raw snapshots before staging normalized evidence;
- keep adapter disablement controlled by configuration;
- fail with structured errors without blocking the public API.
- promote the MVP live bridge into the worker ingestion pipeline so public API reads persisted, auditable snapshots instead of fetching upstream sources on demand.
