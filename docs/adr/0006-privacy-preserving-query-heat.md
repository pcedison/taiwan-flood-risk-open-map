# ADR-0006: Privacy-Preserving Query Heat

## Title

Privacy-Preserving Query Heat

## Status

Accepted

## Date

2026-04-28

## Context

The product includes query popularity aggregation, but query heat must not be treated as flood risk. The SDD prioritizes privacy, avoids unnecessary personal data, rejects social user profiling, and allows IP handling only for abuse prevention with hash, salt, and TTL.

Raw address searches, precise clicked coordinates, and stable user identifiers could reveal sensitive housing interests.

## Decision

Collect query heat only as aggregated counts over coarse spatial buckets and time windows.

Do not store raw addresses, raw query text, persistent user identifiers, or precise user-selected coordinates for query heat. If abuse prevention needs IP-derived signals, store only salted hashes with a short TTL and keep that data separate from analytics.

Apply minimum-count thresholds before exposing query heat publicly. Query heat must be labeled as popularity or attention, not flood evidence or risk.

Exclude query heat from all risk scoring models.

## Consequences

The project can show public interest trends without creating a sensitive search history database.

Analytics will be less precise than raw event logs.

Abuse and debugging workflows may need separate short-lived operational logs.

Public exports can include aggregated query heat only when thresholds and retention rules are satisfied.

## Enforcement Note (2026-07-06)

A sustainability audit found the implementation drifted from this decision:
`location_queries` persisted `raw_input` plus precise coordinates
indefinitely, `risk_assessments.result_snapshot` duplicated the precise
location and raw query text, and profile-refresh job payloads carried both
into `worker_runtime_jobs`. This was fixed by coarsening coordinates to the
~1 km privacy bucket at write time, never persisting raw query text, a data
migration (`infra/migrations/0033_location_queries_privacy.sql`) that
coarsens pre-fix rows, and a scheduler retention job that prunes
`location_queries` after `LOCATION_QUERIES_RETENTION_HOURS` (default 30
days). Known tradeoff: evidence `distance_to_query_m` recomputed from stored
query geometry (the post-cache fallback path) now carries up to ~1 km error.
