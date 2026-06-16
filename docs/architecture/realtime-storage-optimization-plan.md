# Realtime Storage and Load Optimization Plan

Last updated: 2026-06-16

## Purpose

This document records the next optimization track for Flood Risk after the
hosted realtime query speed-up. It focuses on reducing memory pressure, database
scan cost, API payload size, and map serving load while keeping the public risk
answer explainable.

The current production symptom is not only "too much data". Hosted PostGIS has
also shown eviction / `MemoryPressure`, and transient database timeouts can
make the API fall back to partial realtime evidence. Compression helps, but the
first goal is to make the hot read path small, indexed, and cache-safe.

## Current Observations

- `POST /v1/risk/assess` is faster after narrowing realtime evidence queries,
  but some searches can still show an "insufficient realtime data" conclusion
  when the repository query or official station snapshot is temporarily
  unavailable.
- A degraded fallback response must not be stored as a successful cached
  response. Otherwise users can keep seeing the insufficient-data conclusion
  after the next query would have recovered.
- The `evidence` table carries several workloads at once: historical records,
  realtime station observations, source audit payloads, map/search evidence,
  and scoring context. Long-term optimization should split hot read models from
  archival/audit storage.
- Zeabur app health and PostGIS health must be monitored separately. A healthy
  web/API container can still produce weak results if PostGIS was recently
  evicted or is rebuilding cache.

## Optimization Goals

- Keep p95 public risk query latency below 3 seconds for normal hosted traffic.
- Avoid caching degraded realtime responses caused by transient repository
  unavailability.
- Keep live official rainfall/water-level lookup index-friendly and bounded.
- Reduce PostGIS memory pressure by separating latest station reads from full
  evidence history.
- Reduce storage and transfer cost without losing auditability.

## Non-Goals

- Do not replace PostGIS spatial correctness with ad-hoc string or JSON scans.
- Do not hide data gaps in the UI. The user should still see clear freshness
  status when official sources are stale or unavailable.
- Do not rely on public OSM/community tile endpoints as production map
  infrastructure.

## Phase 0 - Immediate Guardrails

Status: in progress.

Actions:

- Keep the risk response cache versioned so old degraded Redis entries do not
  survive a backend query fix.
- Cache successful assessment responses only when the evidence repository was
  reachable, or when the repository is explicitly disabled for that environment.
- Keep realtime rainfall/water-level SQL shaped around indexed predicates:
  `source_type`, `event_type`, `observed_at`, `geom && ST_Expand(...)`, then
  `ST_DWithin(...)`.
- Add deployment smoke checks for `/ready` and at least two known public
  locations, one in northern Taiwan and one in southern Taiwan.

Acceptance criteria:

- A first request that hits a transient repository timeout is not reused for the
  second request.
- When official rainfall or water-level evidence exists near the query point,
  the response includes `db-evidence` freshness and does not summarize the
  result as insufficient realtime data.
- Zeabur deployment is `RUNNING`, `/ready` returns the current commit SHA, and
  public smoke tests return HTTP 200.

## Phase 1 - Hosting Stability Before Compression

Compression will not fix a database that is being evicted. Stabilize the runtime
first.

Actions:

- Move PostGIS to managed Postgres/PostGIS or a Zeabur plan with enough memory
  headroom and persistent I/O for spatial indexes.
- Keep API and ingestion/scheduler workers as separate services. Ingestion
  bursts should not compete with public request handling inside one process.
- Add alerts for:
  - Postgres restarts / evictions.
  - API 502/503 spikes.
  - `EvidenceRepositoryUnavailable` count.
  - realtime source freshness age.
- Keep connection limits explicit. If needed, introduce PgBouncer in transaction
  pooling mode after checking driver compatibility.

Acceptance criteria:

- No PostGIS eviction during a 24-hour public smoke window.
- Official ingestion continues while public API p95 remains stable.
- Database connection count remains below the hosted plan limit under load.

## Phase 2 - Latest Realtime Read Model

The largest practical improvement is to stop using the full `evidence` table as
the primary lookup path for latest station state.

Actions:

- Add an `official_realtime_latest` table keyed by:
  - provider/source id.
  - event type, such as `rainfall` or `water_level`.
  - station id.
- Store only the latest accepted observation per station:
  - `observed_at`.
  - normalized metric columns, such as `rainfall_mm_1h`, `water_level_m`.
  - `geom`.
  - compact attribution fields.
  - pointer to the full evidence/audit row.
- Upsert this table from the worker promotion path.
- Query `official_realtime_latest` first for public risk assessment. Fall back
  to `evidence` only for historical/contextual records.
- Add partial GiST indexes per event type for hot latest rows.

Acceptance criteria:

- The public realtime query reads tens/hundreds of latest station rows, not
  thousands of time-series evidence rows.
- `EXPLAIN (ANALYZE, BUFFERS)` shows spatial index usage for station lookup.
- The API can still link each latest station reading back to full evidence and
  raw-source audit records.

## Phase 3 - Partitioning and Retention

Partition the heavy time-series/audit data so retention and index maintenance
are cheap.

Actions:

- Partition large append-only tables by time, starting with `observed_at` or
  `ingested_at`.
- Keep hot partitions small, for example:
  - latest station table: only current row per station.
  - realtime evidence: 48 hours to 7 days online, depending on audit needs.
  - historical/public reports: longer retention, separate indexes.
