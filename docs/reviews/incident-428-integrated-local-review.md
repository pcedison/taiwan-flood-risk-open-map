# Incident #428 integrated local review

Date: 2026-10-24. Work package: WP-012. Refs #428.
Branch: `fix/428-db-resilience-integrated`.
Base: `44f616a0b8f6477abc9041119bca9041949cd43d`.
At the end of this recorded local integration pass, all changes were uncommitted.
No remote CI, provider login, production request, push, merge, deployment or
database operation was performed in that pass. Subsequent publication and CI
results belong to the linked PR. This is local review, not an independent
reviewer approval.

## Integrated change

- Safe readiness database failure metadata: fixed operation/stage, exception
  class, validated SQLSTATE and elapsed milliseconds, without exception text,
  traceback, DSN, hostnames, SQL or user queries. Public 503 behavior is retained.
- Assessment-scoped pool acquisition timeout state, covering load and persist.
  Only PoolTimeout raised while entering the connection context trips it.
  Query-body and transaction-exit failures cannot trip acquisition state.
- ContextVar token resets in finally; each assess invocation has a fresh set,
  isolated by database and request context. No global outage flag is introduced.
- Existing partial evidence, unknown-risk semantics and cache admission remain
  unchanged. Cache hits preserve the response identity and original timestamps.
- Integration review added a transaction-exit PoolTimeout regression and corrected
  the existing database-probe docstring from /health to /ready.

## Review evidence

Tests cover acquisition timeout through actual repository/service code,
load-plus-persist using one acquisition, next-request retry, independent contexts,
parallel threads, different databases, prior-success retention, loaded high-risk
signals after later failure, per-section independent degradation, unknown/no-cache
on complete unavailability, original cache timestamps, query cancellation,
UndefinedTable and general OperationalError in query bodies, transaction-exit
failure, and sanitized readiness failures including a real loopback unavailable port.
The eight-to-one wait comparison uses a fake exhausted pool: forty versus five
seconds are simulated configured budgets, not measured production latency.

## Final integrated verification

These are fresh results from this integrated tree, not a sum of branch results.

| Scope | Command (cwd) | Result |
|---|---|---|
| Full API | `python -m pytest -q --basetemp ../../../db-integrated-final-pytest-temp` (`apps/api`) | 945 passed, 21 skipped; one pre-existing Starlette/httpx deprecation warning |
| Full workers | `python -m pytest -q --basetemp ../../../db-integrated-worker-temp` (`apps/workers`) | 1348 passed, 81 skipped |
| Cross-app / migrations / workflow contracts | Command below (repository root) | 144 passed |
| Python compile | `python -m compileall -q apps/api apps/workers` | passed |
| Backend lint | `python -m ruff check apps/api/app apps/api/tests apps/workers/app apps/workers/tests tests` | passed |
| API types | `python -m mypy app` (`apps/api`) | 75 source files passed |
| Worker types | `python -m mypy app` (`apps/workers`) | 118 source files passed |
| Repository validators | Seven commands below | all passed |
| Compose static config | `docker compose config --quiet` | passed; no containers started |
| Whitespace | `git diff --check` | passed |

```powershell
python -m pytest tests/test_official_dual_parse_contract.py tests/test_source_registry_validator.py tests/test_render_source_catalog_runtime_state.py tests/test_freshness_threshold_contract.py tests/test_apply_migrations_script.py tests/test_ingestion_readiness_migration.py tests/test_ncdr_alert_area_boundary_contract.py tests/test_ncdr_public_active_feed_contract.py tests/test_safe_fast_official_incident_release_contract.py tests/test_seed_perf_fixture_guard.py tests/test_ci_workflow.py tests/test_hosted_deployment_smoke.py tests/test_hosted_monitoring_workflow.py tests/test_hosted_monitoring_schedule_watchdog_workflow.py tests/test_hosted_source_freshness_smoke.py tests/test_hosted_public_risk_evidence_smoke.py tests/test_route_alert_issue_js.py tests/test_zeabur_single_service_deploy.py -q --basetemp ../db-integrated-guardrails-final-temp
python infra/scripts/validate_openapi.py
python infra/scripts/validate_contract_fixtures.py
python infra/scripts/validate_migrations.py
python infra/scripts/validate_source_allowlist.py
python infra/scripts/validate_source_registry.py
python infra/scripts/validate_monitoring_assets.py
python infra/scripts/validate_production_readiness_evidence.py
```

The first guardrail run was 142 passed / 2 failed due to CRLF source-catalog
input. The unchanged renderer/test files on the original isolated branch
reproduced the same two failures (9 passed / 2 failed). Git reports index LF,
worktree CRLF. Only the integrated catalog checkout bytes were normalized to LF
after checking exact equality with the base Git blob. No catalog content,
renderer code, test assertion or Git setting changed; catalog has no Git diff.
The full guardrail command then passed 144/144. A future Windows CRLF checkout
can reproduce the existing fixture limitation; this pass does not fix that
unrelated test portability issue.

Both original branch diffs still match their saved patch hashes, and the user's
original 13 uncommitted files remain hash-identical. No changes were written to
those original trees by this integration pass.

## Remaining limitations

- Production database root cause is unproven. The earlier existing Zeabur CLI
  authentication was 401; no login or provider operation was attempted here.
- Readiness uses fresh connections and bypasses the request pool. This patch
  cannot repair or explain simultaneous fresh-connection failures by itself.
- The fail-fast scope limits repeated pool waits only, not total request time.
  Several SQL readers default to no application statement timeout; actual
  server-side settings remain unknown. No timeout/health/freshness gate changed.
- If the pool recovers mid-assessment, unread sections remain unavailable until
  the next assessment. Already loaded evidence remains available.
- New diagnostics only exist after an approved deployment and cannot recover
  missing historical errors. OperationalError without SQLSTATE still needs
  provider evidence to distinguish DNS, TLS, authentication and transport faults.
- Skipped tests are not passing database acceptance. No live PostGIS migration
  rehearsal, Docker image build, frontend/browser suite or remote CI ran in this
  pass; no SQL/schema/frontend/dependency/runner change is included.
- Local Python is 3.13; CI uses 3.12. Remote CI remains pending authorization.
