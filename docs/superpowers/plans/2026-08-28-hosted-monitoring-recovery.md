# Hosted Monitoring Production Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore bounded official-realtime ingestion, keep later sources running when one source fails, align the flood-warning requirement contract with deployed gates, and obtain a successful manual plus scheduled Hosted Monitoring run without weakening the acceptance gate.

**Architecture:** Keep the existing per-source v1 scheduler and public API contract, but separate realtime promotion from historical backlog, reuse bounded PostgreSQL connections during promotion, enforce database wait limits, and add a per-source failure boundary. Use an append-only migration to make NCDR CAP the required flood-warning source and CWA heavy-rain warning its reviewed redundant subset until CWA production activation is independently approved.

**Tech Stack:** Python 3.12, psycopg 3, PostgreSQL/PostGIS 16, pytest, Ruff, SQL migrations, GitHub Actions/YAML, Node.js issue-routing tests, Zeabur single-service deployment.

## Global Constraints

- Read `docs/reviews/hosted-monitoring-incident-2026-08-28.md` before changing code. Its confirmed facts, unproven points, and acceptance criteria define this recovery.
- Begin every behavior change with a focused failing test. Record the expected RED result before implementation and rerun the same command for GREEN.
- Keep `scripts/hosted_public_risk_evidence_smoke.py` fail-closed for configured required sources. Do not add `continue-on-error`, do not classify `pipeline_stalled` as degraded, and do not remove timestamp/freshness requirements.
- Keep the Hosted Monitoring schedule at `7 */6 * * *` during P0 recovery. Alert cadence changes are optional P1 work after production is healthy.
- Realtime promotion may process only raw refs emitted by the current cycle. Historical accepted backlog requires an explicit bounded maintenance path and must never be swept by the scheduler.
- Preserve promotion safety: staging authorization, geometry validation, CAP lifecycle ordering, exact-message idempotency, central/local duplicate handling, latest-row monotonicity, terminal rejection, and per-candidate durable commit behavior.
- Reusing a connection must not turn an entire large batch into one all-or-nothing transaction. Commit each candidate; on candidate failure, roll back that candidate and return a managed source failure.
- Production PostgreSQL connection establishment, lock waits, and statement execution must all be bounded. A timeout becomes a public-safe failed pipeline state and the scheduler continues with the next source.
- Never log database URLs, credentials, CAP API keys, authorization headers, source response bodies, raw private evidence, or SQL parameter values. Log only adapter key, raw-ref count, candidate count, chunk index/count, elapsed milliseconds, status, and safe exception class.
- Preserve one-source execution isolation in `run_v1_baseline_adapter_cycle()`. A whole-tick runtime-selection override must not widen the adapters fetched, staged, promoted, or catalog-filtered by a scoped cycle.
- Do not rewrite deployed migration `0040_v1_official_baseline_source_mappings.sql`. Add `0041_v1_warning_source_requirement_alignment.sql`, update the migration README and schema-readiness sentinel, and make the API validate revision equality per reviewed contract instead of filtering every signal through one global revision literal.
- Until separate activation evidence exists, keep `official.cwa.heavy_rain_warning` disabled and make it a `redundant_subset` of required `official.ncdr.cap`. Do not enable it merely to make monitoring green.
- Keep the jurisdiction proof fail-closed: mapping revision, count, digest, reviewed timestamp, review reference, and redundancy-parent validity must all agree for every county.
- Do not combine issues #71, #73, or Dependabot PRs #185–#189 with the P0 runtime commits.
- Use Python 3.12 or newer. The repository imports `datetime.UTC`; system Python 3.9 is not a valid test runtime.
- Performance budgets for acceptance: 1,311 promotion candidates in less than five minutes for one source; all required sources and tick completion in less than fifteen minutes; no individual database statement waits more than 30 seconds and no lock waits more than 5 seconds.
- Do not claim recovery from local tests alone. Recovery requires the deployed SHA, source-completion logs, one successful manual Hosted Monitoring run, and one successful scheduled run.

---

## File and Responsibility Map

### Promotion scope, batching, and wait bounds

- Modify `apps/workers/app/pipelines/promotion.py` — add raw-ref filtering, bounded chunks, connection reuse, transaction-local lock/statement timeouts, and promotion lifecycle logs.
- Modify `apps/workers/app/jobs/runtime_managed.py` — pass only current-cycle raw refs to realtime promotion and skip historical backlog when the current cycle emitted no promotable raw ref.
- Modify `apps/workers/tests/test_staging_pipeline.py` — unit-test raw-ref filtering, legacy writer compatibility, chunking, ordering, and duplicate suppression.
- Modify `apps/workers/tests/test_runtime_managed_ingestion.py` — prove managed runtime sends only current raw refs and turns promotion timeout/failure into a failed managed result.
- Modify `apps/workers/tests/test_promotion_pipeline.py` — verify timeout setup and SQL-level promotion behavior with fakes.
- Modify `apps/workers/tests/test_promotion_monotonicity_postgres.py` — retain all PostgreSQL safety invariants through batch connection reuse and verify per-candidate durability.

### Scheduler liveness

