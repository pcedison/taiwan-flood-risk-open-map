# Runtime Smoke Runbook

This runbook verifies the local Docker Compose runtime without deleting Docker
volumes. It now covers the Phase 2 runtime-demo readiness path: API/Web, risk
query, query heat, durable worker queue, user reports gates, MVT tiles, and the
documented query-heat materialization plus tile feature/cache smoke path.

## Requirements

- Docker Desktop or another Docker engine with Compose v2.
- Ports `8000`, `3000`, `5432`, `6379`, `9000`, and `9001` available, unless overridden through environment variables used by `docker-compose.yml`.
- Run commands from the repository root.
- The smoke assumes the local Compose database can accept temporary runtime
  smoke rows. It does not delete volumes.

## Run

```powershell
.\scripts\runtime-smoke.ps1
```

The script performs these checks:

1. `docker compose config --quiet`
2. `docker info`
3. `docker compose up -d postgres redis minio api web`
4. `docker compose --profile tools run --rm migrate`
5. Polls API `/health`
6. Polls API `/ready`
7. Posts a sample request to `/v1/risk/assess`
8. Verifies `query_heat` is present and not in the `limited-db-unavailable`
   fallback state
9. Verifies `/v1/reports` is default-disabled over live HTTP with
   `feature_disabled`
10. Verifies seeded MVT endpoints:
    - `/v1/tiles/query-heat/8/215/107.mvt`
    - `/v1/tiles/flood-potential/8/215/107.mvt`
11. Runs a queue live smoke in a one-off `worker` container:
    - enables fixture runtime adapters with
      `WORKER_RUNTIME_FIXTURES_ENABLED=true`
    - enqueues one `worker_runtime_jobs` row
    - consumes it through `work_runtime_queue_once`
    - marks it `succeeded`
    - deletes the smoke queue row
12. Runs a reports enabled-path smoke in a one-off `api` container with
    `USER_REPORTS_ENABLED=true`; this inserts a minimized pending row in
    `user_reports`, verifies moderation/audit rows, then deletes the smoke rows
13. Runs a query heat and tile cache job smoke:
    - materializes `P1D` and `P7D` query heat buckets
    - refreshes `flood-potential` map features from accepted evidence
    - writes one smoke tile cache row
    - verifies the API serves the same cached tile payload bytes
    - deletes synthetic tile/evidence/cache rows
14. Polls the web runtime until it responds at `http://localhost:3000`

By default, services are left running for debugging or follow-up manual testing. To stop the runtime containers after the smoke finishes, without removing volumes:

```powershell
.\scripts\runtime-smoke.ps1 -StopOnExit
```

Useful options:

```powershell
.\scripts\runtime-smoke.ps1 -StartupTimeoutSeconds 240 -ApiBaseUrl http://localhost:8000 -WebBaseUrl http://localhost:3000
```

Print help without touching Docker:

```powershell
.\scripts\runtime-smoke.ps1 -Help
```

Run only the base API/Web path when the one-off container checks are too slow
for a local debugging loop:

```powershell
.\scripts\runtime-smoke.ps1 -SkipExtendedSmoke
```

Skip individual extended checks:

```powershell
.\scripts\runtime-smoke.ps1 -SkipQueueSmoke
.\scripts\runtime-smoke.ps1 -SkipReportsEnabledSmoke
```

## Successful Output

A passing run ends with:

```text
API health: status=ok, service=flood-risk-api, version=...
API ready: database=healthy, redis=healthy
Risk smoke: assessment_id=..., realtime=..., historical=..., confidence=...
Query heat smoke: period=P7D, query_count_bucket=..., unique_approx_count_bucket=...
Reports default-disabled smoke: HTTP 404 feature_disabled
MVT smoke: layer=query-heat, HTTP 200, content-type=application/vnd.mapbox-vector-tile
MVT smoke: layer=flood-potential, HTTP 200, content-type=application/vnd.mapbox-vector-tile
queue_smoke=ok job_id=... adapter_key=official.wra.water_level
reports_enabled_smoke=ok report_id=... status=pending
Query heat/tile cache job smoke: aggregation, feature refresh, cache write, API cache read, and cleanup passed.
Web smoke: HTTP 200 from http://localhost:3000
Runtime smoke passed.
```

## Manual Commands

These are the underlying commands to run a focused check while debugging.

Queue live smoke. A consume CLI exists through
`python -m app.main --work-runtime-queue --once`, but there is not yet a
standalone enqueue CLI, so the smoke uses the runtime queue helper to enqueue
one job before consuming it:

