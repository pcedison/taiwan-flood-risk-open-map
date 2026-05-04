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

## Evidence Validator Modes

The checked-in evidence file
`docs/runbooks/production-readiness-evidence.example.yaml` is a safe template
for docs and CI. It intentionally contains placeholders and keeps
`production_complete: false`; it is not a production launch record.

Validate the template/default mode with:

```powershell
python infra/scripts/validate_production_readiness_evidence.py
python infra/scripts/validate_basemap_cdn_evidence.py
```

Private production evidence can use the same schema in an ops-controlled
location. Do not commit real secrets, secret previews, private pager routes, or
private drill artifacts to this repository. Production acceptance requires:

- `production_complete: true` and `readiness_state: production-complete`.
- Real Zeabur project name and a reviewed 7-40 character deployment commit SHA.
- Named, non-template owners and alert routes.
- Secret entries with `value_status: stored-in-secret-manager` and no `value`
  or `value_preview`.
- Production source/report gates with `status: accepted` or `status: reviewed`.
- `drill_preflight` references for runtime smoke, Playwright, alert test,
  rollback target/evidence, backup restore evidence, and secret manager refs.
- On-call, rollback, and backup restore drills with `result: passed` or
  `result: succeeded`, plus at least one production evidence reference outside
  the runbook instructions.
- `pending_production_gaps: []`.

Run production-complete acceptance with:

```powershell
python infra/scripts/validate_production_readiness_evidence.py --production-complete <private-evidence.yaml>
python infra/scripts/validate_basemap_cdn_evidence.py --production-complete <private-basemap-evidence.yaml>
```

Public reports have an additional launch evidence validator because external
intake needs bot-defense, moderation, privacy, deletion, and abuse-measurement
proof before the fail-closed gate can be opened:

```powershell
python infra/scripts/validate_public_reports_launch_evidence.py
python infra/scripts/validate_public_reports_launch_evidence.py --production-complete <private-public-reports-evidence.yaml>
```

Basemap CDN evidence is intentionally separate from the broader readiness
record because it must prove CDN behavior, not just environment ownership. The
basemap record must include the real operator-provided style URL and PMTiles
URL, 206 Range/`Content-Range` proof, CORS and cache-control headers, browser
network log and screenshot references, provider/license/cadence owners, and a
production request capture showing no calls to `tile.openstreetmap.org`.

## Drill Preflight Evidence

Use the no-secret helper to create a JSON `drill_preflight` skeleton. It reads
the current git commit, records the target environment and operator, and emits
only evidence references. It does not read Zeabur env values or print secret
values.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\production-readiness-drill.ps1 `
  -TargetEnv production-beta `
  -Operator "operator@example.com" `
  -RuntimeSmokeRef "private-ops://drills/runtime-smoke/2026-05-04" `
  -PlaywrightRef "private-ops://drills/playwright/2026-05-04" `
  -AlertTestRef "private-ops://drills/alert-test/2026-05-04" `
  -RollbackTarget "known-good-zeabur-deployment-or-commit" `
  -RollbackRef "private-ops://drills/rollback/2026-05-04" `
  -BackupRestoreRef "private-ops://drills/backup-restore/2026-05-04" `
  -AlertRouteRef "API readiness=pagerduty:flood-risk-api" `
  -SecretManagerRef "DATABASE_URL=zeabur://flood-risk-production-beta/env/DATABASE_URL" `
  -OutputPath ".\tmp\production-readiness-drill-preflight.json"
```

For secrets, pass only secret manager references such as `zeabur://`,
`vault://`, `op://`, or `private-ops://`. Do not pass database URLs, Redis URLs,
bearer tokens, provider tokens, screenshots that reveal values, or copied
Zeabur secret contents.

Copy the generated JSON object under `drill_preflight` in the private evidence
file. Attach results as references:

- Runtime smoke: store the `scripts/runtime-smoke.ps1` transcript or CI job URL
  in private ops storage, then set `drill_preflight.runtime_smoke_ref`.
- Playwright: store the report URL, artifact ID, or screenshot bundle ref, then
  set `drill_preflight.playwright_ref`.
- Alert test: store the pager route test, incident-channel message, or
  alertmanager notification evidence, then set `alert_test_ref` and every
  `alert_route_refs` family.
- Rollback: record the known-good Zeabur deployment or commit in
  `rollback.target` and the drill transcript in `rollback.evidence_ref`.
- Backup restore: store the backup archive inspection, scratch restore, and
  post-restore smoke result ref in `backup_restore_ref`.

When `production_complete: true`, the validator requires these references to
point outside the checked-in runbooks and rejects secret-like values in
`secret_manager_refs`.

