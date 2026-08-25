# Core Task 9 implementation report

Date: 2026-08-25

Branch: `codex/v1-official-community`

Exact starting commit: `7a6ead2722ccd937184e98383910c9abd7f680e3`

Task commit: the commit containing this report, with message
`feat: distinguish healthy empty warning polls` (the authoritative SHA is
reported from `git rev-parse HEAD` after the commit because a commit cannot
embed its own SHA).

## Outcome

Core Task 9 is implemented on the authoritative Mac-led branch. The exact
reviewed CWA/NCDR warning sources can now persist a successful
`no_active_event` poll without fabricating evidence or an observation. Warning
freshness uses validated active windows, historical/background sources use
operational fetch completion while retaining authentic event timestamps, and
no-active retirement is serialized against warning lifecycle promotion with
generation-monotonic anti-resurrection behavior. API source health consumes the
persisted marker and catalog freshness thresholds without creating query-local
coverage or weakening the public low-risk gate.

No source was registered or enabled, no catalog migration was changed, no
legacy `public_risk` bridge was ported, and Task 14 was not started.

## Seven-slice TDD record

All commands below were run in the app directory with its dedicated virtual
environment. Worker and API pytest processes were kept separate.

### Slice 1 — backward-compatible defaults

RED:

```bash
../../.venv/workers/bin/python -m pytest \
  tests/test_ingestion_job_runner.py::test_task9_result_and_summary_fields_have_backward_compatible_defaults -q
../../.venv/api/bin/python -m pytest \
  tests/test_nearby_realtime_coverage.py::test_source_health_task9_fields_have_backward_compatible_defaults -q
```

- Worker: 1 failed because `AdapterRunResult.no_active_event` did not exist.
- API: 1 failed because `RealtimeSourceHealthRow.latest_run_error_code` did not
  exist.

GREEN: each focused test passed after adding only defaulted constructor fields.

### Slice 2 — exact valid-empty ingestion semantics

RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_ingestion_job_runner.py -q \
  -k 'valid_empty_warning or plain_or_rejected_empty_warning or station_empty_result'
```

Result: 2 failed, 2 passed. Both reviewed warning valid-empty cases were still
reported as skipped; the negative plain/rejected and station cases already
retained their safe behavior.

GREEN: 5 selected cases passed after the exact warning-key result marker was
implemented, including the unchanged adapter-failure path. No empty staging
snapshot was written.

### Slice 3 — warning windows and background cadence

RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_freshness_monitoring.py -q \
  -k 'background_source or long_lived_warning or warning_window or no_active_warning or ncdr_cap'
```

Result: 10 failed, 2 passed. Failures covered background operational freshness,
separate validated active-window fields, healthy no-active freshness, and
preservation of authentic warning source timestamps.

GREEN:

```bash
../../.venv/workers/bin/python -m pytest \
  tests/test_ingestion_job_runner.py tests/test_freshness_monitoring.py -q
```

The then-current focused set passed (38 tests). Missing, malformed, future, and
expired windows were not rescued; an old CAP `sent` time remained operational
only when the validated active window contained the check time.

### Slice 4 — managed-cycle test seam and registry restoration

This slice changed only test fixtures. The production behavior needed by the
managed cycle was already supplied by slices 2 and 3, so there was no honest
production RED to manufacture.

```bash
../../.venv/workers/bin/python -m pytest tests/test_runtime_managed_ingestion.py -q \
  -k 'managed_valid_empty_warning or plain_empty_or_failed_warning or managed_active_long_lived_warning or managed_historical_flood'
```

Result: 6 passed through the real `run_v1_baseline_adapter_cycle` seam. The
test-local registry fixture patches and restores all three imported registry
views; no production adapter registration or enablement was added.

### Slice 5 — no-active retirement writer and managed ordering

RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_promotion_pipeline.py -q \
  -k 'no_active_retirement'
../../.venv/workers/bin/python -m pytest tests/test_runtime_managed_ingestion.py -q \
  -k 'no_active_retirement'
