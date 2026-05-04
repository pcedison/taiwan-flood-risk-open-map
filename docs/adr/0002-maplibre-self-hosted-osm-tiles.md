# ADR-0002: MapLibre and Open PMTiles Basemap

## Title

MapLibre GL JS with PMTiles/Protomaps OpenStreetMap-Derived Basemap

## Status

Accepted

## Date

2026-04-28

## Updated

2026-05-04

## Context

The product is map-first and must remain open-source-first, self-hostable, and
usable without a commercial map API. The original plan treated self-hosted
Taiwan OSM vector tile infrastructure as a production readiness dependency.
That made map launch depend on a comparatively heavy tile server pipeline.

The new launch path should minimize operating burden while preserving control
over the public basemap, attribution, and provider portability. A static
PMTiles archive served from object storage/CDN is a better MVP default than a
full tile-generation and tile-server stack. It supports MapLibre GL JS, can use
OpenStreetMap-derived data through Protomaps or similar sources, and relies on
HTTP range requests rather than a long-running tile service.

OSM-derived data carries attribution and ODbL obligations. The service must not
present public OpenStreetMap tile endpoints as production infrastructure.

TGOS can be valuable for Taiwan-local geocoding, basemap, or government data
integration later, but it must not block the MVP or the public-interest launch.

## Decision

Use MapLibre GL JS as the primary web map renderer.

Use an open basemap path as the launch baseline:

- PMTiles or Protomaps-compatible OpenStreetMap-derived vector tiles.
- A MapLibre style JSON that is either project-owned, prebuilt and licensed for
  our use, or hosted by a provider whose terms permit the intended launch.
- Object storage plus CDN as the first production delivery path, with
  Cloudflare R2 or any S3-compatible service as acceptable targets.

For MVP and public-interest launch, prefer the lowest-operations path:

1. Use a prebuilt Taiwan/region PMTiles archive or licensed hosted style JSON.
2. Serve PMTiles through object storage/CDN with HTTP range request support,
   long-lived cache headers, and a versioned object path.
3. Keep risk overlays, query heat, flood-potential layers, and other project
   overlays independent from the basemap provider.

Do not use `tile.openstreetmap.org` or other public OSM community tile
endpoints as a production dependency. They are acceptable only for local
development, short-lived prototypes, or explicit emergency fallback while
respecting the upstream usage policy.

Treat TGOS as a future optional Taiwan-local provider. It can be implemented as
a configurable geocoder, basemap, or supplemental provider after credentials,
terms, cost, reliability, and attribution are reviewed. It is not an MVP or
public launch blocker.

Defer heavier tile infrastructure until traffic, data freshness, or styling
needs justify it. Candidate future stacks include OpenMapTiles, Tegola,
PostGIS/ST_AsMVT, Martin, or a dedicated vector tile server. Those options need
more operational ownership for generation, refresh cadence, cache invalidation,
monitoring, storage, and rollback.

Expose map sources through explicit layer metadata and style/source endpoint
configuration so new basemaps or overlays do not require changes to the core
risk query flow.

## Data and License Governance

Public maps using OSM-derived data must show visible OpenStreetMap attribution
and make the ODbL basis clear. The attribution must not be hidden behind UI,
cropped off-screen, or omitted from screenshots intended for publication.

Any OSM-derived database, export, PMTiles archive, or generated tileset must
keep source metadata, generation date, upstream provider, style/license notes,
and ODbL obligations in the attribution manifest.

Do not publish a combined dataset under a single simplified license when source
layers have different obligations. Public exports should separate project-owned
metadata, OSM-derived basemap data, government open data, and derived risk
summaries.

## Consequences

The project avoids lock-in to commercial map providers and can still run in
self-hosted or low-cost environments.

Launch no longer depends on building and operating a full Taiwan OSM tile
server. The first public path can be static PMTiles plus object storage/CDN.

Production operations must verify range request behavior, CDN cache headers,
visible attribution, style JSON availability, and rollback to the previous
PMTiles/style version.

ODbL compliance must be considered whenever OSM-derived data is stored,
transformed, tiled, cached, or exported.

The project keeps a clear upgrade path to OpenMapTiles/Tegola/PostGIS tile
serving when the operating cost is justified.

## Acceptance Criteria

- Browser runtime can load a project-controlled or licensed MapLibre style.
- Basemap tiles load from project-controlled object storage/CDN or an explicitly
  licensed hosted provider.
- Risk overlays and existing MVT/query overlays continue to render on top of
  the basemap.
- Runtime smoke and public launch checks do not require TGOS.
- Documentation and runbooks cover attribution, ODbL/export notes, range
  request checks, cache behavior, and rollback.
- Production configuration does not directly depend on public OSM tile
  endpoints.

## References

- OpenStreetMap copyright and ODbL attribution:
  https://www.openstreetmap.org/copyright
- OpenStreetMap tile usage policy:
  https://operations.osmfoundation.org/policies/tiles/
- Protomaps and PMTiles documentation:
  https://docs.protomaps.com/
- PMTiles concepts and HTTP range request behavior:
  https://docs.protomaps.com/pmtiles/
