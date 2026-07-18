# Flood Risk — Performance / Sustainability Audit

Repo: `C:/Users/y_mea/Desktop/_整理後_待匯出/05_程式專案_內部工具/Flood Risk`
Branch checked: `audit/sustainability-2026-07-06` (working tree, current HEAD `62f008d`, matches latest `origin/main`)
Scope: public deployment on a single 2 vCPU / 2 GB k3s node co-hosting API, Web, workers, PostGIS, Redis (per task brief).

Legend: **[NOW]** = will hurt today under normal/moderate load. **[GROWS]** = fine today, becomes painful as data/traffic volume grows.

---

## Top findings (ranked)

### 1. [NOW] No database connection pooling anywhere in the API — every query opens a brand-new raw connection
**Files:**
- `apps/api/app/domain/evidence/repository.py:1056-1059` (`_connect`)
- `apps/api/app/domain/tiles/repository.py:258`
- `apps/api/app/domain/layers/repository.py:116`
- `apps/api/app/domain/profiles/repository.py:237`
- `apps/api/app/domain/reports/repository.py:348`
- `apps/api/app/domain/geocoding/providers.py:779`
- `apps/api/app/domain/geocoding/postgis_bootstrap.py:148,220`
- `apps/api/app/api/routes/health.py:118-140` (`_check_database`, `_check_redis`)
- `apps/api/app/api/routes/admin.py:646,757`
- `apps/api/pyproject.toml:8` — dependency is plain `psycopg[binary]>=3.2`, no `psycopg_pool` anywhere in the repo.

**Trigger:** Every helper does `psycopg.connect(database_url, connect_timeout=2, ...)` (and `redis.Redis.from_url(...)` in `health.py:135`) per call, with no shared pool. A single `POST /v1/risk/assess` fans out into ~6-8 *sequential* repository calls (`apps/api/app/api/routes/public.py`: `_nearby_realtime_coverage` → `query_nearby_realtime_coverage_rows` [up to 2 connects], `_nearby_db_evidence` → `query_nearby_latest_official` + `query_nearby_evidence` [2 connects], `_precomputed_risk_profile` → `fetch_best_profile_for_point` [1 connect], `_query_heat` → `fetch_query_heat_snapshot` [1 connect], `_persist_assessment` → `persist_risk_assessment` [1 connect]) — i.e. one API request opens roughly 6-8 fresh TCP+auth handshakes to Postgres.

**Impact:** Each `psycopg.connect()` is a full TCP handshake + Postgres backend fork (Postgres allocates a new OS process per connection, ~5-10 MB min RSS each). Routes are sync `def` so FastAPI runs them in Starlette's threadpool (default up to 40 workers) — under concurrent traffic this can spike to dozens of simultaneous new Postgres connections, adding real per-request latency (handshake cost on every DB touch, not amortized) and risking `max_connections` exhaustion / Postgres memory pressure on the shared 2 GB node. This matches the "PostGIS MemoryPressure / eviction" symptom already logged in `docs/architecture/realtime-storage-optimization-plan.md` (Phase 1 lists PgBouncer as still-pending future work, confirming this gap is known but unresolved).

**Fix:** Introduce a shared `psycopg_pool.ConnectionPool` (module-level, sized ~5-10 for a 2 vCPU box) reused across all repository calls, or front Postgres with PgBouncer in transaction-pooling mode. Also reuse one connection per request instead of one per repository call.

### 2. [GROWS→NOW] Non-sargable fallback clause forces a full sequential scan on every geocode request
**File:** `apps/api/app/domain/geocoding/providers.py:753-777` (`fetch_postgis_open_data_candidates`)

```sql
WHERE
    normalized_aliases && %(query_aliases)s::text[]
    OR EXISTS (
        SELECT 1 FROM unnest(normalized_aliases) AS candidate_alias(alias)
        WHERE length(candidate_alias.alias) >= 4
            AND position(candidate_alias.alias IN %(normalized_query)s) > 0
    )
```

**Trigger:** The first branch can use the GIN index on `normalized_aliases` (`infra/migrations/0013_geocoder_open_data_entries.sql:44-45`), but the second branch computes `unnest()` + `position()` per row — not indexable. Because it's OR'd with the indexed branch, PostgreSQL's planner generally cannot restrict to an index scan and falls back to a sequential scan of the *entire* `geocoder_open_data_entries` table on every `/v1/geocode` call.

**Impact:** `docs/data-sources/geocoding/geocoding-data-manifest.yaml` states the *planned* coverage explicitly grows to include nationwide roads, all villages, POIs, and eventually `all_taiwan_doorplate_addresses` — i.e. this table is designed to grow to tens/hundreds of thousands of rows. Every geocode call (public-facing, user-triggered on every search) will re-scan the whole table, burning CPU on the 2-vCPU box; concurrent geocode requests multiply this linearly. Even at moderate current row counts this adds unnecessary latency; it gets materially worse as the address coverage roadmap is executed.

