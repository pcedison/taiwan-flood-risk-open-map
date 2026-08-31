# Nationwide recent flood history

The recent-history recovery contract has two complementary official paths. It
does not depend on a manually curated road or a single county.

## 1. Nationwide official citation recovery

`official.gov_tw.flood_citation` is enabled for hosted API queries when nearby
observed flood history is older than one year.

- Scope: all Taiwan query points supported by the bundled national village data.
- Window: the current year plus the previous six calendar years on every
  eligible lookup.
- Accepted publishers: HTTPS Taiwan government domains ending in `.gov.tw` or
  `.gov.taipei`.
- Stored data: title, citation URL, publication time, official publisher
  domain, and location-match metadata only.
- Rejected data: article bodies, images, comments, non-government publishers,
  undated results, future-dated results, and results older than the rolling
  window.
- Precision: road matches remain road-level; district/town matches are
  `admin_area`. Neither is a doorplate-level measured depth.
- Completeness: search indexes are not official event registries. An empty
  result is a visible coverage gap, never evidence that flooding did not occur.
- Kill switch: `OFFICIAL_NATIONWIDE_HISTORY_CITATIONS_ENABLED=false`.

The former `official.tainan.disaster_news` request path is superseded and
disabled by migration 0054. Its previously stored citations remain available
for audit and deduplication.

## 2. WRA durable incident accumulation

`official.wra.flood_incident` implements the Water Resources Agency endpoint
`GET /OpenApiv3/v2/Disaster/Flooding`. The documented response contains all 22
county/city groups for the latest disaster event, including incident ID, time,
town code, location, optional WGS84 point, source/category codes, reported
depth, and recession state.

The Swagger operation defaults `$top` to 15, which is insufficient for 22
county/city groups. The reviewed adapter URL therefore requires `$top` between
22 and 5,000 and uses `$top=100`; alternate paths or query parameters are
rejected before the API key is sent.

The endpoint is not a historical archive. Once production polling is approved,
the worker stores raw snapshots and promotes each unique incident as historical
evidence. Repeated polling is idempotent, while a later disaster event adds new
rows instead of replacing prior history. This creates a real cross-year archive
from the activation date forward.

Production remains fail-closed until all controls are present:

- `SOURCE_WRA_FLOOD_INCIDENT_ENABLED=true`
- `SOURCE_WRA_FLOOD_INCIDENT_API_ENABLED=true`
- `SOURCE_WRA_FLOOD_INCIDENT_CONTRACT_ENABLED=true`
- `WRA_FLOOD_INCIDENT_API_KEY` stored only in the deployment secret manager
- the adapter key included in `WORKER_ENABLED_ADAPTER_KEYS`
- the reviewed `data_sources` catalog row explicitly changed to `is_enabled=true`

The public API schema does not state a unit for `Depth`. The adapter therefore
retains the raw numeric value with `upstream_schema_unspecified` and never
converts it to centimetres.

## Acceptance standard

A recent flood record is public evidence only when it has an official source,
an event/publication time, a traceable citation or source ID, a location and
declared precision, an idempotent identity, and an explicit limitation. Source
health, rolling coverage years, and incomplete-coverage status must remain
visible so missing ingestion cannot be presented as safety.
