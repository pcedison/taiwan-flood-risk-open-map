# Worker And Scheduler Deployment

Reviewed: 2026-06-09

This runbook defines the production-beta split-service path for Flood Risk. It
complements `deploy-zeabur.md`, which still documents the current single-service
preview path.

## Topology

Deploy these runtime units as separate services or platform-native jobs:

- `web`: Next.js public UI.
- `api`: FastAPI public/admin API.
- `worker`: durable queue consumer and one-off ingestion/maintenance runner.
- `scheduler`: singleton producer for runtime adapter jobs and maintenance
  ticks.
- `migrate`: manual or release-gated database migration job.

PostgreSQL/PostGIS, Redis, object storage, and monitoring storage are managed
dependencies. The worker and scheduler must share the same `DATABASE_URL`,
`REDIS_URL`, adapter gate variables, and source credentials as the API where
applicable.

## Required Commands

API and Web commands are platform-specific, but must expose `/health`, `/ready`,
and the public web origin.

Worker queue consumer:

```sh
python -m app.main --work-runtime-queue --persist
```

Scheduler queue producer:

```sh
python -m app.scheduler --enqueue-runtime-jobs
```

Scheduler maintenance tick:

```sh
python -m app.scheduler --maintenance
```

Migration job:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/migrations/<migration>.sql
```

Use bounded `--once` commands for smoke tests and release checks. Use platform
scheduling or exactly one scheduler replica for recurring production cadence.

## Environment Gates

Required for API, worker, scheduler:

- `APP_ENV=production-beta` or `production`
- `DATABASE_URL`
- `REDIS_URL`
- `ABUSE_HASH_SALT`

Required for hosted public API rate limits:

- `PUBLIC_RATE_LIMIT_ENABLED=true`
- `PUBLIC_RATE_LIMIT_BACKEND=redis`

Required before enabling live official worker adapters:

- `WORKER_ENABLED_ADAPTER_KEYS`
- `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=false` for hosted public API
  traffic. Production and production-beta do not use the API realtime bridge
  as readiness evidence; public risk responses must be backed by
  worker-persisted evidence.
- `SOURCE_CWA_API_ENABLED=true` plus `CWA_API_AUTHORIZATION` for CWA rainfall.
- `SOURCE_WRA_API_ENABLED=true` plus `WRA_API_TOKEN` if the WRA source requires
  it.
- `SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED=true` plus a reviewed
  `FLOOD_POTENTIAL_GEOJSON_URL` for flood-potential imports.

Keep public discussion, forum, social, and public-report ingestion disabled
until their launch evidence is accepted.

## Health And Readiness

- API liveness: `GET /health`.
- API dependency readiness: `GET /ready`.
- Worker health: recent worker heartbeat textfile metric or platform job success.
- Scheduler health: recent scheduler heartbeat textfile metric and a singleton
  lease winner.
- Source health: source freshness metrics and latest adapter run status.
- Queue health: runtime queue metrics plus final-failed row inspection.

Set `WORKER_METRICS_TEXTFILE_PATH` and `SCHEDULER_METRICS_TEXTFILE_PATH` when
using node-exporter textfile collection. Scrape the generated files through the
monitoring profile or the hosted metrics collector.

## Smoke Checks

Local Compose validation:

```powershell
docker compose config --quiet
python -m pytest apps/workers/tests/test_worker_entrypoints.py -q
python infra/scripts/validate_monitoring_assets.py
```

Queue producer smoke:

```sh
WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level \
python -m app.scheduler --enqueue-runtime-jobs --once
```

Queue worker smoke:

```sh
WORKER_RUNTIME_FIXTURES_ENABLED=true \
WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level \
python -m app.main --work-runtime-queue --once --persist
```

Managed ingestion smoke:

```sh
WORKER_RUNTIME_FIXTURES_ENABLED=true \
WORKER_ENABLED_ADAPTER_KEYS=official.cwa.rainfall,official.cwa.tide_level,official.wra.water_level,official.civil_iot.flood_sensor,official.civil_iot.sewer_water_level,official.civil_iot.pump_water_level,official.civil_iot.gate_water_level,official.civil_iot.pond_water_level \
python -m app.main --run-enabled-adapters --persist
```

Before claiming hosted or production readiness, capture evidence that the
worker/scheduler path wrote `raw_snapshots`, `staging_evidence`,
`adapter_runs`, promoted `evidence`, and fresh `official_realtime_latest` rows
for each enabled official adapter. The local managed ingestion smoke now covers
fixture-backed CWA rainfall, WRA water level, and Civil IoT flood, sewer, pump,
gate, and pond water-level adapters, but production readiness still requires
hosted evidence from the real enabled upstreams. The `official_realtime_latest`
rows are the public hot path for nearby realtime coverage; do not use the API
realtime bridge as a substitute for this evidence.

## Maintenance Retention

`python -m app.scheduler --maintenance` runs four bounded retention passes per
cycle, in this order: realtime `evidence`, `location_queries`, expired
`raw_snapshots`, then `staging_evidence`. The staging pass is last on purpose --
it is the largest and newest, and must never delay the privacy passes above it.

### staging_evidence

`staging_evidence` holds one audit row per normalized item per ingestion cycle
and was never pruned before #367 (14,003,032 live rows / 20.8 GB on the hosted
node on 2026-09-06, against a 2 GB node whose whole database is ~30 GB, so every
uncached query reads from disk).

What the pass deletes:

- Rows whose `validation_status` is `rejected` and whose `created_at` is older
  than `STAGING_EVIDENCE_RETENTION_DAYS` (default 7). `rejected` is terminal:
  `pipelines/promotion.py` writes it for a terminal rejection and for the
  batched `idempotent_existing_observation` settle, and no reader selects it.

What the pass never deletes:

- Anything still marked `accepted`. The schema has no `promoted`
  `validation_status` (`0002_phase1_core_domain.sql` allows
  pending/accepted/rejected/quarantined, and `pipelines/staging.py` only ever
  writes accepted or rejected), so a promoted row stays `accepted` and cannot be
  told apart from one still awaiting promotion without a per-row probe into
  `evidence`. `jobs/historical_coverage.py` also still reads aged accepted rows.
  Measure the split before proposing a wider window:

  ```sh
  psql "$DATABASE_URL" -c "SELECT validation_status, count(*) FROM staging_evidence GROUP BY 1 ORDER BY 2 DESC;"
  ```

- `pending` and `quarantined` rows, which the pipeline never writes and which
  are left for human review.

Promotion correctness is unaffected: idempotency compares
`evidence.properties ->> 'staging_evidence_id'` on the evidence side, and
`staging_evidence.raw_snapshot_id` is `ON DELETE SET NULL`.

### Bounds

See `apps/workers/app/jobs/evidence_retention.py`: 5 000 rows per batch, one
committed transaction per batch, a transaction-local 5 s `statement_timeout`
and 2 s `lock_timeout` re-applied before every batch, and
`STAGING_EVIDENCE_RETENTION_MAX_BATCHES` (default 10) batches per cycle. On a
timeout or a refused lock the cycle stops and records
`stopped_reason=statement_timeout` / `lock_timeout`; it never retries inside the
same cycle, and three consecutive such cycles log
`worker.maintenance.staging_retention_timeout_streak` at warning level.

Batches need no cursor: each one deletes exactly the rows it selected, so the
next batch cannot see them again. They are ordered by `created_at`, which takes
the oldest eligible rows first and matches the supporting index.

Measured on local PostGIS with 500 000 aged rejected rows (117 MB table): a
5 000-row batch costs ~100 ms, so a full 10-batch cycle deletes 50 000 rows in
about a second. Once the backlog is gone the terminal probing batch reads the
index and returns nothing in ~3 ms. The hosted table is disk-bound, so budget
several times that per batch and still well under the 5 s limit. What paces the
backfill is the 300 s scheduler interval, not the batch cost.

### The partial index

The batch select depends on:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_evidence_rejected_created_at
    ON staging_evidence (created_at)
    WHERE validation_status = 'rejected';
```

