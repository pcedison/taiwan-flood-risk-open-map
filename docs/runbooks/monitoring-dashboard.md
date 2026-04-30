# Monitoring Dashboard Runbook

## Purpose

This runbook explains how to deploy the baseline Prometheus scrape config,
ingest textfile collector metrics, and import the Grafana dashboard for Flood
Risk runtime monitoring.

## Files

| File | Purpose |
|---|---|
| `infra/monitoring/prometheus.yml` | Seed Prometheus scrape config and alert rule loader. |
| `infra/monitoring/alert-rules.yml` | Alert rules for API readiness, freshness, heartbeats, and worker failures. |
| `infra/monitoring/flood-risk-runtime-dashboard.json` | Grafana dashboard JSON. |
| `docs/runbooks/monitoring-freshness-alerts.md` | Alert triage and freshness metric contract. |

## Grafana Import

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
2. Start node exporter with:

   ```text
   --collector.textfile.directory=/var/lib/node_exporter/textfile_collector
   ```

3. Configure the freshness script and worker runtimes to write files into that
   directory.
4. Add or uncomment a Prometheus node exporter scrape job:

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
- `flood-risk-api` target is up in Prometheus.
- Node exporter scrape target is up when textfile metrics are deployed.
- Freshness script writes `flood-risk-source-freshness.prom`.
- Worker and scheduler write heartbeat `.prom` files when their env vars are
  set.
- Dashboard panels show API readiness, source freshness, worker heartbeat,
  scheduler heartbeat, and worker last-run status.
