# Monitoring Freshness Alerts Runbook

## Purpose

This runbook defines the first operational freshness alert for Flood Risk data
sources. It is intentionally lightweight: it can be run manually, from CI, or
from a scheduled monitor without changing application code.

## Scope

Covered:

- Source freshness checks through `GET /admin/v1/sources`.
- Local-direct 22-county coverage status through
  `GET /admin/v1/local-source-coverage`.
- Prometheus rule coverage for freshness, API readiness, and runtime heartbeats.
- Grafana dashboard coverage for readiness, freshness, heartbeat, and worker
  last-run status plus runtime queue final-failed row visibility.
- Dry-run and fixture-based verification.
- Alert thresholds and triage steps.

Not covered:

- Production pager wiring.
- Hosted TLS/auth/storage setup.
- Production scheduler or cron deployment.
- Adapter retry/DLQ governance beyond current queue `failed`/`final_failed_at`
  visibility, queue metrics export, and row-level list/requeue commands.
- Real credential review or WRA/CWA production egress verification.

## Current Phase Status

Completed for local validation:

- `scripts/ops-source-freshness-check.ps1` can call `GET /admin/v1/sources`
  or run in dry-run/fixture mode.
- Admin API exposes `GET /admin/v1/local-source-coverage` for the conservative
  22-county local-direct source catalog, including ready adapters, candidate
  systems, metadata-only sources, not-found counties, and application-required
  sources. The response also includes `next_action_code`, `upgrade_priority`,
  and `blocking_reason` so operators can separate "run the adapter" from
  "request authorization", "verify an official API contract", and "continue
  discovery".
- The script can write Prometheus textfile metrics with `-MetricsPath`.
- Prometheus alert rules and the Grafana dashboard can read freshness,
  API-readiness, worker heartbeat, scheduler heartbeat, and last-run status
  metrics.
- Worker and scheduler runtimes can emit heartbeat textfiles when explicitly
  configured.
- Operators can export runtime queue metrics for queued/running counts,
  expired leases, final-failed row count, and oldest final-failed age.

Partially complete:

- Freshness export is a script and metric contract, not a deployed production
  monitor. A scheduler/cron owner still has to run it at the target cadence.
- Queue failure visibility is limited to heartbeat/last-run metrics,
  operator-exported queue metrics, and the `worker_runtime_jobs` terminal
  `failed`/`final_failed_at` state plus row-level list/requeue commands. This
  is final-failed row visibility, not a complete DLQ. Replay audit and
  poison-quarantine tables exist, but there is no quarantine/escalation policy
  or accepted production replay procedure yet.
- Official worker freshness is partial: demo/fixture-backed adapter runs are
  safe by default, and CWA rainfall, WRA water-level, and flood-potential
  GeoJSON can run through explicit live-client gates. The API realtime official
  bridge may fetch CWA/WRA data, but that does not create persisted worker
  ingestion freshness evidence.
- Heartbeat alerts prove that textfile metrics are present and recent; they do
  not prove real-source credentials, idempotent job handling, or production
  singleton scheduler behavior.
- Freshness alerts should still distinguish deployable gated live paths from
  fixture/demo validation and production beta readiness.

Pending for production:

- Real source credentials, credential review, deployed source clients,
  WRA/CWA/flood-potential production egress verification, and per-source
  freshness thresholds.
- Alert routing, TLS/auth, durable monitoring storage, retention, and incident
  ownership.
- Hosted scheduler/cadence deployment for freshness export plus
  worker/scheduler heartbeat emission.
- Queue replay operating policy around the audit/quarantine primitives, alert
  routing, and abuse-governance alerts for future public reports/public
  discussion ingestion.

## Placeholder Boundary

`infra/monitoring` now contains Prometheus config, alert rules, Grafana
provisioning, and a local Docker Compose `monitoring` profile. The profile is a
deployment wiring harness for local validation. It is not a full production
monitoring stack: hosted environments still need environment-specific service
DNS, credentials, TLS, persistence, scheduler, and alert routing.

Worker and scheduler heartbeat alerts read Prometheus textfile-compatible
metrics. Set `WORKER_METRICS_TEXTFILE_PATH` or `SCHEDULER_METRICS_TEXTFILE_PATH`
on the worker process to emit these files for a node exporter textfile
collector.

