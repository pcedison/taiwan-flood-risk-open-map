# Runtime Smoke Runbook

This runbook verifies the local Docker Compose runtime without deleting any Docker volumes.

## Requirements

- Docker Desktop or another Docker engine with Compose v2.
- Ports `8000`, `3000`, `5432`, `6379`, `9000`, and `9001` available, unless overridden through environment variables used by `docker-compose.yml`.
- Run commands from the repository root.

## Run

```powershell
.\scripts\runtime-smoke.ps1
```

The script performs these checks:

1. `docker compose config --quiet`
2. `docker info`
3. `docker compose up -d postgres redis minio api web`
4. `docker compose --profile tools run --rm migrate`
5. Polls API `/health`
6. Polls API `/ready`
7. Posts a sample request to `/v1/risk/assess`
8. Polls the web runtime until it responds at `http://localhost:3000`

By default, services are left running for debugging or follow-up manual testing. To stop the runtime containers after the smoke finishes, without removing volumes:

```powershell
.\scripts\runtime-smoke.ps1 -StopOnExit
```

Useful options:

```powershell
.\scripts\runtime-smoke.ps1 -StartupTimeoutSeconds 240 -ApiBaseUrl http://localhost:8000 -WebBaseUrl http://localhost:3000
```

## Successful Output

A passing run ends with:

```text
API health: status=ok, service=flood-risk-api, version=...
API ready: database=healthy, redis=healthy
Risk smoke: assessment_id=..., realtime=..., historical=..., confidence=...
Web smoke: HTTP 200 from http://localhost:3000
Runtime smoke passed.
```

## Common Failures

- `docker compose config --quiet` fails: the Compose file or environment interpolation is invalid.
- Docker command or daemon is unavailable: start Docker Desktop and ensure both `docker compose version` and `docker info` work.
- Port already in use: stop the conflicting process or set the matching `*_PORT` environment variable before running the script.
- `/ready` stays down: inspect `docker compose logs --tail=80 api`, `postgres`, and `redis`.
- Migration fails: inspect the migration output and confirm Postgres is healthy.
- Web check fails: inspect the emitted `web` logs. The first run may need more time while `npm ci` installs dependencies and Next.js compiles the first page; rerun with a larger `-StartupTimeoutSeconds`.

## Safety Notes

The script does not run `docker compose down -v`, `docker volume rm`, or any volume cleanup. With `-StopOnExit`, it only runs `docker compose stop` for the services it started.
