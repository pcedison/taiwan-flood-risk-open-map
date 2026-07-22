# Migrations

PostGIS migrations for local development and deployment.

Files in this directory are mounted into the PostgreSQL container init directory for fresh local databases.

## Applying migrations to an existing database

Fresh initialization is not enough for staging or production. Use the `migrate` tool service to apply every numbered SQL migration in filename order against the configured `DATABASE_URL`:

```powershell
docker compose up -d postgres
docker compose --profile tools run --rm migrate
```

For Zeabur or another Docker Compose compatible host, run the same `migrate` service as an explicit release step before restarting `api`, `worker`, and `scheduler`. The current SQL files are idempotent, so the command is safe to re-run while the schema remains in skeleton mode.

Validate migration filenames and basic SQL shape locally:

```powershell
python infra/scripts/validate_migrations.py
```

CI runs both `validate_migrations.py` and a PostGIS smoke check that applies the migrations and verifies the core SDD plus runtime tables exist.

## Local initialization

The local `postgres` service runs these files once, in filename order, when the
`postgres-data` volume is empty.

```powershell
docker compose up -d postgres
```

To re-run migrations from an empty local database, remove only the local
PostgreSQL volume and start the service again:

```powershell
docker compose down
docker volume rm flood-risk_postgres-data
docker compose up -d postgres
```

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
