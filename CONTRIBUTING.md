# Contributing

This project uses the SDD and work plan as the development contract.

Before changing behavior, data contracts, API schemas, database schema, scoring
rules, privacy policy, licensing, or deployment strategy, update the relevant
SDD section or add an ADR.

## Workflow

1. Pick a work package from `docs/PROJECT_WORK_PLAN.md`.
2. Keep edits within that package's ownership boundary.
3. Add or update tests for behavior changes.
4. Update OpenAPI, migrations, fixtures, or runbooks when contracts change.
5. Report changed files, tests run, known risks, and follow-up tasks.

## Subagent Rule

Multiple agents may work in parallel. Do not revert or overwrite another
agent's changes. Coordinate contract changes through the integration owner.
