# Public Beta MVP Open Data Plan

Status: accepted for MVP planning
Date: 2026-05-04

This plan records the public-beta path after TGOS was removed as an MVP
blocker. The project is public-interest infrastructure, so the default path is
open source software and open or explicitly reusable public data.

Execution roadmap: `docs/runbooks/public-beta-execution-roadmap.md`
Open-data geocoder import: `docs/runbooks/open-data-geocoder-import.md`

## Decisions

- TGOS is optional and future-only. It must not block MVP or public beta.
- Geocoding must prefer open-source and open-data paths.
- PTT, Dcard, forum crawling, and user-submitted reports remain frozen for MVP.
- The first public beta should prove unknown Taiwan address search, risk query,
  and visible evidence/limitations before expanding ingestion scope.

## Geocoding Path

MVP provider order:

1. File-backed local open-data geocoder from `GEOCODER_OPEN_DATA_PATHS`, then a
   future `TaiwanAddressDbProvider`/PostGIS index from reviewed address, road,
   or POI sources.
2. `OpenStreetMapProvider`: self-hosted or project-controlled OSM-based search
   from Taiwan extracts.
3. `NominatimDevFallbackProvider`: public Nominatim only for development or
   low-volume diagnostics, with cache and attribution.
4. `WikimediaPoiFallbackProvider`: POI-only fallback for landmarks, not precise
   address matching.

Candidate datasets and tools:

- Taipei address points: public monthly CSV with address components and
  coordinates.
- Geofabrik Taiwan OSM extract: OSM PBF/GPKG/SHP for self-hosted search,
  POI/road fallback, and future Nominatim/Photon/Pelias imports.
- Nominatim or Photon can be used as the first self-hosted OSM geocoder.
- Pelias is the long-term target when we need to combine OSM, OpenAddresses,
  Who's On First, and project-owned address points.

Acceptance rules:

- If a query resolves only to county/city/district precision, the UI must ask
  the user to confirm or click the map instead of silently running a precise
  risk assessment.
- If the geocoder confidence is low, the API should return candidates with
  precision and limitation metadata; the frontend should not pretend the
  location is exact.
- Unknown-address E2E tests must use real local fixtures, not only mocked
  frontend routes.

Implemented local file-backed path:

- `GEOCODER_OPEN_DATA_PATHS` accepts comma-separated UTF-8 CSV or JSONL files.
- Supported fields include `name`, `aliases`, `lat`, `lng`, `admin_code`,
  `precision`, `type`, and `source`.
- File-backed open-data rows are checked before bundled fixtures and before any
  public fallback.

## CWA Rainfall

Use the Central Weather Administration open-data rainfall observation dataset
for MVP rainfall signals.

Operator steps:

1. Register or log in to the CWA open-data platform.
2. Open the member/API authorization page and generate an API authorization
   code.
3. Store it in `CWA_API_AUTHORIZATION`.
4. Keep `SOURCE_CWA_API_ENABLED=false` until a live smoke run is recorded.
5. Cache or persist rainfall observations; do not call CWA once per user query.

Current assessment:

- The CWA rainfall dataset is open-data, free, and updated every 10 minutes.
- I did not find an official IP/domain binding requirement for the ordinary CWA
  open-data API path.
- Some separate government or agriculture weather APIs may have IP/domain
  binding; those are not the MVP source path.

## WRA Water Level

Use the WRA government open-data realtime water-level dataset first.

Operator steps:

1. Prefer the public WRA open-data dataset/API path for realtime water level.
2. Keep `SOURCE_WRA_API_ENABLED=false` until the endpoint URL is verified in a
   smoke run.
3. If a selected WRA endpoint requires a token, store it in `WRA_API_TOKEN`.
4. Show a limitation in the UI that realtime water-level data is raw and may be
   delayed, interrupted, or abnormal.

Current assessment:

- The public WRA realtime water-level dataset is government open data, free,
  and has documented update cadence/limitations.
- The WRA Water IoT API is a different path. It requires member registration,
  API credential ID/password, and short-lived access tokens.
- I did not find a TGOS-like IP/domain binding requirement for the public WRA
  open-data dataset path.

## Flood Potential

Use WRA/DPRC flood-potential SHP downloads as an offline import, not a live API.

MVP steps:

1. Download reviewed SHP packages.
2. Record source URL, retrieval date, license/usage notes, and rainfall
   scenario.
3. Convert to project MVT/PMTiles or PostGIS features.
4. Display it as a historical/planning risk layer, not a live flood warning.

## Basemap

Use MapLibre plus PMTiles/Protomaps-compatible assets from static object
storage/CDN.

MVP steps:

1. Use a project-controlled PMTiles/style URL.
2. Verify range requests, CORS, cache headers, and attribution.
3. Keep public OSM community tiles as local-development fallback only.

## Community And Social Signals

MVP should not crawl PTT, Dcard, or social networks. Better public-beta options:

- Use official agency feeds and open-data event streams first.
- Use reviewed public news/GDELT only as citation metadata, not full-text
  redistribution.
- Add a public "source suggestion" form later, not direct ingestion.
- Enable user reports only after moderation, abuse prevention, privacy
  redaction, and takedown workflows are implemented.

## Public Beta Gate

Before Zeabur public beta:

- Unknown Taiwan address E2E passes with real local geocoder fixtures.
- CWA rainfall live smoke passes or is visibly disabled with limitations.
- WRA water-level live smoke passes or is visibly disabled with limitations.
- Flood-potential offline layer is loaded with attribution and scenario notes.
- Basemap loads from project-controlled static assets with no public OSM tile
  dependency.
- UI clearly distinguishes exact address, road/lane fallback, district fallback,
  and map-click locations.
