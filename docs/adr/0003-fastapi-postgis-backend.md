# ADR-0003: FastAPI and PostGIS Backend

## Title

FastAPI and PostGIS Backend

## Status

Accepted

## Date

2026-04-28

## Context

The MVP requires address or map-click search, radius query, PostGIS spatial search, evidence lookup, risk scoring, and health endpoints. The SDD names FastAPI, PostgreSQL/PostGIS, Redis, MinIO, background workers, and database migrations as core building blocks.

The backend must keep domain logic framework-independent. UI components should call backend APIs instead of external sources directly. Database migrations must be repeatable, reversible where feasible, and verifiable in CI.

## Alternatives Considered

Recorded 2026-07-06 to preserve the reasoning for future maintainers evaluating whether to replace a core component.

- **API framework — FastAPI vs Django vs Flask vs a Node/TypeScript backend.**
  Django's ORM/admin/batteries exceed this API-plus-workers shape and its ORM steers away from the raw PostGIS spatial SQL the risk queries rely on. Flask works but lacks FastAPI's built-in request/response typing and OpenAPI generation, which this project uses as a contract gate in CI. A Node backend would split the language surface (workers and scoring are Python-centric, and the ML/NLP-adjacent path favors Python). FastAPI keeps one language across API, workers, ingestion, and scoring while giving typed schemas and OpenAPI for free.
- **Spatial store — PostgreSQL/PostGIS vs a non-spatial DB plus app-side geometry vs a dedicated geo engine.**
  Radius search, `ST_DWithin`, and spatial indexing are first-class in PostGIS and central to the product; reimplementing them in application code or bolting geo onto a non-spatial store would be slower and error-prone, while a dedicated geo engine adds a second datastore to operate. PostgreSQL also covers the non-spatial evidence/scoring tables, so one database serves both.
- **Object storage — MinIO/S3-compatible vs storing blobs in Postgres.**
  Raw snapshots and larger artifacts do not belong in the relational store; an S3-compatible interface keeps local (MinIO) and hosted (R2/S3) interchangeable (see ADR-0002 for the basemap-asset side of the same choice).
- **Cache/coordination — Redis.**
  Chosen for rate-limit buckets and cache with fail-open behavior; the durable worker queue deliberately uses PostgreSQL rather than Redis (Redis is not an accepted production queue backend — see the README runtime notes).

These are revisitable: the "keep domain logic independent of FastAPI" rule below is what keeps any one of them replaceable without rewriting the risk engine.

## Decision

Use FastAPI for the backend API service.

Use PostgreSQL with PostGIS for persistent spatial data, evidence metadata, scoring inputs, and queryable geospatial relationships.

Use Redis for cache and background job coordination where needed. Use MinIO-compatible object storage for raw snapshots and larger artifacts.

Keep risk calculation, evidence normalization, and geospatial rules in domain services that do not depend on FastAPI.

Manage database schema through ordered migrations under the repository migration area. Any database change must include a migration and deployment notes when it affects runtime behavior.

## Consequences

FastAPI and Python provide a practical path for API, geospatial, ingestion, and ML/NLP-adjacent workflows.

PostGIS gives the project first-class radius and spatial indexing support.

The team must maintain migration discipline and avoid ad hoc database changes.

Backend APIs become the stable boundary between UI, workers, data sources, and domain logic.

## Proposed enforcement addendum: one acquisition timeout per assessment

2026-10-24, WP-012, Refs #428; local validation only.

An assessment reads seven repository sections and attempts persistence even
after unavailable reads. Under a continuously exhausted connection pool this
can repeat eight full acquisition waits. The default five-second timeout
therefore permits a total forty-second acquisition budget (not a measured
production duration). This amplifies an outage but does not establish the cause
of the incident's fresh-connection readiness failures.

Scope failed pool acquisition state to one AssessmentService.assess invocation.
After acquisition raises PoolTimeout, further calls to that same database in
the assessment raise PoolTimeout immediately through existing unavailable-data
handling. Include persistence in the scope. Reset in finally so the next
assessment always retries; do not share a circuit breaker across requests or
databases. Query and transaction-exit errors must not trip acquisition state.
Do not change scoring, cache admission, pool sizes or SQL timeout policy.
If the pool recovers during the same assessment, additional sections remain
unavailable until the next assessment rather than repeatedly retrying. Already
loaded evidence is retained. This conservative tradeoff favors bounded failure
latency without claiming absence of risk.

Local regression compares the undecorated original flow (eight waits, forty
seconds of simulated budget) against the scoped flow (one wait, five seconds)
through actual repository/service code and an exhausted fake pool. Realtime
risk remains unknown, with identical risk/data-status/explanation results.
The test does not sleep or contact production.

This only bounds repeated pool waits. Readiness uses fresh connections outside
the pool, and connected SQL can still stall: latest/history/observed-history/
recent-context readers default statement_timeout_ms to zero, while jurisdiction,
coverage and health readers use 1500 ms. Production server-side timeout values
are not established. Do not claim an overall request deadline or root-cause fix.
