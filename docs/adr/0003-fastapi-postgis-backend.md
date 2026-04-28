# ADR-0003: FastAPI and PostGIS Backend

## Title

FastAPI and PostGIS Backend

## Status

Accepted

## Date

2026-04-28

## Context

The MVP requires address or map-click search, radius query, PostGIS spatial search, evidence lookup, risk scoring, and health endpoints. The SDD names FastAPI, PostgreSQL/PostGIS, Redis, MinIO, background workers, and database migrations as core building blocks.

The backend must keep domain logic framework-independent. UI components should call backend APIs instead of external sources directly. Database migrations must be repeatable, reversible where feasible, and verifiable in CI.

## Decision

Use FastAPI for the backend API service.

Use PostgreSQL with PostGIS for persistent spatial data, evidence metadata, scoring inputs, and queryable geospatial relationships.

Use Redis for cache and background job coordination where needed. Use MinIO-compatible object storage for raw snapshots and larger artifacts.

Keep risk calculation, evidence normalization, and geospatial rules in domain services that do not depend on FastAPI.

Manage database schema through ordered migrations under the repository migration area. Any database change must include a migration and deployment notes when it affects runtime behavior.

## Consequences

FastAPI and Python provide a practical path for API, geospatial, ingestion, and ML/NLP-adjacent workflows.

PostGIS gives the project first-class radius and spatial indexing support.

The team must maintain migration discipline and avoid ad hoc database changes.

Backend APIs become the stable boundary between UI, workers, data sources, and domain logic.
