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

## Local Development

Follow the README [Quick Start](README.md#quick-start-local) to boot the stack
with Docker Compose. The one step people miss: **run migrations before the API
will work** — `docker compose --profile tools run --rm migrate`.

Verification commands (run the ones matching what you changed):

```bash
# Python (API + workers)
python -m pytest apps/api/tests -q
python -m pytest apps/workers/tests -q
python -m ruff check apps/api/app apps/api/tests apps/workers/app apps/workers/tests
cd apps/api && python -m mypy app && cd ../..
cd apps/workers && python -m mypy app && cd ../..

# Web
npm run lint --prefix apps/web
npm run typecheck --prefix apps/web
npm test --prefix apps/web
npm run build --prefix apps/web

# Contract / repo validators (CI runs all of these)
python infra/scripts/validate_openapi.py
python infra/scripts/validate_contract_fixtures.py
python infra/scripts/validate_migrations.py
python infra/scripts/validate_source_allowlist.py
```

Style: Python follows `ruff` + `mypy` (already configured); TypeScript follows
the ESLint config in `apps/web`. Match the conventions of the file you are
editing.

## Community and Security

- Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security reports: [SECURITY.md](SECURITY.md) — never use public issues for
  vulnerabilities.
- Issues and PRs use the templates in `.github/`.

## Subagent Rule

Multiple agents may work in parallel. Do not revert or overwrite another
agent's changes. Coordinate contract changes through the integration owner.
