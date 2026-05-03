# Production Readiness and On-Call Drill

## Purpose

This runbook turns the Zeabur deployment and monitoring notes into an
acceptance checklist for production beta readiness. It is a drill guide, not a
claim that production is complete.

## Readiness State

Current state: not production complete.

The repository has deploy, monitoring, freshness, queue visibility, and
backup/restore runbooks. A launch decision still requires named owners,
environment evidence, and an on-call drill record for the target Zeabur
project.

## Secrets Inventory

Secrets must live only in Zeabur environment variables or the selected secret
manager. Do not commit real secrets, fake secrets, copied production tokens, or
example values that resemble tokens.

| Variable | Owner | Required for production beta | Storage | Notes |
|---|---|---:|---|---|
| `ADMIN_BEARER_TOKEN` | API/operator owner | yes | Zeabur secret env | Required before admin endpoints or freshness checks are used. |
| `DATABASE_URL` | platform owner | yes | Zeabur secret env | Must point to the production-beta database only. |
| `REDIS_URL` | platform owner | yes | Zeabur secret env | Must point to the production-beta Redis only. |
| `MINIO_ROOT_USER` | platform owner | yes when MinIO is used | Zeabur secret env | Local defaults are not acceptable for hosted environments. |
| `MINIO_ROOT_PASSWORD` | platform owner | yes when MinIO is used | Zeabur secret env | Rotate before beta if ever shared outside Zeabur. |
| `CWA_API_AUTHORIZATION` | source owner | yes when realtime official or worker CWA live path is enabled | Zeabur secret env | Keep blank in `.env.example`; review credential scope and rate limits. |
| `WRA_API_TOKEN` | source owner | only when upstream requires it | Zeabur secret env | Optional; never write token into stored source URLs. |
| `GRAFANA_ADMIN_PASSWORD` | observability owner | yes for hosted Grafana | Zeabur secret env | Local-only placeholder must not be reused. |
| `TGOS_API_KEY` | source owner | no, future only | secret manager | Do not set until runtime reads it. |

Non-secret flags still have owners because they control production behavior.

| Variable | Owner | Production beta default | Gate |
|---|---|---|---|
| `APP_ENV` | platform owner | `production-beta` | Set only in the production-beta Zeabur project. |
| `REALTIME_OFFICIAL_ENABLED` | source owner | explicit launch decision | Requires CWA/WRA credential and egress review. |
| `SOURCE_CWA_API_ENABLED` | source owner | `false` until accepted | Requires `SOURCE_CWA_ENABLED` decision, credential review, cadence, and egress proof. |
| `SOURCE_WRA_API_ENABLED` | source owner | `false` until accepted | Requires source owner, cadence, and egress proof. |
| `SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED` | source owner | `false` until accepted | Requires upstream URL/license and cadence review. |
| `SOURCE_NEWS_ENABLED` | governance owner | `false` until accepted | Requires L2 allowlist and citation policy. |
| `SOURCE_FORUM_ENABLED` | governance owner | `false` | Requires Phase 4 legal/source review. |
| `SOURCE_PTT_ENABLED` | governance owner | `false` | Requires `SOURCE_FORUM_ENABLED=true` and terms acknowledgement. |
| `SOURCE_DCARD_ENABLED` | governance owner | `false` | Requires `SOURCE_FORUM_ENABLED=true` and terms acknowledgement. |
| `SOURCE_TERMS_REVIEW_ACK` | governance owner | `false` until review record exists | Required for terms-reviewed adapters such as GDELT backfill and future forums. |
| `USER_REPORTS_ENABLED` | privacy/governance owner | `false` | Keep disabled until moderation, retention, abuse, and deletion gates are accepted. |

## Zeabur Environment Ownership

Each Zeabur project must have one named owner for environment changes. The
owner records the change reason, deployment SHA, and rollback target before
changing production-beta variables.

Environment changes require:

