# Monitoring Dashboard Runbook

## Purpose

This runbook explains how to deploy the baseline Prometheus scrape config,
ingest textfile collector metrics, and import the Grafana dashboard for Flood
Risk runtime monitoring.

## Current Phase Status

Completed:

- Local Docker Compose `monitoring` profile for Prometheus, Grafana, and node
  exporter wiring.
- Prometheus rule loading and Grafana dashboard JSON/provisioning validation.
- API `/metrics` scrape target for local Compose.
- Source freshness script that can emit Prometheus textfile metrics.
- Opt-in worker and scheduler heartbeat textfile metric contracts.
- Operator-exported runtime queue metrics for queued/running counts,
  final-failed row counts, expired leases, and oldest final-failed age.

Partially complete:

- Dashboard panels are importable and useful for local validation, but they
  only show real freshness/queue/scheduler state after the corresponding
  producers write textfile metrics into a node exporter collector directory.
- Worker queue panels observe heartbeats, last-run status, queued/running
  counts, expired leases, and final-failed row visibility. They do not yet
  prove real-source retries, accepted DLQ/replay handling, poison-job routing,
  or production scheduler singleton behavior.
- Exhausted runtime jobs are inspectable through
  `--list-runtime-dead-letter-jobs`, summarized/exported through
  `--export-runtime-queue-metrics`, and requeue is a row-level CLI action.
  This is final-failed row visibility rather than a complete DLQ.
- Official-source panels do not prove real credential review, hosted cadence,
  or WRA/CWA production egress verification.
- The local profile proves wiring and syntax, not production uptime,
  persistence, access control, or incident response.

Pending for production:

- Hosted scrape targets, service DNS, credentials, TLS/auth, persistent
  Prometheus/Grafana storage, Alertmanager or pager routing, and retention
  policy.
- Scheduled freshness checks for the deployed API and per-source cadence.
- Real credential review and WRA/CWA production egress verification for live
  official-source paths.
- Worker/scheduler deployment with heartbeat paths mounted into a real
  collector.
- Accepted replay policy around the queue replay audit and poison-quarantine
  primitives, plus routing/escalation, alert routing, and incident ownership
  for exhausted jobs.

## Files

| File | Purpose |
|---|---|
| `infra/monitoring/prometheus.yml` | Seed Prometheus scrape config and alert rule loader. |
| `infra/monitoring/alert-rules.yml` | Alert rules for API readiness, freshness, heartbeats, and worker failures. |
| `infra/monitoring/flood-risk-runtime-dashboard.json` | Grafana dashboard JSON. |
| `infra/monitoring/grafana/provisioning/datasources/prometheus.yml` | Local Compose Grafana datasource provisioning. |
| `infra/monitoring/grafana/provisioning/dashboards/flood-risk.yml` | Local Compose Grafana dashboard provider. |
| `docs/runbooks/monitoring-freshness-alerts.md` | Alert triage and freshness metric contract. |

## Local Compose Monitoring Profile

For local deployment wiring checks, start the runtime and monitoring profile:

```powershell
docker compose --profile monitoring config
docker compose --profile monitoring up
```

The profile exposes:

| Service | Default URL | Notes |
|---|---|---|
| Prometheus | `http://localhost:9090` | Loads `infra/monitoring/prometheus.yml` and `alert-rules.yml`. |
| Grafana | `http://localhost:3001` | Uses `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`; defaults are local only. |
| Node exporter | `http://localhost:9100` | Only textfile collector is enabled in this profile. |

Grafana provisions the `Flood Risk Prometheus` datasource and imports the
runtime dashboard automatically. This proves that the dashboard JSON is
importable in the local profile, but it does not prove hosted alert routing,
TLS, authentication, persistent storage policy, or production DNS.

## Grafana Import

In the Compose profile, no manual import is required. For an external Grafana
instance:

1. Open Grafana Dashboards, then import
   `infra/monitoring/flood-risk-runtime-dashboard.json`.
2. Select the Prometheus datasource for `DS_PROMETHEUS`.
3. Keep the dashboard refresh at `30s` for active incident response, or slow it
   down after the deployment is stable.

The dashboard includes:

