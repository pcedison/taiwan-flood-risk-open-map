# 2026-08-25 Windows 更新與 Mac v1 主線整合決策

- 更新時間：2026-08-25（Asia/Taipei）
- Mac 權威分支：`codex/v1-official-community`
- 遠端比較快照：`49fbb7953cb679a1a7ac0d566527bd5243bbcf4a`
- 原始 Task 9 implementation head：`5fb9e544ccdaa48fa05b24a8da40c7cb5d59810c`
- milestone safety-fix 前 review head：`f675af3c90902bcb9163eea979a2073ca14e1258`
- milestone safety-fix：本報告所在提交，commit message
  `fix: close Task 9 milestone safety gaps`（提交後以 `git rev-parse HEAD` 取得權威 SHA）

## 執行結論

不可把 `origin/main` 直接 pull、merge 或 fast-forward 進 Mac v1 分支。
兩邊共同基準是 `a526328052b1faa2ac8a54715228f6cff5c05389`。在
`49fbb79` 遠端比較快照，Mac／remote unique commits 是 `24/3`；在 safety-fix 前
`f675af3` review head 是 `29/3`。這些是具名快照，不是永遠不變的目前數字；本次
safety-fix 提交後若 `origin/main` 未變，會是 `30/3`。
直接合併會同時帶回已被 Task 6/7 刻意移除的 request-time official bridge
與 generic scheduler 路徑，破壞 persisted-only assessment 邊界。

正確策略是以 Mac `49fbb79` 為主線，逐項 manual port，且每項獨立測試及審查。

## 今日遠端更新盤點

### PR #196 — `fix: surface stalled realtime ingestion`

- PR：<https://github.com/pcedison/taiwan-flood-risk-open-map/pull/196>
- 合併時間：2026-08-25 11:58（Asia/Taipei）
- canonical squash：`377ef2865059513a836591d1fa3260ab5953bb8f`
- 原分支三個提交的 tree 與 squash 完全相同，不得重複移植。
- GitHub checks：Backend、Frontend、Contract and compose 全部成功。

內容分為三類：

1. Hosted monitoring 開始拒絕未檢查或 stalled/failed 的必要 worker source。
2. Legacy `public_risk.assess_risk` 在 persisted coverage 不可用時，以 request-time
   CWA/WRA bridge 回補。
3. Web dependency overrides 更新 `brace-expansion`、`js-yaml`、`postcss`，lockfile
   同步解析到修正版本。

### PR #197 — `fix: keep Zeabur realtime ingestion current`

- PR：<https://github.com/pcedison/taiwan-flood-risk-open-map/pull/197>
- 合併時間：2026-08-25 12:32（Asia/Taipei）
- canonical patch：`05324c749d55ec7b348030a3fe36c6e194058c5f`
- main merge commit：`d64b7b37786a52e3967174b9d0e59c55aa6f2f8a`
- `d64b7b3` 與 `05324c7` tree 相同；整合時使用內容 patch，不 cherry-pick merge commit。
- GitHub checks：Backend、Frontend、Contract and compose 全部成功。

內容：

1. WRA v2 無時區 timestamp 視為臺灣時間 UTC+8，再轉成 UTC。
2. Zeabur entrypoint 增加 `POSTGRES_CONNECTION_STRING` 與 `POSTGRES_URI` DB alias。

## 與 Mac 最近兩日工作的關鍵差異

