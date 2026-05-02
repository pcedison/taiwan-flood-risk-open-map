# Runtime Smoke Runbook

This runbook verifies the local Docker Compose runtime without deleting Docker
volumes. It now covers the Phase 2 runtime-demo readiness path: API/Web, risk
query, query heat, worker queue ops CLI surface, queue metrics export surface,
live-gate no-network boundaries, durable worker queue with DLQ-equivalent
list/requeue visibility and replay audit IDs, official adapter fixture
dry-run, managed runtime fixture persistence, user reports gates, MVT tiles,
and the documented query-heat materialization plus tile feature/cache smoke
path.

The smoke is intentionally local. A passing run means the Compose services,
migrations, fixture-backed worker paths, managed persistence writers, queue
primitives, and monitoring entrypoints are runnable together. It does not
prove production source credentials, real upstream official worker ingestion,
source egress, hosted monitoring, scheduler cadence, DLQ/replay operations,
tile hosting, or public report launch readiness.

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
11. Runs `python -m app.main --run-official-demo` in a one-off `worker`
    container to prove the safe official adapter fixture parse/dry-run path
    without external API credentials or persistence.
12. Runs `python -m app.main --run-enabled-adapters --persist` in a one-off
    `worker` container with `WORKER_RUNTIME_FIXTURES_ENABLED=true` and only
    `official.wra.water_level` selected:
    - uses the Compose database and fixture adapter data only
    - keeps all live source API gates disabled
    - verifies the managed runtime CLI path wrote raw snapshot, accepted
      staging evidence, ingestion job, adapter run, and promoted evidence rows
    - deletes rows tied to `raw/official-demo/wra-water-level.json` after the
      verification
    - does not prove CWA/WRA/flood-potential production source readiness
13. Runs a queue ops CLI surface smoke in a one-off `worker` container:
    - executes `python -m app.main --help`
    - verifies the enqueue, consume, queue metrics export, queue summary/list,
      requeue, live-run, and adapter-list flags are present
    - verifies `SOURCE_FLOOD_POTENTIAL_ENABLED=false` gates
      `official.flood_potential.geojson` even when the GeoJSON live gate is on
    - verifies the flood-potential GeoJSON gate and URL settings are present
    - does not connect to the database and does not require CWA/WRA credentials
14. Runs a safe live-gate no-network boundary smoke in a one-off `worker`
    container:
    - calls `--run-enabled-adapters` with CWA/WRA/flood-potential selected
      but live API gates disabled
    - patches socket connection attempts inside the smoke process and fails if
      the no-op path tries to connect externally
    - does not require external credentials and does not prove production
      official ingestion readiness
15. Runs a queue live smoke in a one-off `worker` container:
    - enables fixture runtime adapters with
      `WORKER_RUNTIME_FIXTURES_ENABLED=true`
    - verifies active-job producer dedupe for the same adapter
    - consumes one `worker_runtime_jobs` row through `work_runtime_queue_once`
    - marks the consumed job `succeeded`
    - verifies an exhausted unknown-adapter job remains visible as
      `failed`/`final_failed_at`
    - verifies that `list_dead_letter_jobs` can see the exhausted row
    - requeues that row through the audited `--requeue-runtime-job` CLI against
      the live DB table and verifies it can be dequeued again
    - deletes the smoke queue rows
16. Runs a bounded maintenance scheduler tick for the Query Heat/tile cadence
    path with `--maintenance --scheduler --max-ticks 1`.
17. Runs a reports enabled-path smoke in a one-off `api` container with
    `USER_REPORTS_ENABLED=true`; this inserts a minimized pending row in
    `user_reports`, verifies moderation/audit rows, then deletes the smoke rows
18. Runs a query heat and tile cache job smoke:
    - materializes `P1D` and `P7D` query heat buckets
    - refreshes `flood-potential` map features from accepted evidence
    - writes one smoke tile cache row
    - verifies the API serves the same cached tile payload bytes
    - deletes synthetic tile/evidence/cache rows