- Modify `apps/workers/app/cli/runtime_cli.py` — preflight runnable sources, record the authoritative selection before ingestion, isolate construction/execution failures, continue the loop, and emit source/tick lifecycle logs.
- Modify `apps/workers/app/jobs/runtime_managed.py` — accept a validated reporting-only whole-tick selection without widening scoped execution.
- Modify `apps/workers/tests/test_v1_baseline_runner.py` — prove source B runs after source A raises or fails and prove the full selection is recorded before the first source starts.
- Modify `apps/workers/tests/test_runtime_managed_ingestion.py` — prove a reporting override cannot widen staging or promotion.

### Flood-warning requirement alignment

- Create `infra/migrations/0041_v1_warning_source_requirement_alignment.sql` — convert CWA heavy-rain warning to a reviewed redundant subset of NCDR and recompute all affected contract proofs at one new revision.
- Modify `infra/migrations/README.md` — document migration intent, disabled-source semantics, and operator activation rules.
- Modify `apps/api/app/domain/evidence/repository.py` — remove the global baseline-revision filter and emit mappings only when their revision equals the valid owning contract revision.
- Modify `apps/api/app/api/routes/health.py` — advance the schema-readiness sentinel to migration 0041 with its checked-in checksum.
- Modify `tests/test_v1_official_baseline_migration.py` — assert one required warning source, one valid redundant child, matching revision/digest, and all 22 county contracts.
- Modify `apps/api/tests/test_assessment_repository.py` — assert the redundant CWA source remains applicable for evidence but is absent from `required_realtime_source_keys`.
- Modify `apps/api/tests/test_evidence_repository.py` and `apps/api/tests/test_evidence_repository_postgres.py` — prove mixed signal-specific revisions remain visible only through a valid same-revision contract proof.
- Modify `apps/api/tests/test_public_contract.py`, `tests/test_apply_migrations_script.py`, and `infra/scripts/verify_migration_upgrade_0032_to_0036.py` — keep the migration manifest and readiness sentinel locked to 0041.
- Modify `tests/test_hosted_public_risk_evidence_smoke.py` — prove a disabled non-required redundant source does not fail absence health while a stalled required NCDR source still fails.
- Modify `tests/test_zeabur_single_service_deploy.py` only if implementation chooses activation instead of redundancy. Under this plan's default decision, the entrypoint remains unchanged and the test must continue proving CWA heavy-rain warning is not silently activated.

### Operational acceptance

- Modify `docs/runbooks/monitoring-freshness-alerts.md` — add the recovery verification sequence and explain manual versus scheduled evidence.
- Modify `docs/runbooks/zeabur-single-service-env.md` — document no new CWA gates are required for the redundancy decision and list the log events required before declaring a tick healthy.
- Keep `.github/workflows/hosted-monitoring.yml` unchanged during P0 unless an implementation defect in the workflow itself is newly proven.

---

### Task 1: Scope realtime promotion to the current cycle

**Files:**

- Modify: `apps/workers/app/pipelines/promotion.py`
- Modify: `apps/workers/app/jobs/runtime_managed.py`
- Modify: `apps/workers/tests/test_staging_pipeline.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`

**Interfaces:**

Extend the accepted-staging read contract without breaking callers that intentionally perform an unscoped maintenance promotion:

```python
class EvidencePromotionWriter(Protocol):
    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
        raw_refs: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]: ...


def promote_accepted_staging(
    writer: EvidencePromotionWriter,
    *,
    limit: int | None = None,
    adapter_keys: tuple[str, ...] | None = None,
    raw_refs: tuple[str, ...] | None = None,
) -> PromotionResult: ...
```

`raw_refs=None` retains the explicit maintenance/backfill behavior. A provided tuple must be non-empty, contain trimmed non-empty strings, and be deduplicated without changing order. The SQL adds `AND rs.raw_ref = ANY(%s)` and binds the list after `adapter_keys` and before `limit`.

The managed scheduler computes current refs only from successful or partial summaries for the selected promotion adapter keys:

```python
current_raw_refs = tuple(
    dict.fromkeys(
        summary.raw_ref
        for summary in cycle.summaries
        if summary.adapter_key in target_adapter_keys
        and summary.status in {"succeeded", "partial"}
        and summary.raw_ref is not None
    )
)
```

When `current_raw_refs` is empty, no accepted-staging fetch occurs. Warning `no_active_event` retirement still runs before this decision. Historical backlog is not promoted by the realtime scheduler.

- [ ] **Step 1: Add failing SQL and argument-validation tests**

Add these tests to `apps/workers/tests/test_staging_pipeline.py`:

- `test_accepted_staging_query_filters_to_requested_raw_refs`
- `test_accepted_staging_params_order_adapter_raw_ref_limit`
- `test_promote_rejects_empty_or_blank_raw_ref_filter`
- `test_promote_preserves_candidate_order_inside_raw_ref_scope`

Assert the generated SQL contains `rs.raw_ref = ANY(%s)`, parameters are `([adapter], [raw_ref], limit)`, and duplicate requested refs are normalized before the writer receives them.

- [ ] **Step 2: Add the failing managed-runtime regression**

Extend `_MemoryPromotionWriter` in `apps/workers/tests/test_runtime_managed_ingestion.py` to capture `requested_raw_refs`. Add:

```python
def test_managed_runtime_promotes_only_the_current_cycle_raw_ref() -> None:
    ...
    assert promotion_writer.requested_raw_refs == (
        result.summaries[0].raw_ref,
    )


def test_managed_runtime_does_not_sweep_backlog_without_a_current_raw_ref() -> None:
    ...
    assert promotion_writer.fetch_calls == 0
```

