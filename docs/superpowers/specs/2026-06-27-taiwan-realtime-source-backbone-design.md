# Taiwan Realtime Source Backbone Design

Date: 2026-06-27
Status: Approved direction, pending implementation plan

## Purpose

Flood Risk must answer realtime flood risk for all Taiwan counties, districts,
villages, and neighborhoods without over-relying on distant CWA or WRA stations.
The new backbone makes worker-ingested, auditable official sources the production
source of truth, with Civil IoT flood-depth sensors as the primary neighborhood
signal and CWA/WRA/NCDR sources as supporting official context.

## Decision

Adopt Option A: a worker-first national realtime source backbone.

The hosted public API must not fetch upstream realtime sources during user
requests. Workers fetch, normalize, validate, and persist official data on a
schedule. The public API reads a compact latest-observation model first, then
links back to evidence and raw snapshots for auditability.

## Goals

- Improve realtime spatial relevance by prioritizing road flood-depth sensors
  and local water-resource sensors near the query point.
- Keep official source ingestion auditable through raw snapshots, staging,
  promotion, source health, and data freshness records.
- Keep public risk queries fast and bounded by reading latest station state
  instead of scanning full evidence history.
- Make stale, missing, low-confidence, or distant source data visible to users
  instead of silently treating gaps as low risk.
- Preserve the current scoring model and event-type vocabulary unless a later
  reviewed calibration explicitly changes them.

## Non-Goals

- Do not use undocumented local government map APIs as the national canonical
  source.
- Do not add request-time upstream fetching to hosted API environments.
- Do not infer that current low water depth or low rainfall means a location has
  low historical flood risk.
- Do not replace raw evidence history with only latest rows.
- Do not add a new event type unless existing `rainfall`, `water_level`,
  `flood_warning`, `flood_potential`, and `flood_report` cannot represent the
  source.

## Source Tiers

### Tier 0: Semantic Prerequisite

Before adding new realtime sources, fix and test timestamp semantics:

- `observed_at`: source observation time.
- `fetched_at`: adapter fetch time and raw snapshot fetch time.
- `ingested_at`: system persistence or promotion time.
- `source_timestamp_min` and `source_timestamp_max`: min/max upstream
  observation timestamps in one adapter batch.

Current staging code maps `observed_at` to `evidence.fetched_at`, while API
freshness logic treats `observed_at` as source observation time. This must be
corrected before source freshness can be trusted.

### Tier 1: National Canonical Realtime Sensors

Use Civil IoT Taiwan WaterResource SensorThings as the national backbone for
near-ground conditions.

Primary dataset:

- Civil IoT flood sensors, dataset `water_12`
- Official page: `https://ci.taiwan.gov.tw/dsp/Views/dataset/detail.aspx?id=water_12`
- SensorThings base: `https://sta.ci.taiwan.gov.tw/STA_WaterResource_v2/v1.0/`
- Main event type: `flood_report` for above-threshold road flood depth.
- Supporting metrics: `flood_depth_cm`, signal quality, station authority,
  station code, station name, geometry, latest observation time.

The adapter should fetch only relevant datastreams such as `淹水深度`, follow
SensorThings pagination, reject invalid or stale observations, and preserve the
station authority for attribution and deduplication.

### Tier 2: National Supporting Official Sources

Use these as official context, not as the only realtime evidence:

- WRA realtime water level, dataset `25768`:
  `https://data.gov.tw/dataset/25768`
- WRA water station metadata:
  `https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92`
- CWA automatic rainfall, dataset `9177`, endpoint `O-A0002-001`; requires CWA
  authorization.
- NCDR CAP disaster alerts:
  `https://alerts.ncdr.nat.gov.tw/JSONAtomFeed.ashx`
- WRA flood potential maps, dataset `25766`:
  `https://data.gov.tw/dataset/25766`

These sources provide rainfall drivers, river and drainage context, official
warnings, and planning-layer susceptibility. They should not override direct
nearby flood-depth observations.

### Tier 3: Reviewed Local Government Fallbacks