| Panel | Prometheus query | Reviewer signal |
|---|---|---|
| API Metrics Scrape | `max(up{job="flood-risk-api"})` | Confirms Prometheus can scrape the API target. |
| API Readiness | `max(flood_risk_api_ready) or max(up{job="flood-risk-api"})` | Shows readiness when exported, otherwise scrape availability. |
| Stale Sources | `sum(flood_risk_source_freshness_stale == 1)` | Counts stale or timestamp-missing sources. |
| Worker Last Run Failed | `sum(flood_risk_worker_last_run_status{status="failed"} == 1)` | Flags failed latest worker runs. |
| Source Freshness Status | `flood_risk_source_freshness_status == 1` | Lists active source health status by source. |
| Source Freshness Age | `flood_risk_source_freshness_age_seconds` | Tracks freshness age by source. |
| Worker Heartbeat Age | `time() - flood_risk_worker_heartbeat_timestamp_seconds` | Shows worker heartbeat age by instance and queue. |
| Scheduler Heartbeat Age | `time() - flood_risk_scheduler_heartbeat_timestamp_seconds` | Shows scheduler heartbeat age by instance and scheduler. |
| Worker Last Run Status | `flood_risk_worker_last_run_status == 1` | Lists the latest worker run status by job. |
| Queue Final-Failed Rows | `sum(flood_risk_runtime_queue_final_failed_jobs)` | Counts exhausted final-failed rows; this is not a complete DLQ. |
| Queue Expired Leases | `sum(flood_risk_runtime_queue_expired_leases)` | Counts running rows whose leases have expired. |
| Queue Oldest Final-Failed Age | `max(flood_risk_runtime_queue_oldest_final_failed_age_seconds)` | Shows how long the oldest final-failed row has been visible. |
| Queue Metrics Available | `min(flood_risk_runtime_queue_metrics_available)` | Shows whether the CLI exporter could query the DB. |
| Runtime Queue Counts | queue count metrics | Table view of queued/running/final-failed/expired-lease series. |

## Prometheus API Scrape

The baseline scrape target is in `infra/monitoring/prometheus.yml`:

```yaml
- job_name: flood-risk-api
  metrics_path: /metrics
  static_configs:
    - targets: ["api:8000"]
```

For Compose-like deployments, `api:8000` is the API service name and internal
port. For hosted deployments, replace it with the internal DNS name and port
that exposes `GET /metrics`.

If the API does not export `flood_risk_api_ready` yet, the readiness panel and
`FloodRiskApiReadyDown` alert still use `up{job="flood-risk-api"}` as the
deployment-level signal.

## Textfile Collector Deployment

Source freshness, worker heartbeat, scheduler heartbeat, and worker last-run
metrics are textfile-compatible. Prometheus does not scrape those `.prom` files
directly. Instead:

1. Deploy node exporter on the host or sidecar that can read the metrics files.
   The local Compose profile already provides `node-exporter:9100` with a
   shared `monitoring-textfile` volume.
2. Start node exporter with:

   ```text
   --collector.textfile.directory=/var/lib/node_exporter/textfile_collector
   ```

3. Configure the freshness script and worker runtimes to write files into that
   directory.
4. Keep or adapt the Prometheus node exporter scrape job:

   ```yaml
   - job_name: flood-risk-node-exporter
     static_configs:
       - targets: ["node-exporter:9100"]
   ```

Use one file per producer to avoid clobbering metrics:

| Producer | Recommended file |
|---|---|
| Source freshness script | `/var/lib/node_exporter/textfile_collector/flood-risk-source-freshness.prom` |
| Worker runtime | `/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom` |
| Scheduler runtime | `/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom` |
| Runtime queue metrics CLI | `/var/lib/node_exporter/textfile_collector/flood-risk-runtime-queue.prom` |

The worker runtime paths are controlled by:

```text
WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom
SCHEDULER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom
```

The freshness script writes the same textfile directory with:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "https://<api-domain>" `
  -AdminToken "<token>" `
  -MaxAgeMinutes 60 `
  -WarnOnly `
  -MetricsPath "/var/lib/node_exporter/textfile_collector/flood-risk-source-freshness.prom"
