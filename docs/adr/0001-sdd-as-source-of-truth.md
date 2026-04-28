# ADR-0001: SDD as Source of Truth

## Title

SDD as Source of Truth

## Status

Accepted

## Date

2026-04-28

## Context

Flood Risk is a spec-first project. The project needs one stable source for architecture, data contracts, privacy rules, deployment expectations, and subagent boundaries. The SDD states that code, data pipelines, models, UI, API, deployment, and tests must trace back to the SDD or later ADRs.

Multiple agents may work in parallel. Without a clear document authority order, agents could unintentionally change behavior through implementation details or README notes.

## Decision

Use `docs/PROJECT_SDD.md` as the highest design contract for the project.

Use `docs/adr/*.md` for architecture decisions that supplement, clarify, or intentionally revise the SDD. ADRs must not silently override the SDD. If an ADR changes an SDD-level contract, the ADR must state the change clearly and the SDD should be updated by the appropriate owner.

Use the following authority order:

1. `docs/PROJECT_SDD.md`
2. `docs/adr/*.md`
3. `docs/api/*.yaml`
4. `docs/runbooks/*.md`
5. Code comments and README files

Any change to risk scoring rules, data source assumptions, API contracts, database schema, background job contracts, map layer contracts, privacy/security policy, or subagent ownership boundaries requires an SDD update or a new ADR.

## Consequences

Project decisions become traceable and reviewable before implementation.

Parallel work is safer because agents can resolve conflicts against the same contract.

The project accepts some extra documentation overhead in exchange for auditability and lower integration risk.

Implementation-only notes cannot redefine requirements.
