# 專案進度盤點報告（2026-04-30）

本文件依 `docs/PROJECT_WORK_PLAN.md`、根目錄與各 app README，以及本輪 subagent hardening 結果整理目前狀態。結論：專案已超過 Phase 0 skeleton；Phase 1 核心查詢流程、Phase 2 ingestion groundwork、Phase 3 scoring v0 都已有實作與測試證據，且本輪已完成 local Compose runtime smoke、worker 官方 demo DB persistence、query heat persistence/materialization smoke、DB-backed MVT tile endpoint、worker tile feature/cache smoke、worker/scheduler heartbeat textfile metrics 與 Phase 4/5 governance gates。但仍不應宣稱 MVP 完成，因為 durable production queue、real external source clients、production tile hosting/cache strategy、public reports product UX/governance、production monitoring dashboard 等仍是後續工作。

## 2026-04-30 Hardening 結果

- WP1 文件狀態與 placeholder 邊界：已完成。根 README、work plan、app README 與本報告已區分 fallback、phase-delayed、pending implementation。
- WP2 前端測試可信度：已完成。`npm test` 已改成真實 Node unit tests，並保留 Playwright desktop/mobile smoke。
- WP3 Runtime smoke：已完成擴充版腳本與 runbook。`scripts/runtime-smoke.ps1` 現在納入 base API/Web、query heat、queue live smoke、reports default-disabled/enabled smoke、MVT smoke，以及 query heat materialization / tile feature-cache smoke；整合修正後已重跑完整 `-StopOnExit` 並通過。
- WP4 Data realism / Phase 2 demo：已完成一輪可測 groundwork。Worker 批次流程會使用 `WORKER_ENABLED_ADAPTER_KEYS`；官方 WRA demo path 可用 runtime command 寫入 raw snapshot -> staging -> promotion -> PostGIS geometry；API query heat 由 DB helper 優先計算，DB 不可用時明確回傳 limited bucket。
- WP5 Monitoring / backup-restore：已完成 checkpoint 等級驗收。Prometheus source freshness/API availability alert rules 已新增；backup/restore drill 支援 Docker client fallback 並驗證非 scratch restore guard。
- WP6 Query heat / tile / scheduler：已完成 checkpoint 等級推進。`/v1/risk/assess` 會寫入 query/assessment snapshot；worker CLI 可 materialize `P1D`/`P7D` query heat buckets；`/v1/tiles/{layer_id}/{z}/{x}/{y}.mvt` 可從 DB 或 smoke cache 產生 response；worker 有 safe run-once / bounded scheduler / queue consume path。
- WP7 Heartbeat / governance gates：已完成 checkpoint 等級推進。Worker/scheduler heartbeat textfile metrics 已接上 alert rules；Phase 4/5 public discussion / user report legal/privacy gates 已文件化。

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
- Query heat 已從固定 bucket 推進為 DB-first helper 與 persisted query/assessment history，DB 不可用時明確標示 limited；polygon evidence 也透過 safe centroid 回傳：`apps/api/app/domain/evidence/repository.py`、`apps/api/tests/test_evidence_repository.py`、`apps/api/tests/test_public_contract.py`、`infra/migrations/0005_query_heat_persistence.sql`。
- `/v1/layers` 已改為 DB-first 讀取 seeded `map_layers` metadata，DB 不可用時才走 deterministic fallback：`apps/api/app/domain/layers/repository.py`、`infra/migrations/0004_seed_map_layers.sql`。
- `/v1/tiles/{layer_id}/{z}/{x}/{y}.mvt` 已提供 seeded layer 的最小可驗證 DB-backed MVT endpoint：`apps/api/app/api/routes/tiles.py`、`apps/api/app/domain/tiles/repository.py`、`apps/api/tests/test_tiles_contract.py`。

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
- Worker runtime 現在有 safe run-once / bounded scheduler path，預設不打外部 API，fixture mode opt-in：`apps/workers/app/jobs/runtime.py`、`apps/workers/app/scheduler.py`、`apps/workers/tests/test_worker_entrypoints.py`。
- Worker/scheduler heartbeat textfile metrics 已可由 env opt-in 輸出：`apps/workers/app/metrics.py`、`apps/workers/tests/test_heartbeat_metrics.py`、`infra/monitoring/alert-rules.yml`。

## 開發到一半或仍有 placeholder 的部分

- API 與 Web 仍保留 placeholder server 檔案：`apps/api/app/placeholder_server.py`、`apps/web/server-placeholder.mjs`。目前只能算 fallback，不是主要 runtime。
- Worker scheduler 已有單程序 run-once / bounded-loop path 與 durable queue consume smoke，但 production source clients、queue producer、singleton coordination 尚未完成。
- Query heat 已有 persisted query/assessment history 與 `P1D`/`P7D` materialization smoke；production refresh cadence 與 retention 尚未完成。
- PTT / Dcard / user_report 仍是 phase-delayed/pending implementation：`apps/workers/app/adapters/ptt/__init__.py`、`apps/workers/app/adapters/dcard/__init__.py`、`apps/workers/app/adapters/user_report/__init__.py`。
- `packages/geo`、`packages/shared` 仍以 placeholder / baseline 為主。`infra/monitoring` 已有 Prometheus scrape config、alert rules 與 heartbeat metric contract，但 dashboard 尚未完成。

## 尚未開發或尚未驗證

