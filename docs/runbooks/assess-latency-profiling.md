# Risk Assessment Latency Profiling Runbook

`POST /v1/risk/assess` answers a cached query in about 0.2-0.3 s, but an
uncached query has been measured at 6.5-10.2 s. `docs/PROJECT_SDD.md` section
3.3 sets the targets:

- single-point risk query P95 under 1.5 s, excluding cold-start external fetches;
- cached query P95 under 500 ms.

Request-time external search is already off, so the remaining time is spent in
database reads and scoring. This runbook explains how to find out *which* read,
using the `Server-Timing` response header the endpoint now emits. It is a
measurement runbook: it does not change any behaviour, and the header carries
no user data.

## Read the header

```bash
curl -sD - -o /dev/null -X POST "$API_BASE/v1/risk/assess" \
  -H "content-type: application/json" \
  -d '{"point":{"lat":22.99974,"lng":120.22704},"radius_m":750,"time_context":"now"}' \
  | grep -i "^server-timing:"
```

PowerShell:

```powershell
$body = '{"point":{"lat":22.99974,"lng":120.22704},"radius_m":750,"time_context":"now"}'
$response = Invoke-WebRequest -Method Post -Uri "$env:API_BASE/v1/risk/assess" `
  -ContentType 'application/json' -Body $body
$response.Headers['Server-Timing']
```

An uncached response looks like this (durations in milliseconds):

```
Server-Timing: cache_get;dur=0.4, db_jurisdiction;dur=118.7, db_latest;dur=812.4,
 db_history;dur=2140.9, db_observed_history;dur=95.2, db_coverage;dur=311.0,
 db_context;dur=66.8, db_health;dur=41.3, scoring;dur=3.1, persist;dur=180.5,
 cache_set;dur=1.2, total;dur=3771.9
```

A response served from the assessment response cache is short by design:

```
Server-Timing: cache_get;dur=0.6, cache_hit;desc="true", total;dur=0.9
```

The first request after a deploy, or after the cache TTL expires, is the one
worth profiling. Repeat the same point at least three times and keep the
uncached runs; a single sample is noise.

The same numbers are logged as one JSON line per request, so the profile is
available in hosted logs without a manual curl:

```
{"event": "api.risk.assess.timings", "timestamp": "...", "cache_hit": false,
 "db_latest": 812.4, ..., "total": 3771.9}
```

## What each phase means

| Metric | Phase | Source |
| --- | --- | --- |
| `cache_get` | Response-cache read (memory or Redis) | `AssessmentService.assess` |
| `db_jurisdiction` | Resolve the query point to a jurisdiction and its reviewed source mappings | `_load_jurisdiction` |
| `db_latest` | Latest official realtime rows near the point (5 km support radius) | `_load_latest` |
| `db_history` | Retained historical evidence near the point | `_load_history` |
| `db_observed_history` | Retained positive flood observations (1 km support radius) | `_load_observed_flood_history` |
| `db_coverage` | Nearby realtime coverage rows | `_load_coverage` |
| `db_context` | Display-only recent incident context | `_load_recent_context` |
| `db_health` | Health rows for the applicable adapter keys | `_load_health` |
| `scoring` | Both scorer passes plus realtime safety and overall composition | `AssessmentService.assess` |
| `persist` | Audit write of the assessment | `PostgresAssessmentRepository.persist` |
| `cache_set` | Response-cache write; absent when the read set was incomplete and the response was not cacheable | `AssessmentService.assess` |
| `total` | Whole route handler, measured after the rate-limit check | `assess_risk` |

Notes:

- Every `db_*` phase is measured even when its read fails, so a slow *failing*
  read (a timeout, for example) shows up as a large duration next to a
  `data_status.missing` entry in the body.
- `total` is larger than the sum of the phases. The gap is the unmeasured
  remainder of the request: request validation, the on-demand recent-history
  lookup when history is stale, response building and serialisation.
- A repository that is switched off (`EVIDENCE_REPOSITORY_ENABLED=false`)
  reports no `db_*` phases at all.

## After you find a slow phase

1. **Confirm it is the phase, not the sample.** Three uncached runs against the
   same point; compare against a second point in another jurisdiction. Note
   whether the slow phase is stable or bursty.
2. **Reproduce the query on its own.** Each phase maps to one function in
   `apps/api/app/domain/evidence/repository.py`. Run its SQL directly with
   `EXPLAIN (ANALYZE, BUFFERS)` against a production-shaped database, with the
   same radius and `as_of` the request used.
3. **Classify the cause** before writing any code: missing or unusable index,
   a sequential scan over a large partition, a radius wider than the phase
   needs, a per-row function that blocks index use, or lock/connection wait.
4. **Open an issue with the evidence** — the header line, the `EXPLAIN` output
   and the classification — and fix it there. This runbook and the header only
   measure; they are not the optimisation.
5. **Re-measure the same way after the fix** and record the before/after header
   lines in the issue or PR.

If `total` is high while every phase is small, the cost is in the unmeasured
remainder: check the recent-history lookup path
(`OfficialRecentHistoryLookup`, which has its own timeout) and the response
size before touching any database read.
