# Hosted Monitoring incident handoff — 2026-08-28

## Status

- Severity: P0 production data-freshness incident; the public HTTP service is reachable, but required realtime evidence is not advancing.
- Investigation status: trigger chain, scheduler stop boundary, promotion N+1 defect, and warning-source configuration mismatch are confirmed. The exact PostgreSQL statement or wait event consuming the remaining time still needs production instrumentation.
- Production deployment observed by the failed run: `e4d8205c8398073acf0704ec79bdcb790ece87d3`.
- Implementation order: `docs/superpowers/plans/2026-08-28-hosted-monitoring-recovery.md`.
- This commit is documentation-only. It does not change GitHub Actions, Zeabur, source gates, database mappings, or production runtime behavior.

## Primary references

- [Hosted Monitoring run 33121203759](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33121203759)
- [Failed job, Hosted public risk evidence smoke](https://github.com/pcedison/taiwan-flood-risk-open-map/actions/runs/33121203759/job/98688204783#step:8:34)
- [Alert issue #212](https://github.com/pcedison/taiwan-flood-risk-open-map/issues/212)
- [PR #207, alert-loop reduction](https://github.com/pcedison/taiwan-flood-risk-open-map/pull/207)
- [Current Hosted Monitoring workflow](https://github.com/pcedison/taiwan-flood-risk-open-map/blob/main/.github/workflows/hosted-monitoring.yml)

## Executive diagnosis

`Hosted public risk evidence smoke` is not a GitHub-hosted runner fault. It is an intentional production acceptance gate that exits non-zero when the public risk response cannot prove that required official realtime sources are healthy and fresh.

The long-running warning is triggered by this chain:

1. `.github/workflows/hosted-monitoring.yml` runs every six hours (`7 */6 * * *`).
2. The health and deployment contract checks pass.
3. `scripts/hosted_public_risk_evidence_smoke.py` calls the deployed `/v1/risk/assess` endpoint.
4. The response reports configured required sources with `reason=pipeline_stalled`, and does not contain fresh official rainfall or water-level evidence carrying both `observed_at` and `ingested_at`.
5. `pipeline_stalled` is a hard failure even in `DATA_SOURCE_MODE=degraded-ok`; that mode only excuses a deployment where official sources are genuinely not configured.
6. The smoke exits `1`, GitHub marks the job failed, and the `failure()` issue-routing step updates the stable alert issue.

The production worker trace stops after CWA rainfall staging succeeds with 1,311 rows and before promotion and whole-tick completion are logged. The code at that boundary fetches accepted staging candidates and opens a new PostgreSQL connection and transaction for every candidate. The v1 scheduler processes sources sequentially, so a slow or blocked first-source promotion prevents WRA, NCDR, IoW, and local Tainan sources from running and prevents the final whole-tick runtime-selection heartbeat from being rewritten.

There is a second independent failure: migration `0040_v1_official_baseline_source_mappings.sql` makes `official.cwa.heavy_rain_warning` required for every county, while `infra/docker/entrypoint.sh` neither includes that adapter in its default realtime backbone nor enables its three runtime gates. Even after promotion is repaired, that contract/runtime mismatch can keep Hosted Monitoring red.

## What run 33121203759 actually proved

### Passed checks

- `/health` responded successfully and exposed deployment SHA `e4d8205c8398073acf0704ec79bdcb790ece87d3`.
- `Public API contract` passed.
- `Hosted deployment smoke` passed.
- The deployment was running and serving the expected application commit.

These passes rule out a dead Zeabur service, a missing deployment SHA, and a basic public API outage as the trigger for this run.

### Failed checks

The public-risk evidence smoke reported all of the following:

- No healthy official realtime freshness evidence with both `observed_at` and `ingested_at`.
- No official rainfall or water-level evidence with both timestamps.
- `official-cwa-heavy-rain-warning`: disabled.
- `official-cwa-rainfall`: failed, `pipeline_stalled`.
- `official-ncdr-cap`: failed, `pipeline_stalled`.
- `official-wra-water-level`: failed, `pipeline_stalled`.
- `official-wra-iow-flood-depth`: failed, `pipeline_stalled`.
- `local-tainan-flood-sensor`: failed, `pipeline_stalled`.

The script then exited with status `1`. These are production data-path failures, not harmless annotations from the workflow engine.

## Confirmed production stop boundary

The Zeabur worker log observed during this investigation contains the following sequence for CWA rainfall:

- `2026-08-27T14:31:30Z`: CWA rainfall source starts.
- The adapter batch succeeds.
- `items_fetched=1311` and `items_staged=1311`.
- Adapter start: `14:31:30.604Z`.
- Adapter finish: `14:31:32.922Z`.
- `scheduler.ingestion_cycle.completed`: `14:31:32.949Z`.

For the following hours, the log does not contain:

- `runtime.managed.ingestion.completed` for that cycle.
- `worker.runtime.v1_baseline.source_completed` for CWA rainfall.
- `worker.runtime.v1_baseline.tick_completed`.
- Start or completion records for the downstream required sources.

The next synchronous operation after staging-cycle completion is accepted-staging promotion in `apps/workers/app/jobs/runtime_managed.py`.

## Confirmed code defects

### 1. Promotion performs N+1 PostgreSQL connection setup

`promote_accepted_staging()` in `apps/workers/app/pipelines/promotion.py`:

1. Fetches all unpromoted accepted candidates matching the adapter filter when no limit is supplied.
2. Loops over candidates one by one.
3. Calls `writer.write_evidence(...)` once for every candidate.

`PostgresEvidencePromotionWriter.write_evidence()` opens a fresh PostgreSQL connection for every call. For the observed CWA batch, that means one candidate-fetch connection plus as many as 1,311 new promotion connections and transactions. Accepted backlog from earlier generations can increase the count because the query is adapter-scoped, not current-raw-snapshot-scoped.

This N+1 behavior is directly confirmed in code. It is a production-grade performance defect regardless of whether a particular candidate is also waiting on a lock or a slow SQL statement.

### 2. Realtime promotion is not scoped to the current ingestion generation

`AdapterBatchRunSummary` already exposes `raw_ref`, but `_execute_managed_runtime_ingestion_cycle()` passes only `adapter_keys` to promotion. `_accepted_staging_sql()` therefore includes every accepted, not-yet-promoted row for that adapter. A realtime tick can unexpectedly become a historical backlog drain.

The immediate scheduler path should promote only raw refs produced by the current cycle. Any historical recovery/backfill must use an explicit bounded command so it cannot consume the realtime freshness budget.

### 3. One source can prevent all later sources from running

`_run_v1_baseline_tick()` in `apps/workers/app/cli/runtime_cli.py` runs eligible sources sequentially. It has no top-level per-source exception boundary around adapter construction plus cycle execution. It also writes the authoritative whole-tick runtime selection only after every source returns.

Consequences:

- An unhandled exception can abort the remaining sources.
- A blocking call can hold the entire tick indefinitely.
- Later required sources do not receive fresh pipeline status.
- The final runtime-selection record cannot repair the scoped per-source records until the loop ends.

The existing `apps/workers/tests/test_v1_baseline_runner.py` covers the final-selection regression and gate-off behavior, but it does not prove that a later source still runs after an earlier source raises or returns a failed result.

### 4. Required warning mapping disagrees with deployed runtime gates

`infra/migrations/0040_v1_official_baseline_source_mappings.sql` maps both of these as `required` national `flood_warning` sources:

- `official.cwa.heavy_rain_warning`
- `official.ncdr.cap`

`infra/docker/entrypoint.sh` omits `official.cwa.heavy_rain_warning` from `realtime_backbone_adapter_keys` and does not set its source, API, or reviewed-contract gates. The source is therefore required by absence proof but disabled by deployment defaults.

The schema already supports `requirement_role='redundant_subset'` with `redundancy_of_adapter_key`. The fastest fail-closed correction is to keep NCDR CAP required and mark CWA heavy-rain warning as a reviewed redundant subset of NCDR until its credentials, active-event fixture, and operator activation evidence are complete. Enabling CWA instead is valid only after those readiness requirements are proven.

Do not edit migration `0040` after it has been deployed. Add migration `0041` and recompute every affected contract digest at the new mapping revision.

The API read query currently contains two global
`2026-08-24-v1-baseline` literals. Migration `0041` must not move only the
warning rows until the query is changed to accept each reviewed contract's own
revision and require that its mappings match that revision. Otherwise the
warning catalog will disappear from public reads again.

## What is still unproven

The following must not be presented as confirmed until instrumentation or a database profile supplies evidence:

- Which exact candidate or SQL statement consumed the remaining time.
- Whether the dominant delay was connection establishment, row/advisory locking, statement execution, transaction commit, or a combination.
- Whether the cycle was permanently blocked or merely too slow to finish inside the source-health freshness window.
- The current count and age distribution of accepted unpromoted staging rows in production.

The first repair should therefore add bounded promotion counters, elapsed timings, and PostgreSQL timeouts as well as remove the N+1 connection pattern.

## Why the alert keeps recurring

There are two different frequencies to distinguish:

- Workflow executions: every six hours, four runs per day.
- Duplicate issue comments: the router suppresses an unchanged failure signature for 24 hours by default.

PR #207 already reduced the workflow from every 30 minutes (48 runs per day) to every six hours and added stable-signature deduplication. `scripts/ci/route-alert-issue.js` reuses the open issue title `[hosted-monitoring-alert] Hosted Monitoring failure`, updates its body, and avoids a duplicate comment inside the backoff window. A successful run comments on and closes the issue.

Manually closing issue #212 does not disable the monitor. The next failed run searches for an open matching issue; if none exists, it creates another one.

## Can Hosted Monitoring be disabled?

Yes, but disabling it removes detection, not the production defect.

| Option | Alert volume | Operational drawback | Recommendation |
| --- | ---: | --- | --- |
| Mute personal GitHub notifications for the issue/workflow | Lower for that user | Team monitoring remains intact; another channel must still be watched | Safest temporary noise reduction |
| Increase `ALERT_BACKOFF_HOURS` to 48 or 72 | Fewer duplicate comments | Failed Actions runs still occur; issue body still updates | Safe if comments are the main nuisance |
| Change Hosted Monitoring to every 12 hours | Two runs/day | Detection can be delayed by 12 hours; watchdog `MAX_AGE_MINUTES` must be at least 840 | Acceptable only as a temporary incident measure |
| Change Hosted Monitoring to daily | One run/day | Up to one day of stale/failed data can go undetected; watchdog must be at least 1,560 minutes | Not recommended for launch readiness |
| Remove/disable the schedule | No scheduled smoke alerts | No continuous proof that deployed SHA, risk contract, and realtime freshness still work; schedule watchdog also needs redesign or disablement | Emergency-only |
| Add `continue-on-error` to the public-risk evidence smoke | Workflow appears green | Creates a false-green release signal while required data is stale | Do not do this |
| Treat `pipeline_stalled` as `degraded-ok` | Fewer red runs | Hides failure of sources that are configured and contractually required | Do not do this |

The schedule watchdog runs daily at `47 16 * * *` with `MAX_AGE_MINUTES=480`. Any slower Hosted Monitoring cadence must change that threshold in the same commit. A 12-hour cadence needs at least 12 hours plus headroom (`840` minutes is the recommended floor); daily needs at least `1560`.

## Items ruled out as this run's trigger

- `ADMIN_BEARER_TOKEN` was empty, but `REQUIRE_ADMIN_SOURCE_FRESHNESS=false`; the admin freshness step was not the cause of step 8.
- Missing completion-evidence secrets tracked by issue #73 remain a release/operations blocker, but they did not produce the `pipeline_stalled` failures in run 33121203759.
- Next.js `Failed to find Server Action` messages are unrelated internet scanning/background requests and did not trigger this workflow failure.
- Dependabot PRs #185–#189 are independent dependency maintenance and should not be mixed into the P0 recovery change.
- Issue #71 is external/local-source operator coordination and is not the immediate scheduler stop.

## Recommended correction order

### P0-A — Bound and accelerate promotion

1. Scope realtime promotion to the current cycle's `raw_ref` values.
2. Add a batch writer that reuses one PostgreSQL connection per bounded chunk while preserving per-candidate commit/rollback and idempotency semantics.
3. Add connection, lock, and statement timeouts so a database wait becomes a recorded failed source rather than an unbounded tick.
4. Emit promotion start, candidate count, chunk completion, elapsed time, success, and failure logs.
5. Prove a 1,311-candidate fixture completes inside the agreed budget; target less than five minutes per source and less than fifteen minutes for the whole required-source tick.

### P0-B — Make the scheduler survive one bad source

1. Preflight gated adapters and write the authoritative whole-tick runtime selection before ingestion starts.
2. Wrap adapter construction and cycle execution per source.
3. Record a failed pipeline status and safe error code when a source raises, then continue to the next source.
4. Emit `source_started`, `source_completed`, `source_failed`, and a final tick summary.
5. Add tests proving source B runs when source A raises and that the tick returns failure without abandoning later sources.

### P0-C — Align warning-source contract and runtime

1. Add migration `0041` rather than rewriting `0040`.
2. Keep `official.ncdr.cap` required.
3. Mark `official.cwa.heavy_rain_warning` as `redundant_subset` of NCDR unless production readiness for enabling it is demonstrated before implementation.
4. Move the affected mapping and contract rows to one new revision, recompute approved count/digest, and fail closed if any county lacks exactly one required warning source and its reviewed redundant mapping.
5. Update static and PostgreSQL migration tests plus source-health requiredness tests.

### P0-D — Deploy and prove recovery

1. Run focused worker, API, deployment-contract, workflow, and migration tests.
2. Run the full required CI set before merge.
3. Deploy the merged SHA.
4. Confirm logs show every required source reaches `source_completed` and the tick reaches `tick_completed`.
5. Confirm `/v1/risk/assess` includes fresh official evidence and no required source reports `pipeline_stalled`.
6. Manually dispatch Hosted Monitoring against the deployed SHA, then retain the next successful scheduled run as cadence evidence.
7. Confirm successful routing closes #212; close/replace #199 only with accepted scheduled evidence.

### P1 — Restore the remaining launch evidence

1. Complete the secret/evidence requirements in issue #73.
2. Continue external source/operator work in issue #71.
3. Address Dependabot PRs #185–#189 after the production data path is stable.
4. Change backoff or cadence only if alert noise remains unacceptable after recovery.

## Recovery acceptance criteria

All of the following are required before calling the incident resolved:

- A CWA rainfall batch of at least 1,311 candidates does not open one connection per candidate.
- Realtime promotion does not sweep unrelated historical accepted backlog.
- Every promotion database operation has bounded connection/lock/statement waiting.
- A failed or raised first source does not stop the second source.
- Whole-tick runtime selection is recorded before a long-running source can block the loop.
- NCDR CAP is the required warning source; disabled CWA heavy-rain warning is not reported as required for absence.
- Required rainfall, water-level, flood-depth, and warning source states are fresh and are not `pipeline_stalled`.
- A unique hosted `/v1/risk/assess` request returns fresh official evidence carrying both `observed_at` and `ingested_at`.
- Hosted Monitoring passes once by manual dispatch against the deployed SHA.
- Hosted Monitoring passes again on its normal six-hour schedule.
- The alert router closes #212 on success.

## Baseline verification for this handoff

The documentation branch was created from `origin/main` at `e4d8205`. Before adding these files, the incident-focused baseline was run with Python 3.12:

```text
tests/test_hosted_monitoring_workflow.py
tests/test_hosted_public_risk_evidence_smoke.py
tests/test_route_alert_issue_js.py

20 passed in 0.66s
```

This establishes that the checked-in workflow/router tests are green even while the production data-path acceptance run is red; the problem is not an already-failing local workflow test.
