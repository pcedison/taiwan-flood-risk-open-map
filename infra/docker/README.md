# Docker Infrastructure

Placeholder for service-specific Dockerfiles and deployment helpers.

The root `docker-compose.yml` currently uses upstream runtime images to keep the
skeleton lightweight.

## Monitoring Profile

Local monitoring deployment wiring lives in the root Compose file under the
`monitoring` profile:

```powershell
docker compose --profile monitoring up
```

This starts Prometheus, Grafana, and node exporter using assets from
`infra/monitoring`. It is intended for local validation and reviewer demos.
Hosted deployments should adapt DNS names, credentials, persistent storage,
TLS, scheduler wiring, and alert routing for the target environment.
