# Risk assessment query plans — 2026-09-05

Measurement pass for issue #330 (SDD 3.3: single-point query P95 < 1.5 s).

## Production baseline

Measured on the live site via `Server-Timing`, milliseconds:

| segment | Kaohsiung | Taichung | Chiayi City |
|---|---|---|---|
| db_jurisdiction | 535 | 381 | 468 |
| db_latest | 487 | 155 | 213 |
| **db_history** | **5624** | **2985** | **4650** |
| db_observed_history | 25 | 309 | 127 |
| **db_coverage** | **1515** | **1522** | **1517** |
| db_health | 59 | 51 | 63 |
| total | 8280 | 5428 | 7067 |

## Local fixture

`infra/scripts/seed_perf_fixture.py` builds a production-shaped dataset against
the compose PostGIS 16 / PostGIS 3.4 service:

- 1,342 official rainfall stations, 358 water level stations, 2,000 Civil IoT
  sewer stations (`event_type = 'water_level'`), each with one observation every
  10 minutes across the 48 hour retention window → 1,069,300 `evidence` rows
- 50,000 historical `flood_report` / `flood_potential` rows scattered nationwide
- 3,700 `official_realtime_latest` projection rows
- Stations are 62% clustered around 12 urban centres (Kaohsiung, Taichung and
  Chiayi City first) with a 6 km Gaussian spread, 38% uniform over Taiwan

Total `evidence`: 1,119,301 rows. Reproduce with:

```
docker compose up -d postgres
docker compose --profile tools run --rm migrate
python infra/scripts/seed_perf_fixture.py --reset
```

Caveat: the local node has abundant RAM and NVMe storage, so buffers are warm.
Production is a 2 GB Zeabur node where the same buffer counts turn into real
disk reads. **Buffer counts, not local wall time, are the transferable metric.**

## db_coverage — root cause found and fixed

`db_coverage` is 1515/1522/1517 ms on production and does not vary with
location. That is not a slow query, it is **the 1500 ms statement timeout**
(`query_nearby_realtime_coverage_rows(statement_timeout_ms=1500)`) plus request
overhead. The result is then thrown away:

```python
try:
    evidence_rows = _query_nearby_evidence_coverage_rows(...)
except EvidenceRepositoryUnavailable:
    if latest_rows:
        return latest_rows      # <- production always lands here
    raise
```

Every single request pays the full budget for rows that are discarded.

### Why the scan cannot finish

`EXPLAIN (ANALYZE, BUFFERS)` for `_query_nearby_evidence_coverage_rows` at
Kaohsiung, 15 km bucket, `observed_since=None` (what `_load_coverage` passes):

```
Limit  (actual time=1035.262..1035.297 rows=200)
  Buffers: shared hit=38530, temp read=52735 written=6408
  ->  Unique  (actual time=999.115..1035.131 rows=402)
        ->  Sort  (actual time=999.114..1024.642 rows=116178)
              Sort Method: external merge  Disk: 17528kB
              ->  Nested Loop  (cost=0.54..1911.11 rows=3) (actual rows=116178)
                    Join Filter: (ds.id = e.data_source_id)
                    Rows Removed by Join Filter: 1394136
                    ->  Seq Scan on data_sources ds  (actual rows=13)
                    ->  Materialize  (actual rows=116178 loops=13)
                          ->  Index Scan using idx_evidence_geom_geography on evidence e
                                (cost=0.54..1860.17 rows=12) (actual rows=116178)
                                Rows Removed by Filter: 14037
                                Buffers: shared hit=38511
Execution Time: 1042.381 ms
```

Three compounding problems, all downstream of one bad estimate:

1. **`rows=12` estimated vs `116178` actual** — a 10,000x underestimate. PostGIS
   returns a fixed default selectivity for the geography `&&` operator here; it
   is not a statistics problem (verified below).