The second fixture must return a valid empty/no-staging cycle while its fake promotion writer contains an older accepted candidate; assert that older candidate is untouched.

- [ ] **Step 3: Run focused RED**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_staging_pipeline.py \
  tests/test_runtime_managed_ingestion.py -q
```

Expected: FAIL because `raw_refs` is not accepted or forwarded and the current scheduler fetches unscoped backlog.

- [ ] **Step 4: Implement raw-ref filtering**

Add `_normalized_raw_refs()`, extend `_accepted_staging_sql()` and `_accepted_staging_params()`, and forward the filter through `PostgresEvidencePromotionWriter.fetch_accepted_staging()` and `promote_accepted_staging()`.

In `_execute_managed_runtime_ingestion_cycle()`, compute `current_raw_refs` after warning retirement. Call promotion only when it is non-empty. Preserve the existing `promotion_limit`, adapter-key narrowing, status recording, and complete-replace activation rules.

- [ ] **Step 5: Run focused GREEN and lint**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_staging_pipeline.py \
  tests/test_runtime_managed_ingestion.py -q
../../.venv/workers/bin/ruff check \
  app/pipelines/promotion.py \
  app/jobs/runtime_managed.py \
  tests/test_staging_pipeline.py \
  tests/test_runtime_managed_ingestion.py
```

Expected: all selected tests pass and Ruff exits `0`.

- [ ] **Step 6: Commit current-cycle scoping**

```bash
git add \
  apps/workers/app/pipelines/promotion.py \
  apps/workers/app/jobs/runtime_managed.py \
  apps/workers/tests/test_staging_pipeline.py \
  apps/workers/tests/test_runtime_managed_ingestion.py
git commit -m "fix(worker): scope realtime promotion to current snapshots"
```

### Task 2: Reuse bounded promotion connections and enforce database wait limits

**Files:**

- Modify: `apps/workers/app/pipelines/promotion.py`
- Modify: `apps/workers/tests/test_staging_pipeline.py`
- Modify: `apps/workers/tests/test_promotion_pipeline.py`
- Modify: `apps/workers/tests/test_promotion_monotonicity_postgres.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`

**Interfaces and constants:**

```python
DEFAULT_PROMOTION_BATCH_SIZE = 100
DEFAULT_PROMOTION_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_PROMOTION_LOCK_TIMEOUT_MS = 5_000
DEFAULT_PROMOTION_STATEMENT_TIMEOUT_MS = 30_000


class BatchEvidencePromotionWriter(Protocol):
    def write_evidence_batch(
        self,
        payloads: tuple[EvidencePromotionPayload, ...],
    ) -> tuple[str | None, ...]: ...
```

`promote_accepted_staging()` constructs and deduplicates payloads first, slices them into chunks of at most 100, and calls `write_evidence_batch()` when the writer exposes that callable. Existing injected writers with only `write_evidence()` remain supported and retain their current ordering.

`PostgresEvidencePromotionWriter.write_evidence_batch()` opens one connection for the chunk. For each payload it starts a transaction, applies transaction-local `lock_timeout=5s` and `statement_timeout=30s`, runs the existing candidate decision, commits that candidate, and appends the returned ID or `None`. On an exception it rolls back the current candidate and re-raises. `write_evidence()` delegates to the same internal one-candidate implementation.

Production `psycopg.connect()` receives `connect_timeout=10`. Injected connection factories remain supported; transaction-local timeout SQL must therefore be covered independently from connect keyword tests.

Emit these public-safe events:

- `worker.promotion.started`: adapter count, raw-ref count, candidate count, chunk count.
- `worker.promotion.chunk_completed`: chunk index/count, candidate count, promoted count, elapsed milliseconds.
- `worker.promotion.completed`: candidate count, promoted count, elapsed milliseconds.
- `worker.promotion.failed`: chunk index, safe exception class, elapsed milliseconds.

- [ ] **Step 1: Add failing unit tests for batch selection and chunking**

In `apps/workers/tests/test_staging_pipeline.py`, add a batch-capable memory writer and these tests:

- `test_promote_uses_batch_writer_in_chunks_of_one_hundred`
- `test_promote_keeps_legacy_single_write_writer_compatible`
- `test_promote_keeps_duplicate_suppression_across_chunk_boundaries`
- `test_promote_preserves_none_results_and_evidence_id_order`

Create 201 accepted candidates and assert batch sizes `(100, 100, 1)`, no `write_evidence()` call on the batch writer, and exact result ordering.

- [ ] **Step 2: Add failing connection and transaction tests**

In `apps/workers/tests/test_promotion_pipeline.py`, use recording fake connections/cursors to add:

- `test_postgres_batch_reuses_one_connection_for_the_chunk`
- `test_postgres_batch_commits_every_candidate`
- `test_postgres_batch_rolls_back_the_failed_candidate`
- `test_postgres_batch_sets_lock_and_statement_timeouts_per_candidate`
- `test_postgres_connect_uses_ten_second_connect_timeout`

For three successful payloads, assert one connection, three commits, zero rollbacks, and timeout setup in all three transactions. For a failure on payload two, assert payload one remains committed, payload two rolls back, payload three is not attempted, and the exception propagates to the managed boundary.

