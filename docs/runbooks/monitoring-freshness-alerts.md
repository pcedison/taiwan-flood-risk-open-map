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
  last-run status.
- Dry-run and fixture-based verification.
- Alert thresholds and triage steps.

Not covered:

- Production pager wiring.
- Adapter retry implementation.

## Placeholder Boundary

`infra/monitoring` now contains Prometheus config and alert rules, but the
repository `docker-compose.yml` does not currently run a Prometheus service.
Use the files with the environment's Prometheus deployment, or run the ops
script from a scheduled monitor and export its textfile metrics through the
chosen collector.

Worker and scheduler heartbeat alerts read Prometheus textfile-compatible
metrics. Set `WORKER_METRICS_TEXTFILE_PATH` or `SCHEDULER_METRICS_TEXTFILE_PATH`
on the worker process to emit these files for a node exporter textfile
collector.

Dashboard and scrape deployment details live in:

```text
docs/runbooks/monitoring-dashboard.md
```

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

Until an HTTP `/metrics` endpoint is wired, configure the worker runtime to
write helper output to node exporter textfile collector paths such as:

```text
WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom
SCHEDULER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom
```

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
6. If only the public API is affected, keep the API online and expose missing
   source warnings in risk responses.
7. Record the incident with source id, first stale time, recovery time, and any
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
