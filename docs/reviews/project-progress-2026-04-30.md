# 專案進度盤點報告（2026-04-30）

本文件依 `docs/PROJECT_WORK_PLAN.md`、根目錄與各 app README，以及本輪 subagent hardening 結果整理目前狀態。結論：專案已超過 Phase 0 skeleton；Phase 1 核心查詢流程、Phase 2 ingestion groundwork、Phase 3 scoring v0 都已有實作與測試證據，且本輪已完成 local Compose runtime smoke 與 worker 官方 demo DB persistence 驗證。但仍不應宣稱 MVP 完成，因為 production worker scheduler/queue、query heat persistence、tile hosting、public reports、production monitoring dashboard 等仍是後續工作。

## 2026-04-30 Hardening 結果

- WP1 文件狀態與 placeholder 邊界：已完成。根 README、work plan、app README 與本報告已區分 fallback、phase-delayed、pending implementation。
- WP2 前端測試可信度：已完成。`npm test` 已改成真實 Node unit tests，並保留 Playwright desktop/mobile smoke。
- WP3 Runtime smoke：已完成。`scripts/runtime-smoke.ps1 -StopOnExit` 已啟動 local Compose stack、跑 migration、檢查 API/Web、送出風險查詢並正常收尾。
- WP4 Data realism / Phase 2 demo：已完成一輪可測 groundwork。Worker 批次流程會使用 `WORKER_ENABLED_ADAPTER_KEYS`；官方 WRA demo path 可用 runtime command 寫入 raw snapshot -> staging -> promotion -> PostGIS geometry；API query heat 由 DB helper 優先計算，DB 不可用時明確回傳 limited bucket。
- WP5 Monitoring / backup-restore：已完成 checkpoint 等級驗收。Prometheus source freshness/API availability alert rules 已新增；backup/restore drill 支援 Docker client fallback 並驗證非 scratch restore guard。

## 已完成或已有明確實作證據

### Repo foundation / contracts / runbook

- Monorepo、授權、Docker Compose、環境樣板與基本文件已存在：`README.md`、`LICENSE`、`.env.example`、`docker-compose.yml`、`Dockerfile`。
- SDD / work plan / ADR skeleton 已建立：`docs/PROJECT_SDD.md`、`docs/PROJECT_WORK_PLAN.md`、`docs/adr/0001-sdd-as-source-of-truth.md` 到 `docs/adr/0008-score-versioning-and-explainability.md`。
- OpenAPI draft 已涵蓋 public 與 admin surface：`docs/api/openapi.yaml`。
- Runtime smoke runbook 與可重跑腳本已新增並驗證通過：`docs/runbooks/runtime-smoke.md`、`scripts/runtime-smoke.ps1`。

### API Phase 1/3 surface

- FastAPI entrypoint、router、health/readiness、public risk/evidence/layers routes 已存在：`apps/api/app/main.py`、`apps/api/app/api/router.py`、`apps/api/app/api/routes/health.py`、`apps/api/app/api/routes/public.py`。
- Admin routes 與 admin auth contract skeleton 已存在：`apps/api/app/api/routes/admin.py`、`apps/api/tests/test_admin_contract.py`。
- Risk scoring v0 有實作與 golden fixtures：`apps/api/app/domain/risk/scoring.py`、`apps/api/tests/test_scoring.py`、`apps/api/tests/fixtures/scoring/`。
- Query heat 已從固定 bucket 推進為 DB-first helper，DB 不可用時明確標示 limited；polygon evidence 也透過 safe centroid 回傳：`apps/api/app/domain/evidence/repository.py`、`apps/api/tests/test_evidence_repository.py`、`apps/api/tests/test_public_contract.py`。
- `/v1/layers` 已改為 DB-first 讀取 seeded `map_layers` metadata，DB 不可用時才走 deterministic fallback：`apps/api/app/domain/layers/repository.py`、`infra/migrations/0004_seed_map_layers.sql`。

### Web Phase 1 flow

