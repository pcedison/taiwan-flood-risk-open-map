# Flood Risk API

FastAPI Phase 1 public API routes and service health.

## Entry points

- FastAPI app: `app.main:app`
- Docker Compose command: `pip install -e . && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Local FastAPI command after installing dependencies: `python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Current scope

- `/health`
- `/v1/geocode` mock provider
- `/v1/risk/assess` mock assessment
- `/v1/evidence/{assessment_id}` mock evidence list
- `/v1/layers` and `/v1/layers/{layer_id}/tilejson` mock layer metadata
- Environment-based settings loader
- Structured error payload helper
- Focused public contract tests
