# Core Task 9 Readiness Packet

更新時間：2026-08-25（Asia/Taipei）  
整合分支：`codex/v1-official-community`  
核准起點：`49fbb7953cb679a1a7ac0d566527bd5243bbcf4a`

## 結論

Task 8 已完成、整合並通過兩次獨立 final review 與一次 post-integration
review。Task 9 尚未實作，但依賴、檔案、RED 測試順序、真 DB concurrency
matrix、驗證命令與風險都已盤點，可以從 `49fbb79` 建立新的隔離 worktree
直接開始。

不要從 `.worktrees/v1-task10` 開始 Task 9；該 worktree 是 Task 10 的舊保留
分支，基礎早於已核准的 Task 8。

## 權威需求

- Core plan：`docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`
- Task 9 heading：`Task 9: Add Successful no_active_event Semantics and Source-Specific Health`
- 本機 extracted brief：
  `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/.superpowers/sdd/task-9-brief.md`
- 完整 read-only preflight：
  `/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/.superpowers/sdd/task-9-preflight-report.md`

## 必須沿用的 Task 8 契約

1. `warning_lifecycle_lock_key(adapter_key)` 的值為
   `official-warning-lifecycle|{adapter_key}`。Empty retirement 必須取得同一個
   per-adapter transaction advisory lock，不得另外創造不相容的 lock order。
2. Warning latest 的
   `quality_flags.ingestion_generation_started_at` 是 managed cycle 捕捉的
   `started_at`；不得改用 `finished_at`、CAP `sent` 或 fetch time。
3. Task 8 exact accepted-staging authorization 是唯一 staging promotion
   授權邊界。`no_active_event` 不建立 staging snapshot 或假 evidence。
4. Empty poll 只能刪除同 adapter、`event_type='flood_warning'`、且有效 generation
   小於等於 empty generation 的 latest；永不刪除 linked `evidence`。
5. Alert/Update 在相同 lifecycle lock 下，必須查詢該 adapter 最新成功的
   `no_active_event` job generation。較舊或相同 generation 的候選只能保留
   audit evidence，不得 resurrect latest。
6. 健康的 empty warning poll 只代表來源運作正常，不建立 query-local coverage，
   也不能滿足 public low-risk gate 所需的 local rainfall + hydrology。

## Task 9 檔案地圖

### Workers

- `apps/workers/app/adapters/contracts.py`
  - `AdapterRunResult` 增加 `no_active_event: bool = False`。
- `apps/workers/app/jobs/ingestion.py`
  - `AdapterBatchRunSummary` 增加 defaulted
    `event_active_from_min`、`event_active_until_max`。
  - 僅 reviewed CWA/NCDR warning 的無錯誤 empty poll 可成為
    `succeeded / no_active_event`。
- `apps/workers/app/jobs/freshness.py`
  - CWA/NCDR event 使用 validated active window。
  - WRA historical flood 與 flood-potential 使用背景 fetch cadence，不偽造事件時間。
- `apps/workers/app/jobs/runtime_managed.py`
  - 成功 run marker 持久化後、且 `promote=True` 才呼叫 empty retirement。
- `apps/workers/app/pipelines/promotion.py`
  - 增加 `retire_warning_latest_for_no_active_event(...) -> int`。
  - Alert/Update 增加 persisted max-empty generation anti-resurrection。
- Tests：
  - `test_ingestion_job_runner.py`
  - `test_freshness_monitoring.py`
  - `test_runtime_managed_ingestion.py`
  - `test_promotion_pipeline.py`
  - `test_promotion_monotonicity_postgres.py`

注意：原 Task 9 files list 漏列
`test_promotion_monotonicity_postgres.py`，但 concurrency acceptance 必須修改它。

### API

- `apps/api/app/domain/evidence/repository.py`
  - `RealtimeSourceHealthRow` 增加
    `latest_run_error_code`、`freshness_threshold_seconds`。
  - SQL 讀取 `ingestion_jobs.error_code` 與 catalog metadata threshold。
- `apps/api/app/domain/realtime/nearby_coverage.py`
  - Station fresh threshold 採 catalog 值，fallback `600` 秒，degraded window
    為三倍。
  - Event/status-only 的近期成功 empty poll 可為 operational，但不產生 nearby
    observation。
- Tests：
  - `test_evidence_repository.py`
  - `test_nearby_realtime_coverage.py`

## 建議實作切片

1. 先加 constructor/default RED，保證既有 caller 相容。
2. 加 CWA/NCDR valid-empty、plain-empty、transport/parse failure RED；最小實作
   contracts + ingestion summary。
3. 加 active-window、historical/background cadence RED；最小實作 freshness。
4. 在 managed-runtime tests 建立會恢復 registry 的 test-local monkeypatch fixture；
   不註冊未完成 production adapters，也不放寬 unknown adapter。
5. 加 same-adapter retirement、cross-adapter retention、evidence retention、invalid
   generation fail-closed 及 `promote=False` RED；實作 writer method。
6. 在真 PostgreSQL 以兩個 connections 覆蓋四種 generation/commit order：
   - older empty / newer Alert：Alert 必須存在；
   - newer empty / older Alert：Alert 不得復活；
   - 每個方向都跑兩種 commit order。
7. 最後加 repository mapping、source threshold、healthy empty/no-local-coverage
   API RED，再做最小實作。

每個 slice 都先看見預期 RED，再最小 GREEN；不得用 fake cursor 取代需要證明
advisory lock、generation ordering 或 PostGIS state 的案例。

## 必測矩陣

- CWA 與 NCDR 各自 valid empty、ordinary empty、transport/parse failure。
- Long-lived active CAP：舊 `sent` 但 active window 包含 checked time。
- Missing、malformed、future、expired active window 不得被救回。
- Station source 不得進 warning empty branch。
- Threshold：catalog 值、600 秒 fallback、三倍 degraded window。
- Historical/background 使用 fetch cadence，保留真實 historical timestamp。
- Empty retirement 只刪同 adapter latest，保留 peer adapter 與 audit evidence。
- 四種兩連線 concurrency commit-order 結果皆單調。
- Healthy empty warning 不建立 query-local coverage，不降低 public safety gate。

## 驗證命令

```bash
cd apps/workers
python -m pytest tests/test_ingestion_job_runner.py tests/test_freshness_monitoring.py tests/test_runtime_managed_ingestion.py tests/test_promotion_pipeline.py tests/test_promotion_monotonicity_postgres.py -q

PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
python -m pytest tests/test_promotion_monotonicity_postgres.py -q -rs

cd ../api
python -m pytest tests/test_evidence_repository.py tests/test_nearby_realtime_coverage.py tests/test_assessment_repository.py -q
```

完成後另跑 full Worker、full API、worker/API mypy、OpenAPI、changed-file Ruff、
`git diff --check`，再交給新的獨立 reviewer。Ruff 0.16.4 全樹目前有既有
baseline 問題；不得以 mass-format 無關檔案處理，但所有 Task 9 changed files
必須乾淨。

## 派工起始指令

```text
從 codex/v1-official-community 的精確 HEAD 49fbb7953cb679a1a7ac0d566527bd5243bbcf4a
建立新的隔離 Task 9 worktree。完整讀取 Core plan 的 Task 9、本文與本機
task-9-preflight-report。只做 Task 9；使用 TDD；production adapters 仍保持
disabled；先完成 synthetic registry fixture 與 RED tests，再依七個切片實作。
需要 advisory lock/generation ordering 的行為必須以 mandatory live PostgreSQL
兩連線測試證明。實作完成後不得自行核准，交由獨立 reviewer。
```

