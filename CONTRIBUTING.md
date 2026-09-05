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

## Pull Request Rules

These apply to every PR, including ones opened by automation (Codex, Claude,
Dependabot excepted):

1. **Link an issue.** The PR body must contain `Fixes #N` or `Refs #N`. Work
   that has no issue gets an issue first; the issue states the user-visible
   problem, not the implementation.
2. **One PR, one change.** A fix, a refactor and a status update are three PRs.
   Do not open a PR whose only change is `PROJECT_STATUS.md`; status is
   recorded in the PR that changed the behaviour, or by the release checklist.
3. **Migrations that rewrite data need rehearsal evidence.** A migration that
   updates or deletes rows in `evidence`, `evidence_staging` or
   `official_realtime_latest` must link a staging-clone rehearsal (row counts
   before/after, duration) in the PR body. Catalog-row updates in
   `data_sources` do not need this. Migrations run inside the API start-up
   transaction, so a whole-table rewrite takes production down (see #317).
4. **Plans are not requirements.** Documents under `docs/superpowers/plans/`
   describe how a task could be done; the requirement is the linked issue and
   the SDD. A PR must not cite a plan document as its only justification.
5. **Monitoring red is a symptom.** A PR that changes a smoke test, watchdog or
   alert must state which upstream or code fault it responds to; loosening a
   check without a named cause is not accepted.
6. **Verification numbers, not adjectives.** The Verification section lists
   the commands run and their result counts; "tests pass" without numbers is
   incomplete.

## Subagent Rule

Multiple agents may work in parallel. Do not revert or overwrite another
agent's changes. Coordinate contract changes through the integration owner.
