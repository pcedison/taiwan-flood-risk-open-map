# ADR-0005: Dual Risk Score Model

## Title

Dual Risk Score Model

## Status

Accepted

## Date

2026-04-28

## Context

Users need both immediate flood risk and historical reference risk for housing or location decisions. The SDD also requires confidence, evidence lists, explanations, and public UI labels of `低`, `中`, `高`, and `極高`, with `未知` used when data is insufficient. Query heat must remain separate from risk.

Combining all signals into a single opaque number would make the result harder to explain and easier to misuse.

## Decision

Maintain a dual risk model:

- Realtime risk: current or near-current signals such as rainfall, warnings, water level, recent reports, and source freshness.
- Historical reference risk: historical flood potential, past events, recurring public evidence, and static geospatial context.

Expose confidence separately from risk. Confidence is based on freshness, source diversity, spatial precision, adapter health, and missing source status.

Render public risk using levels: `低`, `中`, `高`, `極高`, and `未知`. Internal numeric scores may exist, but explanations must show the main contributing evidence and factors.

Query heat is not an input to either risk score.

## Consequences

Users can distinguish current danger from longer-term reference risk.

The model is easier to explain, test, and tune through golden fixtures.

UI and API responses must carry more fields than a single score.

Scoring configuration and thresholds must be versioned to keep results reproducible.
