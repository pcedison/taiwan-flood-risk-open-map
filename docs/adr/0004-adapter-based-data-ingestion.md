# ADR-0004: Adapter-Based Data Ingestion

## Title

Adapter-Based Data Ingestion

## Status

Accepted

## Date

2026-04-28

## Context

The MVP requires official weather, water, and flood-potential adapters plus at least one non-official public evidence adapter, subject to legal review. The SDD requires all external data sources to enter through a `DataSourceAdapter` interface and states that adding a source should not modify the risk model core.

Source reliability, freshness, legal terms, data shape, and failure modes will vary across official APIs, files, news/RSS, public web, forums, and future sources.

## Decision

Use adapter-based ingestion for every external source.

Each adapter must convert source-specific data into normalized evidence records with source type, source timestamp, ingestion status, location inference, confidence, and source URL or attribution metadata where available.

Use a raw snapshot, staging, validation, and promote flow for ingestion. Adapter failures must be isolated so they do not bring down the API or unrelated sources.

Adapters must be configurable and disableable. Optional public/forum adapters remain disabled until source terms and legal constraints are reviewed.

## Consequences

New data sources can be added with adapter and mapping work rather than core risk engine changes.

The project gains clearer source freshness and ingestion health tracking.

Every adapter needs fixtures, normalization tests, and failure behavior.

The ingestion pipeline has more structure than direct API calls, but it is easier to audit and recover.