1. Target project confirmed as staging or production beta.
2. Variable names match `.env.example` and the deployment runbook.
3. Secrets entered through Zeabur UI or secret manager only.
4. No copied values from `.env.example` for real credentials.
5. Source gates reviewed with source/governance owners.
6. Rollback target and previous env values captured in private ops notes.

## SLO and SLI Targets

Production beta SLOs are acceptance targets. They become enforceable only after
hosted monitoring and alert routing are wired.

| Surface | SLI | Beta target | Dashboard or alert |
|---|---|---:|---|
| API availability | `up{job="flood-risk-api"}` or `flood_risk_api_ready` | 99.5% over 7 days | `API Metrics Scrape`, `API Readiness`, `FloodRiskApiReadyDown` |
| Source freshness | enabled sources with `flood_risk_source_freshness_stale == 0` | 95% of checks over 7 days | `Stale Sources`, `Source Freshness Age`, `FloodRiskSourceFreshnessStale` |
| Worker heartbeat | heartbeat age under 300 seconds | 99% of checks over 7 days | `Worker Heartbeat Age`, `FloodRiskWorkerHeartbeatMissing` |
| Scheduler heartbeat | heartbeat age under 600 seconds and one scheduler replica | 99% of checks over 7 days | `Scheduler Heartbeat Age`, `FloodRiskSchedulerHeartbeatMissing` |
| Queue visibility | queue exporter available | 99% of checks over 7 days | `Queue Metrics Available`, `FloodRiskRuntimeQueueMetricsUnavailable` |
| Final-failed jobs | final-failed rows triaged | triage started within 1 business hour | `Queue Final-Failed Rows`, `FloodRiskRuntimeQueueFinalFailedRowsPresent` |
| Backup restore | latest backup can be inspected and restored to scratch | one successful drill per release candidate | `backup-restore-drill.ps1` and drill notes |

## Alert Routing

Before production beta, every critical alert must route to a named primary and
backup owner. If pager tooling is not available, use the team incident channel
and record the manual escalation path.

| Alert family | Severity | Primary owner | Backup owner | First response |
|---|---|---|---|---|
| API readiness | critical | platform owner | backend owner | Check `/health`, `/ready`, Zeabur deployment, DB, Redis. |
| Source freshness | critical/warning | source owner | worker owner | Check admin source status, upstream, credentials, worker logs. |
| Worker heartbeat/last run | critical/warning | worker owner | platform owner | Check worker process, queue, leases, textfile collector. |
| Scheduler heartbeat | warning | platform owner | worker owner | Confirm exactly one scheduler and recent heartbeat file. |
| Runtime queue rows | warning | worker owner | backend owner | Inspect final-failed rows; do not bulk requeue without audit. |
| Backup/restore drill | warning/manual | platform owner | database owner | Inspect backup archive and scratch restore evidence. |

## On-Call Drill

Run this drill for staging first. Repeat for production beta before launch.

1. Confirm the deployed commit SHA and Zeabur project.
2. Run the safe readiness validator:

   ```powershell
   python infra/scripts/validate_monitoring_assets.py
   ```