| 面向 | Mac v1（權威） | Windows／remote main | 決策 |
|---|---|---|---|
| 公開風險查詢 | `AssessmentService` 只讀持久化 evidence/health | legacy service 可在 request-time 抓 CWA/WRA | 保留 Mac；拒絕 bridge hunk |
| 正式 worker 入口 | generic managed/scheduler 已 frozen；只允許 scoped v1 seam | entrypoint 仍呼叫 `--run-enabled-adapters --persist --scheduler` | 不復活 legacy；由 Task 14 v1 runner 接管 |
| Promotion | Task 8 已有 exact staging authorization、同 adapter lock、generation monotonicity | 今日 PR 未涵蓋 | 完整保留 Mac |
| Empty warning | Task 9 已實作 `no_active_event`、anti-resurrection，並完成 milestone safety-fix wave | 今日 PR 未實作 | 保留 Mac 實作；完成獨立 milestone 複審 |
| WRA timestamp | 無 offset 值被共同 parser 當 UTC，可能落在未來 | 改以 UTC+8 解析 | 立即 manual port |
| Source health | persisted health 與 public safety seam 已建立，Task 9 再精化 | smoke 開始拒絕 stalled/failed | 保留監控意圖，接到 Mac seam |
| DB aliases | API 接受平台 alias；entrypoint 不完整 | entrypoint 補 alias | 由 Task 14 新 runner/entrypoint 採用 |
| Web 依賴 | lockfile 仍有 high severity audit 項目 | remote 更新 overrides/lockfile | 分離成安全更新，不與 realtime 混合 |

## 正式環境即時證據與根因

### 已確認正常

- `https://floodrisk.cc/health` 已部署
  `d64b7b37786a52e3967174b9d0e59c55aa6f2f8a`。
- GitHub run `32848151850` 的 main CI 成功。
- 2026-08-25 13:38 後，公開風險回應已有新的 CWA rainfall 與 WRA water-level
  persisted evidence；舊版公開 evidence smoke 可通過。
- 背景 scheduler 確實持續運作；用新的 `location_text` 避開固定 smoke request 的
  10 分鐘 response cache 後，同一 500m 查詢可見 15 筆 persisted evidence。

### 仍然失敗

- Hosted Monitoring runs `32851048430`、`32852139879` 失敗。
- 13:03／13:14 的「無 CWA/WRA evidence」包含部署後首輪尚未完成，以及固定 smoke
  request 命中舊 response cache 的暫態；它不是目前持續失敗的主因。
- 使用 remote main 最新 smoke 重跑，仍會拒絕 6 個
  `pipeline_unavailable` 的 Civil IoT source。
- 遠端目前把尚未完成 publication pipeline 的 Civil IoT sewer/pond/pump/gate/
  river/flood-sensor 全部列為 `required_for_absence=true`。
- 部分 public response 同時呈現 `nearby_realtime_coverage.overall_level=low` 與
  `source_health_status=degraded`、缺 flood-depth/sewer-water-level。這個語意不能
  作為正式 low-risk 上線證明。
- `gh secret list --app actions` 與 `gh variable list` 均未回傳任何設定；scheduled
  workflow 已要求 admin freshness，因此即使 public smoke 恢復，缺少
  `ADMIN_BEARER_TOKEN` 仍會按設計失敗。

### 根因

PR #196 的監控不是穩定失敗根因；它只是把既有 catalog/runtime 不一致揭露出來。
真正根因是舊來源目錄與 generic runtime 嘗試管理超出核准 v1 baseline 的來源，
但這些來源沒有完整 staging → promotion → latest publication 成功鏈。

Mac Task 14 的 migration 0038 已針對此問題設計：以精確 v1 mapping 取代舊 policy，
Civil IoT 與 tide 不再成為全國 low/absence proof 的 required source；所有 v1 catalog
row 在 migration 後仍預設 disabled，逐來源通過 staging proof 後才由 operator
transaction 啟用。

## 精確採用／拒絕清單

### 立即採用

1. `05324c7` 的 WRA 無 offset timestamp UTC+8 parser 與 regression test。
2. `377ef28` 的 Web dependency 安全更新，獨立 audit/build/test。

### 依 Task 9/14 seam 採用

1. Hosted smoke 的 worker source-health gate；再加一條「至少實際檢查一個 required
   source」的 fail-closed 規則。
2. Scheduled admin freshness gate；先配置 `ADMIN_BEARER_TOKEN`，否則排程會按設計
   持續紅燈。