```

- Promotion writer: 3 failures because the retirement method did not exist.
- Managed runtime: 2 failures, 1 pass because retirement was not invoked and
  its failure could not be contained.

GREEN: 6 selected cases passed. Retirement occurs only after successful summary
persistence, only with `promote=True`, and exceptions return the explicit
`no_active_event_retirement_failed` managed result.

### Slice 6 — live monotonicity and anti-resurrection

RED:

```bash
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_monotonicity_postgres.py -q -rs \
  -k 'older_empty_generation or newer_empty_generation'
```

Result: the four two-connection generation/commit-order cases produced one
expected failure: when the newer empty transaction committed first, the older
Alert could still resurrect latest state.

Unit RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_promotion_pipeline.py -q \
  -k 'alert_not_newer_than_persisted_no_active'
```

Result: 1 failed because Alert/Update promotion did not query the persisted
maximum successful no-active generation.

GREEN: the unit case and all four live race cases passed after adding the query
under the existing lifecycle lock and retaining blocked candidates as
historical audit evidence only. Two further live acceptance cases also pass:
same-adapter retirement preserves peer-adapter latest and both evidence rows,
and malformed latest generation fails closed.

### Slice 7 — persisted API health and source thresholds

RED:

```bash
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository.py tests/test_nearby_realtime_coverage.py -q \
  -k 'task9 or threshold or no_active or skipped_warning or source_observation_freshness'
```

Result: 9 failed, 3 passed. The SQL projection, mapping/positional conversion,
catalog thresholds, CWA warning source, healthy-empty marker, and skipped-event
semantics were not yet present.

GREEN: all 12 selected cases passed. A recent successful persisted marker is
operational without a latest observation, but contributes zero local coverage
and does not lower the public safety gate.

## Changed files

Production:

- `apps/workers/app/adapters/contracts.py`
- `apps/workers/app/jobs/ingestion.py`
- `apps/workers/app/jobs/freshness.py`
- `apps/workers/app/jobs/runtime_managed.py`
- `apps/workers/app/pipelines/promotion.py`
- `apps/api/app/domain/evidence/repository.py`
- `apps/api/app/domain/realtime/nearby_coverage.py`

Tests:

- `apps/workers/tests/test_ingestion_job_runner.py`
- `apps/workers/tests/test_freshness_monitoring.py`
- `apps/workers/tests/test_runtime_managed_ingestion.py`
- `apps/workers/tests/test_promotion_pipeline.py`
- `apps/workers/tests/test_promotion_monotonicity_postgres.py`
- `apps/api/tests/test_evidence_repository.py`
- `apps/api/tests/test_nearby_realtime_coverage.py`

Report:

- `.superpowers/sdd/core-task-9-report.md`

## Final verification

Focused Worker:

```bash
../../.venv/workers/bin/python -m pytest \
  tests/test_ingestion_job_runner.py tests/test_freshness_monitoring.py \
  tests/test_runtime_managed_ingestion.py tests/test_promotion_pipeline.py \
  tests/test_promotion_monotonicity_postgres.py -q
```

Result: `153 passed, 55 skipped`. The skips are the expected optional live
database collection when the mandatory environment is absent from this
non-live focused invocation.

Focused API:

```bash
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository.py tests/test_nearby_realtime_coverage.py \
  tests/test_assessment_repository.py -q
```

Result: `125 passed`.

Mandatory live PostgreSQL:

```bash
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_monotonicity_postgres.py -q -rs
```

Result: `55 passed`, zero skips.

Full Worker:

```bash
../../.venv/workers/bin/python -m pytest -q
```

Result: `681 passed, 55 skipped`.

Full API:

```bash
../../.venv/api/bin/python -m pytest -q
```

Result: `666 passed, 13 skipped, 1 warning`. The warning is the existing
Starlette/httpx TestClient deprecation from the installed dependency.

Static and contract checks:

```bash
# apps/workers
../../.venv/api/bin/python -m mypy app
# apps/api
../../.venv/api/bin/python -m mypy app
# repository root
.venv/api/bin/python infra/scripts/validate_openapi.py
git diff --check
```

Results:

- Worker mypy: success, 106 source files.
- API mypy: success, 68 source files; one informational note about an existing
  untyped function body.