Dashboard and scrape deployment details live in:

```text
docs/runbooks/monitoring-dashboard.md
```

Local Compose validation:

```powershell
docker compose --profile monitoring config
docker compose --profile monitoring up prometheus grafana node-exporter
```

## Queue Replay Boundary

Current queue monitoring can detect worker last-run failures, export queue
counts, and inspect exhausted final-failed rows, but it does not expose a
complete DLQ or replay alert workflow. Use this CLI during triage:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --list-runtime-dead-letter-jobs --dead-letter-limit 20"
```

To print the queue visibility summary as JSON:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --export-runtime-queue-metrics --runtime-queue-metrics-format json"
```

To write Prometheus textfile metrics:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --export-runtime-queue-metrics --runtime-queue-metrics-path /var/lib/node_exporter/textfile_collector/flood-risk-runtime-queue.prom"
```

To requeue one failed row with audit context:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --requeue-runtime-job <job-id> --requeue-requested-by <operator> --requeue-reason '<why-safe-to-retry>'"
```

Do not treat the row-level list/requeue commands or metrics summary as a
complete DLQ or replay operating model. Requeue now writes replay audit records
and refuses active poison-quarantined jobs, but replay still needs payload
safety review, source idempotency, backoff, quarantine escalation, alert
routing, alert labels, and incident ownership. There is no purge or auto replay
in this phase.

## Alert Policy

Start with these thresholds:

| Source family | Warning | Critical | Notes |
|---|---:|---:|---|
| Official realtime sources | 30 minutes stale | 60 minutes stale | CWA/WRA-style observations should move frequently. |
| Official static or slow cadence sources | 24 hours stale | 72 hours stale | Use per-source cadence when `update_frequency` is slow. |
| Reviewed L2 public-web sources | 6 hours stale | 24 hours stale | Only for enabled, reviewed sources. |
| Disabled or phase-delayed sources | no alert | no alert | `disabled` sources are expected to be quiet. |

For the current script, use `-MaxAgeMinutes 60` for a conservative smoke alert.
Move to per-source thresholds when a dashboard or monitor config exists.

These alert thresholds support the production beta SLO surfaces in
[production-readiness.md](production-readiness.md):

| SLO surface | Alert signal | Response expectation |
|---|---|---|
| API availability/readiness | `FloodRiskApiReadyDown` | Critical owner triage starts immediately after routing fires. |
| Source freshness | freshness failed/degraded/unknown/stale alerts | Source owner decides disable, upstream wait, or credential fix. |
| Worker heartbeat/latest run | worker heartbeat and last-run alerts | Worker owner confirms process, queue, and textfile collector health. |
| Scheduler heartbeat | scheduler heartbeat alert | Platform owner confirms singleton scheduler and recent heartbeat. |
| Queue visibility/final-failed rows | queue metrics unavailable, final-failed rows, expired leases | Worker owner inspects rows; no bulk replay without accepted policy. |

## Prometheus Rules

Rule file:

```text
infra/monitoring/alert-rules.yml
```

Loaded by:

```text
infra/monitoring/prometheus.yml
```

Alerts:

