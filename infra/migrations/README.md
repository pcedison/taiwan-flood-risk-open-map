# Migrations

PostGIS migrations for local development and deployment.

The tracked migration runner is the only authority that applies these files.
PostgreSQL does not mount this directory into `docker-entrypoint-initdb.d`:
doing so would execute migrations without recording their checksums and would
then replay old migrations against a newer schema.

## Applying migrations to an existing database

Fresh initialization is not enough for staging or production. Use the `migrate` tool service to apply every numbered SQL migration in filename order against the configured `DATABASE_URL`:

```powershell
docker compose up -d postgres
docker compose --profile tools run --rm migrate
```

For Zeabur or another Docker Compose compatible host, run the same `migrate`
service as an explicit release step before restarting `api`, `worker`, and
`scheduler`. The runner records every applied filename and checksum in
`schema_migrations`, skips recorded migrations, rejects drift, and serializes
concurrent runs with a PostgreSQL advisory lock.

Validate migration filenames and basic SQL shape locally:

```powershell
python infra/scripts/validate_migrations.py
```

CI runs both `validate_migrations.py` and a PostGIS smoke check that applies the migrations and verifies the core SDD plus runtime tables exist.

## Local initialization

Starting the local `postgres` service creates an empty PostGIS database. Apply
the tracked migrations explicitly before starting API or worker services:

```powershell
docker compose up -d postgres
docker compose --profile tools run --rm migrate
```

Do not mount all numbered SQL files into PostgreSQL's init directory or run them
with an untracked shell loop. A legacy local volume created by the former
init-directory path can contain schema objects without `schema_migrations`;
back it up and rebuild that development database, or have an operator review
and baseline it deliberately. The runner does not guess which migrations a
non-empty untracked database has already received.

Smoke-check the Phase 1 tables:

```powershell
docker compose exec postgres psql -U flood_risk -d flood_risk -c "\dt"
docker compose exec postgres psql -U flood_risk -d flood_risk -c "\di"
```

`0002_phase1_core_domain.sql` creates the SDD §11.1 table skeletons:

- `data_sources`
- `raw_snapshots`
- `staging_evidence`
- `evidence`
- `location_queries`
- `risk_assessments`
- `risk_assessment_evidence`
- `query_heat_buckets`
- `map_layers`
- `ingestion_jobs`
- `adapter_runs`
- `user_reports`
- `audit_logs`

Later migrations add runtime and beta-hardening tables, including worker queues,
tile caches, user-report privacy redaction fields, open-data geocoder entries,
and precomputed risk profile tables:

- `admin_area_profiles`
- `risk_grid_profiles`
- `profile_evidence_links`
- `profile_refresh_jobs`
- `evidence_embeddings`
- `official_realtime_latest`

`0018_official_realtime_latest.sql` also seeds additional disabled data-source
candidates for the official realtime read model rollout:

- `official.civil_iot.flood_sensor`
- `official.civil_iot.river_water_level`
- `official.civil_iot.pond_water_level`
- `official.civil_iot.sewer_water_level`
- `official.civil_iot.pump_water_level`
- `official.civil_iot.gate_water_level`
- `official.ncdr.cap`
- `local.tainan.flood_sensor`

`0034_public_realtime_source_health.sql` adds the bounded latest-ingestion-job
lookup index used by the public source-health read model and registers the
authorization-gated `local.kinmen.kwis_pump_station` adapter as disabled by
default. It also adds conservative station-inventory review gates. No source is
marked complete by this migration: an operator must first review a full-snapshot
contract and set a positive minimum station baseline. Public-safe runtime
selection and final pipeline outcome fields let the API distinguish an explicit
disable from a stalled worker and a promotion failure from fetch success. It
also stores the ingestion-attempt timestamp for each final outcome, preventing
an older overlapping cycle from certifying a newer run. The minimum baseline is
only an anomaly floor: approval still requires declared-total/pagination and a
versioned station-ID manifest plus jurisdiction/redundancy review. It does not
store an API token or enable the source.

`0035_station_inventory_and_jurisdiction_proofs.sql` adds per-ingestion station
inventory snapshots, the fixed `station-id-json-v1` manifest/checksum contract,
reviewed 22-county boundary snapshot tables, and per-county/per-signal source
catalog mappings. The migration seeds canonical county codes and candidate
source mappings only. It does not import official boundary geometry, activate a
boundary snapshot, approve a station manifest, or certify any source catalog;
all 22 × 4 jurisdiction signal contracts start as `unreviewed`. Until every
applicable proof and review gate is complete, the public API must fail closed
and must not emit `no_station_in_range`. Reviewed boundaries are immutable and
revalidated against their EWKB manifest; each reviewed county/signal catalog is
also pinned to the exact applicable source-mapping count and checksum, so later
mapping drift revokes the proof automatically. See the
[station inventory and jurisdiction review runbook](../../docs/runbooks/station-inventory-and-jurisdiction-review.md)
before changing any review or approval field.