- Next.js + MapLibre map-first UI 已存在：`apps/web/app/page.tsx`、`apps/web/app/layout.tsx`、`apps/web/app/globals.css`。
- Evidence drawer 會用 `assessment_id` 取完整 evidence list，並保留 preview fallback：`apps/web/app/page.tsx`。
- 前端 display/data shaping helper 與 unit tests 已新增：`apps/web/app/lib/risk-display.ts`、`apps/web/tests/unit/risk-display.test.ts`。
- Playwright E2E smoke 已覆蓋 desktop/mobile map-risk path：`apps/web/tests/e2e/map-risk.spec.ts`。

### Worker adapters / ingestion pipeline groundwork

- Adapter contract、registry、官方 CWA/WRA/flood-potential parsers 與 L2 news sample groundwork 已存在：`apps/workers/app/adapters/`、`apps/workers/tests/test_official_adapters.py`。
- Raw snapshot、staging、validation、promotion、PostGIS writer pipeline 已有模組與測試：`apps/workers/app/pipelines/`、`apps/workers/tests/test_staging_pipeline.py`、`apps/workers/tests/test_promotion_pipeline.py`、`apps/workers/tests/test_postgres_writer.py`。
- `WORKER_ENABLED_ADAPTER_KEYS` 可限制啟用 adapter，且不繞過 terms/sample gates：`apps/workers/app/config.py`、`apps/workers/app/adapters/registry.py`、`apps/workers/tests/test_adapter_registry_config.py`。
- `run_enabled_adapter_batches()` 已讓 worker 批次流程實際使用 enabled adapter config：`apps/workers/app/jobs/ingestion.py`、`apps/workers/tests/test_ingestion_job_runner.py`。
- 官方 WRA demo path 已有 raw snapshot -> staging -> promotion payload 測試，也可用 `python -m app.main --run-official-demo --persist --database-url ...` 寫入 PostGIS：`apps/workers/tests/test_official_demo_path.py`。

## 開發到一半或仍有 placeholder 的部分

- API 與 Web 仍保留 placeholder server 檔案：`apps/api/app/placeholder_server.py`、`apps/web/server-placeholder.mjs`。目前只能算 fallback，不是主要 runtime。
- Worker scheduler/sample 仍是 smoke/fallback path：`apps/workers/app/scheduler.py`、`apps/workers/app/jobs/sample.py`。production queue/scheduler 尚未完成；目前可演示的是 official demo runtime command。
- Query heat 已有 DB helper，但尚未有完整 query persistence / heat bucket materialization flow；目前是最小可測真實度。
- PTT / Dcard / user_report 仍是 phase-delayed/pending implementation：`apps/workers/app/adapters/ptt/__init__.py`、`apps/workers/app/adapters/dcard/__init__.py`、`apps/workers/app/adapters/user_report/__init__.py`。
- `packages/geo`、`packages/shared` 仍以 placeholder / baseline 為主。`infra/monitoring` 已有 Prometheus scrape config 與 alert rules，但 dashboard 與 worker heartbeat metrics 尚未完成。

## 尚未開發或尚未驗證

- Query heat persistence 與 materialized heat buckets 尚未完成。
- Production worker scheduler/queue 尚未完成。
- Tile generation/hosting 尚未完成；目前只有 layer metadata。
- Phase 4 forum/public discussion expansion 尚未完成。
- Phase 5 public reports and governance 尚未完成。
- Phase 6 production hardening 尚未完成。
- Tile/layer production pipeline 尚未完成。

## 下一步建議

1. 讓 `/v1/risk/assess` 寫入 `location_queries` / `risk_assessments`，把 query heat 從即時計算 helper 推進到可累積的 privacy-preserving flow。
2. 補 worker production scheduler/queue 行為，讓 official adapters 能在 demo command 之外穩定排程執行。
3. 建 tile generation/hosting，接上目前已 seeded 的 layer metadata。
4. 將 worker/scheduler heartbeat metrics 接到 Prometheus alert placeholders。
5. 對本 checkpoint 做 final diff check、commit、push、draft PR。
---