- [ ] **Step 3: Add failing logging and managed-timeout tests**

Capture `log_event` in unit tests. Assert started/chunk/completed contain only bounded counters and timings. Simulate PostgreSQL `QueryCanceled` or `LockNotAvailable` from the promotion writer and assert `_execute_managed_runtime_ingestion_cycle()` returns:

```python
ManagedRuntimeIngestionResult(
    status="failed",
    reason="promotion_failed",
    error_code="QueryCanceled",
    ...,
)
```

Also assert pipeline status is recorded as `failed`, `complete=False` for the target adapter.

- [ ] **Step 4: Run focused RED**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_staging_pipeline.py \
  tests/test_promotion_pipeline.py \
  tests/test_runtime_managed_ingestion.py -q
```

Expected: FAIL because no batch protocol, connection reuse, timeout SQL, or lifecycle events exist.

- [ ] **Step 5: Factor the one-candidate implementation without changing decisions**

Move the body of `write_evidence()` into a private helper that accepts an existing connection. Do not reorder authorization, locks, CAP checks, duplicate handling, evidence insert, latest upsert, retirement, or terminal rejection. Make commit/rollback ownership explicit in the public one-item and batch methods.

Run the existing promotion unit suite immediately after the mechanical refactor, before adding batching:

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_pipeline.py \
  tests/test_staging_pipeline.py -q
```

Expected: existing behavior remains green.

- [ ] **Step 6: Implement chunking, connection reuse, timeouts, and logs**

Add the constants and batch protocol, detect a callable `write_evidence_batch`, chunk at 100, and implement the PostgreSQL batch writer. Use `time.monotonic()` for elapsed time. Never include `payload`, `raw_ref` values, URLs, SQL text, or exception messages in lifecycle fields.

- [ ] **Step 7: Run focused GREEN**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_staging_pipeline.py \
  tests/test_promotion_pipeline.py \
  tests/test_runtime_managed_ingestion.py -q
../../.venv/workers/bin/ruff check \
  app/pipelines/promotion.py \
  tests/test_staging_pipeline.py \
  tests/test_promotion_pipeline.py \
  tests/test_runtime_managed_ingestion.py
```

Expected: all selected tests pass and Ruff exits `0`.

- [ ] **Step 8: Run mandatory PostgreSQL safety regressions**

Start the local PostGIS service and apply current migrations:

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
cd apps/workers
PROMOTION_TEST_DATABASE_URL=postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk \
  OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
  ../../.venv/workers/bin/python -m pytest \
  tests/test_promotion_monotonicity_postgres.py -q
```

Expected: all promotion monotonicity, CAP lifecycle, duplicate, authorization, topology, and race tests pass without skips.

- [ ] **Step 9: Add and run the 1,311-candidate benchmark regression**

Add `test_postgres_batch_uses_bounded_connections_for_1311_candidates` to `apps/workers/tests/test_promotion_monotonicity_postgres.py`. Use synthetic accepted rows, assert no more than 15 total promotion connections including candidate fetch, and record elapsed time. Keep the CI assertion on bounded connection count; enforce the five-minute wall budget in the production rehearsal because shared CI timing is noisy.

Run the single benchmark test with `-vv -s` and retain its elapsed output in the PR description.

- [ ] **Step 10: Commit bounded promotion**

```bash
git add \
  apps/workers/app/pipelines/promotion.py \
  apps/workers/tests/test_staging_pipeline.py \
  apps/workers/tests/test_promotion_pipeline.py \
  apps/workers/tests/test_promotion_monotonicity_postgres.py \
  apps/workers/tests/test_runtime_managed_ingestion.py
git commit -m "fix(worker): bound realtime evidence promotion"
```

### Task 3: Continue the v1 tick after one source fails

**Files:**

- Modify: `apps/workers/app/cli/runtime_cli.py`
- Modify: `apps/workers/app/jobs/runtime_managed.py`
- Modify: `apps/workers/tests/test_v1_baseline_runner.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`

**Behavioral contract:**

One source's adapter construction, ingestion, staging, promotion, audit, or timeout failure must set `had_failure=True`, persist that source's failed pipeline status when possible, emit a public-safe failure event, and continue to the next eligible source. A normal gate-off remains non-failing.

Add a reporting-only parameter to the sanctioned scoped cycle:

```python
def run_v1_baseline_adapter_cycle(
    adapter_by_key: Mapping[str, DataSourceAdapter],
    *,
    settings: WorkerSettings,
    runtime_selection_adapter_keys: tuple[str, ...] | None = None,
    ...,
) -> ManagedRuntimeIngestionResult: ...
```

Validation rules and trust boundary:

- Scoped execution still contains exactly one adapter.
- `runtime_selection_adapter_keys` must be non-empty when supplied.
- It must contain the scoped adapter key.
- Every reporting key must belong to `V1_BASELINE_ADAPTER_KEYS`.
- `_run_v1_baseline_tick()` owns the full-tick settings/catalog/gate preflight and constructs the reporting tuple only from adapters that passed it. The scoped cycle does not attempt to re-prove peer gates from its deliberately single-key settings object; tests must instead prove the caller never includes a catalog-disabled, gate-off, or failed-construction key.
- The override changes only `record_runtime_selection()` arguments; adapter resolution, catalog checks, staging, promotion keys, and raw refs remain scoped to one source.