- OpenAPI: `OpenAPI 3.1 spec valid. paths=15 schemas=75`.
- `git diff --check`: clean.

Scoped Ruff passed for every changed Task 9 Python file. Full-tree Ruff 0.16.4
still reports the pre-existing baseline outside the now-clean scoped files:

- Worker: 227 findings (136 safe-fixable).
- API: 150 findings (73 safe-fixable).

No unrelated mass-formatting was performed.

## Self-review

- Confirmed the generic Task 7 managed/scheduler facade remains unchanged;
  Task 9 enters through `run_v1_baseline_adapter_cycle` and the existing private
  engine only.
- Confirmed Task 8 accepted-staging authorization, geometry checks, generation
  propagation, lifecycle lock key, and warning lock ordering remain intact.
- Confirmed no-active retirement deletes only same-adapter warning latest rows
  with valid generation less than or equal to the empty generation and never
  deletes linked evidence.
- Confirmed blocked older/equal Alert/Update candidates keep audit evidence as
  historical-only and never upsert latest.
- Confirmed the public assessment path remains persisted-only; there are no
  request-time official fetches and no legacy bridge calls.
- Confirmed all source/catalog migrations and production adapter registration or
  enablement are untouched.
- Confirmed the four existing untracked `docs/reviews/*.md` handoff/readiness
  files remain unmodified and unstaged.
- Confirmed the branch is retained for independent review; no merge, push,
  deployment, cleanup, or self-approval was performed.

## Concerns and reviewer focus

- Full-tree Ruff remains red only because of the documented pre-existing Worker
  and API baselines above; all Task 9 changed files are clean.
- Expected optional database skips remain in ordinary full/focused Worker runs;
  the mandatory live run separately passed all 55 cases with zero skips.
- The API suite emits one existing third-party TestClient deprecation warning.
- This is implementer self-review only. Independent approval is still required.

## Independent review fix wave 1

Date: 2026-08-25

Review base: `72e382c3df9e50265f59b4f1f7e94c6e934fae2f`

Commit message: `fix: protect no-active warning state`

### Critical — blocked audit-only Update lifecycle mutation

Root cause: `blocked_by_no_active_event` disabled latest upsert, but the later
Update/Cancel branch still invoked `_retire_cap_references`. That unguarded
DELETE could remove referenced same- or peer-reviewed-adapter warning latest
rows even though the candidate was historical audit evidence only.

Unit RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_promotion_pipeline.py -q \
  -k 'update_blocked_by_no_active'
```

Result: `1 failed, 87 deselected`. The assertion proved that the executed SQL
still contained `/* retire-cap-references */`.

Live PostgreSQL RED:

```bash
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_monotonicity_postgres.py -q -rs \
  -k 'blocked_update_keeps_same_and_peer'
```

Result: `1 failed, 55 deselected`. The blocked Update audit evidence was
retained, but the actual DELETE path removed both referenced latest rows
(`latest_rows == []`).

Fix: reference retirement is now guarded by
`not blocked_by_no_active_event`. Blocked Alert/Update candidates keep their
historical-only audit evidence and perform no latest upsert or reference
retirement. Ordinary newer Update and Cancel behavior is unchanged.

Targeted GREEN:

```bash
../../.venv/workers/bin/python -m pytest tests/test_promotion_pipeline.py -q \
  -k 'update_blocked_by_no_active or cap_mutation_retires_only_exact_reference_triples'
```

Result: `3 passed, 85 deselected`, covering the blocked branch plus ordinary
Update/Cancel reference retirement.

The strengthened live case uses two referenced current Alerts (same CWA adapter
and peer NCDR adapter) whose ingestion generations are newer than the equal
no-active marker. It passed with both latest rows retained and the blocked
Update evidence stored as `historical` with reason
`superseded_by_no_active_event`.

### Important — skipped/partial static background freshness

Root cause: the static cadence branch used `finished_at` and returned fresh for
every non-failed status. Skipped/empty and partial summaries therefore bypassed
their unsuccessful batch outcome.

RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_freshness_monitoring.py -q \
  -k 'unsuccessful_background_source'
```