2. Because the evidence side looks like 12 rows, the planner picks a **nested
   loop with `Materialize`** and re-scans 116,178 rows for each of 13 enabled
   `data_sources` rows → **1,394,136 join-filter evaluations** and a temp spill.
3. The `DISTINCT ON` sorts all 116,178 rows on disk (17.5 MB) to keep 402.

The scan reads **all 289 retained observations per station** in order to keep
the single newest row per station.

### Fixes evaluated and rejected

| candidate | measured result | verdict |
|---|---|---|
| Partial GiST matching the coverage predicate exactly (`source_type='official' AND event_type IN ('rainfall','water_level') AND ...`) | index-scan buffers 38,511 → 9,196 (**4.2x less I/O**), but **the planner never chooses it**: geography index costed 1,860 vs 1,873,219 for the geometry partial index | rejected — 36 MB of index maintenance on a 48 h churn table for a plan the optimiser ignores |
| `ALTER TABLE evidence ALTER COLUMN geom SET STATISTICS 1000` | estimate unchanged at `rows=12` | rejected |
| `ALTER INDEX idx_evidence_geom_geography ALTER COLUMN 1 SET STATISTICS 1000` | estimate unchanged at `rows=12` | rejected |
| `enable_nestloop=off` + `work_mem=64MB` (best achievable plan: hash join, in-memory sort) | 967 ms → 678 ms | insufficient — still >2x the target |
| Defer `ST_Distance` / freshness `CASE` until after the `DISTINCT ON` | 967 ms → 754 ms, but buffers rose to 499,927 because the freshness lateral is then evaluated per candidate row | rejected |

The floor for *any* plan that reads 116,178 rows is ~680 ms locally on a warm
cache. **No index or statistics change reaches the < 300 ms target**, because
the row count itself is the cost.

### Fix applied

The `official_realtime_latest` projection is authoritative — it holds exactly
one bounded row per station and answers the same question in **8 ms**
(402 rows, 1,025 buffers). The `evidence` scan is only a supplement for stations
the projection has not captured yet.

`query_nearby_realtime_coverage_rows` now budgets the supplement:

- projection returned rows → supplement capped at
  `_COVERAGE_EVIDENCE_SUPPLEMENT_TIMEOUT_MS = 250` ms, so an unfinishable scan is
  abandoned early instead of consuming the whole request budget
- projection returned nothing → supplement keeps the full budget, so the genuine
  fallback path is unchanged

No SQL was modified, so every SQL-string assertion in
`apps/api/tests/test_evidence_repository.py` still holds.

**Returned rows are identical** on the production-shaped fixture — verified by
running the merge with the capped budget and with an effectively unbounded one:

```
kaohsiung:   old=402 new=402 identical=True
taichung:    old=374 new=374 identical=True
chiayi_city: old=154 new=154 identical=True
```

This result is necessary rather than informative, and must not be read as
evidence on its own: `seed_perf_fixture.py` projects `official_realtime_latest`
from the same station list it uses to write `evidence`, so the projection is a
superset of the supplement by construction. **The fixture cannot disprove that
the supplement matters; it can only fail to.**

The reason the cap is low risk comes from the ingestion pipeline instead.
`REVIEWED_OFFICIAL_REALTIME_ADAPTER_EVENTS`
(`apps/workers/app/pipelines/promotion.py:26-42`) enumerates every
`(adapter_key, event_type)` pair promoted as an official realtime observation,
and it covers **all** official rainfall and water level adapters the coverage
query can select — `official.cwa.rainfall`, `official.cwa.tide_level`,
`official.wra.water_level`, and the five `official.civil_iot.*` water level
feeds. `_is_reviewed_current_candidate` gates on exactly that set
(`promotion.py:2118-2124`), and every promotion that passes it upserts the
station's newest row into `official_realtime_latest` (`promotion.py:556-558`).

