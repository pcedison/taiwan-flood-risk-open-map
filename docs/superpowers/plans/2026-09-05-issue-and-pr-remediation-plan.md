# 2026-09-05 Issue 與 PR 整治計畫

規劃者：Claude Fable 5.1（本檔只做規劃與驗收定義）。實作者：Claude Opus 5，每個任務一個 fresh subagent、一個 worktree、一個 PR。
基準：`origin/main@6dea263`、正式站 `/health` 同 SHA。狀態來源：`gh` CLI 與 Playwright 巡檢（截圖與文字存於 session scratchpad `gh/`）。

## 0. 現況盤點（2026-09-05 05:30Z）

| 項目 | 狀態 | 依據 |
|---|---|---|
| 昨日六個修正 PR（#326、#338、#339、#340、#341、#342）與 #343、#344、#345 | 全部已合併並部署 | `git log c75c114..origin/main`、`/health` = 6dea263 |
| 快取 | 修好：同點第二次查詢 0.18–0.30 s、`assessment_id` 相同 | 三點實測 |
| 未快取查詢 | 仍 6.5–10.2 s（SDD 3.3 目標 1.5 s） | 三點實測 |
| 來源健康標籤 | 又全部 degraded：「部分站點更新較慢（新鮮 0、較慢 1317、活躍 1342）」 | `data_freshness` 實測 |
| IoW 淹水感測 | 從 partial 變成 `failed / pipeline_failed`，監控再度紅燈（#348） | `/v1/ingestion-readiness`、issue #348 |
| Civil IoT 淹水／抽水站／閘門 | 自 7/1 起 `run_failed`，上游 `sta.colife.org.tw/STA_WaterResource_v2` 今日仍回 HTTP 500（RainSewer 正常 200） | curl 實測 |
| `explanation.missing_sources` | 被三條含站數的 degraded 訊息灌滿，前端「資料限制」顯示給一般使用者 | 實測 |
| 開放 PR | 只剩 #346（retire citation source），`Contract and compose checks` 失敗 | `gh pr checks 346` |
| 開放 issue | #348、#337、#335、#334、#332（#346 會關）、#330、#329、#328、#327、#71 | `gh issue list` |
| 殘留 worktree | `.worktrees/` 22 個；19 個分支是已合併 PR 的 head，1 個有未提交變更，2 個 detached 且領先 main | `git worktree list --porcelain` |
| 遠端分支 | 100 個；63 個是已合併 PR 的 head | `gh pr list --state merged` 交叉比對 |

## 1. 根因（每條都已用程式碼或實測證實）

R1. **#346 失敗**：`infra/scripts/verify_migration_upgrade_0032_to_0036.py:26` 釘死 `EXPECTED_CHECKED_IN_VERSION = 59`，PR 加了 `0060` 但沒同步，CI 在 `:195-198` 比對版本清單時炸掉。

R2. **全部 degraded**：公開健康判定的 fresh 視窗來自 `data_sources.metadata.freshness_threshold_seconds`，只有潮位（migration 0051）有設；其餘退回 `apps/api/app/domain/evidence/repository.py:47` 的 600 秒。CWA 雨量、WRA 水位、下水道皆為 10 分鐘觀測、發布延遲數分鐘、擷取每 5 分鐘一輪，查詢當下觀測齡幾乎永遠在 10–20 分鐘，所以「新鮮 0」。#338 的比例規則是對的，門檻錯了。

R3. **IoW 變成 pipeline_failed**：worker `apps/workers/app/jobs/freshness.py:299-334` 對 IoW（門檻 90m/2h/3h）的觀測齡 30 小時判 `status="failed"`，`FreshnessCheck.is_alert()` 為真；`apps/workers/app/jobs/runtime_managed.py:741-742` 只要有 alert 就把整個 cycle 標 `failed`；`apps/workers/app/cli/runtime_cli.py:470-495` 隨後把它當失敗處理，最後 `record_pipeline_status(status="failed")` 落到 `runtime_pipeline_status`。API `nearby_coverage.py:951-958` 與 readiness `readiness.py:188-189` 都只看這個欄位，於是「上游停更」被記成「我方 pipeline 失敗」；#338 加的 `upstream_stale` 路徑根本沒機會被走到。

