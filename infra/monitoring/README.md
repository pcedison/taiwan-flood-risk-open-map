# Monitoring

This directory contains the baseline Prometheus configuration and alert rules
for operational checks that can run before the full Grafana/pager stack exists.

## Files

- `prometheus.yml` scrapes the API metrics endpoint at `api:8000/metrics` and
  loads `alert-rules.yml`. It also scrapes the Compose `node-exporter` service
  for textfile metrics.
- `alert-rules.yml` defines source freshness, API readiness, and future
  worker/scheduler heartbeat alerts.
- `flood-risk-runtime-dashboard.json` is an importable Grafana dashboard for
  API readiness, source freshness, worker heartbeat, scheduler heartbeat, and
  worker last-run status.
- `grafana/provisioning` contains the local Compose datasource and dashboard
  provider used by the optional monitoring profile.

## Local Compose Profile

The root `docker-compose.yml` includes an optional `monitoring` profile for
local deployment checks:

```powershell
docker compose --profile monitoring up prometheus grafana node-exporter
```

Prometheus is available on `http://localhost:9090` by default. Grafana is
available on `http://localhost:3001` with `GRAFANA_ADMIN_USER` and
`GRAFANA_ADMIN_PASSWORD` from `.env` or `.env.example`.

The profile wires:

- Prometheus config and alert rules from this directory.
- Grafana datasource `Flood Risk Prometheus` pointing at
  `http://prometheus:9090`.
- Grafana dashboard provisioning for `flood-risk-runtime-dashboard.json`.
- Node exporter textfile collector backed by the Compose
  `monitoring-textfile` volume.

This profile is a local deployment harness, not a production topology. Hosted
environments should replace service DNS names, credentials, persistence,
network policy, TLS, and alert routing with environment-specific values.

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
local Compose profile already provides the `flood-risk-node-exporter` target.
External deployments can replace `node-exporter:9100` with their collector DNS
name or remove the job when another collector owns textfile ingestion.

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

The Compose profile's named `monitoring-textfile` volume is easy for worker and
scheduler containers to share, but a host-run PowerShell freshness job cannot
write into that named volume directly. For host-run checks, write to a host
path and expose it through your node exporter, or run the check in a container
that mounts the same collector directory.

## Grafana Dashboard

With the Compose monitoring profile, Grafana provisions the Prometheus
datasource and imports `flood-risk-runtime-dashboard.json` automatically. For
external Grafana instances, import the JSON manually and select the Prometheus
datasource when prompted. The dashboard covers:

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