Result: `4 failed, 25 deselected`. Both
`official.wra.historical_flood` and `official.flood_potential.geojson` returned
fresh for both skipped and partial summaries.

Fix: an explicit static/background non-success branch now returns an alerting
`stale` check with a `static/slow-cadence batch did not succeed` reason and the
authentic summary source timestamp. Only `succeeded` static batches use
completion-time operational freshness.

Targeted GREEN:

```bash
../../.venv/workers/bin/python -m pytest tests/test_freshness_monitoring.py -q \
  -k 'background_source'
```

Result: `6 passed, 23 deselected`, covering successful completion-time
freshness and both non-success statuses for both exact background keys.

### Fix-wave final verification

Required focused Worker:

```bash
../../.venv/workers/bin/python -m pytest \
  tests/test_freshness_monitoring.py tests/test_promotion_pipeline.py \
  tests/test_promotion_monotonicity_postgres.py -q
```

Result: `117 passed, 56 skipped`. The skips are the expected optional live
database cases in the non-live focused invocation.

Mandatory live PostgreSQL:

```bash
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_monotonicity_postgres.py -q -rs
```

Result: `56 passed`, zero skips.

Full Worker:

```bash
../../.venv/workers/bin/python -m pytest -q
```

Result: `686 passed, 56 skipped`.

Static checks:

```bash
../../.venv/workers/bin/python -m ruff check \
  app/jobs/freshness.py app/pipelines/promotion.py \
  tests/test_freshness_monitoring.py tests/test_promotion_pipeline.py \
  tests/test_promotion_monotonicity_postgres.py
../../.venv/api/bin/python -m mypy app
git diff --check
```

Results: scoped Ruff passed; Worker mypy passed for 106 source files; diff check
passed. No API production file changed, so the prior full API/OpenAPI evidence
above remains applicable.

The full-tree Ruff baseline concerns documented above are unchanged. This fix
wave remains implementer work pending another independent review; it was not
self-approved, pushed, merged, or deployed.

## Integration milestone safety-fix wave 2

Date: 2026-08-25

Review base: `f675af3c90902bcb9163eea979a2073ca14e1258`

Commit: the commit containing this report, with message
`fix: close Task 9 milestone safety gaps`. Because a commit cannot embed its
own final SHA, `git rev-parse HEAD` after this commit is the authoritative
identifier.

The independent integration milestone review found one critical race and six
important code/operator-documentation gaps after the earlier task-level
approval. This wave closes all findings without changing the frozen generic
runtime, Task 8 staging authorization, persisted-only assessment boundary, or
source registration/enablement state.

### RED/GREEN evidence

#### Trusted result identity, exact empty shape, and disjoint warning windows

RED:

```bash
../../.venv/workers/bin/python -m pytest \
  tests/test_ingestion_job_runner.py tests/test_runtime_managed_ingestion.py \
  -k 'mismatch or nonempty_normalized or disjoint_expired' -q
```

Result: `4 failed, 41 deselected`. A forged result key was accepted as NCDR,
a nonempty normalized result became `no_active_event`, and expired-plus-future
alerts for both reviewed keys were combined into a false active interval.

GREEN: the same selection returned `4 passed, 41 deselected`. Managed-cycle
coverage was then added for trusted-key failure plus normalized and inventory
proof incompatibilities; `3 passed, 28 deselected`. The shared warning-window
evaluation instant is the authenticated raw snapshot fetch time, so historical
test fixtures remain deterministic while disjoint intervals cannot bridge a
gap.

#### Atomic no-active marker and generation-safe CAP reference retirement

Marker RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_ingestion_run_writer.py \
  -k locks_warning_lifecycle -q
```

Result: `1 failed, 12 deselected`; the ingestion job insert occurred without
the warning lifecycle advisory lock. GREEN after the minimal lock change:
`13 passed` for the full run-writer suite.

Reference-retirement RED:

```bash
../../.venv/workers/bin/python -m pytest tests/test_promotion_pipeline.py \
  -k cap_mutation_retires_only_exact_reference_triples -q