3. `POSTGRES_CONNECTION_STRING`／`POSTGRES_URI` alias；由 Task 14A/16 接到 scoped
   v1 baseline runner、Docker entrypoint 與 Compose/Zeabur contract tests，不宣稱
   frozen generic scheduler 已恢復。
4. 對應 runbook 只在實際 v1 行為存在後更新。

### 明確拒絕

1. `apps/api/app/api/services/public_risk.py` 的 request-time bridge fallback。
2. 依賴該 legacy bridge 的 `test_public_risk_service.py` hunks。
3. 把 `python -m app.main --run-enabled-adapters --persist --scheduler` 當成 v1
   production recovery command。
4. 整體 cherry-pick `377ef28`、`d64b7b3` 或直接 merge `origin/main`。

## 加速整合與上線切片

### P0-A：可公開技術預覽

- API/Web 可對外，但畫面必須保留 preview/資料不足語意。
- 可保持既有 hosted 服務；不可用目前的 degraded source health 宣稱正式 production
  readiness。
- user reports、dynamic tiles、community browser discovery、未核准 local/Civil IoT
  sources保持 disabled。
- request-time official diagnostic fallback 保持 disabled。
- preview deployment 必須省略 `SERVICE_ROLE=scheduler`；在 Task 14A/16 完成平台
  alias 與 entrypoint 契約前，必須明確把平台連線值映射成 `DATABASE_URL`。

### P0-B：安全修正整合

1. WRA UTC+8 修正，focused Worker tests + Task 8 staging/promotion regressions。
2. Web dependency update，`npm audit --audit-level=high`、lint、typecheck、unit、build。
3. 兩者分開提交，便於單獨 rollback。

### P1-A：Task 9

完整依 `docs/reviews/task-9-readiness-2026-08-25.md`：

- valid CWA/NCDR empty poll → succeeded/no-active；
- same-adapter warning retirement；
- persisted generation anti-resurrection；
- catalog freshness threshold；
- mandatory live PostgreSQL 兩連線 concurrency matrix。

不得用 request-time bridge 取代。

### P1-B：Task 14 拆分但不放寬契約

為縮短上線時間，把原 Task 14 依提交拆為：

1. `14A`：per-source v1 wrapper、CLI、scoped v1 command wiring、Docker entrypoint、
   Compose/Zeabur contract tests、runtime 文件與 isolation tests。
2. `14B`：migration 0038 精確 catalog/mapping/contract replacement，所有來源 disabled。

14A/14B 都屬原 Task 14 契約，不能以跳過 14B 或批次開啟來源換速度；migration
0038 後所有來源仍保持 disabled。

### P2：正式上線核准

- Task 15 rolling Web fallback。
- Task 16 full API/Worker/Web、empty DB、0037→0038、mandatory DB suites、Docker／
  Compose／Zeabur hosted wiring 複證，並逐來源執行 isolated staging proof、operator
  activation、assessment smoke、backup/rollback/on-call evidence。
- 只有這一層通過才稱 production ready；在此之前稱 technical preview 或 staging。

## 最短安全路徑

`49fbb79` → WRA fix → Web dependency fix → Task 9 safety-fix／獨立複審 →
Tasks 10–13 → Task 14A → Task 14B（0038、rows disabled）→ Task 15 →
Task 16 isolated proof／operator activation／hosted acceptance。

Community/社群爬文混合模式不進入這條 P0/P1 critical path；它保持既定獨立計畫，
不得阻塞官方資料 baseline 上線，也不得在尚未完成 privacy/source-policy acceptance
前影響官方風險分數。

## 本次實作與審查狀態

### 1. WRA 無時區 timestamp 修正

- Commit：`4ec88857afd1bd47c25c457061ba65cefdc8a343`
- 行為：WRA v2 無 offset 時間視為 UTC+8，再正規化為 UTC；有 offset 時保持正常
  轉換。
- 保留：Task 8 的 `evidence_scope="current"` raw/staging 契約。
- 驗證：official adapter `19 passed`；staging/promotion `112 passed`；scoped Ruff、
  diff-check 通過。