`0037_yilan_mobile_pump_status_source.sql` registers the disabled-by-default
`local.yilan.mobile_pump_status` source and its required Yilan County
`pump_or_gate_status` jurisdiction mapping. The migration does not enable the
adapter or approve station-inventory evidence; operators must still enable both
runtime gates and complete the existing fail-closed source review.

`0038_official_incident_context_sources.sql` registers four disabled-by-default
official catalog rows: `official.cwa.heavy_rain_warning`, `official.ncdr.cap`,
`official.npa.police_radio_traffic`, and `official.wra.flood_warning`. Every row
is inserted with `is_enabled = false` and the conflict branch re-asserts that
value, so re-running the migration on a database where an operator enabled one
of these rows forces it back off. The migration stores no API key, token, or
other credential; it records only public-safe owner, landing/resource URL,
license, limitation, review status, and phase metadata. The police-radio and WRA
warning rows are marked `evidence_scope = context` with `scoring_use = never`;
the CWA and NCDR rows keep `spatial_review = unapproved`. The migration
deliberately creates no `realtime_source_jurisdictions` mapping, so none of
these sources can become a required realtime coverage signal. Operators must
still enable each runtime gate and complete the fail-closed source review before
enabling a row.

`0041_v1_warning_source_requirement_alignment.sql` aligns the reviewed
flood-warning absence contract with the deployed hosted backbone. NCDR CAP is
the single required flood-warning mapping; the CWA heavy-rain warning remains
applicable and reviewed as a `redundant_subset` of NCDR. Redundancy changes only
which source is required before the API may confirm absence. It does not enable
CWA, fetch warning data, alter credentials or runtime gates, lower NCDR
freshness requirements, or allow an unhealthy required NCDR source to pass.
The migration advances only flood-warning contracts to
`2026-08-28-v1-warning-alignment` and recomputes all 22 count/checksum proofs;
rainfall, water-level, and flood-depth contracts retain their independently
reviewed revisions.

`0042_evidence_staging_lookup_index.sql` adds the bounded expression index used
by per-candidate promotion idempotency checks. Without it, each accepted staging
row scans the growing public `evidence` table for its `staging_evidence_id`,
which can delay ingestion and contend with public risk requests. The migration
changes no evidence rows, source gates, scoring rule, or public response shape.

`0043_retire_inactive_tainan_stations.sql` repairs Tainan sensor observations
written before the worker persisted the official realtime/metadata `IsEnabled`
flags. It removes matching rows from `official_realtime_latest` and preserves
their audit evidence as `rejected` with a public-safe lifecycle reason. The
worker handles later active-to-inactive transitions through authenticated
staging tombstones. A stale realtime tombstone cannot replace a newer active
observation, while the separately fetched current metadata can retire the row
immediately. This migration is only a backward-data repair; it does not delete
audit history or change any source gate.

`0044_ncdr_public_active_feed_source.sql` aligns the persisted NCDR catalog
with the official public active-warning Atom feed used when no member API key
is configured. It records the feed's one-minute refresh cadence and keeps the member
datastore/dump endpoints as optional compatibility metadata. The migration
does not enable a source, change warning geometry approval, or weaken the
audit-only promotion policy.

`0045_current_snapshot_staging_lookup_index.sql` adds the partial staging index
used by managed ingestion after it resolves the current raw snapshot by the
snapshot's unique `raw_ref`. This prevents a current WRA or Civil IoT cycle from
scanning all historical accepted staging rows before promotion. The worker's
unscoped maintenance path retains orphan-staging compatibility; the migration
changes no staging status, evidence row, source gate, scoring rule, or public
response contract.

`0046_ncdr_alert_area_boundaries.sql` adds a dedicated, immutable 368-township
boundary snapshot for NCDR's `Taiwan_Geocode_103` CAP profile. It is deliberately
separate from the 22-county jurisdiction boundary so a township warning can
never be widened to its parent county. Activation requires exact archive and
manifest checksums, a complete unique geocode set, valid PostGIS geometry, and
an operator review reference. Until one reviewed snapshot is active, NCDR
warning rows remain audit-only and fail closed before public evidence.

`0047_wra_historical_flood_source.sql` repairs the persisted catalog omission
for the already reviewed `official.wra.historical_flood` complete-replace
adapter. It enables the public official source row, records its GOL 1.0 and
historical-only limitation, and deliberately preserves the ingestion-managed
active snapshot marker on conflict. It also links pre-fix NULL-source evidence,
activates the newest repaired complete snapshot, and terminally consumes the
matching accepted staging backlog. Runtime gates and the catalog gate still
apply independently; no credential is stored by this migration.