R4. **missing_sources 灌爆**：`apps/api/app/api/services/assessment.py:310-316` 把所有 required 來源中 `state not in {"fresh","not_applicable"}` 的訊息全部塞進 `missing`，degraded 也算，於是每次回應帶三條含站數的長句，前端「資料限制」照單全收。

R5. **Civil IoT WaterResource 上游 500**：三個 adapter 每輪都真的失敗；readiness 把它們算進 `failed_source_count`，與「我方壞掉」無法區分。

R6. **未快取查詢 6–10 秒**：引註搜尋已關，剩下的時間在 DB 讀取（jurisdiction 邊界、latest、history、observed history、15 km coverage rows、health rows）與評分；目前沒有任何分段計時，無法對症。

R7. **監控與 watchdog 噪音**：#348 由 R3 造成；#71 的 watchdog 每天在同一張 issue 留言（已 18 則），內容幾乎不變。

R8. **Repo 衛生**：見 §0 最後兩列。

## 2. 任務（依執行順序；T2–T6 可平行）

通用規則（每個任務都適用）：
- worktree：`git worktree add -b <branch> C:/Users/y_mea/AppData/Local/Temp/fr/<name> origin/main`（主 repo 路徑含中文與空白，短路徑才安全）。
- pytest 必須在 `apps/api` 或 `apps/workers` 目錄下執行，否則 import 到主 repo 的 editable install。
- 改檔一律保留原換行（用 bytes 讀寫），否則整檔 diff。
- 新增 migration 時四處同步：`apps/api/app/api/routes/health.py` 的 `REQUIRED_SCHEMA_{VERSION,FILENAME,CHECKSUM}`、`apps/api/tests/test_public_contract.py` 兩處、`infra/scripts/verify_migration_upgrade_0032_to_0036.py` 的 `EXPECTED_CHECKED_IN_VERSION`，並跑 `python infra/scripts/validate_migrations.py`。
- 每個 PR：先寫失敗測試 → 實作 → 三段驗證綠 → commit（結尾 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`）→ push → `gh pr create` 附驗證輸出 → 獨立審查 → CI 綠 → squash merge → 刪分支。
- 合併順序：T1 先（其餘 migration 編號依賴它）；T2 的 migration 0061 在 T1 合併後才能定案。

### T1. 修好並合併 #346（retire citation source）

- 分支：直接推到 PR 既有分支 `p1/retire-flood-citation-source`。
- 改：`infra/scripts/verify_migration_upgrade_0032_to_0036.py:26` → `EXPECTED_CHECKED_IN_VERSION = 60`。
- 測：`python infra/scripts/validate_migrations.py`（60 valid）、`python -m pytest tests/test_retired_flood_citation_source.py tests/test_apply_migrations_script.py -q`、`cd apps/api && python -m pytest -q tests/test_public_contract.py`。
- 驗收：PR #346 七項檢查全綠；合併後 `/ready` 的 schema 哨兵為 0060；正式站 `official.gov_tw.flood_citation` 在 `data_sources.is_enabled=false`。
- 風險：0060 只 UPDATE 一列，可在啟動交易內完成；不動 evidence 表。

### T2. 新鮮度門檻對齊實際發布節奏（修 R2）

- 分支：`p1/freshness-thresholds`。
- 改：
  1. 新增 `infra/migrations/0061_realtime_freshness_thresholds.sql`：對 `data_sources.metadata` 設 `freshness_threshold_seconds`：`official.cwa.rainfall` 1800、`official.wra.water_level` 1800、`official.civil_iot.sewer_water_level` 1800、`official.civil_iot.flood_sensor`／`pump_water_level`／`gate_water_level`／`river_water_level`／`pond_water_level` 1800、`official.wra_iow.flood_depth` 5400（與 worker、admin 的 90 分鐘一致）。潮位已有 5400 不動。用 0051 的 `jsonb_set` 寫法。
  2. `apps/api/app/domain/evidence/repository.py:47` `_DEFAULT_FRESHNESS_THRESHOLD_SECONDS` 600 → 1800；`apps/api/app/domain/realtime/nearby_coverage.py:129` 同步 1800；`apps/api/app/api/routes/admin.py` `REALTIME_FRESH_SECONDS` 600 → 1800（degraded 1800→5400、stale 維持 3600？不：改為 fresh 1800／degraded 5400／stale 10800 與 worker 一致）。
  3. `apps/workers/app/jobs/freshness.py` 的 `REALTIME_FRESH_SECONDS`／`REALTIME_DEGRADED_SECONDS`／`REALTIME_STALE_SECONDS` 與 API 對齊（讀現值後統一為 1800／5400／10800）。
  4. 新增根目錄 `tests/test_freshness_threshold_contract.py`：用 `importlib` 分別載入 api 與 workers 的常數（比照 `tests/support/dual_parse_extract.py` 的子行程 cwd 隔離），斷言兩邊三個數值相等，且 migration 0061 內每個 adapter 的秒數等於 `REALTIME_THRESHOLDS_BY_ADAPTER` 或預設 fresh 值。加進 CI `Cross-app contract guardrails` step。
  5. 四處 migration 釘死點同步到 0061。
- 測（先寫失敗）：`apps/api/tests/test_nearby_realtime_coverage.py`：1,342 站、觀測齡 18 分鐘、fresh 門檻 1800 → `healthy/operational`；觀測齡 40 分鐘 → `degraded/delayed`；IoW 觀測齡 30 小時、run 5 分鐘前成功 → `degraded/upstream_stale`（T3 合併後此案例才會在正式站成立，測試先鎖住 API 行為）。`test_evidence_repository.py` 斷言 SQL 預設 1800。
- 驗收：部署後三點實測 `data_freshness` 中 `official.cwa.rainfall`／`official.wra.water_level`／`official.civil_iot.sewer_water_level` 為 `healthy`（正常日）；`nearby_realtime_coverage` 的 `nearest_freshness_state` 對 20 分鐘內觀測回 `fresh`。

### T3. 上游停更不再被記成 pipeline 失敗（修 R3，關 #348）

- 分支：`p1/upstream-stale-not-pipeline-failure`。
- 改（worker）：
  1. `apps/workers/app/jobs/runtime_managed.py:732-745` `_status_from_cycle`：freshness alert 不再把 cycle 標 `failed`；新增 `ManagedRuntimeIngestionResult.freshness_alerts: tuple[FreshnessCheck, ...]`，cycle 狀態由 summaries 決定（`succeeded`／`partial`），alerts 另外帶出。`has_alerts` 屬性維持。
  2. `apps/workers/app/cli/runtime_cli.py:470-495`：`result.has_alerts and not result.failed` 走新分支：`log_event("worker.runtime.v1_baseline.freshness_alert", adapter_key=..., age_seconds=..., status=...)`，不計入 `failed_count`、不呼叫 `_record_v1_source_failure`；確認 `:560-575` 附近不會因 `had_failure` 把 pipeline 狀態寫成 failed（用測試鎖住：freshness-only alert 後 `runtime_pipeline_status == "succeeded"` 且 `complete=True`）。
  3. 保留 queue 路徑（`runtime.py:1405-1417`）現行行為不動。
- 改（API readiness）：`apps/api/app/domain/ingestion/readiness.py:150-200` 在 `operational` 判定前加一條：`latest_run_status == "succeeded"`、pipeline complete、但 `latest_observed_at` 早於 `3 × freshness_threshold_seconds`（從 `data_sources.metadata` 讀，缺省 1800）→ `status="degraded"`、`reason_code="upstream_stale"`；`SourceReadinessStatus`／reason Literal、`docs/api/openapi.yaml` 的 readiness schema、`apps/web` 若有對應型別一併補。
- 改（監控）：`scripts/hosted_public_risk_evidence_smoke.py:523-556` 在 failures 之外輸出 `advisories`，把 `reason_code == "upstream_stale"` 的 required source 列為 advisory（health 已是 degraded，本來就不會 fail，這一步只是讓報告可讀）。
- 測（先寫失敗）：`apps/workers/tests/test_runtime_managed.py`／`test_v1_baseline_runner.py`：summaries 全部 succeeded、freshness check `failed`（age 30h）→ 結果 `status="succeeded"`、`freshness_alerts` 長度 1、`record_pipeline_status` 收到 `status="succeeded", complete=True`；`apps/api/tests/test_ingestion_readiness.py`（找既有檔名）：上述 row → `degraded/upstream_stale`；smoke 測試：advisory 出現、failures 空。
- 驗收：部署一輪擷取後 `/v1/ingestion-readiness` 的 `official-wra-iow-flood-depth` 為 `degraded/upstream_stale`；`data_freshness` 的 IoW 為 `degraded` 且訊息含「上游資料來源自 … 起未更新」；下一次 Hosted Monitoring schedule 綠燈、#348 自動關閉。

### T4. `missing_sources` 只放使用者需要知道的缺口（修 R4）

- 分支：`p1/missing-sources-user-facing`。
- 改：`apps/api/app/api/services/assessment.py:298-326` `_data_status`：
  - required 來源 `state in {"failed","stale","disabled","unknown"}` → 保留原訊息。
  - `state == "degraded"` → 不逐條列；若至少一個 degraded，加一句彙總：「部分官方即時來源更新較慢（{訊號中文名以頓號連接}），仍可作當下參考。」訊號中文名用 `apps/api/app/domain/realtime/nearby_coverage.py` 的 `SIGNAL_LABELS`。
  - `upstream_stale` 的來源另加一句：「{來源中文名}上游自 {台北時間} 起未更新。」（訊息已由 T3 產生，這裡只做去重）。
- 測（先寫失敗）：`apps/api/tests/test_assessment_service.py`：三個 degraded required 來源 → `missing_sources` 只含一句彙總；一個 failed → 原訊息保留；`explanation.missing_sources` 與 `data_status.missing` 一致。
- 驗收：實測臺北 `explanation.missing_sources` 長度 ≤ 2，且不含「新鮮 0、較慢」字樣。

### T5. Civil IoT WaterResource 上游故障隔離（#327，修 R5）

- 分支：`p1/civil-iot-upstream-quarantine`。
- 改：
  1. `readiness.py`：`latest_run_status == "failed"` 且 `latest_run_error_code` 屬於上游類（`HTTPError`、`URLError`、`TimeoutError`、`RemoteDisconnected`；讀 `apps/workers/app/adapters/civil_iot/sta_client.py` 實際丟出的例外類名補齊）→ `status="failed"`、`reason_code="upstream_unavailable"`；`source_summary` 新增 `upstream_unavailable_source_count`，並從 `failed_source_count` 扣除；`status` 總結：只有 upstream_unavailable 而無其他 failed 時為 `degraded` 而非 `failed`。
  2. 公開 `data_freshness`／`nearby_coverage` 對這三個來源已有 `upstream_unavailable`（`_pipeline_failure_decision` 的 TimeoutError 分支）；補 `HTTPError`／`URLError` 分支，訊息「上游服務目前回應錯誤；本站每輪重試中。」
  3. `config/source-registry.yaml` 三個來源加 `upstream_incident: "2026-07-01 STA_WaterResource_v2 HTTP 500"` 註記欄（validator 允許未知欄位；若不允許則加進 schema），`docs/runbooks/civil-iot-live-enablement.md` 補「上游 500 通報流程」段落與聯絡窗口（民生公共物聯網 ci.taiwan.gov.tw 客服）。
- 測（先寫失敗）：readiness 測試：error_code `HTTPError` → `failed/upstream_unavailable` 且 summary 計數正確；nearby_coverage 測試：同上 → `failed/upstream_unavailable` 與新訊息。
- 驗收：`/v1/ingestion-readiness` 頂層 `status` 由 `degraded` 的原因不再包含這三個來源的 `run_failed`；`failed_source_count` 不含它們。
- 人工待辦（開在 #327 留言）：向民生公共物聯網回報 `STA_WaterResource_v2` 500，附最小重現 `GET /v1.0/Things?$top=1`。

### T6. 未快取查詢分段計時（#330 第一步，修 R6 的前置）

- 分支：`p1/assess-server-timing`。
- 改：
  1. `apps/api/app/domain/assessment/repository.py` `PostgresAssessmentRepository.load`：用 `time.perf_counter()` 包住 `_load_jurisdiction`、`_load_latest`、`_load_history`、`_load_observed_flood_history`、`_load_coverage`、`_load_recent_context`、`_load_health`，結果放進 `AssessmentData.timings_ms: dict[str, float]`（dataclass 新欄位，預設空 dict）。
  2. `apps/api/app/api/services/assessment.py` `assess()`：量 `scoring`、`persist`、`cache_get`／`cache_set`，合併到 `response` 的非序列化屬性（用 `RiskAssessmentResponse.model_config` 的 `extra` 或另一個回傳型別 `AssessOutcome(response, timings)`；不得改公開 JSON schema）。
  3. `apps/api/app/api/routes/public.py` `assess_risk` 路由：回應加 `Server-Timing` 標頭，格式 `db_jurisdiction;dur=12.3, db_latest;dur=…, …, total;dur=…`，並 `log_event("api.risk.assess.timings", **timings)`。快取命中時只帶 `cache_hit;dur=…`。
  4. `docs/runbooks/` 新增 `assess-latency-profiling.md`：如何用 `curl -sD - -o /dev/null` 讀標頭、預期目標（SDD 3.3）。
- 測（先寫失敗）：repository 測試斷言 `timings_ms` 含七個鍵且皆 ≥ 0；路由測試（TestClient）斷言 `Server-Timing` 存在、含 `total`；快取命中時含 `cache_hit`。
- 驗收：部署後對三點各打一次未快取查詢，把 `Server-Timing` 記到 #330，指出前兩大耗時段；T6b（實際優化）依此另開。

### T7. Watchdog 去重（#71 噪音，修 R7）

- 分支：`p2/local-source-watchdog-dedupe`。
- 改：`.github/workflows/local-source-dispatch-watchdog.yml` 的 github-script 段（第 123–220 行）：計算 request-packet bundle 的 SHA-256（`artifacts/request-packet-bundle/*.json` 串接），與 issue #71 body 尾端 HTML 註解 `<!-- dispatch-state: {"digest":..., "last_comment_at":...} -->` 比對；digest 相同且距上次留言 < 7 天 → 只更新 body 的 `last_seen_at`，不留言。實作放到 `scripts/ci/local-source-watchdog-state.js`，比照 `scripts/ci/route-alert-issue.js` 的結構，並補 `tests/test_local_source_watchdog_state_js.py`（用 node 跑，PATH 需含 `C:\Program Files\nodejs`）。
- 驗收：連續兩次 workflow_dispatch 只產生一則留言。

### T8. Repo 衛生（#334）

- 由規劃者本人執行（不需 Opus），逐項留紀錄：
  1. 移除 `.worktrees/` 下 19 個「分支為已合併 PR head 且 `git status` 乾淨」的 worktree（`git worktree remove --force`），保留 `ncdr-active-window-monitor`（3 個未提交檔）、`history-staging-release`（領先 11 commit 未合併）、`prod-main-verify`／`verify-promotion`（detached，需人工看內容）。
  2. 刪除 63 個「已合併 PR head」的遠端分支（`git push origin --delete`），保留 `production-release`、`p1/retire-flood-citation-source`（T1 合併後再刪）與所有未合併的 `codex/*`。
  3. `CONTRIBUTING.md` 新增「自動化 PR 守則」：每個 PR 必須連結 issue；一個 PR 一件事；不得只為更新 `PROJECT_STATUS.md` 開 PR；含資料改寫的 migration 必須附 staging 演練證據；`docs/superpowers/plans/` 的計畫書不是需求來源。`.github/pull_request_template.md` 加 `Linked issue:` 欄位。
- 驗收：`git worktree list` ≤ 4；遠端分支 < 40；CONTRIBUTING 與模板更新進 main。

### T9. catalog 的 runtime 狀態由 registry 產生（#335）

- 分支：`p2/catalog-runtime-state-from-registry`。
- 改：新增 `infra/scripts/render_source_catalog_runtime_state.py`：讀 `config/source-registry.yaml`，把每個 `adapter_key` 的 `enablement_decision`／`deployment_default`／`catalog_state` 映射成 `runtime_state`（`production_backbone`→`live`、`eligible_default_off`→`available_off`、`audit_only`→`retired`、`blocked_*`／`*_pending`→`blocked`、其餘→`reference`），寫回 `docs/data-sources/official/official-source-catalog.yaml` 每個 source 的 `runtime_state` 欄（保留舊 `status`），`--check` 模式只比對不寫。`infra/scripts/validate_source_registry.py` 呼叫 `--check`，CI 已跑此 validator。
- 測：`tests/test_render_source_catalog_runtime_state.py`：映射表覆蓋 registry 中出現的全部 `enablement_decision` 值；`--check` 在 catalog 缺欄位時非零退出。
- 驗收：改 registry 不重跑 render 時 CI 紅。

### T10. 不在本輪寫程式、需要你決策的項目

- #328 啟用 `official.wra.flood_incident`：等你註冊 fhy.wra.gov.tw/openapiv3 金鑰；拿到後照 `docs/runbooks/safe-fast-official-incident-activation.md` 單源啟用，Opus 再補 live fixture 與 false-positive 測試。
- #329 worker 端 L2 新聞 adapter：需要先定 allowlist 出版者與 RSS 清單（`docs/data-sources/news/l2-source-allowlist.yaml` 目前只有樣板）；下一輪。
- #337 社群路線：PTT L3 是否以非營利身分推進、Threads 是否寫 ADR。
- 正式站 Zeabur 記憶體（2 GB）仍是每次部署 502 風險的根源；本輪 6 個 PR 合併＝6 次部署。

## 3. 執行與合併

- 平行：T1 完成並合併後，同時派 T2、T3、T4、T5、T6（五個 worktree、五個 Opus 實作員）；T7、T9 隨後；T8 由規劃者做。
- 每個 PR 由另一個 Opus 審查員做規格符合＋品質審查，必修項回給同一實作員修，再複審。
- 合併：規劃者執行 `gh pr merge --squash --delete-branch`；若權限管控擋下，回報並請你合併或加 `Bash(gh pr merge:*)` 允許規則。
- 合併後驗收：`/health` 追上 SHA → 三點實測（快取、延遲、`data_freshness`、`missing_sources`）→ `/v1/ingestion-readiness` → 下一次 Hosted Monitoring schedule 結果。

## 4. 執行紀錄（2026-09-05，由規劃者更新）

| 任務 | PR | 審查 | 狀態 | 部署後驗證 |
|---|---|---|---|---|
| T1 修 #346 | #346 | 一行釘死值，規劃者自修 | 已合併 3450a59 | `/ready` 正常，0060 套用無事故 |
| T8 守則 | #349 | 純文件 | 已合併 ba6cd63 | 18 個 worktree、63 個遠端分支已清（100→38） |
| T4 missing_sources | #350 | APPROVE（3 小項補齊） | 已合併 f4391fa | 臺北 `missing_sources` 由 4 句降為 2 句 |
| T6 Server-Timing | #351 | 第 1 輪抓到 `app.events` logger 無 handler 永遠不輸出，修後 APPROVE | 已合併 9ee741c | 未快取 5.4–8.3 s：`db_history` 3.0–5.6 s、`db_coverage` 1.5 s（已記 #330） |
| T7 watchdog 去重 | #352 | 第 1 輪抓到 digest 未含 status，修後 APPROVE | 已合併 f1210be | 下次 #71 排程驗證 |
| T9 catalog runtime_state | #355 | APPROVE（4 小項補齊） | 已合併 6ca103a | CI `--check` 守門生效 |
| T5 Civil IoT 隔離 | #354 | 第 1 輪抓到 down 條件放寬、PayloadError 混入、訊息分支不可達，修後 APPROVE | 已合併 789b8f1 | readiness `failed=0`、`upstream_unavailable=3` |
| T2 新鮮度門檻 | #353 | 一項必修（postgres 測試 600→1800）＋ NCDR 輪詢常數分離，修後 APPROVE | 已合併 fdf22bf | CWA 1317/1342、WRA 341/358、下水道 1613/1998 皆 **healthy** |
| T3 上游停更 | #357 | APPROVE（4 個一行修正補齊） | 已合併 828f743 | IoW 在部分週期已顯示「上游資料來源自 2026/09/02 12:29 起未更新；本站背景更新正常」 |
| T6b DB 讀取優化 | #359 | 第 1 輪抓到 seed 腳本無生產防呆，修後 APPROVE | 已合併 26b7589 | 本機 112 萬列實測：`db_coverage` 1.5 s 是 supplement 撞 1500 ms 逾時後整批丟掉，預算降 250 ms；`db_history` 本機 30–40 ms 無法重現正式站，未加索引（planner 不選） |
| T3b promotion 逐列交易 | #360 | APPROVE（建議 FOR SHARE 與 peer 存活測試 → T3c） | 已合併 0cff52c | 停更快照每輪 11,228 SQL／1,366 commit → 1,410／14；順帶修掉「凍結快照每輪刪臺南 peer latest 列」既有 bug |
| T6c admin DB 診斷 | #364 | 審查中 | 開放 | `GET /admin/v1/db-diagnostics` ＋ Hosted Monitoring advisory artifact，讓正式站 EXPLAIN／表膨脹可見 |
| T3c 批次查重加鎖 | #365 | 規劃者自審（diff 小） | 已合併 efd8389 | `FOR SHARE OF official_realtime_latest` ＋ Postgres 測試釘住「凍結快照重放時臺南 peer latest 列存活」（mutation check 通過） |

2026-09-06 08:0xZ 手動觸發 Hosted Monitoring（run 34020099663）**success**，#348 由 route-alert 自動關閉；這是 8/31 以來第一次在含 IoW 上游停更的狀態下綠燈。

2026-09-06 07:40Z 部署 0cff52c 後三個週期：IoW readiness `degraded/run_incomplete`、公開 `degraded/upstream_stale`（不再 `pipeline_failed`）；`db_coverage` 1515 → 268–283 ms；`db_history` 3.0–5.6 s → 1.9–2.5 s；total 5.4–8.3 s → 4.3–4.6 s（仍未達 SDD 1.5 s，等 #364 的正式站 EXPLAIN）。新開 issue：#356（reason_code 串進 AssessmentSourceState）、#358（新鮮度門檻）、#361（促銷階段錯誤碼未保存）。