19. Polls the web runtime until it responds at `http://localhost:3000`

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
.\scripts\runtime-smoke.ps1 -SkipAdapterFixtureSmoke
.\scripts\runtime-smoke.ps1 -SkipManagedRuntimePersistSmoke
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
Official adapter fixture dry-run smoke: --run-official-demo completed without external API credentials.
Managed runtime persist smoke: --run-enabled-adapters --persist wrote raw/staging/run and promoted evidence rows, then cleanup completed.
queue_cli_surface_smoke=ok enqueue=true work=true queue_metrics_export=true queue_summary=true queue_list=true requeue=true flood_potential_geojson_gate=true
live_gate_no_network_boundary_smoke=ok run_enabled_adapters_noop=true network_attempts=0
queue_smoke=ok dedupe_active_count=1 consumed_job_id=... adapter_key=official.wra.water_level failed_job_id=... failed_status=failed dead_letter_visible=true dead_letter_requeued=true
Maintenance scheduler bounded tick smoke: --maintenance --scheduler --max-ticks 1 completed.
reports_enabled_smoke=ok report_id=... status=pending
Query heat/tile cache job smoke: aggregation, feature refresh, cache write, API cache read, and cleanup passed.
Web smoke: HTTP 200 from http://localhost:3000
Runtime smoke passed.
```

## Manual Commands

These are the underlying commands to run a focused check while debugging.

Official adapter fixture dry-run. This exercises the current safe fixture parser
path and does not persist rows or call external official APIs:

```powershell
docker compose run --rm `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-official-demo"
```

Queue producer and worker smoke. Standalone CLIs exist for enqueue, consume,
dead-letter listing, and requeue. The full smoke script still uses a small
Python helper so it can capture the generated job id, verify DLQ-equivalent
list/requeue/dequeue against the live `worker_runtime_jobs` table, and delete
the synthetic queue row after the check.

Queue ops CLI surface smoke. This is the focused no-database/no-network check
used by the full smoke before the live queue helper. It parses
`python -m app.main --help`, verifies the expected landed ops flags are present,
and verifies the flood-potential source gate plus GeoJSON live config fields:

```powershell
docker compose run --rm worker sh -c "pip install -e . >/tmp/worker-install.log && python -m app.main --help"
```

Expected landed flags include `--enqueue-runtime-jobs`, `--work-runtime-queue`,
`--list-runtime-dead-letter-jobs`,
`--summarize-runtime-dead-letter-jobs`, `--dead-letter-queue-name`,
`--dead-letter-limit`, `--requeue-runtime-job`, `--requeue-keep-attempts`,
`--requeue-requested-by`, and `--requeue-reason`. Queue metrics export is also
required through `--export-runtime-queue-metrics`,
`--runtime-queue-metrics-format`, and `--runtime-queue-metrics-path`. The
current smoke also expects `--run-enabled-adapters`, `--persist`, and
`--list-adapters`.

Live-gate no-network boundary. This focused check is safe to run without
credentials. It selects the official live adapters but leaves the CWA/WRA API
and flood-potential GeoJSON gates disabled. The smoke patches socket connection
attempts and expects `--run-enabled-adapters` to be a no-op:

```powershell
docker compose run --rm worker sh -c "pip install -e . >/tmp/worker-install.log && python /workspace/.runtime-smoke/<generated-smoke>.py"
```

Producer:

```powershell
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  worker sh -c "pip install -e . && python -m app.main --enqueue-runtime-jobs"
```

Worker:

```powershell
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --work-runtime-queue --once"
```

Maintenance scheduler bounded tick:

```powershell
docker compose run --rm `
  -e WORKER_INSTANCE=runtime-smoke-maintenance `
  worker sh -c "pip install -e . && python -m app.main --maintenance --scheduler --max-ticks 1 --query-heat-periods P1D,P7D --query-heat-retention-days 14 --tile-layer-id flood-potential --tile-feature-limit 25 --tile-prune-limit 10"
```

Use `.\scripts\runtime-smoke.ps1` for the full cleanup-aware queue check. The
script uses smoke-isolated queue names so active dedupe and final-failed
visibility can be verified without leaving durable jobs behind on successful
runs. The requeue check only requeues a synthetic smoke row; no accepted
production replay policy or dedicated DLQ table exists yet.

Inspect final-failed queue rows:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --list-runtime-dead-letter-jobs --dead-letter-limit 20"
```

Requeue one failed row after confirming payload/idempotency and incident
context:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --requeue-runtime-job <job-id> --requeue-requested-by <operator> --requeue-reason '<why-safe-to-retry>'"
```

