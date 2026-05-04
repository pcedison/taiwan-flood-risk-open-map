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