Preflight all eligible keys before ingestion: apply source catalog filtering once, build each gated adapter inside its own exception boundary, and collect `runnable`. Record the full runnable selection before executing the first source. Pass that same selection into each scoped cycle so a cycle cannot overwrite every peer as disabled.

Emit:

- `worker.runtime.v1_baseline.source_started`
- `worker.runtime.v1_baseline.source_completed`
- `worker.runtime.v1_baseline.source_failed` with adapter key, phase, and exception class only
- `worker.runtime.v1_baseline.tick_completed` with configured/runnable/completed/failed/gated-off counts and elapsed milliseconds

- [ ] **Step 1: Add failing continuation tests**

In `apps/workers/tests/test_v1_baseline_runner.py`, add:

```python
def test_tick_continues_when_first_adapter_builder_raises(...) -> None: ...

def test_tick_continues_when_first_source_cycle_raises(...) -> None: ...

def test_tick_continues_when_first_source_returns_failed(...) -> None: ...
```

Use two keys. Assert source two is built and run, the return value is `True`, failed status is recorded for source one when possible, and the final event reports one failure and one completion.

- [ ] **Step 2: Add failing early-selection and scope tests**

Add:

- `test_tick_records_full_selection_before_first_source_starts`
- `test_every_scoped_cycle_reports_the_same_full_tick_selection`
- `test_runtime_selection_override_cannot_widen_staging_or_promotion`
- `test_runtime_selection_override_rejects_unknown_or_gate_off_key`

The last test is split across boundaries: the tick-level test proves gate-off
and catalog-disabled keys never enter the preflight reporting tuple; the scoped
cycle test proves an unknown/non-v1 key is rejected and that the scoped key is
mandatory.

Use one ordered timeline list. The first selection record must precede `source_started`. Assert only the scoped adapter reaches `_execute_scheduled_ingestion_cycle()` and promotion.

- [ ] **Step 3: Run focused RED**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_v1_baseline_runner.py \
  tests/test_runtime_managed_ingestion.py -q
```

Expected: FAIL because source exceptions currently escape and the full selection is written only after the loop.

- [ ] **Step 4: Implement preflight, reporting validation, and per-source boundaries**

Keep the implementation synchronous; database and HTTP calls are bounded by their own timeouts. Do not add a thread timeout that leaves a live database operation running after the scheduler has moved on.

For a caught exception, call `record_pipeline_status()` with the source key, `status="failed"`, `complete=False`, and a fresh run timestamp. If writing the audit also fails, log only `audit_unavailable` and continue. Never suppress `KeyboardInterrupt`, `SystemExit`, or cancellation signals; catch `Exception`, not `BaseException`.

- [ ] **Step 5: Run focused GREEN and lint**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest \
  tests/test_v1_baseline_runner.py \
  tests/test_runtime_managed_ingestion.py \
  tests/test_worker_entrypoints.py -q
../../.venv/workers/bin/ruff check \
  app/cli/runtime_cli.py \
  app/jobs/runtime_managed.py \
  tests/test_v1_baseline_runner.py \
  tests/test_runtime_managed_ingestion.py
```

Expected: all selected tests pass and Ruff exits `0`.

- [ ] **Step 6: Commit scheduler liveness**

```bash
git add \
  apps/workers/app/cli/runtime_cli.py \
  apps/workers/app/jobs/runtime_managed.py \
  apps/workers/tests/test_v1_baseline_runner.py \
  apps/workers/tests/test_runtime_managed_ingestion.py
git commit -m "fix(worker): isolate v1 source failures"
```

### Task 4: Align flood-warning requiredness with deployed gates

**Files:**

- Create: `infra/migrations/0041_v1_warning_source_requirement_alignment.sql`
- Modify: `infra/migrations/README.md`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/api/routes/health.py`
- Modify: `tests/test_v1_official_baseline_migration.py`
- Modify: `apps/api/tests/test_assessment_repository.py`
- Modify: `apps/api/tests/test_evidence_repository.py`
- Modify: `apps/api/tests/test_evidence_repository_postgres.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `tests/test_apply_migrations_script.py`
- Modify: `infra/scripts/verify_migration_upgrade_0032_to_0036.py`
- Modify: `tests/test_hosted_public_risk_evidence_smoke.py`
- Verify unchanged: `infra/docker/entrypoint.sh`
- Verify unchanged: `tests/test_zeabur_single_service_deploy.py`

**Mapping decision:**

Use revision `2026-08-28-v1-warning-alignment` for every affected flood-warning mapping and contract. The resulting national rows are exactly:

```text
official.ncdr.cap                required          redundancy_of=NULL
official.cwa.heavy_rain_warning redundant_subset redundancy_of=official.ncdr.cap
```

Both mappings remain applicable and reviewed. Only NCDR enters `required_realtime_source_keys`; the disabled CWA source may not fail required-source absence. If CWA is activated later, that is a separate operator-reviewed migration/configuration task and does not reverse this recovery automatically.

The repository query must support signal-specific reviewed revisions. It may
emit a mapping only when a valid proof exists for the same jurisdiction and
signal and `mapping.mapping_revision = proof.contract_mapping_revision`. Do not
replace the old literal with a new global literal: rainfall, water-level,
flood-depth, and flood-warning contracts may legitimately advance separately.

