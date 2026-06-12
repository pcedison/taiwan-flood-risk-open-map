# ADR-0010: Realtime Official Bridge as Local Diagnostic Tool

## Title

Realtime Official Bridge as Local Diagnostic Tool

## Status

Accepted

## Date

2026-06-11

## Context

Official CWA/WRA data currently reaches risk responses through two paths:

1. The worker official-adapter path ingests, validates, and persists official
   observations as auditable evidence rows (raw snapshot, staging, promote per
   ADR-0004). Hosted risk assessment reads this persisted evidence within a
   freshness window.
2. The API realtime bridge (`app/domain/realtime/official.py`) fetches CWA/WRA
   observations directly from upstream during a risk request.

The two paths duplicate parsing logic and upstream URL constants, and the
README has carried an open decision on whether the bridge stays. In hosted
runtimes the bridge was already effectively disabled: route-level code in
`public.py` short-circuited to "worker-persisted evidence only" statuses
before calling the bridge. That guard lived only in one route wrapper, so any
other caller of `fetch_official_realtime_bundle` could still hit upstream from
a hosted runtime, and the bridge's role remained informal.

## Decision

The API realtime bridge is a local diagnostic tool, not a production data
path.

- Hosted runtimes (`staging`, `production`, `production-beta`) must serve
  official realtime risk evidence exclusively from worker-persisted evidence.
  The bridge must not call CWA/WRA upstream from hosted runtimes unless
  `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED` is explicitly set, which is
  reserved for supervised incident diagnosis.
- The hosted guard is enforced inside `fetch_official_realtime_bundle` itself
  (`app/domain/realtime/official.py`), not in route wrappers, so every caller
  inherits it. Callers may pass `app_env` / `diagnostic_fallback_enabled`
  explicitly; otherwise the guard resolves them from the environment.
- Local, development, and test runtimes keep direct bridge fetching as the
  default so contributors can diagnose upstream behavior without a worker
  deployment.
- Convergence of the duplicated parsing logic into a shared installable
  package is deferred until the bridge retirement decision (below), rather
  than planned as its own phase. A 2026-06-12 review found that (a) only
  small parsing primitives (TWD97 conversion, WGS84 coordinate selection,
  precipitation/float coercion) and URL constants are duplicated verbatim —
  the higher-level parsing legitimately differs because the bridge builds
  typed nearest-station observations while workers build ingestion record
  mappings; and (b) a path-dependency package would break the standalone
  `pip install -e .` flows that Docker Compose run commands, the Zeabur
  single-service image, and CI all rely on. Until then, upstream schema
  changes must still be applied to both `app/domain/realtime/official.py`
  and the worker adapters; within the workers app the shared primitives live
  in `app/adapters/_helpers.py`.
- Retiring the bridge entirely is blocked on a deployed production worker
  scheduler.

## Consequences

Hosted environments have a single trusted official-data path (worker
ingestion), which keeps evidence auditable and prevents unmonitored upstream
calls from request handlers.

The guard is defense-in-depth at the domain boundary: new routes or services
calling the bridge cannot accidentally reintroduce hosted upstream fetching.

Local diagnostics remain cheap: developers still get live CWA/WRA observations
without running workers.

Parsing logic and URL constants remain duplicated between the API bridge and
worker adapters until the bridge is retired; changes to upstream schemas must
be applied in both places until then. The duplication is bounded to the
bridge's lifetime, which is why a shared package was judged not worth its
packaging and deployment cost.