## WP-E placeholder boundary / ops runbooks update - 2026-04-30

This pass stayed inside README, work-plan/review docs, runbooks, and ops
scripts. No app code was changed.

### Placeholder boundary scan result

- Keep as fallback-only: API and Web placeholder server files. Compose and the
  current runtime smoke target FastAPI and Next.js, so these files are no
  longer acceptance evidence for Phase 1+.
- Keep as fallback/smoke-only: Worker scheduler and sample job paths. Production
  queue/scheduler behavior is still a known limitation.
- Keep as phase-delayed: PTT, Dcard, and user_report adapters. They remain
  blocked by legal/source/privacy review and must stay disabled.
- Keep as baseline placeholders: `packages/geo` and `packages/shared`.
  `infra/monitoring` now has scrape config and alert rules, while dashboards
  and worker heartbeat metrics remain pending.
- Convert to explicit known limitation: query heat has DB-first read groundwork,
  but `/v1/risk/assess` persistence and heat bucket materialization are still
  pending.

### Five-point status update

1. Documentation/status alignment remains done.
2. Placeholder boundary cleanup is now documented as fallback-only,
   phase-delayed, baseline placeholder, or known limitation.
3. Runtime smoke is complete for this checkpoint; runbook/script are linked
   from README and `scripts/runtime-smoke.ps1 -StopOnExit` passed locally.
4. Worker/API ingestion realism remains WP-D owned; official demo DB
   persistence is verified, while production scheduler and persisted query heat
   remain limitations.
5. Ops monitoring/backup now has runbooks and dry-run script entrypoints:
   `docs/runbooks/monitoring-freshness-alerts.md`,
   `docs/runbooks/backup-restore-drill.md`,
   `scripts/ops-source-freshness-check.ps1`, and
   `scripts/backup-restore-drill.ps1`.

## WP-5 checkpoint scope / PR hygiene update - 2026-04-30

This pass completed item 1 of the current five-point next-step sequence:
checkpoint scope and PR hygiene. Later integration passes added runtime smoke,
worker DB demo persistence, DB-backed layers, monitoring alerts, and
backup/restore verification. This report still records that no staging/commit
had happened at the documentation checkpoint moment.

### Scope review result

- Branch: `codex/phase2-runtime-demo`.
- Staged changes: none.
- Tracked modified scope: root config/docs, API route/repository/tests, Web
  UI/tests/package metadata, Worker config/jobs/pipeline/tests,
  `docs/PROJECT_WORK_PLAN.md`, and monitoring baseline files.
- Untracked scope: API layer-domain files and evidence repository test, Web
  display helper/unit test, Worker freshness/demo/entrypoint tests and job
  helpers, progress/runbook docs, monitoring alert rules, and three PowerShell
  ops/runtime scripts.
- Checkpoint review artifact:
  `docs/reviews/checkpoint-phase2-runtime-demo-2026-04-30.md`.

### PR-ready summary

- Functional scope: docs/status alignment, runtime smoke readiness, Web evidence
  UX hardening, API query heat and layer-domain groundwork, Worker adapter/demo
  realism, monitoring baseline, and ops runbooks.
- Test matrix: backend contract/domain tests, frontend unit and Playwright smoke
  tests, worker adapter/freshness/demo tests, ops dry-run scripts, and CI hard
  gate wiring.
- Known risks: query heat persistence/materialized buckets pending; production
  scheduler/queue pending; tile hosting pending; worker/scheduler heartbeat
  metrics pending; placeholders remain fallback-only or phase-delayed; final
  diff check should be run before staging.
- Rollback notes: roll back by reverting the eventual checkpoint commit and use
  `WORKER_ENABLED_ADAPTER_KEYS` to limit adapter execution during repair.

### Acceptance criteria for item 1

- Scope summary is captured from `git status --porcelain=v1 -uall`.
- No staging action was taken.
- Suggested commit message and PR body draft are available in the checkpoint
  review artifact.
- Work plan now includes a PR-body-ready five-point status and checkpoint
  acceptance criteria.