- [ ] **Step 1: Change static expectations first and run RED**

Update `tests/test_v1_official_baseline_migration.py` constants and assertions:

- 22 flood-warning contracts still exist.
- Each contract sees exactly both adapter keys.
- NCDR has role `required` and no parent.
- CWA has role `redundant_subset` and parent `official.ncdr.cap`.
- The production `redundancy_parent_valid` expression is true.
- Mapping revision, contract revision, approved count, and digest all match `2026-08-28-v1-warning-alignment` for flood-warning rows.

Run:

```bash
.venv/workers/bin/python -m pytest tests/test_v1_official_baseline_migration.py -q
```

Expected: FAIL because migration `0041` does not exist and migrated rows still make both sources required.

- [ ] **Step 2: Add API and hosted-smoke RED tests**

In `apps/api/tests/test_assessment_repository.py`, construct one required and one redundant flood-warning mapping. Assert:

```python
assert data.required_realtime_source_keys == frozenset({"official.ncdr.cap"})
assert {
    mapping.adapter_key for mapping in jurisdiction.source_mappings
} >= {
    "official.ncdr.cap",
    "official.cwa.heavy_rain_warning",
}
```

In `tests/test_hosted_public_risk_evidence_smoke.py`, add:

- Disabled CWA with `required_for_absence=False` plus healthy NCDR passes required-source health.
- Stalled NCDR with `required_for_absence=True` still fails in `degraded-ok` mode.
- A repository SQL regression contains no global baseline revision predicate and requires mapping/contract revision equality.
- A PostgreSQL read-path fixture with the warning contract at the new revision and other signals at the baseline revision returns both sets; a mismatched warning mapping is omitted.

Run both files and record RED if repository fixtures currently mark both required.

- [ ] **Step 3: Implement append-only migration 0041**

Within one transaction:

1. Update NCDR flood-warning mapping to `required`, clear its redundancy parent, and set the new revision/review evidence.
2. Update CWA heavy-rain warning mapping to `redundant_subset`, point it to NCDR, and set the same revision/review evidence.
3. Update every flood-warning contract to the new revision.
4. Recompute each contract's approved mapping count and SHA-256 manifest using the exact JSON array, ordering, and encoding used by `query_realtime_jurisdiction_context()`.
5. Fail closed if there are not 22 flood-warning contracts.
6. Fail closed unless every contract has exactly one required NCDR mapping and exactly one CWA redundant mapping with a valid required parent.
7. Fail closed if any revision, approved count, digest, reviewed timestamp, or review reference is missing or inconsistent.

Do not change `data_sources.is_enabled`, runtime gates, credentials, or `infra/docker/entrypoint.sh`.

- [ ] **Step 4: Make revision validation contract-scoped and advance readiness**

Remove both global revision literals from
`query_realtime_jurisdiction_context()`. Join mappings to valid proof rows using
the same jurisdiction/signal applicability rules plus exact mapping/contract
revision equality. Advance the health schema sentinel, its checksum contract,
the checked-in migration version, and the associated API/root tests to 0041 in
the same commit.

- [ ] **Step 5: Document migration semantics**

Add a `0041` entry to `infra/migrations/README.md` explaining that redundancy changes absence requiredness only; it does not enable CWA, fetch data, lower NCDR freshness requirements, or let an unhealthy required NCDR source pass.

- [ ] **Step 6: Run static GREEN**

```bash
.venv/workers/bin/python -m pytest \
  tests/test_v1_official_baseline_migration.py \
  tests/test_apply_migrations_script.py \
  tests/test_hosted_public_risk_evidence_smoke.py \
  tests/test_zeabur_single_service_deploy.py -q
cd apps/api
../../.venv/api/bin/python -m pytest \
  tests/test_assessment_repository.py \
  tests/test_evidence_repository.py \
  tests/test_public_contract.py -q
```

Expected: all selected tests pass. The Zeabur deployment test must still prove that CWA heavy-rain warning is not silently added to the default backbone.

- [ ] **Step 7: Run migration validation and PostgreSQL proof tests**

```bash
.venv/workers/bin/python infra/scripts/validate_migrations.py
docker compose up -d postgres
docker compose --profile tools run --rm migrate
MIGRATION_TEST_DATABASE_URL=postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk \
  .venv/workers/bin/python -m pytest \
  tests/test_v1_official_baseline_migration.py \
  apps/api/tests/test_evidence_repository_postgres.py -q
```

Expected: migration validator exits `0`; PostgreSQL tests run without skips and all 22 contract proofs pass.

- [ ] **Step 8: Commit requirement alignment**

```bash
git add \
  infra/migrations/0041_v1_warning_source_requirement_alignment.sql \
  infra/migrations/README.md \
  apps/api/app/domain/evidence/repository.py \
  apps/api/app/api/routes/health.py \
  tests/test_v1_official_baseline_migration.py \
  apps/api/tests/test_assessment_repository.py \
  apps/api/tests/test_evidence_repository.py \
  apps/api/tests/test_evidence_repository_postgres.py \
  apps/api/tests/test_public_contract.py \
  tests/test_apply_migrations_script.py \
  infra/scripts/verify_migration_upgrade_0032_to_0036.py \
  tests/test_hosted_public_risk_evidence_smoke.py
git commit -m "fix(db): align warning requiredness with runtime"
```