| Alert | Severity | Metric source | Meaning |
|---|---|---|---|
| `FloodRiskSourceFreshnessFailed` | critical | `flood_risk_source_freshness_status{status="failed"}` | An enabled source reported failed health. |
| `FloodRiskSourceFreshnessDegraded` | warning | `flood_risk_source_freshness_status{status="degraded"}` | Source is still usable but impaired. |
| `FloodRiskSourceFreshnessUnknown` | warning | `flood_risk_source_freshness_status{status="unknown"}` | Source health could not be classified. |
| `FloodRiskSourceFreshnessStale` | critical | `flood_risk_source_freshness_stale` | Source timestamp exceeded the script threshold. |
| `FloodRiskOfficialSourceFreshnessStale` | critical | `flood_risk_source_freshness_stale{source_type="official"}` | An official source exceeded the freshness threshold. |
| `FloodRiskApiReadyDown` | critical | `up{job="flood-risk-api"}` or future `flood_risk_api_ready` | API scrape/readiness is down. |
| `FloodRiskWorkerHeartbeatMissing` | warning | `flood_risk_worker_heartbeat_timestamp_seconds` | Worker heartbeat is absent or older than 300 seconds. |
| `FloodRiskSchedulerHeartbeatMissing` | warning | `flood_risk_scheduler_heartbeat_timestamp_seconds` | Scheduler heartbeat is absent or older than 600 seconds. |
| `FloodRiskWorkerLastRunFailed` | critical | `flood_risk_worker_last_run_status{status="failed"}` | Latest observed worker run failed. |
| `FloodRiskRuntimeQueueMetricsUnavailable` | warning | `flood_risk_runtime_queue_metrics_available` | Queue metrics exporter could not read the durable queue backend. |
| `FloodRiskRuntimeQueueFinalFailedRowsPresent` | warning | `flood_risk_runtime_queue_final_failed_jobs` | Exhausted final-failed rows are present; inspect before any manual requeue. |
| `FloodRiskRuntimeQueueExpiredLeases` | warning | `flood_risk_runtime_queue_expired_leases` | Running queue rows have expired leases. |
| `FloodRiskRuntimeQueueLagHigh` | warning | `flood_risk_runtime_queue_lag_seconds` | A ready queued job has waited more than the accepted lag threshold. |

The current API scrape target is `api:8000/metrics`. If the deployed API does
not expose Prometheus metrics yet, `FloodRiskApiReadyDown` should be interpreted
as "API metrics target down" until a readiness probe exporter is wired.

## Grafana Dashboard

Dashboard file:

```text
infra/monitoring/flood-risk-runtime-dashboard.json
```

Import it into Grafana and choose the Prometheus datasource when prompted. The
dashboard covers the same operational surfaces as the alert rules:

- API scrape and readiness.
- Source freshness age, stale count, last-success age, and active status.
- Worker heartbeat age.
- Scheduler heartbeat age.
- Worker last-run failed count and active last-run status.
- Queue final-failed row count, expired leases, queue lag, oldest final-failed
  age, and metrics availability.

## Manual Check

From the repository root:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "https://<api-domain>" `
  -AdminToken "<token>" `
  -MaxAgeMinutes 60
```

For hosted release evidence against the admin source contract, use the Python
smoke. It records only aggregate source diagnostics and reads the token from the
named environment variable:

```powershell
python scripts\hosted_source_freshness_smoke.py `
  --base-url "https://<api-domain>" `
  --admin-token-env ADMIN_BEARER_TOKEN `
  --evidence-output ".\tmp\hosted-source-freshness-smoke.json" `
  --completion-evidence-output ".\tmp\hosted-source-freshness-completion-evidence.json"
```

This smoke can support completion evidence for the hosted worker-persisted
freshness path, but it is not a scheduler monitor and does not prove alert
routing, raw snapshot retention, hosted egress approval, or incident ownership.

## Hosted GitHub Actions Monitor

The repository also has a scheduled hosted monitoring workflow:

```text
.github/workflows/hosted-monitoring.yml
```

It runs every 30 minutes and can also be started manually from GitHub Actions.
Each run executes:

- `scripts/hosted_deployment_smoke.py` against `https://floodrisk.cc`.
- `scripts/hosted_public_risk_evidence_smoke.py` against the hosted public
  risk API.
- `scripts/local-source-signal-gap-discovery-refresh.py` against the
  data.gov.tw dataset export for every current signal-gap group.
- `scripts/local-source-signal-gap-dispatch-readiness.py` to turn the latest
  signal-gap discovery summary into a public-safe dispatch checklist.
- `scripts/local-source-contract-dispatch-readiness.py` to publish a
  public-safe checklist for authorization, metadata release, and public API
  contract request dispatch.
- `scripts/local-source-request-packet-bundle.py` to publish the generated
  official request packets, signal-gap request batches, and placeholder
  dispatch/completion templates operators need for the remaining official
  request work.
- `scripts/hosted_private_evidence_readiness.py` to publish which private
  evidence/admin-token inputs are configured or missing without printing values.
- `scripts/github-actions-secret-readiness.py` for an operator-side check of
  required GitHub Actions secret names. It reads only `gh secret list` metadata
  (`name` and `updatedAt`) and can write a public-safe JSON/Markdown artifact;
  it never reads or prints secret contents.
