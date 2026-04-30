# Monitoring

This directory contains the baseline Prometheus configuration and alert rules
for operational checks that can run before the full Grafana/pager stack exists.

## Files

- `prometheus.yml` scrapes the API metrics endpoint at `api:8000/metrics` and
  loads `alert-rules.yml`.
- `alert-rules.yml` defines source freshness, API readiness, and future
  worker/scheduler heartbeat alerts.

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

The current `docker-compose.yml` does not define a Prometheus service or a
node-exporter textfile collector. Do not add one here without the runtime owner
agreeing on the deployment topology. For now, mount this directory into any
external Prometheus instance and wire the textfile output through the chosen
collector or scheduled monitor.

## Future Metrics

The worker and scheduler heartbeat alerts are intentionally non-firing
placeholders because the runtime does not publish heartbeat timestamp metrics
yet. Replace their expressions when these metrics exist:

- `flood_risk_worker_heartbeat_timestamp_seconds`
- `flood_risk_scheduler_heartbeat_timestamp_seconds`