### Task 5: Run full recovery verification before deployment

**Files:**

- Modify only if a test reveals a recovery regression.

- [ ] **Step 1: Prepare isolated Python environments**

From repository root:

```bash
python3.12 -m venv .venv/workers
.venv/workers/bin/python -m pip install -e 'apps/workers[dev]'
python3.12 -m venv .venv/api
.venv/api/bin/python -m pip install -e 'apps/api[dev]'
```

Expected: both editable installs complete without dependency conflicts.

- [ ] **Step 2: Run worker and API suites**

```bash
cd apps/workers
../../.venv/workers/bin/python -m pytest tests -q
../../.venv/workers/bin/ruff check app tests
cd ../api
../../.venv/api/bin/python -m pytest tests -q
../../.venv/api/bin/ruff check app tests
```

Expected: all tests pass and both Ruff runs exit `0`.

- [ ] **Step 3: Run root acceptance suites**

```bash
cd ../..
.venv/workers/bin/python -m pytest \
  tests/test_hosted_monitoring_workflow.py \
  tests/test_hosted_public_risk_evidence_smoke.py \
  tests/test_route_alert_issue_js.py \
  tests/test_zeabur_single_service_deploy.py \
  tests/test_v1_official_baseline_migration.py -q
.venv/workers/bin/python infra/scripts/validate_migrations.py
docker compose config --quiet
```

Expected: all selected tests pass; migration and Compose validation exit `0`.

- [ ] **Step 4: Run database-backed acceptance without skips**

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
MIGRATION_TEST_DATABASE_URL=postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk \
PROMOTION_TEST_DATABASE_URL=postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
  .venv/workers/bin/python -m pytest \
  tests/test_v1_official_baseline_migration.py \
  apps/workers/tests/test_promotion_monotonicity_postgres.py -q
```

Expected: all database-backed tests pass and none are skipped.

- [ ] **Step 5: Inspect the diff for scope and secret safety**

```bash
git status --short
git diff --check
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- \
  apps/workers/app \
  apps/workers/tests \
  apps/api/tests \
  infra/migrations \
  docs/runbooks \
  tests
```

Confirm no workflow weakening, credential value, private URL, generated artifact, local database file, or unrelated issue change is present.

- [ ] **Step 6: Request code review**

Use the `requesting-code-review` skill. Require reviewers to verify:

- Current-raw-ref scoping cannot drop valid current rows.
- Batch connection reuse preserves every existing promotion invariant.
- Timeout errors become failed source state and allow later sources to run.
- Reporting-only runtime selection cannot widen execution.
- Migration digest logic exactly matches the production read query.
- Disabled redundant CWA does not become required, while stalled NCDR remains a hard failure.

Apply review feedback with the `receiving-code-review` skill and rerun every affected test.

### Task 6: Deploy the merged commit and prove production recovery

**Prerequisites:**

- Tasks 1–5 are merged to `main`.
- GitHub CI is green.
- Zeabur deployment points to the merged main SHA.
- No source credential or gate is changed as part of this rollout.

- [ ] **Step 1: Record the GitHub and deployed SHAs**

```bash
main_sha="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
deployed_sha="$(curl -fsS https://floodrisk.cc/health | \
  .venv/workers/bin/python -c 'import json,sys; print(json.load(sys.stdin)["deployment_sha"])')"
printf 'main_sha=%s\ndeployed_sha=%s\n' "$main_sha" "$deployed_sha"
test "$main_sha" = "$deployed_sha"
```

Expected: both 40-character SHAs are identical. If not, wait for or repair deployment; do not run acceptance against the wrong commit.

- [ ] **Step 2: Inspect Zeabur logs for one complete tick**

Using the already authenticated Zeabur browser session, filter logs from deployment `$deployed_sha`. Confirm the sequence contains:

- `worker.promotion.started`
- bounded `worker.promotion.chunk_completed`
- `worker.promotion.completed`
- `worker.runtime.v1_baseline.source_completed` for CWA rainfall, WRA water level, WRA IoW flood depth, NCDR CAP, and local Tainan sensor
- `worker.runtime.v1_baseline.tick_completed`

Reject the rollout if secrets, source payloads, raw URLs with credentials, or database URLs appear in any new log event.

- [ ] **Step 3: Verify production source freshness with a unique request**

```bash
probe_label="hosted-recovery-$(date -u +%Y%m%dT%H%M%SZ)"
.venv/workers/bin/python scripts/hosted_public_risk_evidence_smoke.py \
  --base-url https://floodrisk.cc \
  --location-text "$probe_label" \
  --data-source-mode strict \
  --evidence-output /tmp/hosted-public-risk-recovery.json
```

Expected: exit `0`, fresh official evidence includes both `observed_at` and `ingested_at`, required source health is healthy/degraded without `pipeline_stalled`, and disabled CWA heavy-rain warning is not required for absence.

- [ ] **Step 4: Manually dispatch Hosted Monitoring against the deployed SHA**

```bash
deployed_sha="$(curl -fsS https://floodrisk.cc/health | \
  .venv/workers/bin/python -c 'import json,sys; print(json.load(sys.stdin)["deployment_sha"])')"
gh workflow run hosted-monitoring.yml \
  --repo pcedison/taiwan-flood-risk-open-map \
  --ref main \
  -f expected_deployment_sha="$deployed_sha" \
  -f data_source_mode=strict