**Fix:** Drop the substring-fallback branch or replace it with a trigram (`pg_trgm` GIN) index and `%` similarity/`LIKE` operator that Postgres can actually use, or precompute additional alias tokens so the array-overlap branch alone is suf0icient.

### 3. [GROWS] Evidence retention job does not cover `flood_report` / `flood_warning` event types — unbounded row growth
**Files:**
- `apps/workers/app/jobs/evidence_retention.py:26-28` — `PRUNABLE_REALTIME_EVENT_TYPES = ("rainfall", "water_level")` only.
- `apps/workers/app/pipelines/promotion.py:605-620` (`_should_upsert_official_realtime_latest`) shows `flood_report` (Civil IoT flood sensors) and `flood_warning` (NCDR CAP alerts) are live per-cycle station snapshots just like rainfall/water_level, but they insert a **new** `evidence` row each cycle (via `write_evidence`, `ON CONFLICT ... DO UPDATE SET updated_at = evidence.updated_at` only dedupes on identical `raw_ref`, which typically changes each ingestion cycle for a live snapshot).
- Adapters producing `flood_report`: `apps/workers/app/adapters/civil_iot/flood_sensor.py:208`, plus county-level flood-sensor adapters (Tainan, New Taipei, Hsinchu City, Chiayi County, Kaohsiung, Keelung, Taoyuan, Yilan, 6x FHY counties) all registered in `apps/workers/app/jobs/runtime.py`.

**Trigger:** With the default 300s scheduler cadence and 10+ flood-sensor adapters nationwide, each covering many stations, the `evidence` table accumulates new `flood_report`/`flood_warning` rows indefinitely — the retention job's own comment (`evidence_retention.py:1-13`) explicitly says it targets "CWA rainfall (~570 stations) plus WRA/Civil IoT water levels" but silently excludes the other two live event types.

**Impact:** Table/index bloat on `evidence` (already flagged generically in `docs/architecture/realtime-storage-optimization-plan.md` as a PostGIS memory-pressure driver) grows without bound for these event types, degrading `ST_DWithin`/GiST index performance over time and consuming disk/cache on the 2 GB node. This is a "grows painful" issue, not yet acute, but the design gap is real and will surface as more county sensor adapters are enabled (multiple are still gated behind flags today).

**Fix:** Extend `PRUNABLE_REALTIME_EVENT_TYPES` to include `flood_report` and `flood_warning` (mirroring the same short retention window), or rely exclusively on `official_realtime_latest` for the live/current view and prune the underlying `evidence` audit rows more aggressively.

### 4. [NOW] Production topology co-locates API + Web + ingestion scheduler in one process group inside one 2 GB container
**Files:**
- `Dockerfile:88-213` (`start-zeabur-single.sh`) — launches `uvicorn app.main:app` (API), then Next.js `next start` (Web), then `python -m app.main --run-enabled-adapters --persist --scheduler &` (ingestion scheduler with ~9+ national backbone adapters forced on by default via `REALTIME_BACKBONE_FORCE_INGESTION_ON_START=true`), all as sibling processes in the same container.
- `docs/runbooks/deploy-zeabur.md:38-46,306-322` confirms this is the *current* production path ("Quick Path: Single Zeabur Service" / "The single-service mode above is not the final production topology").
- `docs/architecture/realtime-storage-optimization-plan.md:86-88` (Phase 1, still open) explicitly calls for separating API from ingestion workers "so ingestion bursts should not compete with public request handling inside one process" — i.e. this is a known, unresolved risk, not a hidden one.

