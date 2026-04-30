# Monitoring

This directory contains the baseline Prometheus configuration and alert rules
for operational checks that can run before the full Grafana/pager stack exists.

## Files

- `prometheus.yml` scrapes the API metrics endpoint at `api:8000/metrics` and
  loads `alert-rules.yml`.
- `alert-rules.yml` defines source freshness, API readiness, and future
  worker/scheduler heartbeat alerts.
- `flood-risk-runtime-dashboard.json` is an importable Grafana dashboard for
  API readiness, source freshness, worker heartbeat, scheduler heartbeat, and
  worker last-run status.

## Prometheus Deployment

Use `prometheus.yml` as a seed config for the environment's Prometheus service.
The active scrape target is:

```yaml
- job_name: flood-risk-api
  metrics_path: /metrics
  static_configs:
    - targets: ["api:8000"]
```

Replace `api:8000` with the deployed API service DNS name and port when the API
is not running on a Compose-style network. The target must serve
`GET /metrics`; the readiness panel and `FloodRiskApiReadyDown` alert use
`flood_risk_api_ready` when present and otherwise rely on `up{job="flood-risk-api"}`.

For textfile metrics, deploy Prometheus node exporter next to the process that
writes `.prom` files and start it with:

```text
--collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

Prometheus then scrapes node exporter, not the `.prom` files directly. The
optional `flood-risk-node-exporter` job in `prometheus.yml` documents the target
shape; uncomment it only after node exporter is deployed.

## Freshness Metrics

`scripts/ops-source-freshness-check.ps1` can emit Prometheus textfile metrics
with `-MetricsPath`. These metrics are the bridge between the admin source
freshness endpoint and the Prometheus alerts:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "https://<api-domain>" `
  -AdminToken "<token>" `
  -MaxAgeMinutes 60 `
  -WarnOnly `
  -MetricsPath ".\tmp\source-freshness.prom"
```

For production-style ingestion, write the freshness output into the same
node-exporter textfile collector directory:

```powershell
.\scripts\ops-source-freshness-check.ps1 `
  -BaseUrl "https://<api-domain>" `
  -AdminToken "<token>" `
  -MaxAgeMinutes 60 `
  -WarnOnly `
  -MetricsPath "/var/lib/node_exporter/textfile_collector/flood-risk-source-freshness.prom"
```

The current `docker-compose.yml` does not define a Prometheus service or a
node-exporter textfile collector. Do not add one here without the runtime owner
agreeing on the deployment topology. For now, mount this directory into any
external Prometheus instance and wire the textfile output through node exporter
or the chosen scheduled monitor.

## Grafana Dashboard

Import `flood-risk-runtime-dashboard.json` into Grafana and select the
Prometheus datasource when prompted. The dashboard covers:

- API metrics scrape status and readiness.
- Source freshness status and source age.
- Stale source count.
- Worker heartbeat age.
- Scheduler heartbeat age.
- Worker last-run failed count and last-run status table.

## Future Metrics

Worker and scheduler heartbeat alerts read textfile-compatible metrics emitted
by the runtime when the corresponding environment variables are set:

- `flood_risk_worker_heartbeat_timestamp_seconds`
- `flood_risk_scheduler_heartbeat_timestamp_seconds`
- `flood_risk_worker_last_run_status`

Configure:

```text
WORKER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-worker.prom
SCHEDULER_METRICS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/flood-risk-scheduler.prom
```

## Validation

Run syntax validation before shipping monitoring changes:

```powershell
python infra/scripts/validate_monitoring_assets.py
```