```powershell
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  -e WORKER_INSTANCE=runtime-smoke `
  worker sh -c "pip install -e . && python - <<'PY'
from app.config import load_worker_settings
from app.jobs.runtime import enqueue_enabled_runtime_adapter_jobs, work_runtime_queue_once
settings = load_worker_settings()
job_ids = enqueue_enabled_runtime_adapter_jobs(settings)
result = work_runtime_queue_once(settings=settings)
print(job_ids, result)
PY"
```

Reports default-disabled live HTTP check:

```powershell
Invoke-WebRequest `
  -Method Post `
  -Uri http://localhost:8000/v1/reports `
  -ContentType application/json `
  -Body '{"point":{"lat":25.033,"lng":121.5654},"summary":"Runtime smoke report"}'
```

The expected status is `404` with error code `feature_disabled`.

Reports enabled-path check. This is intentionally a one-off API container
because the running Compose API defaults reports off:

```powershell
docker compose run --rm -e USER_REPORTS_ENABLED=true api sh -c "pip install -e . && python - <<'PY'
import asyncio
from app.api.routes.reports import create_user_report
from app.api.schemas import LatLng, UserReportCreateRequest
from app.core.config import get_settings
get_settings.cache_clear()
async def main():
    response = await create_user_report(UserReportCreateRequest(point=LatLng(lat=25.033, lng=121.5654), summary='Runtime smoke enabled report path.'))
    print(response)
asyncio.run(main())
PY"
```

MVT smoke:

```powershell
Invoke-WebRequest http://localhost:8000/v1/tiles/query-heat/8/215/107.mvt
Invoke-WebRequest http://localhost:8000/v1/tiles/flood-potential/8/215/107.mvt
```

Query heat materialization:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --aggregate-query-heat --query-heat-periods P1D,P7D"
```

Tile feature refresh:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --refresh-tile-features --tile-layer-id flood-potential --tile-feature-limit 25"
```

Tile cache write smoke. The worker helper can upsert a cache row that the API
will serve, but full production tile generation, expiry, invalidation, and
external hosting are still not accepted:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python - <<'PY'
from app.config import load_worker_settings
from app.jobs.tile_cache import PostgresTileCacheWriter

settings = load_worker_settings()
writer = PostgresTileCacheWriter(database_url=settings.database_url)
result = writer.upsert_tile_cache_entry(
    layer_id='flood-potential',
    z=8,
    x=215,
    y=107,
    tile_data=b'runtime-smoke-cache',
    metadata={'source': 'manual-smoke'},
)
print(result)
PY"
```

## Common Failures

- `docker compose config --quiet` fails: the Compose file or environment interpolation is invalid.
- Docker command or daemon is unavailable: start Docker Desktop and ensure both `docker compose version` and `docker info` work.
- Port already in use: stop the conflicting process or set the matching `*_PORT` environment variable before running the script.
- `/ready` stays down: inspect `docker compose logs --tail=80 api`, `postgres`, and `redis`.
- Migration fails: inspect the migration output and confirm Postgres is healthy.
- Queue smoke fails: inspect `docker compose logs --tail=80 worker` and confirm
  migration `0006_worker_runtime_queue.sql` has been applied.
- Reports enabled smoke fails: inspect the one-off API container output and
  confirm migration tables `user_reports` and `audit_logs` exist.
- MVT smoke fails: inspect `docker compose logs --tail=80 api` and confirm
  `map_layers`, `map_layer_features`, and `tile_cache_entries` migrations have
  applied. Empty MVT payloads are acceptable for empty data; non-200 responses
  are not.
- Web check fails: inspect the emitted `web` logs. The first run may need more time while `npm ci` installs dependencies and Next.js compiles the first page; rerun with a larger `-StartupTimeoutSeconds`.

## Safety Notes

The script does not run `docker compose down -v`, `docker volume rm`, or any volume cleanup. With `-StopOnExit`, it only runs `docker compose stop` for the services it started.

The extended smoke writes limited local verification rows. On successful runs,
it deletes the synthetic queue, report/audit, tile cache, map feature, and
evidence smoke rows before exit; tile/evidence/cache cleanup is also registered
as best-effort cleanup if a later assertion fails. Rows that may remain as
useful local evidence are:

- one or more risk/query assessment rows from `/v1/risk/assess`
- materialized `query_heat_buckets` rows generated from local query history

These rows are expected in a local runtime-smoke database. Use a throwaway
Compose volume when you need a completely clean dataset.