- Drop or detach old partitions instead of deleting millions of rows in-place.
- Run scheduled `VACUUM`/`ANALYZE` after bulk ingestion and partition changes.

Acceptance criteria:

- Realtime retention does not require large blocking deletes.
- Hot spatial indexes stay small enough to remain cache-friendly.
- Historical evidence remains queryable through slower, explicit paths.

## Phase 4 - Compression Strategy

Use compression where the read/write pattern fits. Do not compress the columns
that the hot path needs to filter on.

Actions:

- Keep frequently filtered/scored fields in typed columns:
  - `event_type`.
  - `source_type`.
  - `observed_at`.
  - `geom`.
  - `rainfall_mm_1h`.
  - `water_level_m`.
- Move large raw upstream payloads and verbose JSON audit blobs to cold storage
  or compressed archival tables.
- Use PostgreSQL TOAST behavior intentionally for large `jsonb`/text fields;
  prefer compact JSON shapes and avoid duplicating full upstream payloads in
  multiple tables.
- Evaluate PostgreSQL LZ4 compression support if the managed database version
  and settings support it.
- Consider TimescaleDB/Hypercore only if time-series retention and compression
  become a dominant cost and the hosting platform supports the extension
  cleanly.

Acceptance criteria:

- Hot risk assessment no longer needs to load large JSON/TOAST values.
- Table and index bloat are measured before/after changes.
- Compression changes are benchmarked with production-like payloads before
  enabling in production.

## Phase 5 - Spatial Query Hygiene

Spatial query shape matters more than general compression for public search.

Actions:

- Use bounding-box prefilters and `ST_DWithin` before expensive distance
  calculations.
- Keep partial GiST indexes for public/accepted event types used by the public
  API.
- Store point-on-surface or representative points for large polygons when the
  public query only needs proximity ranking.
- Use `ST_Subdivide` for large polygons that must remain spatially searchable.
- Avoid computing `ST_Distance(geography)` until after candidate rows are
  narrowed.

Acceptance criteria:

- Hot queries use index-assisted spatial filters.
- Large administrative/flood-potential geometries do not dominate query time.
- Distance calculations happen on bounded candidate sets.

## Phase 6 - Map Serving and Static Tiles

Map rendering should not turn PostGIS into a tile server for every visitor.

Actions:

- Pre-generate stable basemap and low-frequency overlays as PMTiles or MVT
  assets.
- Serve versioned tile assets from object storage/CDN with byte-range support.
- Keep dynamic API endpoints for search, risk assessment, and small evidence
  result sets.
- Use short-lived manifests for current tile version pointers and immutable
  cache headers for versioned tile files.

Acceptance criteria:

- Normal map pan/zoom traffic does not hit PostGIS.
- CDN range requests return `206 Partial Content` for PMTiles.
- Overlay tile rollback is possible by switching a versioned manifest pointer.

## Phase 7 - API Payload and Cache Discipline

Reduce transferred bytes only after response semantics are correct.

Actions:

- Enable gzip or Brotli at the edge/platform for JSON and static assets.
- Keep public responses compact:
  - send scored evidence summaries, not raw source payloads.
  - include source links and audit identifiers for drill-down.
  - avoid duplicating the same station metadata in multiple evidence objects.
- Cache successful public responses briefly, keyed by point/radius/time/source
  feature flags and cache version.
- Do not cache responses when critical dependencies were unreachable.
- Cache source freshness and latest station snapshots independently from full
  risk assessment responses.

Acceptance criteria:

- Repeated successful queries are fast without masking dependency outages.
- Payload size is measured and tracked for representative search locations.
- Users see freshness gaps as freshness gaps, not stale cached conclusions.

## Implementation Backlog

1. Finish Phase 0 deployment and production smoke verification.
2. Add a repository-availability metric and expose it in `/ready` or a private
   diagnostics endpoint.
3. Add `official_realtime_latest` schema migration and worker upsert path.
4. Move public realtime lookup to `official_realtime_latest`.
5. Add `EXPLAIN` fixtures for known north/south Taiwan query points.
6. Define retention windows and partition candidates.
7. Measure table/index size and payload size before compression changes.
8. Prototype PMTiles/CDN path for public overlays.
9. Evaluate PgBouncer only after connection metrics show it is needed.

## Reference Notes

- PostgreSQL partitioning is recommended when table size outgrows memory or
  maintenance operations need to target whole partitions.
  https://www.postgresql.org/docs/current/ddl-partitioning.html
- PostgreSQL TOAST stores oversized values out-of-line and supports compression
  for large values.
  https://www.postgresql.org/docs/current/storage-toast.html
- PostGIS `ST_DWithin` is the preferred indexed proximity predicate for many
  distance searches.
  https://postgis.net/docs/ST_DWithin.html
- PostGIS `ST_Subdivide` can make very large geometries cheaper to index and
  query.
  https://postgis.net/docs/ST_Subdivide.html
- PgBouncer provides connection pooling modes, including session, transaction,
  and statement pooling.
  https://www.pgbouncer.org/usage.html
- PMTiles packages tiled map data in a single archive that can be served from
  static object storage/CDN with range requests.
  https://docs.protomaps.com/pmtiles/
- TimescaleDB compression/Hypercore can reduce time-series storage cost, but it
  should be evaluated only if the managed database platform supports it and the
  query pattern matches columnar time-series reads.
  https://docs.tigerdata.com/use-timescale/latest/compression/