- `scripts/hosted_private_evidence_template_bundle.py` to publish public-safe
  pending templates for the hosted worker, worker-policy split route, and
  hosted monitoring private evidence manifests.
- `scripts/hosted_monitoring_schedule_evidence.py` to publish public-safe
  schedule-run evidence. On real `schedule` events it also emits partial
  completion evidence for `scheduled_freshness_checks`; manual runs only write
  a skipped evidence artifact.
- `scripts/hosted_source_freshness_smoke.py` when the repository secret
  `ADMIN_BEARER_TOKEN` is configured.
- `scripts/hosted_worker_evidence.py` when the repository secret
  `HOSTED_WORKER_EVIDENCE_MANIFEST_B64` is configured.
- `scripts/hosted_worker_policy_evidence.py` when the repository secret
  `HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` is configured.
- `scripts/hosted_monitoring_evidence.py` when the repository secret
  `HOSTED_MONITORING_EVIDENCE_MANIFEST_B64` is configured.
- `scripts/local-source-request-followups.py` when the repository secret
  `LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` is configured.
- `scripts/local-source-completion-audit.py` with every completion-evidence
  overlay produced by the hosted smoke steps.

The workflow uploads JSON and Markdown artifacts as the
`hosted-monitoring-<run-id>` artifact, including
`hosted-completion-audit.json` and `hosted-completion-audit.md`. These artifacts
are useful evidence inputs for deployment, public-risk, and hosted
source-freshness review. They do not, by themselves, complete the monitoring
gate: `production_monitoring_and_alerting` still needs accepted alert routing
ownership, scheduled source freshness evidence, and worker/scheduler alert
ownership recorded through
`scripts/hosted_monitoring_evidence.py`.

Manual workflow dispatch accepts an optional `expected_deployment_sha`. Omit it
for the workflow commit SHA, or provide the exact deployed SHA while verifying a
specific release. The hosted deployment smoke retries for a bounded window so
scheduled runs do not fail simply because Zeabur is still catching up to a fresh
main push. It also accepts `require_admin_source_freshness`; set that to `true`
for release or completion-gate runs where `/admin/v1/sources` freshness evidence
must be present. In strict mode, the workflow fails fast if the repository
secret `ADMIN_BEARER_TOKEN` is missing. For routine scheduled monitoring, the
default remains non-strict: if `ADMIN_BEARER_TOKEN` is not configured, the
public smokes still run and the admin source freshness check is skipped with a
notice rather than a leaked token or failed secret lookup.

Manual dispatch also accepts `fail_on_overdue_local_source_followups`. Set it
to `true` when a release/completion review should fail if the private
local-source dispatch evidence contains overdue official follow-ups. Scheduled
runs leave this non-strict by default so they can publish the public-safe
follow-up report without turning a known external-response wait into a red
build unless operators opt in.

The three hosted evidence `*_MANIFEST_B64` secrets are optional base64-encoded
JSON manifests validated by the evidence CLIs. Use them only for reviewed
private ops refs and requirement statuses; do not store raw provider secrets,
tokens, screenshots, or full incident transcripts in these GitHub secrets. When
present, their generated completion overlays are folded into
`hosted-completion-audit.json` alongside the public smoke evidence.

`HOSTED_WORKER_EVIDENCE_MANIFEST_B64` is the all-in-one hosted worker route for
`freshness_policy`, `raw_snapshot_retention_policy`,
`monitored_scheduler_cadence`, `hosted_egress_review`, and
`worker_persisted_evidence_path`. Operators can instead use the split route:
`ADMIN_BEARER_TOKEN` supplies hosted source freshness evidence for
`freshness_policy` and `worker_persisted_evidence_path`, while
`HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64` supplies
`raw_snapshot_retention_policy`, `monitored_scheduler_cadence`, and
`hosted_egress_review`. Either route still requires the decoded private
manifests to pass their evidence CLIs before the completion audit can accept the
gate.

`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64` is also optional. It should contain
a base64-encoded `local-source-completion-evidence/v1` dispatch overlay whose
items are still `status: request_dispatched`. The workflow decodes it only into
runner temp storage, writes `local-source-request-followups.json`, and writes a
sanitized completion overlay with `evidence_ref` replaced by
`private-ops://redacted/local-source-request-dispatch`. That sanitized overlay
lets the aggregate audit show dispatch and overdue-follow-up counts without
uploading private correspondence refs.

