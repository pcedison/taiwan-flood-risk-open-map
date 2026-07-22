# Flood Risk API

FastAPI Phase 1 public API routes, service health, and Phase 3 scoring
groundwork.

## Entry points

- FastAPI app: `app.main:app`
- Docker Compose command: `pip install -e . && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Local FastAPI command after installing dependencies: `python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Current scope

- `/health`
- `/ready` dependency readiness checks
- `/v1/geocode` mock provider
- `/v1/risk/assess` mock/live-groundwork assessment surface backed by the
  current risk contract
- Public-safe realtime source health under
  `nearby_realtime_coverage.source_health`. It derives status from the latest
  ingestion attempt and persisted observations without exposing raw exceptions,
  connection details, worker parameters, or credentials. `station_count` is an
  observed count; `inventory_complete` is the separate completeness gate.
- `/v1/evidence/{assessment_id}` evidence list surface for the current
  assessment contract
- `/v1/layers` and `/v1/layers/{layer_id}/tilejson` placeholder layer metadata
  until the tile/layer pipeline lands
- Protected `/admin/v1/jobs` and `/admin/v1/sources` contract skeleton
- Default-disabled `/v1/reports` intake groundwork with shared rate limiting,
  optional required challenge verification, admin moderation, and admin
  privacy redaction/tombstoning
- Environment-based settings loader
- Structured error payload helper
- Focused public contract tests

## Placeholder boundary

- `app/placeholder_server.py` is a fallback artifact only. Docker Compose and
  normal local development should use `app.main:app`.
- Geocode and layer data remain mock/placeholder surfaces until provider and
  tile pipeline work is implemented.
- User reports remain pre-launch and disabled by default. Do not enable public
  intake outside a reviewed sandbox until challenge provider configuration,
  deletion request operations, moderation SLA/metrics, media redaction, consent,
  and corroboration gates are approved.

## Nearby coverage and source health

`missing_cause=no_station_in_range` is emitted only when every applicable
national/local required source has an explicitly reviewed station inventory,
its upstream total and terminal pagination are proven, its latest manifest
checksum matches the approved value, its exact batch matches the complete
publication outcome, and the spatial query finds no station within 15 km. The
query must also resolve against an immutable checksum-verified 22-county boundary
snapshot and a county/signal mapping manifest whose source count, checksum,
revision, and redundancy parents still match. No boundary, source inventory, or
county/signal contract is approved by default. Healthy sources with an unverified inventory use
`missing_cause=inventory_unverified`; source failures, partial updates, a stalled
ingestion schedule, disabled sources, and unavailable health diagnostics have
separate reason codes and must not be interpreted as proof that no nearby station
exists.

`pipeline_stalled` means either the runtime-selection heartbeat or ingestion
activity is older than the accepted schedule. `pipeline_unavailable` also covers
an adapter initialization failure, final publication failure, or a successful
fetch whose exact final outcome was not confirmed after the grace period. Hosted
intentional disable records an authoritative empty selection before the public
service starts, so it remains distinct from a stopped worker.

The current `station_inventory_min_count` is only an anomaly floor, not a
standalone completeness proof. Approval requires the workflow in
`docs/runbooks/station-inventory-and-jurisdiction-review.md`; any station,
boundary, or source-mapping drift immediately returns the response to a
fail-closed state.
