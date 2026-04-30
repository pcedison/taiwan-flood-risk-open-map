# Monitoring Freshness Alerts Runbook

## Purpose

This runbook defines the first operational freshness alert for Flood Risk data
sources. It is intentionally lightweight: it can be run manually, from CI, or
from a scheduled monitor without changing application code.

## Scope

Covered:

- Source freshness checks through `GET /admin/v1/sources`.
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
  is final-failed row visibility, not a complete DLQ. There is no replay audit,
  poison-job quarantine/escalation policy, or accepted production replay
  procedure yet.
- Official worker freshness is partial: demo/fixture-backed adapter runs are
  safe by default, and CWA rainfall plus WRA water-level can run through
  explicit live-client gates. Flood-potential worker freshness still needs a
  real source client. The API realtime official bridge may fetch CWA/WRA data,
  but that does not create persisted worker ingestion freshness evidence.
- Heartbeat alerts prove that textfile metrics are present and recent; they do
  not prove real-source credentials, idempotent job handling, or production
  singleton scheduler behavior.
- Freshness alerts should still distinguish deployable gated live paths from
  fixture/demo validation and production beta readiness.

Pending for production:

- Real source credentials, credential review, deployed source clients,
  WRA/CWA production egress verification, and per-source freshness thresholds.
- Alert routing, TLS/auth, durable monitoring storage, retention, and incident
  ownership.
- Hosted scheduler/cadence deployment for freshness export plus
  worker/scheduler heartbeat emission.
- Queue replay audit, poison-job quarantine, alert routing, and
  abuse-governance alerts for future public reports/public discussion
  ingestion.

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

To requeue one failed row:

```powershell
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --requeue-runtime-job <job-id>"
```

Do not treat the row-level list/requeue commands or metrics summary as a
complete DLQ or replay operating model. Replay still needs audit records,
payload safety review, source idempotency, backoff, poison-job quarantine,
alert routing, alert labels, and incident ownership. There is no purge,
quarantine, or auto replay in this phase.

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
| `FloodRiskApiReadyDown` | critical | `up{job="flood-risk-api"}` or future `flood_risk_api_ready` | API scrape/readiness is down. |
| `FloodRiskWorkerHeartbeatMissing` | warning | `flood_risk_worker_heartbeat_timestamp_seconds` | Worker heartbeat is absent or older than 300 seconds. |
| `FloodRiskSchedulerHeartbeatMissing` | warning | `flood_risk_scheduler_heartbeat_timestamp_seconds` | Scheduler heartbeat is absent or older than 600 seconds. |
| `FloodRiskWorkerLastRunFailed` | critical | `flood_risk_worker_last_run_status{status="failed"}` | Latest observed worker run failed. |
| `FloodRiskRuntimeQueueMetricsUnavailable` | warning | `flood_risk_runtime_queue_metrics_available` | Queue metrics exporter could not read the durable queue backend. |
| `FloodRiskRuntimeQueueFinalFailedRowsPresent` | warning | `flood_risk_runtime_queue_final_failed_jobs` | Exhausted final-failed rows are present; inspect before any manual requeue. |
| `FloodRiskRuntimeQueueExpiredLeases` | warning | `flood_risk_runtime_queue_expired_leases` | Running queue rows have expired leases. |

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
- Source freshness age, stale count, and active status.
- Worker heartbeat age.
- Scheduler heartbeat age.
- Worker last-run failed count and active last-run status.
- Queue final-failed row count, expired leases, oldest final-failed age, and
  metrics availability.

## Manual Check

From the repository root:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "https://<api-domain>" `
  -AdminToken "<token>" `
  -MaxAgeMinutes 60
```

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
| `flood_risk_source_freshness_age_seconds` | `source_id`, `health_status` | Age of the newest source timestamp, or `-1` if missing. |
| `flood_risk_source_freshness_stale` | `source_id`, `health_status` | `1` when the source is stale or missing timestamps. |
| `flood_risk_source_freshness_status` | `source_id`, `status` | One-hot health status gauge for `healthy`, `degraded`, `failed`, `unknown`, `disabled`. |

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

Runtime queue visibility metrics:

| Metric | Labels | Meaning |
|---|---|---|
| `flood_risk_runtime_queue_metrics_available` | `service`, `surface`, `reason` | `1` when the queue metrics exporter queried the DB, otherwise `0`. |
| `flood_risk_runtime_queue_queued_jobs` | `service`, `surface`, `queue_name` | Rows currently in `queued` status. |
| `flood_risk_runtime_queue_running_jobs` | `service`, `surface`, `queue_name` | Rows currently in `running` status. |
| `flood_risk_runtime_queue_final_failed_jobs` | `service`, `surface`, `queue_name` | Exhausted `failed` rows where attempts reached max attempts. Not a complete DLQ. |
| `flood_risk_runtime_queue_expired_leases` | `service`, `surface`, `queue_name` | Running rows with an expired lease. |
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