Without it the select has to walk the table to find 5 000 aged rejected rows:
measured at ~1.31 M buffers and 2.5 s per batch on 1 M rows, which both blows
the 5 s budget during the backlog and, once the backlog is gone, re-scans the
whole table every five minutes and evicts the page cache of a 2 GB node.

It is **not** a migration. Migrations run inside the API start-up transaction,
and a plain `CREATE INDEX` on a 14 M row table locks out writes until it
finishes (#317). Instead the job builds it itself at the start of each cycle, on
an autocommit connection, with `CREATE INDEX CONCURRENTLY` and no
`statement_timeout` (`lock_timeout` is kept, so the brief locks the build takes
never queue behind ingestion). It then re-reads `pg_index.indisvalid`; an index
left invalid by a build that died half way is dropped concurrently and rebuilt,
because the planner ignores an invalid index and its presence blocks
`CREATE INDEX ... IF NOT EXISTS` from replacing it.

**Until the index is valid the job deletes nothing** and reports
`stopped_reason=index_not_ready`. That is deliberate: the alternative is the
pathological scan above.

On the hosted 14 M row table the concurrent build takes **minutes to tens of
minutes** and is IO-heavy while it runs, and the maintenance cycle waits for it
(the three privacy retention passes have already finished by then, since the
staging pass runs last). To take that cost in a window you choose instead, run
the statement above by hand and set:

```
STAGING_EVIDENCE_RETENTION_ENSURE_INDEX=false
```

The deletes still run with that flag off; only the build step is skipped. If the
index is in fact missing, the per-batch `statement_timeout` bounds the damage to
one cancelled batch per cycle. Check the build afterwards with:

```sh
psql "$DATABASE_URL" -c "SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE indexrelid = 'idx_staging_evidence_rejected_created_at'::regclass;"
```

### Observing a rollout

- `worker.maintenance.staging_retention` log events carry `deleted_rows`,
  `batches`, `index_state`, and `stopped_reason` per cycle. Expect
  `index_state=building` and `stopped_reason=index_not_ready` for the cycles the
  concurrent index build occupies, before any row is deleted.
- `worker.maintenance.staging_retention_index_built` /
  `..._index_failed` report the index step;
  `..._timeout_streak` warns after three consecutive timed-out cycles.
- `scheduler.maintenance.completed` carries `staging_evidence_rows_pruned`,
  `staging_evidence_stopped_reason` and `staging_evidence_index_state`.
- The scheduler heartbeat in `GET /v1/ingestion-readiness` must stay fresh
  across the backfill; a stalling heartbeat means the prune is competing with
  ingestion and `STAGING_EVIDENCE_RETENTION_MAX_BATCHES` should be lowered.
- The next `hosted-db-diagnostics.json` capture should show the
  `staging_evidence` live row count falling by up to 50 000 per cycle.

Set `STAGING_EVIDENCE_RETENTION_ENABLED=false` to stop the pass without a
redeploy.

### Autovacuum thresholds

Deleting rows is only half the job: until autovacuum runs, the dead tuples and
their index entries still occupy the page cache of a 2 GB node. PostgreSQL's
default `autovacuum_vacuum_scale_factor` is 0.2, so `staging_evidence` would
have to accumulate ~2.9 M dead rows -- roughly 58 full retention cycles, i.e.
days -- before a single vacuum triggered. `0063_autovacuum_tuning_for_evidence_tables.sql`
sets per-table storage parameters instead:

| Table | scale factors (vacuum / analyze) | dead rows before a vacuum | cost delay / limit |
| --- | --- | --- | --- |
| `staging_evidence` | 0.02 / 0.02 | ~287 k (of 14.35 M) | 2 ms / 1000 |
| `evidence` | 0.05 / 0.05 | ~113 k (of 2.25 M) | 2 ms / default 200 |

`staging_evidence` gets the tighter factor and the 5x cost limit because it is
the table the retention pass churns (up to 600 k deleted rows per hour during
the backfill); `evidence` churns far more slowly and is read-hot, so it keeps
the default IO budget. The analyze factors move with the vacuum factors so the
planner statistics behind the prune and promotion queries stay current on a
table whose live-row count is falling fast.

These are thresholds, not a schedule: they change *when* autovacuum fires, so
they need no worker change and cost nothing when the table is quiet. They also
do not replace the one-off `VACUUM (ANALYZE)` below -- that is still the way to
force the first pass rather than wait for the threshold.

Confirm the settings landed:

```sh
psql "$DATABASE_URL" -c "SELECT relname, reloptions FROM pg_class WHERE relname IN ('staging_evidence','evidence');"
```

Then watch them work in `hosted-db-diagnostics.json`
(`python scripts/hosted_db_diagnostics.py`), under `tables[]`:

- `last_autovacuum` for both tables should start advancing within hours instead
  of standing days stale (it was 2026-09-04 for `staging_evidence` and the
  morning of 2026-09-06 for `evidence` before this change).
- `n_dead_tup` for `staging_evidence` should oscillate under ~300 k rather than
  climbing monotonically; `dead_tuple_ratio` should stay near or below 0.02.
- If `n_dead_tup` keeps climbing past those numbers while `last_autovacuum`
  stays stale, autovacuum is being starved, not mis-tuned: check for a long-
  running transaction holding back the xmin horizon
  (`SELECT pid, state, xact_start FROM pg_stat_activity ORDER BY xact_start;`)
  and check whether the hosted node caps `autovacuum_max_workers`.

### After the backlog clears

Deleting rows does not return disk to the operating system; it only marks
tuples dead for reuse -- and until autovacuum clears them the retention index
still holds their entries, so the probing batch stays a few milliseconds rather
than dropping to its floor. Once `stopped_reason` has been `exhausted` for several
consecutive cycles, run this once in a maintenance window:

```sh
psql "$DATABASE_URL" -c "VACUUM (ANALYZE) staging_evidence;"
```

`VACUUM (ANALYZE)` takes no exclusive lock, so ingestion keeps running. It makes
the freed space reusable by `staging_evidence` and refreshes the planner
statistics the prune and promotion queries depend on.

Reclaiming the 20 GB back to the filesystem needs a table rewrite, which is a
separate, scheduled decision:

- `VACUUM FULL staging_evidence` takes an `ACCESS EXCLUSIVE` lock for the whole
  rewrite. Ingestion, promotion, and every read of the table block until it
  finishes, so it requires an announced downtime window and roughly as much free
  disk as the final table size.
- `pg_repack` rewrites the table with only brief locks, but the extension must
  be installed on the hosted instance first and it also needs the extra disk.

Do neither on the hosted node without confirming free disk first; a rewrite that
runs out of space leaves the table locked and the node down.

## Failure Detection

Investigate before restarting workers when any of these fire:

- API `/ready` reports database or Redis failed.
- Worker heartbeat age exceeds the documented alert threshold.
- Scheduler heartbeat age exceeds the documented alert threshold.
- Source freshness marks CWA, WRA, flood-potential, public news, or historical
  evidence stale.
- Runtime queue final-failed rows increase.
- Adapter run status is `failed` or freshness checks are alerting.

Use row-level requeue only after confirming idempotency, source safety, and the
reason the previous run failed. Record the operator, reason, and evidence ref in
private ops notes.