Local sources may supplement Civil IoT only when they have an official landing
page, clear license or terms review, stable machine-readable API, schema
contract, and health checks.

Tainan proof-of-concept:

- Preferred formal fallback: Tainan open data platform dataset
  `https://data.tainan.gov.tw/DataSet/Detail/03dd4536-3fe7-46ec-9920-a120cb5c502c`
- Realtime API:
  `https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c`
- Station metadata API:
  `https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864`

Tainan WMap and its internal endpoints can inform a derived overlay, but they
are not canonical sources because they are not independently documented as a
public API.

## Architecture

### Worker Ingestion

Workers remain the only production path that fetches upstream realtime sources.
They should:

1. Select enabled adapters through registry and environment gates.
2. Fetch upstream data with source-specific timeouts and pagination.
3. Store raw snapshots and adapter run summaries.
4. Normalize records to existing evidence event types.
5. Validate schema, coordinates, timestamp semantics, and source freshness.
6. Promote accepted staging evidence.
7. Upsert latest official observations for fast public lookup.
8. Emit freshness metrics and source-health diagnostics.

Civil IoT flood sensors should move from opt-in experimental support toward the
primary enabled production candidate, behind explicit source gates until terms,
TLS, cadence, and hosted egress are accepted.

### Latest Read Model

Implement the previously planned `official_realtime_latest` table as the public
hot path.

Each row stores the latest accepted observation for one provider/event/station:

- `source_id`
- `adapter_key`
- `event_type`
- `station_id`
- `station_name`
- `authority`
- `observed_at`
- `ingested_at`
- `geom`
- normalized metric columns, such as `rainfall_mm_1h`, `water_level_m`,
  `warning_level_m`, and `flood_depth_cm`
- `confidence`
- `freshness_score`
- `source_weight`
- `risk_factor`
- `evidence_id`
- compact attribution and source URL
- source quality flags in JSON metadata

Public risk assessment should query this table before falling back to historical
evidence. The full `evidence`, `raw_snapshots`, and `adapter_runs` tables remain
the audit trail.

### API Flow

The public API should:

1. Resolve the query point and radius.
2. Query `official_realtime_latest` for recent official observations near the
   point, with source-specific relevance radii.
3. Prefer nearby flood-depth observations over distant rainfall or river-level
   observations.
4. Merge latest realtime observations with historical evidence and planning
   layers.
5. Return source freshness for every enabled official source, including healthy,
   stale, disabled, degraded, and failed states.
6. Use direct CWA/WRA bridge only as a local diagnostic fallback, consistent with
   ADR-0010.

### Fusion Rules

Use deterministic rules so results are explainable:

- Direct flood depth near the query point has the strongest realtime relevance.
- Official CAP warnings apply to their declared alert area and should appear as
  warning evidence even if no nearby sensor is flooded.
- Rainfall and water level are drivers or context unless they are directly
  adjacent to the query point.
- Planning-layer flood potential affects historical or susceptibility context,
  not current observed flooding.
- Local fallback can override central Civil IoT only when it is formally
  reviewed, newer, schema-valid, and not flagged doubtful.
- Duplicates across WRA and Civil IoT are resolved by station code, location,
  authority, observation time, and metric type. Duplicate evidence must not
  double-count in scoring.

## Data Quality Gates

Every production source must pass:

- Official landing page or public catalog URL.
- License or terms review.
- Explicit source owner and attribution.
- Machine-readable endpoint with stable schema contract.
- Required fields: station id, observation time, metric value, coordinate or
  joinable station metadata, status or quality flag when available.
- Timestamp validation using source observation time.
- Staleness threshold specific to the source cadence.
- Coordinate validity inside Taiwan bounds.
- Invalid value rejection, including sentinel values and impossible depths.
- Pagination completeness checks.
- Hosted egress and TLS verification.
- Source-health metrics and disable switch.

Civil IoT TLS has shown local certificate-chain verification risk in curl. The
production implementation should not use unverified TLS silently. It should
document the trusted CA path, fail closed in hosted production, and allow only
explicit local diagnostic bypass where already permitted.