gh run list \
  --repo pcedison/taiwan-flood-risk-open-map \
  --workflow hosted-monitoring.yml \
  --limit 3
```

Open the dispatched run and require every smoke step to pass. Download and retain the public-safe artifact. Confirm the success router comments on and closes issue #212.

- [ ] **Step 5: Wait for and verify one normal scheduled run**

Do not substitute another manual dispatch. The next `schedule` event must pass at the normal six-hour cadence. Verify its event is `schedule`, deployment SHA equals the current production SHA, and schedule-completion evidence is accepted.

Issue #199 may be closed only after this scheduled evidence is available or the existing auto-resolution path closes it.

- [ ] **Step 6: Record the recovery evidence in the PR/issue**

Post only public-safe references:

- merged commit SHA
- Zeabur deployment SHA
- successful manual run URL
- successful scheduled run URL
- elapsed promotion time and candidate count
- confirmation that all required sources completed
- issue #212 resolution link

Do not paste environment variables, raw logs containing credentials, database URLs, private manifests, or bearer tokens.

### Task 7: Add an explicit bounded promotion-backlog maintenance path

This is P1 operational hardening and must be a separate PR after production
recovery. Current-cycle scoping deliberately stops the realtime scheduler from
draining unrelated accepted rows, so operators need a safe, observable path for
rows left behind by a partial historical run or a failed old snapshot.

Minimum contract:

- Require an explicit adapter key and a positive limit no greater than 1,000.
- Require either exact reviewed raw refs or a bounded age window; never provide
  an unbounded "all backlog" mode.
- Report backlog count plus oldest/newest accepted-row age before writing.
- Reuse the same authorization, topology, lifecycle, idempotency, timeout, and
  per-candidate durability rules as realtime promotion.
- Persist an operator audit record containing requester, reason, adapter key,
  bounds, candidate count, promoted count, and safe failure class.
- Document dry-run, execute, retry, and cleanup behavior in an operator runbook.
- Prove a failed chunk leaves the remaining rows visible and retryable without
  making them eligible for the realtime scheduler.

### Task 8: Reduce alert noise only after recovery, if still necessary

This task is optional and must be a separate PR after Task 6 succeeds.

**Files, only if selected:**

- Modify: `.github/workflows/hosted-monitoring.yml`
- Modify: `.github/workflows/hosted-monitoring-schedule-watchdog.yml`
- Modify: `tests/test_hosted_monitoring_workflow.py`
- Modify: relevant watchdog tests

- [ ] **Step 1: Prefer notification mute or comment backoff**

If the problem is personal notification volume, mute the issue/workflow notification without changing repository monitoring. If repository comments are too frequent, set `ALERT_BACKOFF_HOURS` to `48` or `72`; this changes duplicate comments only, not failure status or run frequency.

- [ ] **Step 2: If cadence changes, change watchdog in the same commit**

For a temporary 12-hour monitor, use `7 */12 * * *` and set watchdog `MAX_AGE_MINUTES` to at least `840`. For daily monitoring, use `7 0 * * *` and at least `1560`. Add tests asserting the watchdog age always exceeds cadence plus headroom.

- [ ] **Step 3: Preserve fail-closed semantics**

Run:

```bash
.venv/workers/bin/python -m pytest \
  tests/test_hosted_monitoring_workflow.py \
  tests/test_hosted_public_risk_evidence_smoke.py \
  tests/test_route_alert_issue_js.py -q
```

Expected: monitoring still fails for a configured `pipeline_stalled` source, stable-signature deduplication still works, and success still closes the alert issue.

- [ ] **Step 4: Commit noise-only changes separately**

```bash
git add \
  .github/workflows/hosted-monitoring.yml \
  .github/workflows/hosted-monitoring-schedule-watchdog.yml \
  tests/test_hosted_monitoring_workflow.py
git commit -m "chore(actions): tune hosted alert cadence"
```

Do not use `continue-on-error`, remove step 8, or broaden `degraded-ok` to configured stalled sources.

---

## Completion Checklist

- [ ] Current-cycle raw-ref scoping is covered and historical backlog is excluded from scheduler promotion.
- [ ] 1,311 candidates use no more than 15 promotion connections and preserve per-candidate durability.
- [ ] Connect, lock, and statement waits are bounded and tested.
- [ ] Source B runs after source A raises, times out, or returns failed.
- [ ] Full runtime selection is reported without widening scoped execution.
- [ ] Migration 0041 leaves NCDR required and CWA redundant/disabled.
- [ ] Every county warning contract has a valid count/digest/revision proof.
- [ ] Worker, API, root, migration, and PostgreSQL tests pass without required-suite skips.
- [ ] Review confirms no monitoring weakening and no secret exposure.
- [ ] Deployed SHA equals merged main SHA.
- [ ] Production logs show all required source completions and tick completion.
- [ ] Unique strict public-risk smoke passes.
- [ ] Manual Hosted Monitoring run passes and closes #212.
- [ ] Normal scheduled Hosted Monitoring run passes.
- [ ] Historical accepted backlog has a bounded, audited maintenance path or is tracked as explicit P1 follow-up work.
- [ ] Remaining issues #71 and #73 are tracked separately; Dependabot work remains separate.