3. Run PowerShell parser/help checks:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops-source-freshness-check.ps1 -DryRun
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup-restore-drill.ps1
   ```

4. Confirm `.env.example` has blank real-secret values and production gates are
   disabled by default.
5. Confirm Zeabur environment variables are owned, reviewed, and not copied
   from local placeholders.
6. Confirm monitoring dashboard panels map to each SLO in this runbook.
7. Trigger or simulate each alert family and confirm routing reaches the owner.
8. Run runtime smoke against the deployed API and web domain.
9. Run source freshness check against the deployed API when admin token exists.
10. Run backup archive inspection and scratch restore if a scratch database is
    available.
11. Practice rollback order: stop scheduler, drain worker, roll back API/web,
    restart worker, restart scheduler last.
12. Record launch blockers, skipped checks, owner handoff, and next action.

## Rollback Drill

Application rollback:

1. Freeze deploys and record the bad deployment SHA.
2. Pause scheduler or scale it to zero replicas.
3. Let active worker jobs finish, or scale worker down if schema/source state is
   unsafe.
4. Roll back API and web to the previous known-good Zeabur deployment.
5. Roll back worker only after API/schema compatibility is confirmed.
6. Restart scheduler last with exactly one replica.
7. Run `/health`, `/ready`, runtime smoke, and source freshness checks.

Data rollback:

1. Prefer forward fixes for bad derived data.
2. Keep raw snapshots immutable.
3. Restore only to a replacement or scratch database during a drill.
4. Point services to restored data only after owner approval and smoke checks.

## Source Kill Switch

Use source kill switches before taking the API down when a source is stale,
misbehaving, or legally blocked.

| Source family | Kill switch |
|---|---|
| CWA worker live ingestion | `SOURCE_CWA_API_ENABLED=false` and optionally `SOURCE_CWA_ENABLED=false` |
| WRA worker live ingestion | `SOURCE_WRA_API_ENABLED=false` and optionally `SOURCE_WRA_ENABLED=false` |
| Flood potential GeoJSON | `SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED=false` and optionally `SOURCE_FLOOD_POTENTIAL_ENABLED=false` |
| News/public web | `SOURCE_NEWS_ENABLED=false` |
| Forums | `SOURCE_FORUM_ENABLED=false`, `SOURCE_PTT_ENABLED=false`, `SOURCE_DCARD_ENABLED=false` |
| Sample data | `SOURCE_SAMPLE_DATA_ENABLED=false` |

After flipping a kill switch, confirm the source is disabled or no longer
scheduled, then record the reason and recovery owner.

## Public Report Disable

`USER_REPORTS_ENABLED` must remain `false` until legal/privacy, moderation,
retention, deletion, and abuse-prevention gates are accepted. If public report
intake is accidentally enabled:

1. Set `USER_REPORTS_ENABLED=false`.
2. Restart affected services if runtime config is not hot-reloaded.
3. Confirm public report routes are unavailable or return disabled responses.
4. Preserve any received records for privacy review; do not manually delete
   before the owner decides the retention/deletion path.

## GDELT and Forum Gates

GDELT backfill and future forum ingestion are not production beta defaults.
Before enabling either:

1. Confirm source terms and robots review are recorded.
2. Set `SOURCE_TERMS_REVIEW_ACK=true` only after review approval.
3. Keep `SOURCE_FORUM_ENABLED=false` until Phase 4 forum governance is accepted.
4. For PTT/Dcard, require both family gate and source-level gate.
5. Confirm no full-text redistribution beyond approved citation/snippet policy.
6. Add per-source freshness thresholds and alert routing before launch.

## Launch Blockers

Do not launch production beta until these are closed or explicitly accepted by
the accountable owner:

- Hosted monitoring scrape targets, TLS/auth, persistence, retention, and alert
  routing are configured.
- Critical alerts have primary and backup owners.
- Zeabur production-beta env vars are reviewed against this runbook.
- Real credential review is complete for every enabled live source.
- WRA/CWA/flood-potential production egress and upstream cadence are verified.
- Worker and scheduler are deployed with heartbeat metrics and scheduler
  singleton evidence.
- Replay policy, poison-job quarantine/escalation, and final-failed row
  ownership are accepted.
- Backup creation, archive inspection, and scratch restore drill are recorded.
- Runtime smoke, freshness check, and rollback drill have production-beta or
  staging evidence.
- Public reports remain disabled unless the privacy/governance owner accepts
  all intake gates.
- Forum/GDELT gates remain disabled unless governance approval and alerting are
  recorded.

## Owner Handoff

Before launch decision, record:

- Deployment SHA and Zeabur project.
- Platform owner for env and rollback.
- Source owner for each enabled source.
- Observability owner for dashboards and routing.
- Worker owner for queue, replay, and scheduler.
- Privacy/governance owner for public reports and forum/GDELT gates.
- Known launch blockers and accepted risks.
- Next drill date and backup restore evidence location.