```

Schedule that command with the platform scheduler or cron equivalent. Keep
`-WarnOnly` enabled for monitoring export jobs so a stale source does not stop
the next metrics write.

When running the PowerShell freshness script on the host, `.\tmp\*.prom` is
useful for validation, but it is not automatically visible to the Compose
node-exporter named volume. Either run node exporter against that host path or
run the freshness check in a container that mounts the same collector directory.

## Source Freshness And Worker Queue Panels

Use the dashboard panels as deployment acceptance signals:

| Surface | Panels | Required metric path |
|---|---|---|
| Source freshness | `Stale Sources`, `Source Freshness Status`, `Source Freshness Age` | Scheduled `ops-source-freshness-check.ps1` with `-MetricsPath`, exported through node exporter. |
| Worker queue health | `Worker Heartbeat Age`, `Worker Last Run Failed`, `Worker Last Run Status` | Worker process writes `WORKER_METRICS_TEXTFILE_PATH` into the collector directory. |
| Runtime queue row visibility | `Queue Final-Failed Rows`, `Queue Expired Leases`, `Queue Oldest Final-Failed Age`, `Queue Metrics Available`, `Runtime Queue Counts` | Scheduled `python -m app.main --export-runtime-queue-metrics --runtime-queue-metrics-path <collector-file>`. |
| Scheduler health | `Scheduler Heartbeat Age` | Scheduler process writes `SCHEDULER_METRICS_TEXTFILE_PATH` into the collector directory. |

For local Compose, set these paths when you want worker/scheduler textfile
metrics:

```text
WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom
SCHEDULER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom
```

The panels intentionally show missing metrics as deployment gaps until those
producers are enabled. A clean dashboard import alone is not evidence that
freshness jobs, queue heartbeats, or scheduler heartbeats are running.

## Operator Commands

```powershell
# Validate monitoring YAML/JSON assets.
python infra/scripts/validate_monitoring_assets.py

# Start only the monitoring profile services.
docker compose --profile monitoring up prometheus grafana node-exporter

# Write a local freshness textfile without calling a live API.
.\scripts\ops-source-freshness-check.ps1 `
  -DryRun `
  -MetricsPath ".\tmp\source-freshness.prom"

# Write worker heartbeat metrics into the Compose textfile collector volume.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  worker sh -c "pip install -e . && python -m app.main --run-enabled-adapters"

# Write scheduler heartbeat metrics for a bounded local adapter scheduler run.
docker compose run --rm `
  -e WORKER_ENABLED_ADAPTER_KEYS=official.wra.water_level `
  -e SCHEDULER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom `
  -e WORKER_RUNTIME_FIXTURES_ENABLED=true `
  scheduler sh -c "pip install -e . && python -m app.scheduler --run-enabled-adapters --once"

# Inspect final-failed queue rows outside the dashboard. This is not a DLQ.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --list-runtime-dead-letter-jobs --dead-letter-limit 20"

# Export queue visibility metrics for Prometheus textfile collection.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --export-runtime-queue-metrics --runtime-queue-metrics-path /var/lib/node_exporter/textfile_collector/flood-risk-runtime-queue.prom"

# Print the same queue visibility surface as JSON for operator inspection.
docker compose run --rm worker sh -c "pip install -e . && python -m app.main --export-runtime-queue-metrics --runtime-queue-metrics-format json"
```

## Validation

Run YAML and JSON syntax validation from the repository root:

```powershell
python infra/scripts/validate_monitoring_assets.py
```

Optionally run the freshness script dry-run to prove the textfile writer path:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -DryRun `
  -MetricsPath ".\tmp\source-freshness.prom"
```

## Reviewer Checklist

- Grafana dashboard imports without JSON errors.
- Local profile validates with `docker compose --profile monitoring config`.
- `flood-risk-api` target is up in Prometheus.
- Node exporter scrape target is up when textfile metrics are deployed.
- Freshness script writes `flood-risk-source-freshness.prom`.
- Worker and scheduler write heartbeat `.prom` files when their env vars are
  set.
- Dashboard panels show API readiness, source freshness, worker heartbeat,
  scheduler heartbeat, worker last-run status, and runtime queue final-failed
  row visibility.

## Pending Checklist

- Do not promote final-failed row visibility to a first-class DLQ until replay
  audit and poison-job policy are accepted.
- Add poison-job quarantine/routing and incident workflow before treating
  row-level requeue as production replay.
- Wire hosted scrape targets, TLS/auth, persistent storage, and pager/alert
  routing.
- Schedule source freshness export and worker/scheduler heartbeat emission in
  the target environment.
- Verify WRA/CWA production egress and complete real credential review before
  using official-source dashboard health as production beta evidence.
