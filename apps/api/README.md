# Flood Risk API

FastAPI Phase 1 public API routes, service health, and Phase 3 scoring
groundwork.

## Entry points

- FastAPI app: `app.main:app`
- Docker Compose command: `pip install -e . && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Local FastAPI command after installing dependencies: `python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Current scope

- `/health`
- `/ready` dependency readiness checks
- `/v1/geocode` mock provider
- `/v1/risk/assess` mock/live-groundwork assessment surface backed by the
  current risk contract
- `/v1/evidence/{assessment_id}` evidence list surface for the current
  assessment contract
- `/v1/layers` and `/v1/layers/{layer_id}/tilejson` placeholder layer metadata
  until the tile/layer pipeline lands
- Protected `/admin/v1/jobs` and `/admin/v1/sources` contract skeleton
- Environment-based settings loader
- Structured error payload helper
- Focused public contract tests

## Placeholder boundary

- `app/placeholder_server.py` is a fallback artifact only. Docker Compose and
  normal local development should use `app.main:app`.
- Geocode and layer data remain mock/placeholder surfaces until provider and
  tile pipeline work is implemented.
- User reports are pending Phase 5 API/governance implementation.
