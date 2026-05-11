# ADR-0009: Precomputed Risk Profiles and Vector-Assisted Evidence

## Title

Precomputed Risk Profiles and Vector-Assisted Evidence

## Status

Accepted

## Date

2026-05-08

## Context

Public beta users will search many locations that have never been queried before.
If every cold lookup waits for exact-radius PostGIS searches, official source
refresh checks, and public-news enrichment, the first user for each location can
experience slow or incomplete results. That is especially painful for a Taiwan-wide
flood-risk map, where users expect a useful first answer even outside the
locations already warmed by previous traffic.

The project also needs a clear answer to whether Taiwan should be pre-split into
county, township, village, neighborhood, or grid units, and whether vector storage
should be used to reduce database size or speed access.

## Decision

Use precomputed administrative-area and grid risk profiles as the primary cold
lookup optimization.

Initial profile scopes are county, township/district, village, and H3/geohash
cells at roughly 500m-1km equivalent resolution. Neighbor-level (`lin`/鄰)
profiles are deferred until reliable open boundary data, privacy-density review,
and public explanation wording are accepted.

Profiles are derived summaries, not source evidence. They must be computed from
accepted evidence, official flood-potential data, historical/news evidence,
source freshness, score version, and explicit coverage gaps. Public beta profile
aggregation starts with a 2km preview radius or an accepted polygon/buffer rule.

The `/v1/risk/assess` read path should resolve the query point to village/town and
grid cell, read the freshest matching profile when the exact radius result is
cold or slow, label the response as profile-backed, and enqueue an exact-radius
refresh job in the background.

Query heat may influence profile refresh priority, source backfill priority,
cache warming, review queues, and public attention indicators. Query heat must
not directly increase realtime risk, historical risk, or confidence scores.

Vector embeddings may be added only as an auxiliary evidence-intelligence layer
for public-news deduplication, semantic relevance ranking, ambiguous location
matching, and reviewer triage. Vector similarity alone cannot create accepted
evidence, raise a risk level, or satisfy public explanation. Every vector-derived
candidate must link to source metadata, an evidence or staging evidence ID, model
version, geospatial confidence, and PostGIS geometry or explicit uncertainty.

## Consequences

Cold public beta searches can return a faster, evidence-backed first answer while
exact-radius refresh completes asynchronously.

The project needs new migrations, profile builders, profile refresh jobs,
cache/staleness rules, UI labels, and golden fixtures comparing profile-backed
results with exact-radius results.

Profiles introduce eventual consistency. Responses must show profile scope,
radius or polygon rule, `computed_at`, `expires_at`, score version, and missing
source warnings so users do not mistake profile-level summaries for address-level
certainty.

Embeddings are not a guaranteed storage reduction. They add storage and
operational complexity, but can improve deduplication and review efficiency when
bounded by evidence linkage, retention, and takedown rules.
