# ADR-0008: Score Versioning and Explainability

## Title

Score Versioning and Explainability

## Status

Accepted

## Date

2026-04-28

## Context

Every risk result must be explainable through evidence. The SDD requires new scoring factors to use versioned scoring config, public exports to include score version, and AI/NLP outputs to preserve evidence ID, model version, and test fixtures.

Flood risk decisions may change as sources, weights, thresholds, or model helpers improve. Users and maintainers need to know which scoring logic produced a result.

## Decision

Version every scoring configuration. The initial version is `risk-v0`.

Every risk response and persisted score artifact must include score version, risk level, confidence, main factors, evidence IDs, source timestamps, source freshness, and missing source information when applicable.

Every scoring change that affects output semantics must either create a new score version or be documented by ADR when it changes the architecture or public contract.

Maintain golden fixtures for score versions. Any NLP or classifier-assisted evidence processing must include model version, evidence linkage, and fixture coverage.

## Consequences

Risk outputs are reproducible and auditable across time.

Users can inspect why a location received a risk level.

The project must keep compatibility and migration behavior in mind when changing score versions.

More metadata must be stored and returned, but it directly supports trust and debugging.