**Trigger:** Any memory spike in one of the three co-located runtimes (a slow/verbose ingestion cycle building large in-memory JSON payloads from a Civil IoT STA `Things` fetch, a burst of concurrent public risk-assessment requests each opening several DB connections per finding #1, or Next.js SSR memory) competes for the same 2 GB ceiling as the other two.

**Impact:** An OOM in this container kills API + Web + ingestion together (not an isolated component), causing a full outage rather than a degraded one. This matches the task's stated history of "記憶體不足曾造成部署失敗與 OOM." No per-process memory limits/cgroup separation exist inside the container to contain one runtime's leak/spike from starving the others.

**Fix:** Follow the already-documented Phase 1 plan: split API and ingestion scheduler into separate services (the `docker-compose.yml` already models this split for local dev — `api`, `worker`, `scheduler` are already separate services there); keep the single-container mode only for the initial preview, not steady-state production.

### 5. [GROWS] Ingestion staging writes use per-row `cursor.execute` loops instead of batch insert
**File:** `apps/workers/app/pipelines/postgres_writer.py:25-31` (`write_batch`) — `for item in (*batch.accepted, *batch.rejected): _insert_staging_evidence(cursor, raw_snapshot_id, item)`, one `INSERT` statement per station reading, all within a single connection/transaction (good), but not batched via `executemany`/`COPY`.

**Trigger:** CWA rainfall alone is ~570 stations per cycle; combined with WRA, Civil IoT, and 20+ county-level adapters, each adapter run does one-row-at-a-time inserts. Not urgent today (ingestion runs every 300s off the request-serving critical path, and it's a single connection so no connection-storm), but adds unnecessary round-trip/CPU overhead on the shared 2-vCPU box and will extend ingestion cycle duration as more counties/stations are enabled, risking cycles that approach or exceed the 300s cadence.

**Fix:** Batch with `executemany` (or `COPY` for the raw/staging tables) per adapter batch.

---

## Aspects checked with no material finding

**1. Event-loop blocking (async def + sync I/O).** Checked every route module (`apps/api/app/api/routes/{public,reports,admin,health,tiles}.py`). All routes that touch Postgres/Redis are declared as plain `def` (`assess_risk`, `geocode`, `list_evidence`, `create_user_report`, `list_admin_jobs`, etc.), which FastAPI/Starlette correctly runs in the threadpool — so the sync `psycopg`/`redis` clients used throughout do **not** block the asyncio event loop. The only `async def` handlers are `health()` (`health.py:14`, no I/O) and the `_require_admin` dependency (`admin.py:580`, bearer-token compare only, no I/O). No finding here — the "sync repo functions" pattern is architecturally correct given the sync-def-in-threadpool design; the real cost is connection overhead (finding #1), not loop blocking.

**2. Spatial index alignment.** Compared `WHERE`/`ORDER BY` predicates in `apps/api/app/domain/evidence/repository.py` (`query_nearby_evidence`, `query_nearby_latest_official`, `query_nearby_realtime_coverage_rows`) against index definitions in `infra/migrations/0012_evidence_geography_index.sql`, `0014_location_queries_geography_index.sql`, `0017_evidence_realtime_partial_indexes.sql`, `0018_official_realtime_latest.sql`. Partial GiST indexes on `geom` filtered by `event_type`/`source_type` match the query shapes (bbox `&&` prefilter + `ST_DWithin`), and `official_realtime_latest` (the Phase-2 optimization from the architecture doc) is already implemented and queried first. No N+1 within a single request — each helper is one round trip; the earlier finding is about connection setup cost, not row-by-row queries.

**3. Redis cache design (keys/TTL/fail-open/in-process caps).** Checked `apps/api/app/api/services/{redis_support,public_response_cache,public_evidence_cache,public_geocode_cache}.py`. All three caches use bounded in-process FIFO dicts (128/256/512 max entries) with TTL, and Redis access always fails open with a 30s cooldown after any `redis.RedisError` (`redis_support.py:15,38`) so a dead Redis cannot add per-request connection stalls. No unbounded growth, no thundering-herd risk found.

**4. Frontend bundle/re-render.** `apps/web/package.json` dependencies are minimal (`maplibre-gl`, `next`, `react`, `pmtiles` — no heavy chart/utility libs). `maplibre-gl` is dynamically imported (`import("maplibre-gl")` in `apps/web/app/components/use-flood-map.ts:57,147`), not bundled eagerly. `apps/web/app/page.tsx` (393 lines, full file read) uses `useMemo` appropriately for all derived display state; no oversized state objects or obvious re-render hot loops.

**5. Ingestion adapter concurrency model.** `apps/workers/app/jobs/ingestion.py` (`run_adapter_batches`) runs adapters strictly sequentially in a single process, not concurrently. This bounds peak memory (only one adapter's fetched payload is resident at a time) at the cost of total cycle wall-clock time — a reasonable tradeoff for a memory-constrained node, though it does mean the cycle duration grows linearly as more county adapters are turned on (see finding #5 for the compounding write-side cost).

**6. Admin endpoints result-set bounds.** `apps/api/app/api/routes/admin.py:615-650` (`_db_jobs`, `_db_sources`) both apply `LIMIT 100`; no unbounded admin query found.

---

## Not independently verified (out of repo scope)

- Actual Postgres `max_connections` / memory settings and the hosting platform's (Zeabur/k3s) enforced container memory limit are not declared anywhere in this repo (no `mem_limit`/`deploy.resources` in `docker-compose.yml`, no k8s manifest found) — these are configured on the platform side and could not be verified from source alone.
