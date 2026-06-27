# Optimization Focus Worklist

Reviewed: 2026-06-27

This document captures the current high-value optimization areas for Taiwan
Flood Risk Open Map after the repository orientation pass. It is a working
review note, not a replacement for `docs/PROJECT_SDD.md`, ADRs, or production
runbooks. Any change to source-of-truth semantics, scoring, API contracts,
privacy policy, or deployment topology still needs the appropriate SDD/ADR
update.

## 1. Production Realtime Source Of Truth

Hosted risk assessment should continue converging on worker-persisted evidence
as the trusted official realtime path. The API realtime bridge should remain a
local diagnostic tool unless an explicit, supervised production exception is
accepted.

Current backbone status:

- Task 8 adds source-level freshness states: `fresh`, `degraded`, `stale`, and
  `failed`.
- `/admin/v1/sources` now carries source diagnostics: latest observed/fetched/
  ingested timestamps, lag seconds, latest-row count, upstream adapter/job
  status, `is_enabled`, open gates, and freshness state.
- Realtime official/local sources start with 10-minute fresh, 30-minute
  degraded, and 60-minute stale/failed windows. NCDR CAP is event-window based;
  flood-potential remains static/slow cadence and is not a realtime failure.
- Disabled sources are visible as disabled/stale diagnostics rather than failed
  upstream fetches.

Follow-up work:

- Keep CWA rainfall and WRA water-level production reads tied to promoted
  Postgres evidence with freshness metadata.
- Add hosted collection for `/admin/v1/sources` freshness diagnostics and wire
  alert ownership for stale/failed official realtime sources.
- Add CAP `effective`/`expires` persistence to diagnostics when NCDR production
  ingestion is promoted.
- Add or strengthen schema fixture checks for upstream CWA/WRA payload changes.
- Keep any diagnostic bridge fallback clearly labeled in public responses and
  operator logs.
- Track remaining duplication between the API bridge and worker parsers until
  the bridge can be retired.

## 2. Production Evidence Completion

Local and fixture-backed paths are strong, but production beta still depends on
real launch evidence for official and public sources.

Follow-up work:

- Capture source approval, credential, license, cadence, egress, alert routing,
  and rollback evidence for CWA, WRA, flood-potential, Civil IoT, and GDELT.
- Keep live source gates closed until the matching evidence is accepted.
- Store private production evidence outside the public repository when it
  contains credentials, endpoints, or operational details.
- Make release notes distinguish local green checks from production-complete
  checks.

## 3. Scheduler And Queue Operations

The runtime queue, requeue, replay audit, and quarantine primitives are useful
groundwork, but they are not yet a complete production DLQ and incident model.

Follow-up work:

- Define poison-job handling, retry exhaustion policy, alert owner, and replay
  approval steps.
- Deploy a singleton scheduler model for ingestion, profile refresh, query heat,
  tile refresh, and retention.
- Add operator-facing runbook examples for final-failed rows, audited requeue,
  and quarantine decisions.
- Ensure worker and scheduler heartbeats are visible in hosted monitoring.

## 4. Risk Calibration And Score Versioning

`risk-v0.1.0` is explainable and testable, but production trust needs replayed
calibration against historical events and known non-events.

Follow-up work:

- Build a calibration replay set from historical official disaster points,
  flood-potential intersections, public news, and selected no-flood controls.
- Record false-positive and false-negative reviews per score version.
- Keep threshold changes tied to a scoring manifest and acceptance evidence.
- Preserve the rule that query heat never changes realtime or historical risk.

## 5. Performance And Cost Controls

Public beta should prefer fast, bounded read paths before expensive exact-radius
or on-demand enrichment work.

Follow-up work:

- Treat precomputed township, village, and grid/H3 profiles as the preferred
  first response path where coverage exists.
- Use exact-radius evidence queries and on-demand public news as controlled
  enrichment paths, not the default hot path.
- Load-test query heat, tile cache, evidence retention, and profile refresh.
- Verify cache TTLs do not hide transient realtime gaps or stale-source states.

## 6. Public Trust And Risk Communication UX

The UI should make data gaps visible without implying that missing data means
low risk.

Follow-up work:

- Strengthen copy and visual states for stale, disabled, degraded, and missing
  realtime sources.
- Keep flood-potential language framed as planning/reference context, not an
  active disaster warning.
- Surface basemap and attribution readiness clearly before public launch.
- Make evidence freshness and source limitations easy to scan on mobile.

## 7. Privacy And Abuse Gates

Public interaction surfaces need production-grade abuse and privacy controls
before wider launch.

Follow-up work:

- Keep Redis-backed public rate limits for geocode and risk assessment enabled
  in hosted environments.
- Complete public report moderation, retention, deletion, EXIF/metadata
  handling, and challenge flow before enabling reports publicly.
- Keep public discussion/forum/social ingestion disabled until legal, terms,
  privacy, and moderation gates are accepted.
- Ensure client signals used for abuse prevention are hashed, salted, scoped,
  and TTL-bound.

## 8. Deployment Boundary Split

The Zeabur single-service container is practical for preview and early hosted
deployment, but production beta will benefit from clearer failure boundaries.

Follow-up work:

- Plan a staged split of Web, API, worker, scheduler, database, Redis, object
  storage, and monitoring responsibilities.
- Keep single-service mode documented as a constrained deployment path with
  explicit ingestion scheduler controls.
- Verify TLS/auth, persistent monitoring storage, backup/restore, and source
  freshness checks per hosted environment.
- Avoid describing local Docker Compose or single-service smoke as full
  production readiness.

## Near-Term Discussion Topic

The next likely decision area is production operation of realtime source
freshness: who owns stale/failed alerts, how CAP event windows should be
persisted in the diagnostics model, and which live-source smoke evidence is
required before opening each default-closed gate.