## Secrets Inventory

Secrets must live only in Zeabur environment variables or the selected secret
manager. Do not commit real secrets, fake secrets, copied production tokens, or
example values that resemble tokens.

| Variable | Owner | Required for production beta | Storage | Notes |
|---|---|---:|---|---|
| `ADMIN_BEARER_TOKEN` | API/operator owner | yes | Zeabur secret env | Required before admin endpoints or freshness checks are used. |
| `ABUSE_HASH_SALT` | privacy/governance owner | yes before public reports launch | Zeabur secret env | Hashes public report abuse/rate-limit client signals; keep blank in `.env.example`. |
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
| `SOURCE_PTT_ENABLED` | governance owner | `false` | Requires `SOURCE_FORUM_ENABLED=true`, terms acknowledgement, and candidate approval ack. |
| `SOURCE_DCARD_ENABLED` | governance owner | `false` | Requires `SOURCE_FORUM_ENABLED=true`, terms acknowledgement, and candidate approval ack. |
| `SOURCE_PTT_CANDIDATE_APPROVAL_ACK` | governance owner | `false` | Permits only no-network synthetic PTT candidate fixture testing. |
| `SOURCE_DCARD_CANDIDATE_APPROVAL_ACK` | governance owner | `false` | Permits only no-network synthetic Dcard candidate fixture testing. |
| `SOURCE_TERMS_REVIEW_ACK` | governance owner | `false` until review record exists | Required for terms-reviewed adapters such as GDELT backfill and future forums. |
| `GDELT_SOURCE_ENABLED` | governance owner | `false` until accepted | Required before any GDELT rehearsal or production-candidate egress. |
| `GDELT_BACKFILL_ENABLED` | governance owner | `false` until accepted | Separate operator gate for bounded backfill windows. |
| `GDELT_PRODUCTION_INGESTION_ENABLED` | governance owner | `false` until accepted | Required for the persistence/promotion production-candidate command. |
| `GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH` | governance owner | private evidence path | Points to non-committed source/legal/egress approval evidence. |
| `GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK` | governance owner | `false` | Required human acknowledgement for production-candidate runs; it is valid only together with a concrete external evidence path/ref. |
| `GDELT_PRODUCTION_QUERIES` | governance owner | reviewed bounded query set | Do not reuse rehearsal queries without approval. |
| `GDELT_PRODUCTION_MAX_RECORDS_PER_QUERY` | governance owner | reviewed numeric policy | Caps GDELT DOC maxrecords per query. |
| `GDELT_PRODUCTION_CADENCE_SECONDS` | governance owner | reviewed numeric policy | Minimum delay between GDELT requests. |
| `USER_REPORTS_ENABLED` | privacy/governance owner | `false` | Keep disabled until moderation, retention, abuse, and deletion gates are accepted. |
| `USER_REPORTS_RATE_LIMIT_ENABLED` | privacy/governance owner | `true` when intake is enabled | Public report abuse guard; keep enabled for any reviewed launch. |
| `USER_REPORTS_RATE_LIMIT_BACKEND` | privacy/governance owner | `redis` | Shared backend required for multi-replica launch; memory is local/test-only. |
| `USER_REPORTS_RATE_LIMIT_MAX_REQUESTS` | privacy/governance owner | reviewed numeric policy | Tune with abuse-prevention review. |
| `USER_REPORTS_RATE_LIMIT_WINDOW_SECONDS` | privacy/governance owner | reviewed numeric policy | Tune with abuse-prevention review. |
| `USER_REPORTS_RATE_LIMIT_CLIENT_HEADER` | privacy/governance owner | blank unless trusted edge proxy overwrites it | Avoid spoofable client signals. |
| `USER_REPORTS_CHALLENGE_REQUIRED` | privacy/governance owner | `true` before public reports launch | Fails closed before storage when challenge tokens are missing or invalid. |
| `USER_REPORTS_CHALLENGE_PROVIDER` | privacy/governance owner | `turnstile` or reviewed equivalent | `static` is sandbox/test-only. |
| `USER_REPORTS_CHALLENGE_SECRET_KEY` | privacy/governance owner | yes when challenge is required | Store only in secret env; do not commit provider keys. |
| `USER_REPORTS_CHALLENGE_STATIC_TOKEN` | privacy/governance owner | blank in production | Sandbox/test-only; do not use for public launch. |
| `USER_REPORTS_CHALLENGE_VERIFY_URL` | privacy/governance owner | provider default unless reviewed | Override only for approved provider endpoint changes. |
| `USER_REPORTS_CHALLENGE_TIMEOUT_SECONDS` | privacy/governance owner | reviewed numeric policy | Keep low enough to fail closed without exhausting API workers. |
| `USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS` | privacy/governance owner | `false` | Explicit staging/preview-only bypass; production-like public intake otherwise fails closed without a configured challenge provider. |
| `NEXT_PUBLIC_BASEMAP_STYLE_URL` | web owner | reviewed URL or blank | Open basemap style URL; record provider/license/attribution evidence before hosted use. |
| `NEXT_PUBLIC_BASEMAP_KIND` | web owner | reviewed kind or blank | Must match frontend implementation, for example style, pmtiles, or raster. |
| `NEXT_PUBLIC_BASEMAP_PMTILES_URL` | web owner | reviewed URL or blank | PMTiles source/package must have license, attribution, and update-cadence evidence. |
| `NEXT_PUBLIC_BASEMAP_RASTER_TILES` | web owner | reviewed tile template or blank | Raster tile provider terms, attribution, and rate limits must be accepted before hosted use. |
| `NEXT_PUBLIC_BASEMAP_ATTRIBUTION` | web owner | reviewed attribution or blank | Must match the selected open basemap provider requirements. |

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
   python infra/scripts/validate_production_readiness_evidence.py
   python infra/scripts/validate_basemap_cdn_evidence.py
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
12. Copy the schema shape from
    `docs/runbooks/production-readiness-evidence.example.yaml`, replace the
    placeholders with private evidence references, and validate the record with
    `python infra/scripts/validate_production_readiness_evidence.py --production-complete <path>`.