Signal-gap discovery refresh artifacts are public-safe and are uploaded on
every hosted monitoring run:

- `signal-gap-discovery-refresh-summary.json`
- `signal-gap-discovery-refresh-pump-or-gate-status.json`
- `signal-gap-discovery-refresh-flood-depth.json`
- `signal-gap-discovery-refresh-sewer-water-level.json`
- `signal-gap-dispatch-readiness.json`
- `source-contract-dispatch-readiness.json`
- `hosted-private-evidence-readiness.json`
- `local-source-request-packet-bundle-manifest.json`
- `local-source-request-packet-bundle.md`
- `local-source-official-request-packets.json`
- `local-source-official-request-packets.md`
- `local-source-official-request-completion-template.json`
- `local-source-signal-gap-request-batches.json`
- `local-source-signal-gap-request-batches.md`
- `local-source-signal-gap-dispatch-template.json`
- `local-source-source-contract-dispatch-template.json`
- `hosted-monitoring-schedule-evidence.json`
- `hosted-monitoring-schedule-completion-evidence.json` on scheduled runs only
- `hosted-private-evidence-template-bundle-manifest.json`
- `hosted-private-evidence-template-bundle.md`
- `hosted-worker-evidence-template.json`
- `hosted-worker-policy-evidence-template.json`
- `hosted-monitoring-evidence-template.json`

These artifacts monitor whether official open-data catalogs have published new
machine-readable candidates for the unresolved signal families. A
`candidate_live_read_api_found` conclusion is not completion by itself; it is a
triage signal to review the API contract, freshness fields, coordinates, and
license before turning it into an accepted production adapter or source-contract
evidence.

`signal-gap-dispatch-readiness.json` is also public-safe. It does not include
private dispatch evidence refs. It lists each unresolved signal family, the
current discovery counts, whether official read API requests should still be
sent, and the exact command operators can use to generate private dispatch
evidence after sending those requests.

`source-contract-dispatch-readiness.json` provides the same public-safe dispatch
checklist for the `official_authorization_and_contracts` gate. It lists the
remaining authorization requests, metadata-release monitor, and public API
contract reviews, but it does not prove requests were sent and does not satisfy
the gate without accepted private source-contract evidence.

The `local-source-request-packet-bundle-*` and related `local-source-*template`
artifacts are the operator handoff for that same unfinished work. They collect
the generated official request bodies, signal-family batches, and placeholder
dispatch/completion overlays in one hosted artifact set. They intentionally use
placeholder evidence refs and are not folded into the completion audit as
accepted evidence.

`hosted-private-evidence-readiness.json` lists the configured/missing state for
`ADMIN_BEARER_TOKEN`, `HOSTED_WORKER_EVIDENCE_MANIFEST_B64`,
`HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`,
`HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`, and
`LOCAL_SOURCE_REQUEST_DISPATCH_EVIDENCE_B64`. It never prints or decodes secret
values. It also records the alternative hosted-worker completion routes, so a
release review can tell whether the all-in-one worker manifest route or the
split admin-freshness plus worker-policy route is currently unblocked.
Configured secrets still do not satisfy completion gates unless their decoded
private manifests produce accepted completion evidence.

Use this local operator command when you need a GitHub-history-friendly snapshot
of whether the repository Actions secrets are present before a release or
completion review:

```powershell
python scripts\github-actions-secret-readiness.py `
  --repo "pcedison/taiwan-flood-risk-open-map" `
  --captured-at "$(Get-Date -Format o)" `
  --output ".\docs\reviews\github-actions-secret-readiness-YYYY-MM-DD.json" `
  --markdown-output ".\docs\reviews\github-actions-secret-readiness-YYYY-MM-DD.md"
```

This artifact is public-safe because GitHub exposes only secret names and update
timestamps through `gh secret list`. It does not prove the underlying private
evidence has been reviewed, and it does not replace the workflow-generated
`hosted-private-evidence-readiness.json`.