## Freshness Policy

Use per-source freshness thresholds instead of one global threshold:

- Civil IoT flood sensors: target 10 minutes, degraded at 30 minutes, failed or
  stale alert at 60 minutes.
- WRA realtime water level: target 10 minutes, degraded at 30 minutes, stale
  alert at 60 minutes.
- CWA rainfall: target 10 minutes, degraded at 30 minutes, stale alert at
  60 minutes.
- NCDR CAP: evaluate by CAP `sent`, `effective`, and `expires`; expired alerts
  must not be scored as active.
- Flood potential maps: static or slow cadence; use dataset build/update date,
  not realtime stale thresholds.
- Local fallback sources: source-specific thresholds set during terms and
  operations review.

Freshness should be computed from source observation timestamps, not fetch time.

## Risk And Confidence

Keep the existing scoring model until a separate calibration review changes it.
The new backbone changes evidence quality and locality, not the public meaning of
score levels.

Implementation must fix persisted water-level and flood-depth risk factors so
low water-level evidence does not become full-strength risk merely by being
present. Each latest observation should carry an explicit `risk_factor` computed
from source-specific metric thresholds.

## Operations

Add source diagnostics before enabling production traffic:

- `--diagnose-source <adapter_key> --json`: gates, fetch status, normalized and
  rejected counts, timestamp min/max, raw ref, and error code.
- `--source-status --adapter-key <adapter_key> --json`: data source state,
  latest adapter run, latest raw snapshot, latest evidence, and latest read-model
  row.
- Metrics for observed age, fetch lag, ingest lag, items fetched, items
  normalized, items rejected, latest-row count, and source-health status.
- Alerts for official source stale or failed state.

## Testing Strategy

CI uses fixtures and injected fetch clients. Live upstream smoke tests are
explicit opt-in and should never make normal CI flaky.

Required test groups:

- Worker timestamp contract tests for `observed_at`, `fetched_at`, and
  `ingested_at`.
- Civil IoT parser tests for pagination, flood-depth observations, station
  metadata, invalid values, stale observations, and quality flags.
- Adapter registry and runtime gate tests for national backbone sources.
- Promotion/upsert tests for `official_realtime_latest`.
- Repository tests for spatial lookup, source-specific relevance radius,
  staleness filtering, and duplicate suppression.
- API service tests for source freshness, displayed evidence, water-level and
  flood-depth risk factor handling, and cache behavior.
- Monitoring tests for Prometheus textfile output and freshness alert rules.
- Optional live smoke matrix for Civil IoT, WRA, CWA, NCDR, and one reviewed local
  fallback.

## Rollout

1. Fix timestamp semantics and tests.
2. Add source catalog and seed data-source entries for Civil IoT backbone sources.
3. Implement latest read model schema and worker upsert path.
4. Promote Civil IoT flood sensor ingestion to reviewed production candidate.
5. Update API lookup to read latest model first.
6. Add NCDR CAP warning ingestion.
7. Add Tainan open-data fallback as a reviewed local POC.
8. Add dashboards, alerts, and opt-in live smoke tests.
9. Recalibrate scoring only after enough fixture and live observation evidence is
   collected.

## OpenDesign Use

OpenDesign is available locally, but the research helper currently requires a
Tavily API key, and live artifact access requires an injected OpenDesign tool
token. This design therefore uses repository markdown as the source of truth. If
OpenDesign project tools become available, this spec can be mirrored into an
artifact showing the source tiers, ingestion flow, and freshness state machine.

## Review Defaults

- Civil IoT flood-depth sensors remain explicit production configuration until
  terms, hosted egress, TLS, and freshness monitoring are accepted.
- The first local fallback rollout is limited to formal open-data APIs with clear
  license metadata. Official but undocumented endpoints can only be used for
  derived overlays or manual diagnostics until separately approved.
- The first production alert thresholds use the freshness policy in this spec.
  Threshold tuning requires live smoke evidence and an updated runbook entry.
