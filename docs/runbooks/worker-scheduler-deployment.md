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

One more step follows the four: the concurrent `evidence` index rebuild, under
"Evidence Index Rebuilds" below. It is pure housekeeping and runs behind its own
guard, so it can neither delay nor fail the retention passes.

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

## Evidence Index Rebuilds

The last step of a maintenance cycle rebuilds one bloated `evidence` index with
`REINDEX INDEX CONCURRENTLY`. See
`apps/workers/app/jobs/index_maintenance.py`.

Why it exists: `evidence` is high churn. Realtime station rows are inserted
every ingestion cycle and deleted 48 h later, and every NSTC/WRA historical
snapshot re-imports a whole batch before the old one is dropped. No VACUUM ever
returns an index page, and a GiST index grown one insert at a time ends up with
heavily overlapping bounding boxes. On 2026-09-07 the hosted table was 2.27 M
rows / 5.4 GB of heap under 2.26 GB of indexes, and the `nearby_evidence` probe
in `GET /admin/v1/db-diagnostics` (Taipei City Hall, 500 m) took 2.3 s, of which
1.87 s was 2 875 cold shared blocks read from
`idx_evidence_nearby_non_realtime_geom` to fetch 168 candidate rows whose
geometry and properties add up to 0.1 MiB. Nearly all of those blocks were index
pages, or index entries pointing at heap tuples retention had already deleted.

It cannot be a migration: migrations run inside the API start-up transaction, so
an index build there locks the table and returns 502s (#317). Hence a worker
job, on an autocommit connection, `CONCURRENTLY`, exactly like
`_ensure_rejected_index` above.

### Policy

- **Window only.** `EVIDENCE_INDEX_REINDEX_WINDOW_UTC` (default `18:00-21:00`
  UTC = 02:00-05:00 Taipei). Outside it the pass records
  `skipped_outside_window` and opens no connection. A window may cross midnight.
- **One index per cycle**, the first eligible entry of
  `EVIDENCE_INDEX_REINDEX_INDEXES` (default: the list in the job module, which
  starts with `idx_evidence_nearby_non_realtime_geom`, the index the assessment
  read path scans). A cycle is 300 s and a rebuild is minutes, so a cycle never
  queues two.
- **One rebuild per index per `EVIDENCE_INDEX_REINDEX_INTERVAL_HOURS`**
  (default 168 = a week).
- **One *attempt* per index per window.** A rebuild that fails records the
  attempt, so the next cycle five minutes later does not retry into the same
  contention. The next window tries again.
- **Skips**, all recorded in the log line: `skipped_missing` (not in the current
  schema), `skipped_invalid` (`pg_index.indisvalid = false` -- needs a human,
  see below), `skipped_small` (under
  `EVIDENCE_INDEX_REINDEX_MIN_SIZE_BYTES`, default 8 MiB),
  `skipped_interval`, `skipped_attempted`, `skipped_unsupported`
  (PostgreSQL < 12, where `REINDEX ... CONCURRENTLY` does not exist).
- **Bounds.** `EVIDENCE_INDEX_REINDEX_LOCK_TIMEOUT_MS` (default 5 000) so the
  brief locks a concurrent rebuild takes never queue behind ingestion, and
  `EVIDENCE_INDEX_REINDEX_STATEMENT_TIMEOUT_MS` (default 1 800 000 = 30 min) so
  a rebuild cannot run past the window into morning traffic. Both are session
  settings, because `REINDEX CONCURRENTLY` runs outside a transaction block.
- **Failure is not a failed cycle.** A refused lock, a cancelled statement, or
  an unreachable server is logged as `failed:<sqlstate>` and maintenance
  finishes normally. A malformed `EVIDENCE_INDEX_REINDEX_*` value logs
  `scheduler.maintenance.evidence_reindex_misconfigured` and the pass is
  skipped; retention still runs.
- Set `EVIDENCE_INDEX_REINDEX_ENABLED=false` to stop rebuilding without a
  redeploy.

### Restart semantics

"When was this index last rebuilt" lives in a module-level dict in the
scheduler process, not in the database -- the same trade-off the staging timeout
streak makes, and the scheduler is a single long-lived process. A worker restart
forgets the history, so the next window rebuilds one more round of indexes than
it strictly needed. That is wasted I/O inside the low-traffic window, never a
correctness problem; there is nothing to reconcile after a deploy.

### Observing it

Each cycle logs one line:

```
worker.maintenance.evidence_reindex
  index, outcome, window_utc, before_bytes, after_bytes, reltuples,
  elapsed_ms, skipped
```

and `scheduler.maintenance.completed` carries `evidence_reindex_outcome` and
`evidence_reindex_index` (`disabled` when the pass is switched off). Every other
field of that event is unchanged.

To confirm a rebuild landed, compare `indexes[].index_size_bytes` in
`hosted-db-diagnostics.json` (`python scripts/hosted_db_diagnostics.py`) across
the window, and re-read the `nearby_evidence` probe timing in the same file:

```sh
python scripts/hosted_db_diagnostics.py > /tmp/before.json
# ... after the window ...
python scripts/hosted_db_diagnostics.py > /tmp/after.json
python - <<'PY'
import json
load = lambda p: {i["indexrelname"]: i["index_size_bytes"] for i in json.load(open(p))["indexes"]}
before, after = load("/tmp/before.json"), load("/tmp/after.json")
for name, size in sorted(after.items()):
    if before.get(name) and size != before[name]:
        print(name, before[name], "->", size)
PY
```

Measured locally on an isolated schema with the hosted write pattern (150 000
non-realtime point rows inserted across three rounds, nine tenths deleted each
round, no VACUUM):
`idx_evidence_nearby_non_realtime_geom` went from 6 266 880 to 622 592 bytes,
and the 500 m bounding-box probe went from 3 010 shared blocks and 1 866
candidate index entries to 360 blocks and 178 entries for the same 178 matching
rows. See `apps/workers/tests/test_index_maintenance_postgres.py`.

### When a rebuild fails

A cancelled or interrupted `REINDEX INDEX CONCURRENTLY` leaves the half-built
index behind as `<name>_ccnew`: invalid, ignored by the planner, still occupying
disk, and blocking the next rebuild on the name. The job drops it itself before
its next attempt, so no action is normally needed. To clear one by hand (it
takes no exclusive lock):

```sh
psql "$DATABASE_URL" -c "DROP INDEX CONCURRENTLY IF EXISTS idx_evidence_nearby_non_realtime_geom_ccnew;"
```

List everything left over first:

```sh
psql "$DATABASE_URL" -c "SELECT cls.relname, idx.indisvalid, pg_size_pretty(pg_relation_size(cls.oid)) FROM pg_class cls JOIN pg_index idx ON idx.indexrelid = cls.oid WHERE cls.relname LIKE '%_ccnew' OR cls.relname LIKE '%_ccold' OR NOT idx.indisvalid;"
```

- `_ccnew` rows: drop them concurrently as above.
- `_ccold` rows: a crash between the two swap phases can leave the *old* index
  under this name. It is a real index holding real entries; confirm the base
  name exists and is valid before dropping it.
- A base index reported `indisvalid = false` is why the job records
  `skipped_invalid` and refuses to touch it. Either a build is still running
  (`SELECT * FROM pg_stat_progress_create_index;`) or one died. If nothing is
  running, drop and recreate it concurrently using the definition in
  `infra/migrations/` -- never inside a migration, and never without
  `CONCURRENTLY`.

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