- 獨立 task review：APPROVED，無 finding。

### 2. Web dependency audit blockers

- Commit：`7a6ead2722ccd937184e98383910c9abd7f680e3`
- 只移植 canonical `377ef28` 的 `package.json`／lockfile 兩檔，byte-identical。
- Audit：`11 high` → `0 vulnerabilities`。
- 驗證：lint、typecheck、Web unit `66 passed`、production build 通過。
- 獨立 task review：APPROVED，無 finding。
- 本機使用 Node 26；GitHub CI／Docker 的正式 runtime 仍是 Node 22。

### 3. Core Task 9 — `no_active_event` 與來源健康

- Feature commit：`72e382c3df9e50265f59b4f1f7e94c6e934fae2f`
- Review-fix commit：`5fb9e544ccdaa48fa05b24a8da40c7cb5d59810c`
- Milestone safety-fix commit：本報告所在提交
  `fix: close Task 9 milestone safety gaps`
- 完成：
  - exact CWA/NCDR valid empty → persisted succeeded/no-active；
  - active-window freshness 與 authentic source timestamp 分離；
  - same-adapter retirement、evidence/peer retention；
  - persisted generation anti-resurrection；
  - catalog source threshold、600 秒 fallback、3 倍 degraded window；
  - healthy empty warning 不建立 local coverage，也不放寬 public low gate。
- 初次獨立 review 找到：
  - Critical：blocked audit-only Update 仍可經 CAP references 刪 current latest；
  - Important：skipped/partial static background run 被誤標 fresh。
- 首輪兩項均以新 RED tests 修正，task-level 複審曾 APPROVED；後續 milestone review
  又找出跨 adapter deletion race、result identity/empty shape、disjoint windows、coverage
  固定時窗、unsafe metadata cast 與文件順序問題。
- 本次 safety-fix 已修正全部 milestone findings；實作者驗證：
  - focused Worker `178 passed`；
  - mandatory live PostgreSQL `58 passed`、zero skips（包含 Update/empty marker 兩種
    commit order 與 same/peer latest retention）；
  - full Worker `694 passed`、`58 skipped`（optional live collection）；
  - focused API `126 passed`；full API `667 passed`、`14 skipped`、1 個既有
    dependency deprecation warning；
  - live API unsafe-threshold full-query regression `1 passed`；
  - worker/API mypy、changed-file Ruff、OpenAPI、diff-check 通過。
- safety-fix 仍須獨立 milestone 複審；實作者不得自行核准。

## 目前 go/no-go

### Technical preview：GO（有條件）

- 現有 `floodrisk.cc` 可繼續作為部分來源 Beta／technical preview。
- 必須如實呈現 unknown／資料不足，不能以 degraded source health 宣稱全國低風險。
- 若把 Mac 分支部署到 hosted preview，在 Task 14 runner 完成前必須保持
  `REALTIME_BACKBONE_INGESTION_DISABLED=true`，省略 `SERVICE_ROLE=scheduler`，並明確
  映射 `DATABASE_URL`；否則 Docker entrypoint 可能呼叫 Task 7 已 frozen 的 generic
  scheduler，或無法辨識平台 DB alias。

### 正式 production：NO-GO

仍需：

1. Tasks 10–13 的正式 adapter/artifact acceptance；
2. Task 14A per-source runner／host wiring、14B migration 0038（rows disabled）；
3. Task 15 rolling Web fallback；
4. Task 16 isolated proof、逐來源 operator enable／rollback 與 hosted acceptance；
5. Hosted monitoring cache-safe probe 與只針對 approved+enabled source 的 acceptance
   gate；
6. GitHub `ADMIN_BEARER_TOKEN` 與其餘私有監控／備份／rollback/on-call evidence。

在這些條件完成前，不應關掉監控、把失敗來源假標 degraded/healthy，或重新啟用
request-time official bridge 來取得表面綠燈。
