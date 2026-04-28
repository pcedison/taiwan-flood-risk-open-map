# Flood Risk Workers

Worker and scheduler skeleton for ingestion, scoring, and maintenance jobs.

## Entry points

- Single sample job: `python -m app.main --once`
- Scheduler loop placeholder: `python -m app.scheduler`

The current implementation uses only Python standard library modules so it can run before queue dependencies are selected.