`hosted-monitoring-schedule-evidence.json` records whether the current hosted
monitoring run came from the scheduled trigger. If and only if
`GITHUB_EVENT_NAME` is `schedule`, the workflow also uploads
`hosted-monitoring-schedule-completion-evidence.json`, which satisfies the
`scheduled_freshness_checks` requirement of
`production_monitoring_and_alerting`. It does not satisfy `hosted_alert_routing`
or `worker_scheduler_alert_ownership`; those still require the reviewed private
monitoring manifest.

The hosted private evidence template bundle is an operator handoff, not
evidence. It publishes pending manifest templates and route mapping for
`HOSTED_WORKER_EVIDENCE_MANIFEST_B64`,
`HOSTED_WORKER_POLICY_EVIDENCE_MANIFEST_B64`, and
`HOSTED_MONITORING_EVIDENCE_MANIFEST_B64`. Filled manifests must stay in
private ops storage and be encoded into the matching GitHub secret only after
review.

盤點縣市級地方政府直連即時水情缺口時，使用 local-source coverage endpoint：

```powershell
Invoke-RestMethod `
  -Uri "https://<api-domain>/admin/v1/local-source-coverage" `
  -Headers @{ Authorization = "Bearer <admin-token>" }
```

`summary` 可用於維運 dashboard 與工作排序。它會回報已有地方直連
production adapter 的縣市數、仍缺中央最低基線的縣市數、缺水文觀測的縣市，
以及等待授權、live smoke 或公開 API contract 驗證的縣市數。`summary` 內的
縣市清單刻意支援多重歸類：同時是 `metadata_only` 與 `not_found` 的縣市，
例如連江縣，會同時出現在 metadata release monitoring 與 official discovery
queue。

請分開判讀 `local_direct_complete` 與 `central_backbone_available`。前者代表
官方地方政府 live adapter 已實作；後者代表 Civil IoT/WRA/CWA/NCDR 中央主幹
仍能為該縣市提供基礎即時脈絡。
`central_backbone_signal_types` 可查看目前存在的基線訊號，例如 `rainfall`、
`river_water_level`、`flood_depth`、`sewer_water_level`、`pump_water_level`、
`gate_water_level` 或 `cap_alert`。
`central_backbone_minimum_complete`、`central_backbone_missing_signal_types`
與 `central_backbone_coverage_level` 是縣市級健康門檻。最低基線需要官方雨量、
官方 CAP 警戒脈絡，以及至少一種水位、淹水深度、下水道、抽水站、閘門或
埤塘水位等水文觀測訊號。`needs_hydrologic_backbone` 表示該縣市仍缺中央
水文觀測訊號。
頂層 `central_backbone_required_families`、`central_backbone_missing_families`、
`central_backbone_family_complete`、`central_backbone_required_adapter_keys` 與
`central_backbone_missing_adapter_keys` 用於檢查全台中央主幹是否包含必要的
CWA、WRA、NCDR、Civil IoT family 與 production adapter key。這些欄位不代表
每個縣市的地方政府直連 API 都已完成。

分派後續工作前，先依 `upgrade_priority` 排序縣市：

| Action code | Meaning | Operator next step |
|---|---|---|
| `request_official_authorization` | A county source requires application or cooperation. | Use `application_urls` to ask the data owner for read API authorization and confirm the API is for observation reads, not only device uploads. |
| `verify_public_api_contract` | An official candidate system exists, but no public API contract is verified. | Use `candidate_source_urls` to find an official API landing page, open-data catalog entry, or written endpoint/schema before implementation. |
| `verify_live_smoke` | An official API contract is known, but live smoke, freshness, geometry, or field semantics still need verification. | Use `candidate_source_urls` to run a live smoke check before opening adapter TDD work. |
| `monitor_open_data_release` | Only static metadata exists. | Use `metadata_source_urls` to monitor source catalogs for live fields and use metadata only for station joins after a live source appears. |
| `continue_official_discovery` | No conforming local source has been found. | Continue official-source discovery; keep central backbone as the realtime baseline. |
| `operate_adapter` | A production local adapter exists. | Use `production_source_urls` while keeping source gates, freshness, county coverage, and duplicate handling healthy. |

For `monitor_open_data_release`, run the data.gov.tw release monitor and inspect
`summary.by_county.<county>.readiness_state`. The state is:

- `live_candidate_found`: a machine-readable dataset with live-water keywords
  appeared and needs API contract/freshness/geometry verification.
- `metadata_only`: only static metadata or flood-prone-area catalog entries are
  visible; keep the official release request open.
- `no_candidate`: the monitored county has no matching data.gov.tw candidate in
  the current export.

`candidate_live_read_api_count_by_county`, `metadata_only_count_by_county`, and
`target_counties_without_candidates` are intended for scheduler output,
freshness jobs, or alert routing so a P0 release-monitor county such as
連江縣 does not silently remain unreviewed.

To export Prometheus textfile metrics while keeping the check non-blocking:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "https://<api-domain>" `
  -AdminToken "<token>" `
  -MaxAgeMinutes 60 `
  -WarnOnly `
  -MetricsPath ".\tmp\source-freshness.prom"
```

For local development:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "http://localhost:8000" `
  -AdminToken $env:ADMIN_BEARER_TOKEN `
  -MaxAgeMinutes 60
```

## Dry Run

Dry-run mode is safe for CI and does not require a running API:

```powershell
.\scripts\ops-source-freshness-check.ps1 -DryRun
```

Dry-run can also prove the metrics writer path:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -DryRun `
  -MetricsPath ".\tmp\source-freshness.prom"
```

Fixture mode validates the same freshness logic against a JSON file:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -FixturePath ".\path\to\admin-sources.fixture.json" `
  -MaxAgeMinutes 60
```

Expected fixture shape:

```json
{
  "sources": [
    {
      "id": "cwa-rainfall",
      "adapter_key": "official.cwa.rainfall",
      "source_type": "official",
      "health_status": "healthy",
      "last_success_at": "2026-04-30T08:00:00Z",
      "source_timestamp_max": "2026-04-30T07:55:00Z"
    }
  ]
}
```

## Metric Contract

The ops script writes these metrics when `-MetricsPath` is supplied:

| Metric | Labels | Meaning |
|---|---|---|
| `flood_risk_source_freshness_check_success` | none | `1` when the latest script run passed, otherwise `0`. |
| `flood_risk_source_freshness_threshold_seconds` | none | The `-MaxAgeMinutes` threshold converted to seconds. |
| `flood_risk_source_freshness_age_seconds` | `source_id`, `adapter_key`, `source_type`, `health_status` | Age of the newest source timestamp, or `-1` if missing. |
| `flood_risk_source_freshness_stale` | `source_id`, `adapter_key`, `source_type`, `health_status` | `1` when the source is stale or missing timestamps. |
| `flood_risk_source_freshness_status` | `source_id`, `adapter_key`, `source_type`, `status` | One-hot health status gauge for `healthy`, `degraded`, `failed`, `unknown`, `disabled`. |
| `flood_risk_source_last_success_timestamp_seconds` | `source_id`, `adapter_key`, `source_type`, `health_status` | Unix timestamp of the latest successful ingestion recorded by the admin source endpoint, or `0` if unknown. |
| `flood_risk_source_last_success_age_seconds` | `source_id`, `adapter_key`, `source_type`, `health_status` | Age of the latest successful ingestion recorded by the admin source endpoint, or `-1` if unknown. |

The Prometheus freshness alerts read the `status` and `stale` metrics directly.
The script and alert rules therefore share one threshold source:
`-MaxAgeMinutes`.

## Runtime Heartbeat Metric Contract

The worker package defines Prometheus text rendering helpers in:

```text
apps/workers/app/metrics.py
```

Runtime heartbeat metrics:

| Metric | Labels | Meaning |
|---|---|---|
| `flood_risk_worker_heartbeat_timestamp_seconds` | `service`, `instance`, `queue` | Unix timestamp of the latest worker heartbeat. |
| `flood_risk_scheduler_heartbeat_timestamp_seconds` | `service`, `instance`, `scheduler` | Unix timestamp of the latest scheduler heartbeat. |
| `flood_risk_worker_last_run_status` | `service`, `instance`, `queue`, `job`, `status` | One-hot latest worker run status for `succeeded`, `failed`, `skipped`, `running`, `unknown`. |
| `flood_risk_scheduler_last_run_status` | `service`, `instance`, `scheduler`, `status` | One-hot latest scheduler run status. |
| `flood_risk_adapter_last_success_timestamp_seconds` | `service`, `adapter_key` | Unix timestamp of a successful adapter run observed by the worker textfile path. |