- Query heat production refresh cadence 與 retention 尚未完成。
- Durable production worker queue / singleton scheduler 尚未完成。
- Production tile generation/cache expiry/invalidation/hosting 尚未完成；目前是 DB-backed MVT 加 worker feature/cache smoke path。
- Phase 4 forum/public discussion expansion 尚未完成。
- Phase 5 public reports and governance 尚未完成。
- Phase 6 production hardening 尚未完成。
- Tile/layer production pipeline 尚未完成。

## 下一步建議

1. 用 reviewed real source clients 取代 fixture-backed worker runtime adapters，並加入 durable queue / singleton scheduler。
2. 將 MVT source 從 evidence/query fallback SQL 推進到 production layer tables、tile cache 與 hosting 策略。
3. 補 production monitoring dashboards，接上 freshness、heartbeat、worker last-run status。
4. Phase 4/5 public discussion / user reports 只能依新 governance gate checklist 開發。
5. 對本 checkpoint 做 final diff check、commit、push、更新 draft PR。

## WP5 Runtime smoke / phase readiness hardening（2026-04-30）

本輪 WP5 原本只改 runtime smoke、runbook、README 與 review/work-plan 文件；後續整合已加入 worker/API runtime path 與測試。下一個 phase 的驗收標準另記於 `docs/reviews/phase-next-runtime-queue-heat-tiles-reports-2026-04-30.md`。

### 已完成

- `scripts/runtime-smoke.ps1` 新增 `-Help`，並將 extended smoke 設為預設：queue live smoke、reports default-disabled/enabled smoke、MVT smoke、query heat materialization、tile feature refresh、tile cache API-read smoke。
- `docs/runbooks/runtime-smoke.md` 已補齊實際執行步驟、手動除錯 commands、安全注意事項，以及哪些 smoke 會寫入 local DB rows。
- README、work plan、本報告已連到 next-phase readiness checklist。

### 開發中

- Queue：已有 `worker_runtime_jobs`、worker consume path 與 fixture-backed smoke；production source clients、queue producer CLI、singleton scheduler 驗收仍在後續。
- Reports：default-disabled 與 enabled-path smoke 已可驗證；Phase 5 UX、moderation、abuse prevention、deletion/retention 與 governance approval 尚未完成。
- MVT：seeded `query-heat` / `flood-potential` endpoint 可 smoke；worker CLI 可 refresh `flood-potential` features，runtime smoke 也會寫入一筆 cache row 並確認 API 回傳同一份 smoke cache bytes；production tile generation/expiry/invalidation/hosting 尚未完成。
- Query heat：API persisted history fallback 可 smoke；worker CLI 可 materialize privacy-preserving `P1D`/`P7D` buckets；production refresh cadence 與 retention 尚未完成。

### 尚未完成

- Query heat production refresh cadence / retention strategy。
- Full tile cache generation、expiry、invalidation、hosting strategy。
- Public reports product readiness。
- Production queue producer、real source clients、singleton scheduler rollout。

### 下一個 phase 驗收底線

1. Runtime smoke 預設必須涵蓋 base API/Web、queue、reports、MVT、query heat materialization 與 tile feature/cache readiness。
2. Queue 不得只靠 fixture smoke 宣稱 production-ready；必須有 producer command、lease/singleton 驗證、success/retry/failure observability。
3. Reports 必須維持 default disabled；enabled smoke 只代表 repository/gate path 可運作，不代表 Phase 5 可上線。
4. MVT endpoint HTTP 200 只是最低門檻；production tile cache generation、expiry、refresh/invalidation 與 hosting 必須另行驗收。
5. Query heat 已有 local materialized bucket smoke；production readiness 仍需 refresh cadence、retention 與隱私分桶策略驗收。
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
  `infra/monitoring` now has scrape config, alert rules, and heartbeat metric
  contract, while dashboards remain pending.
- Convert to explicit known limitation: query heat has persisted history and
  local bucket materialization smoke, but production cadence/retention is still
  pending.

### Five-point status update

1. Documentation/status alignment remains done.
2. Placeholder boundary cleanup is now documented as fallback-only,
   phase-delayed, baseline placeholder, or known limitation.
3. Runtime smoke is complete for this checkpoint; runbook/script are linked
   from README and `scripts/runtime-smoke.ps1 -StopOnExit` passed locally.
4. Worker/API ingestion realism remains WP-D owned; official demo DB
   persistence, safe runtime scheduler commands, and query persistence are
   verified, while durable queue and real source clients remain limitations.
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
  UX hardening, persisted API query heat history, layer metadata, MVT tile
  endpoint, Worker adapter/demo/runtime realism, monitoring heartbeat baseline,
  and ops runbooks.
- Test matrix: backend contract/domain tests, frontend unit and Playwright smoke
  tests, worker adapter/freshness/demo tests, ops dry-run scripts, and CI hard
  gate wiring.
- Known risks: query heat production cadence/retention pending; durable
  production queue/singleton scheduler pending; production tile cache
  generation/expiry/hosting pending;
  monitoring dashboards pending; placeholders remain fallback-only or
  phase-delayed; final diff check should be run before staging.
- Rollback notes: roll back by reverting the eventual checkpoint commit and use
  `WORKER_ENABLED_ADAPTER_KEYS` to limit adapter execution during repair.

### Acceptance criteria for item 1

- Scope summary is captured from `git status --porcelain=v1 -uall`.
- No staging action was taken.
- Suggested commit message and PR body draft are available in the checkpoint
  review artifact.
- Work plan now includes a PR-body-ready five-point status and checkpoint
  acceptance criteria.