So a station can only exist in `evidence` but not in the projection if its
promotion wrote the evidence row and then failed before the upsert. In that
case the projection is stale for that station, not missing it, and the merge
keeps whichever row is newer. The residual risk is therefore a station whose
projection upsert has been failing while its evidence writes succeed — which is
an ingestion defect that should surface as a pipeline alert, not something the
read path should spend 1.3 s per request compensating for.

The supplement being cancelled is logged as
`api.coverage.supplement_cancelled` with the budget it was given, so this
assumption stays falsifiable on production rather than silently baked in.

## db_history — not reproducible locally

`query_nearby_evidence` already uses the intended partial indexes from
migration 0017. At Kaohsiung, 500 m radius, on the 1.12M-row fixture:

```
->  Index Scan using idx_evidence_nearby_non_realtime_geom on evidence e
      Index Cond: (geom && st_expand(qp.geom, qp.degree_radius))
      Buffers: shared hit=102 read=3
->  Index Scan using idx_evidence_official_rainfall_geom on evidence e_1
      Buffers: shared hit=34 read=5
->  Index Scan using idx_evidence_official_water_level_geom on evidence e_2   (actual rows=289)
      Buffers: shared hit=2097 read=12
Planning Time: 14.915 ms
Execution Time: 11.885 ms
```

Local timings: **30 / 43 / 29 ms** (Kaohsiung / Taichung / Chiayi City) — already
well under the 300 ms target, against production's 5624 / 2985 / 4650 ms.

The spec's hypothesis that `e.geom && ST_Expand(...)` misses a geography-only
index **does not hold**: migration 0017 already provides plain-geometry partial
GiST indexes matching each branch predicate, and all three branches use them.

Sensitivity check: the densest point in the fixture has 6 stations and 1,735
evidence rows within 500 m, and still runs in 37 ms warm. To reach 5.6 s by row
count alone you would need ~250,000 rows within 500 m, which the station
inventory cannot produce.

The remaining explanation is **cold-cache random heap I/O**: the branches read
every retained observation for each station in radius (289 rows per station per
48 h window), and `evidence` plus its indexes is well over 2 GB (`evidence_pkey`
87 MB, `evidence_source_raw_ref_unique` 168 MB, `idx_evidence_geom_geography`
146 MB, `idx_evidence_geom` 89 MB on the fixture alone), so nothing stays
resident on the production node. A 48 h insert/delete retention cycle also
bloats the heap and GiST indexes between vacuums.

One real inefficiency is visible even locally: the water level branch spends
2,097 of its 2,109 buffers re-scanning `data_sources` (`Seq Scan on data_sources
ds_2 ... loops=289`, `Rows Removed by Join Filter: 2601`) — the same nested-loop
misestimate pattern as `db_coverage`, at 1/500th the scale.

**No change shipped for `db_history`**: there is no local measurement that would
justify one, and guessing at an index without a reproduction is how the 0017
indexes ended up not helping `db_coverage`. Next step should be
`pg_stat_statements` / `auto_explain` on the production node, or a scaled-down
restore of the production volume, to get a plan that reflects its cache and
bloat state.

## db_jurisdiction

20–39 ms locally against the seeded boundary snapshot, versus 381–535 ms on
production. Same cold-cache profile as `db_history`; not investigated further in
this pass.

## Expected production effect

| segment | before | after (expected) |
|---|---|---|
| db_coverage | 1515–1522 ms | ~260 ms (8 ms projection + 250 ms capped supplement) |

Local, on the 1.12M-row fixture:

| segment | before | after |
|---|---|---|
| db_history | 30 / 43 / 29 ms | unchanged |
| db_coverage | 943 / 889 / 398 ms | 296 / 305 / 310 ms |
| db_jurisdiction | 22 / 30 / 22 ms | unchanged |

`db_coverage` alone does not bring the Kaohsiung total (8280 ms) under the SDD
3.3 budget; `db_history` remains the largest segment and needs production-side
plan capture before it can be fixed responsibly.