```

Result: `2 failed, 86 deselected`; the reference DELETE had no validated latest
generation guard. GREEN: `2 passed, 86 deselected`; ordinary Update/Cancel
retirement remains effective only for referenced latest rows with a valid
generation less than or equal to the mutation generation.

The review's live reproduction had already demonstrated the composite bug:
both same- and peer-adapter latest rows were deleted when an older Update held
the lock while a newer empty marker committed. After the two constituent RED
fixes, the new mandatory two-connection composite test passed on its first run
for both `update_first` and `empty_marker_first`. It asserts same- and peer-row
survival and the historical-only Update state when the marker commits first.
The marker lock is acquired only after adapter fetch/normalization is complete;
no upstream request is made while it is held.

#### Safe catalog thresholds in health, latest coverage, and evidence fallback

RED:

```bash
../../.venv/api/bin/python -m pytest tests/test_evidence_repository.py \
  -k 'query_nearby_realtime_coverage_rows_counts_radius_buckets or \
      query_nearby_realtime_coverage_rows_falls_back_to_official_evidence_when_latest_empty or \
      query_realtime_source_health_rows_returns_public_safe_runtime_state' -q
```

Result: `3 failed, 38 deselected`. Both coverage queries still used fixed
10/30-minute windows, and source health still exposed an unsafe direct integer
cast.

GREEN: `3 passed, 38 deselected`. One reusable lateral SQL resolver now trims
metadata, accepts only `1..86400`, falls back to 600, and is reused by source
health station counts/projection plus both coverage paths. A live full-query
regression passed all values: whitespace-wrapped 120, nonnumeric text, zero,
negative, a 1000-digit overflow input, 86401, and valid 86400. A stale
short-cadence redundant rainfall row is also proven unable to satisfy the low
coverage gate.

### Durable operator report corrections

`docs/reviews/remote-integration-2026-08-25.md` now distinguishes the
`49fbb79` remote-comparison snapshot, original Task 9 head, pre-fix review head,
and this safety-fix commit. Its activation path is now explicitly:

`Tasks 10–13 -> Task 14A/B (0038, rows disabled) -> Task 15 -> Task 16 isolated proof/operator activation`.

Task 14A/16 own scoped v1 command wiring, Docker entrypoint,
Compose/Zeabur contract tests, database aliases, and runtime documentation.
Preview deployments must omit `SERVICE_ROLE=scheduler` and explicitly map
`DATABASE_URL` until those contracts are ported. Production remains **NO-GO**.

### Fix-wave verification

Focused Worker lifecycle suites:

```bash
../../.venv/workers/bin/python -m pytest \
  tests/test_ingestion_job_runner.py tests/test_ingestion_run_writer.py \
  tests/test_freshness_monitoring.py tests/test_runtime_managed_ingestion.py \
  tests/test_promotion_pipeline.py -q
```

Result: `178 passed`.

Mandatory live PostgreSQL:

```bash
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@localhost:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_monotonicity_postgres.py -q
```

Result: `58 passed`, zero skips.

Focused API:

```bash
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository.py tests/test_nearby_realtime_coverage.py \
  tests/test_assessment_repository.py -q
```

Result: `126 passed`.

Live API threshold full-query regression:

```bash
EVIDENCE_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@localhost:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
../../.venv/api/bin/python -m pytest \
  tests/test_evidence_repository_postgres.py -k safely_resolves_bounded -q
```

Result: `1 passed, 13 deselected`.

Full suites:

- Worker: `694 passed, 58 skipped` (the skips are optional live collection;
  the required live process above has zero skips).
- API: `667 passed, 14 skipped, 1 warning` (the existing third-party
  Starlette/httpx TestClient deprecation).

Static/contract checks:

- Worker mypy: success, 106 source files (run with the API tooling venv because
  the Worker venv intentionally has no mypy package).
- API mypy: success, 68 source files; only the existing informational note
  about an untyped function body.
- Scoped Ruff: all changed Worker/API Python files passed.
- OpenAPI: `OpenAPI 3.1 spec valid. paths=15 schemas=75`.
- `git diff --check`: clean before commit.

This is implementer evidence, not self-approval. No merge, rebase, push,
deployment, source activation, or mutation of the three user-owned untracked
handoff files was performed.