Runtime queue visibility metrics:

| Metric | Labels | Meaning |
|---|---|---|
| `flood_risk_runtime_queue_metrics_available` | `service`, `surface`, `reason` | `1` when the queue metrics exporter queried the DB, otherwise `0`. |
| `flood_risk_runtime_queue_queued_jobs` | `service`, `surface`, `queue_name` | Rows currently in `queued` status. |
| `flood_risk_runtime_queue_running_jobs` | `service`, `surface`, `queue_name` | Rows currently in `running` status. |
| `flood_risk_runtime_queue_final_failed_jobs` | `service`, `surface`, `queue_name` | Exhausted `failed` rows where attempts reached max attempts. Not a complete DLQ. |
| `flood_risk_runtime_queue_expired_leases` | `service`, `surface`, `queue_name` | Running rows with an expired lease. |
| `flood_risk_runtime_queue_lag_seconds` | `service`, `surface`, `queue_name` | Age of the oldest queued job whose `run_after` is due, or `0` when no due queued job exists. |
| `flood_risk_runtime_queue_oldest_final_failed_age_seconds` | `service`, `surface`, `queue_name` | Age of the oldest exhausted final-failed row, or `0` when none exists. |

Until an HTTP `/metrics` endpoint is wired, configure the worker runtime to
write helper output to node exporter textfile collector paths such as:

```text
WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom
SCHEDULER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom
```

Queue metrics are written by the CLI rather than the worker heartbeat path:

```text
python -m app.main --export-runtime-queue-metrics --runtime-queue-metrics-path /var/lib/node_exporter/textfile_collector/flood-risk-runtime-queue.prom
```

The local Compose worker and scheduler services mount the shared collector
directory, but these variables remain empty by default. Set them explicitly in
`.env` or the shell when validating queue and scheduler dashboard panels.

## Reading Alerts

When a freshness alert fires, first read these labels:

- `source_id`: the affected source.
- `status`: the active health status for status alerts.
- `health_status`: the API health status attached to age/stale metrics.

Then map the alert to the script output:

- `FloodRiskSourceFreshnessFailed` matches script failures like
  `<source> status=failed`.
- `FloodRiskSourceFreshnessDegraded` matches `<source> status=degraded`.
- `FloodRiskSourceFreshnessUnknown` matches `<source> status=unknown` or a
  source missing `health_status`.
- `FloodRiskSourceFreshnessStale` matches
  `<source> stale for <minutes> minutes; threshold=<MaxAgeMinutes>`.

If only `FloodRiskApiReadyDown` fires, run `/health`, `/ready`, and the runtime
smoke script before debugging source freshness. If API readiness and freshness
alerts fire together, treat the API/dependency outage as the parent incident.

## Triage

1. Confirm whether the source is expected to be enabled in the environment.
2. Check `health_status`; `failed`, `degraded`, and `unknown` are alerting
   states unless the source is intentionally disabled.
3. Compare `source_timestamp_max` first, then `last_success_at`.
4. Inspect worker and scheduler logs for repeated adapter failures.
5. Confirm source credentials and upstream availability.
6. Confirm the environment has completed real credential review and WRA/CWA
   production egress verification before treating a live official-source signal
   as production beta evidence.
7. If only the public API is affected, keep the API online and expose missing
   source warnings in risk responses.
8. Record the incident with source id, first stale time, recovery time, and any
   skipped adapters.

## Heartbeat Thresholds

- Worker missing heartbeat: no heartbeat or latest heartbeat older than 300s.
- Scheduler missing heartbeat: no heartbeat or latest heartbeat older than 600s.

## CI Smoke

The minimum CI-safe check is PowerShell parsing plus dry-run execution:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops-source-freshness-check.ps1 -DryRun
```

Also validate the monitoring YAML before shipping changes:

```powershell
python infra/scripts/validate_monitoring_assets.py
```

This does not prove production freshness. It proves the supported monitoring
entrypoints are syntactically valid and runnable.