13. Copy the schema shape from
    `docs/runbooks/basemap-cdn-evidence.example.yaml`, replace the demo URLs and
    runbook refs with real CDN/browser evidence, and validate it with
    `python infra/scripts/validate_basemap_cdn_evidence.py --production-complete <path>`.
14. Record launch blockers, skipped checks, owner handoff, and next action.

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
| Forums | `SOURCE_FORUM_ENABLED=false`, `SOURCE_PTT_ENABLED=false`, `SOURCE_DCARD_ENABLED=false`, `SOURCE_PTT_CANDIDATE_APPROVAL_ACK=false`, `SOURCE_DCARD_CANDIDATE_APPROVAL_ACK=false` |
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

Hosted or production-like environments fail closed when `USER_REPORTS_ENABLED`
is true but no bot-defense provider secret is configured. `preview` and
`staging` may use `USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS=true` only as a
recorded non-production exception; production environments must configure the
real challenge provider instead.

Before any public launch, also validate a private
`public-reports-launch-evidence` record with `--production-complete`. That
record must prove real owners, challenge secret storage, moderation SLA,
delete/redaction and takedown procedures, media/EXIF policy or disabled-media
confirmation, audit review, dashboards, alerts, and launch owner approval.

## GDELT and Forum Gates

GDELT backfill and future forum ingestion are not production beta defaults.
Before enabling either:

1. Confirm source terms and robots review are recorded.
2. Set `SOURCE_TERMS_REVIEW_ACK=true` only after review approval.
3. Keep `SOURCE_FORUM_ENABLED=false` until Phase 4 forum governance is accepted.
4. For PTT/Dcard, require the family gate, source-level gate, terms ack, and candidate approval ack before fixture contract testing.
5. Confirm no full-text redistribution beyond approved citation/snippet policy.
6. Add per-source freshness thresholds and alert routing before launch.

For GDELT production-candidate fetch, persist, or promote flows,
`GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH` must point to concrete external
source/legal/egress approval evidence. `GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK`
must also be true as a second human confirmation. Neither gate can release the
flow by itself.

### GDELT live acceptance evidence

The worker also exposes a no-network GDELT live acceptance preflight:

```powershell
cd apps/workers
python -m app.main --validate-gdelt-live-acceptance ..\..\docs\data-sources\news\gdelt-live-acceptance.example.yaml
```

The checked-in example is `not-production-complete`; a valid parse returns a
JSON `skipped` payload with `network_allowed=false`. Private production evidence
must set `production_complete: true` and `readiness_state:
production-complete`, then replace every placeholder with real legal/source
approval, source owner, egress owner, rate-limit policy, hosted cadence,
alert owner/route, production persistence promotion evidence, rollback or
kill-switch evidence, and the latest dry-run or production-candidate run
evidence.

Do not describe GDELT as true live ingestion complete unless this private
evidence exists and the preflight returns `status: "succeeded"`. The preflight
does not fetch GDELT, does not schedule live ingestion, and does not replace the
source/legal approval record.

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
- Basemap CDN evidence is production-complete, including 206 Range, CORS,
  cache-control, real style/PMTiles URLs, screenshots, browser network log, and
  proof that no public OSM community tile endpoint is used.
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