`0049_cap_warning_lifecycle_indexes.sql` bounds the NCDR/CWA CAP lifecycle and
idempotency lookups to the small set of current, actual official warning rows.
This prevents high-volume rainfall, water-level, and sensor history in the
shared `evidence` table from causing warning promotion statement timeouts. It
adds indexes only; it changes no source gate, warning state, or scoring rule.

`0050_retention_cleanup_indexes.sql` adds the bounded lookup paths used by the
deployed scheduler's official realtime-evidence and raw-snapshot retention
passes. Raw snapshots are selected by the per-source-family expiry deadline
already persisted during staging; deleting an expired raw row leaves the
normalized staging audit in place through `ON DELETE SET NULL`. The migration
also covers that foreign-key update across every staging status so one expiry
does not scan the full staging audit table. It adds indexes only and changes no
retained row by itself.

`0052_observed_flood_history_indexes.sql` bounds the spatial and time-window
lookup that reuses retained positive flood-depth sensor observations as
historical evidence after the realtime window ends. It adds indexes only: the
query layer performs the historical projection, and stored current observations
remain unchanged for audit and realtime use.

`0053_tainan_official_disaster_news.sql` registers the reviewed L1,
citation-only Tainan City Government disaster-news source. The public API uses
it only when nearby observed flood history is older than one year, stores title,
publication date, URL, and location-match metadata (never the article body), and
marks district-only matches as imprecise historical evidence. The independent
`OFFICIAL_TAINAN_HISTORY_NEWS_ENABLED=false` kill switch stops request-time
egress and writeback.

`0054_nationwide_recent_flood_history.sql` supersedes and disables the
Tainan-only request-time lookup, registers the rolling seven-year
`official.gov_tw.flood_citation` source for all Taiwan locations, and registers
the fail-closed `official.wra.flood_incident` worker source. The citation path
stores official publisher metadata only and explicitly records incomplete
coverage. The WRA path remains disabled until its credential and contract gates
are approved; after activation it preserves successive latest-event responses
instead of claiming an unavailable historical backfill.

`0055_require_direct_official_citation_urls.sql` tightens the nationwide
request-time source so the user-facing citation itself must be an approved
government HTTPS URL. Existing aggregator-only citations are retained for
audit but moved to `rejected`; they can no longer appear as public evidence or
make an unreadable Google/Bing redirect look like an official source page.

`0056_historical_coverage_ledger.sql` creates the fail-closed county/year
historical ingestion coverage ledger and seeds the first 22 × 9 review matrix
for 2018–2026. Every cell starts as `unassessed`; this is an explicit work state,
not evidence that no flood occurred. Resolved empty and unavailable states need
review evidence, successful source checks remain distinct from failures, and
`/v1/history-coverage` exposes only public-safe counts, source adapter keys,
timestamps, and limitations. The migration does not backfill events or mark any
cell complete.

`0057_ingestion_runtime_readiness.sql` persists the V1 scheduler heartbeat and
the initial 11-source production-backbone readiness profile. Worker lease renewals now
refresh the public-safe heartbeat atomically, while graceful release records a
stopped state; an expired heartbeat therefore cannot borrow API/database
liveness. `/v1/ingestion-readiness` combines that state with exact adapter-run
and promotion outcomes plus the reviewed 22-county signal manifests. Ordinary
sources use a 30-minute stale gate and the daily WRA historical snapshot uses a
25-hour gate. The endpoint exposes no holder, URL, credential, raw error, or
secret metadata, and county readiness is explicitly not nearby-station proof.

`0058_nstc_recent_history_ingestion.sql` registers the official NSTC flood
disaster-point source as a daily production-backbone adapter, bringing the
readiness profile to 12 sources. It also creates
`historical_coverage_source_checks`, which records each promoted historical
snapshot's per-source, per-county, per-year result separately from the
aggregated `historical_ingestion_coverage` state. A successful live snapshot can
therefore advance only the years actually present in that payload, while a
failed or unassignable snapshot cannot be misrepresented as an empty year.

`0059_historical_coverage_15y_retention.sql` expands the fail-closed review
matrix to 22 × 15 county/year cells for 2012–2026. It also changes the rolling
NSTC source from active-snapshot replacement to revision retention, so a newly
published five-year snapshot cannot hide older official rows already ingested.
The migration only expands and preserves audit state; it does not claim that
the unresolved 15-year cells are complete.

`0060_historical_event_semantics.sql` separates event time from ingestion time
for historical evidence. It adds `event_year`, `temporal_precision`, explicit
event bounds, and a stable upstream record key to staging and promoted
evidence. Dataset 130016 rows are migrated from the legacy synthetic December
31 timestamp to true year-only semantics with nullable event timestamps. Raw
snapshot revisions remain available for audit, while public readers can dedupe
them by stable record identity. The migration also adds bounded indexes for
newest-first history pages and query-time flood-sensor episode aggregation; it
does not delete raw observations or claim missing years are complete.