Official demo persistence path. This proves fixture/demo official adapters can
write staging, ingestion-run, promotion, and evidence rows; it does not fetch
real CWA/WRA upstream data from the worker runtime:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --run-official-demo --persist"
```

Managed runtime persistence path. This is the focused smoke equivalent for
`--run-enabled-adapters --persist`: it uses fixture adapters and the Compose
database, verifies evidence side effects, then should be cleaned up. It proves
the managed runtime CLI/persistence path, not production source readiness:

```powershell
docker compose run --rm `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e SOURCE_CWA_API_ENABLED=false `
  -e SOURCE_WRA_API_ENABLED=false `
  -e SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED=false `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters --persist"
```

Verification can stay narrow by checking the WRA fixture raw ref:

```sql
SELECT count(*) FROM evidence
WHERE raw_ref = 'raw/official-demo/wra-water-level.json'
  AND source_type = 'official'
  AND event_type = 'water_level'
  AND ingestion_status = 'accepted';
```

Cleanup SQL for that focused smoke:

```sql
WITH smoke_jobs AS (
    SELECT DISTINCT ingestion_job_id
    FROM adapter_runs
    WHERE raw_ref = 'raw/official-demo/wra-water-level.json'
      AND ingestion_job_id IS NOT NULL
),
deleted_risk_links AS (
    DELETE FROM risk_assessment_evidence
    WHERE evidence_id IN (
        SELECT id FROM evidence
        WHERE raw_ref = 'raw/official-demo/wra-water-level.json'
    )
    RETURNING 1
),
deleted_evidence AS (
    DELETE FROM evidence
    WHERE raw_ref = 'raw/official-demo/wra-water-level.json'
    RETURNING 1
),
deleted_staging AS (
    DELETE FROM staging_evidence
    WHERE raw_snapshot_id IN (
        SELECT id FROM raw_snapshots
        WHERE raw_ref = 'raw/official-demo/wra-water-level.json'
    )
    OR payload ->> 'raw_ref' = 'raw/official-demo/wra-water-level.json'
    RETURNING 1
),
deleted_adapter_runs AS (
    DELETE FROM adapter_runs
    WHERE raw_ref = 'raw/official-demo/wra-water-level.json'
    RETURNING 1
)
DELETE FROM ingestion_jobs
WHERE id IN (SELECT ingestion_job_id FROM smoke_jobs);

DELETE FROM raw_snapshots
WHERE raw_ref = 'raw/official-demo/wra-water-level.json';
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

## Pending Checklist

- Harden the gated CWA/WRA/flood-potential worker live clients with source
  review, credentials, attribution, production egress verification, hosted
  cadence, and non-fixture runtime queue smoke before claiming production
  ingestion readiness.
- Promote the row-level list/requeue commands and audit/quarantine primitives
  into an accepted DLQ/poison-job policy; current smoke only proves synthetic
  final-failed list/requeue/dequeue visibility.
- Deploy a singleton scheduler cadence for ingestion, query heat, tile refresh,
  retention, and freshness export.
- Wire hosted monitoring with alert routing, TLS/auth, and persistent storage.
- Finish production tile generation, expiry, invalidation, and hosting.
- Keep public reports and public discussion sources disabled until governance
  gates are accepted.

## Common Failures

- `docker compose config --quiet` fails: the Compose file or environment interpolation is invalid.
- Docker command or daemon is unavailable: start Docker Desktop and ensure both `docker compose version` and `docker info` work.
- Port already in use: stop the conflicting process or set the matching `*_PORT` environment variable before running the script.
- `/ready` stays down: inspect `docker compose logs --tail=80 api`, `postgres`, and `redis`.
- Migration fails: inspect the migration output and confirm Postgres is healthy.
- Queue smoke fails: inspect `docker compose logs --tail=80 worker` and confirm
  migration `0006_worker_runtime_queue.sql` has been applied.
- Official adapter fixture dry-run fails: inspect the one-off worker output.
  This path should use in-repo fixtures only and should not require external
  API credentials.
- Managed runtime persist smoke fails: inspect the one-off worker output and
  confirm migrations have created `raw_snapshots`, `staging_evidence`,
  `ingestion_jobs`, `adapter_runs`, and `evidence`. This path is fixture-backed
  and should not require external API credentials.
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
it deletes the synthetic managed-runtime persistence, queue, report/audit, tile
cache, map feature, and evidence smoke rows before exit; managed-runtime and
tile/evidence/cache cleanup are also registered as best-effort cleanup if a
later assertion fails. Rows that may remain as useful local evidence are:

- one or more risk/query assessment rows from `/v1/risk/assess`
- materialized `query_heat_buckets` rows generated from local query history

These rows are expected in a local runtime-smoke database. Use a throwaway
Compose volume when you need a completely clean dataset.
