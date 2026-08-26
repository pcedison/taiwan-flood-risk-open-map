# Flood Risk v1 Subagent-Driven 開發中斷交接報告

> **2026-08-25 更新：** 本報告的 Task 8「進行中」內容已成為歷史紀錄。
> Task 8 已完成並整合到 `codex/v1-official-community` HEAD `49fbb79`，經兩次
> 獨立 final review 與一次 post-integration review `APPROVED`。後續請從
> [Task 9 readiness packet](./task-9-readiness-2026-08-25.md) 接續；不要再依
> 本報告第 6 節重做或重置 Task 8。

更新時間：2026-08-24 19:43 CST  
工作區：`/Users/marcus/Documents/ChatGPT/flood-risk`  
主要整合分支：`codex/v1-official-community`  
開發方式：Subagent-Driven Development、TDD、獨立複審、真實 PostGIS 驗證

## 1. 交接摘要

目前**尚不可宣稱完成、不可直接上線、也尚未部署**。

- Core Task 1–7 已完成、提交並通過獨立複審。
- Core Task 8 是目前唯一正在修正的核心工作。
- Task 8 已有兩個提交，但最新四項複審修正仍是**未提交 diff**。
- 最新未提交 Task 8 狀態：真實 PostGIS `49 passed`，Ruff、mypy、`git diff --check` 通過；focused unit 為 `77 passed, 3 failed`，完整 worker/API suite 尚未重跑。
- Core Task 10 的隔離 worktree 已建立，但尚未開始實作。
- Core Task 9–16 及 Community Task 1–11 均未完成。
- `main`、遠端、Zeabur 或其他 hosted environment 都沒有被這一輪工作修改或部署。

最重要的接手原則：**保留 Task 8 未提交 diff，不要 reset、checkout 或覆寫；先解決 3 個 unit failures，再完成 full verification、commit、獨立複審與整合。**

## 2. 已核准的產品範圍

v1 只處理一個清楚流程：

1. 使用者輸入地址、地標、道路，或直接點選地圖。
2. 使用者選擇搜尋半徑。
3. Geocoder 回傳候選座標、位置精度、縣市、行政區、道路與別名。
4. API 只從已持久化資料查詢附近官方即時、官方歷史、淹水潛勢與社群訊號。
5. 系統分開計算即時風險與歷史背景風險，再產生整體摘要、信心、主導模式、證據與資料缺口。
6. 使用者查詢只提高背景社群搜尋優先度；初次 response 不等待外部網站。

全臺中央基線的核准來源：

- CWA 自動雨量與豪大雨 CAP。
- WRA 水位與 IoW 淹水深度。
- NCDR/WRA 民生示警 CAP。
- WRA 歷史淹水 KML。
- WRA 淹水潛勢資料。
- 臺南市正式開放淹水感測器作地方補充。

高雄、屏東若沒有正式機器介面，v1 顯示資料缺口，不以人讀網頁或登入式爬蟲冒充正式資料。

社群採混合模式：

- Production 自動擷取只准正式 API、RSS/Atom/CAP/SensorThings、核准 bulk data 或書面授權介面。
- 第一個規劃中的正式社群 adapter 是 Threads keyword search API，但必須通過 App、permission、review、token 與 real-App metadata-only artifact 等硬閘門。
- 使用者回報是另一個獨立來源。
- Browser Agent 只做受監督的來源發現、人工事件複核與公開頁面存續確認；結果先進隔離狀態，不能直接改公開風險。
- 不登入、不繞 CAPTCHA/反爬、不保存作者、完整文章、留言、HTML、Cookie、截圖或原始媒體。
- 單篇社群文章不改分；兩個獨立社群來源，或一個社群來源加相容官方異常，才能形成交叉佐證。
- 社群只能提高警戒、不能降低風險；官方資料 stale/failed/missing 不能被解讀成低風險。

## 3. 架構與資料流

### 3.1 Public request path

```text
地址／地標／道路／地圖點
        ↓
Geocoder（位置候選、精度、server-resolved 行政區）
        ↓
POST /v1/risk/assess（point + radius）
        ↓
AssessmentService
        ↓
EvidenceRepository 單次持久化讀取
  ├─ current official latest
  ├─ historical evidence
  ├─ flood-potential context／coverage
  ├─ source health／freshness
  └─ 後續 community clusters
        ↓
realtime scorer 與 historical scorer 分開執行
        ↓
base overall composition
        ↓
後續只允許一個 community uplift seam
        ↓
風險、信心、dominant_mode、證據、資料狀態與缺口
```

Public request 不可同步打 CWA/WRA/NCDR/社群上游，不可使用 legacy profile、query heat、tile writer 或 generic runtime dispatch。

### 3.2 Official ingestion path

```text
per-source scheduler / v1 baseline wrapper（Task 14）
        ↓
adapter fetch → normalize
        ↓
raw snapshot + staging evidence
        ↓
strict metadata／時間／座標／CAP lifecycle validation
        ↓
promotion transaction
  ├─ immutable/audit evidence
  ├─ monotonic official_realtime_latest
  ├─ exact central/local dedupe
  └─ CAP Alert/Update/Cancel lifecycle
        ↓
persisted-only AssessmentService read
```

每個來源獨立成功或失敗；舊 accepted 值可保留作 audit，但 freshness/health 必須顯示真實狀態。

### 3.3 Community path（全部仍待實作）

```text
正式 Threads API／first-party user report／quarantined browser discovery
        ↓
metadata-only normalization + keyed fingerprint
        ↓
location/keyword controlled matching
        ↓
suppression + retention + source-policy gates
        ↓
origin grouping + event clustering + corroboration
        ↓
sanitized repository read
        ↓
AssessmentService 的單一 community uplift seam
```

原文只可短暫存在 adapter 記憶體；sanitized signal 預設最多保存 30 天，public social evidence 的 `raw_ref` 必須是 `null`。

## 4. Git、worktree 與環境快照

| 路徑 | 分支／HEAD | 狀態 | 用途 |
| --- | --- | --- | --- |
| `/Users/marcus/Documents/ChatGPT/flood-risk` | `main` @ `ce61edb` | 原工作樹乾淨；`origin/main` ahead 2 | 不要在此直接整合 Task 8 |
| `.worktrees/v1-official-community` | `codex/v1-official-community` @ `124a59d` | 程式碼原本乾淨；本交接報告為新未提交檔 | Core Task 1–7 整合分支 |
| `.worktrees/v1-task8` | `codex/v1-task8` @ `684468a` | **dirty：3 個檔案未提交** | Task 8 修正與真 DB 測試 |
| `.worktrees/v1-task10` | `codex/v1-task10` @ `ec396e6` | 乾淨、尚未實作 | 預留 WRA historical KML Task 10 |
| `.worktrees/v2-risk-engine-rebuild` | `codex/v2-risk-engine-rebuild` | 與本 v1 路徑無關 | 不要合併到 v1 |

遠端：`origin https://github.com/pcedison/taiwan-flood-risk-open-map.git`。  
三個 `codex/v1-*` feature branches 目前沒有 upstream 設定；本輪未 push、未 PR、未 merge、未 deploy。

本機 PostGIS：

- Container：`flood-risk-postgres-1`
- 狀態：healthy
- Port：`127.0.0.1:5432`
- URL：`postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk`
- Docker CLI：`/opt/homebrew/Cellar/docker/29.5.3/bin/docker`

Python：

- API：`/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python`
- Workers：`/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python`
- Node wrapper：`/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/node-bin`

API 與 workers 都使用 import package 名稱 `app`，pytest/mypy 必須在不同 process、各自 project directory 執行。

## 5. Core 工作進度

| Task | 狀態 | Commit／證據 | 說明 |
| --- | --- | --- | --- |
| 1. Lock scorer/geocoder/constructor behavior | 完成 | `ce61edb..4ebe2bb`; API 39、Web 66、E2E 8 | Characterization baseline |
| 2. Pure assessment types/query-local safety/base composition | 完成 | `4ebe2bb..a355224`; pytest 21、Ruff | 缺資料不得判低 |
| 3. Persisted read model/independent failure states | 完成 | `a355224..540208a`; live PostGIS 9、full API 517 | current/history/coverage/health/jurisdiction 隔離 |
| 4. Additive API response contract | 完成 | `540208a..8dedfe0`; contract/cache 85 | 舊 constructor/response 相容 |
| 5. AssessmentService/separate scoring/privacy-safe persistence | 完成 | `8dedfe0..c20d017`; live 13、focused 77、full API 531 | single service path |
| 6. Collapse public route to AssessmentService | 完成 | `c20d017..1aa7a76`; live full API 524 | 2 個 Web E2E 明確延到 15–16 |
| 7. Freeze legacy readers/writers/generic dispatch | 完成 | `1aa7a76..124a59d`; full API 655+13 skip、Workers 551 | 獨立 spec/release rereview APPROVED |
| 8. Advisory-locked monotonicity/CAP lifecycle/dedupe | **進行中、未核准** | `f70b34e`, `684468a` + dirty diff | 詳見下一節 |
| 9. `no_active_event` 與 source-specific health | 未開始 | 依賴 Task 8 | CWA/NCDR empty poll、generation anti-resurrection |
| 10. WRA historical flood metadata → KML | 未開始 | worktree 已備妥 @ `ec396e6` | 需要 defusedxml、真歷史 timestamp、disabled gates |
| 11. CWA heavy-rain CAP | 未開始 | 依賴 8、9 | 正式 CAP adapter |
| 12. NCDR datastore → dump CAP | 未開始 | 依賴 8、9 | 取代舊 Atom runtime path |
| 13. Flood-potential production manifest | 未開始 | 可能受官方 artifact/toolchain 阻擋 | 必須量測每個 archive/checksum/CRS/count/coverage |
| 14. Per-source managed v1 baseline + migration 0038 | 未開始 | 依賴 9–13 | 唯一 scoped runtime entry、來源預設 disabled |
| 15. Web additive model + legacy fallback | 未開始 | 依賴 API final contract | unknown 不得變 low；移除 public diagnostics/profile |
| 16. Full acceptance + operator docs | 未開始 | 依賴全部 core | full API/worker/web/E2E/DB/migration/source activation |

### Task 7 特別交接

Task 7 經多輪 release review 後已收斂為：

- 外部 tile/TileJSON URL 只接受 exact reviewed public outer host。
- bounded NFKC + percent decoding 後，path/query/fragment 內任何明確 nested network reference 都 fail closed，即使 nested host 本身也在 allowlist。
- `+//`、encoded-plus、userinfo、loopback、未核准 host、PMTiles、本機 `/v1/tiles`、mixed invalid raw list 均被拒絕。
- `ratio=1//2`、`wordx//y` 等真正 alphanumeric token text 保留。
- `V1_BASELINE_ADAPTER_KEYS` 精確八個 key；generic public facades 固定 frozen JSON/exit 2；private execution engine 不再由 production generic path 觸達。

Task 7 最終 HEAD 是 `124a59d2f4b01bdca36dd05da011b5bc1e538b16`，不要回退至 `ec396e6` 或 `8a0bcb0`。

## 6. Task 8 詳細狀態

### 6.1 已提交部分

Task 8 隔離分支以 `8a0bcb0` 為基礎，尚未包含 Task 7 後續 `91ee3e4..124a59d`。

已提交：

1. `f70b34e76096fce1daf87697b81722b61f6d6038` — `fix: serialize official latest promotion decisions`
2. `684468abda8f8ad69caa441c5a84b4eefd183ac5` — `fix: close official promotion lifecycle bypasses`

`684468a` 當時驗證：

- Workers full：`623 passed, 30 skipped`
- Required live PostGIS：`30 passed, 0 skipped`
- API full：`518 passed, 13 skipped`
- Ruff、worker/API mypy、diff-check：通過

但獨立複審仍以真 DB 重現四項阻擋：

1. **Critical**：mixed references 只需一筆 earlier 就可使 stale Update/Cancel retire 或 tombstone later warning。
2. **Critical**：非法/out-of-range CAP MultiPolygon 可繞過 Point-only 驗證，刪除有效 Alert 並成為 current geometry。
3. **Important**：generic `DO NOTHING RETURNING` loser 回 `None`，但 distinct authorized staging row 保持 `accepted`、會永久重試。
4. **Important**：staging authorization 只綁九個 identity scalar，合法 UUID 可被冒用以改 title/summary/url/confidence/metric/geometry/CAP lifecycle。

複審報告：`.worktrees/v1-task8/.superpowers/sdd/task-8-spec-rereview.md`。

### 6.2 目前未提交部分

Task 8 worktree 現在 dirty，請勿丟棄：

```text
M apps/workers/app/pipelines/promotion.py
M apps/workers/tests/test_promotion_monotonicity_postgres.py
M apps/workers/tests/test_promotion_pipeline.py
```

相對 `684468a`：約 983 行變更，其中 production 約 220 行，其餘主要為 unit/live regression tests。

已實作但尚未完成驗收的修正：

- Lifecycle effect 只使用 `reference.sent < candidate.cap_sent` 的 canonical earlier subset；完整 mixed list仍保留於 audit evidence。
- Tombstone query 也要求 referenced sent 早於 lifecycle evidence 的 `cap_sent`。
- Current CAP explicit Point/Polygon/MultiPolygon 做 finite、WGS84、ring closure、最少 distinct positions 等 pure validation，再用 PostGIS `ST_IsEmpty`/`ST_IsValid`/geometry type 檢查 topology；在任何 retire/insert/latest 前執行。
- Generic natural-key loser 若是 authorized staging，terminal reason 設為 `idempotent_existing_evidence` 並 commit。
- Staging authorization 追加 title、summary、url、confidence 與 exact JSONB payload 比對；只從 emitted properties 移除 writer-owned `staging_evidence_id`、`raw_snapshot_id`。

原實作者中斷前回報四個修正 slice 各自 focused GREEN，但尚未跑完整 suite、尚未更新最終 report、尚未 commit。主代理在凍結後重新驗證得到以下**真實現況**：

#### 已通過

```text
Required live PostGIS:
49 passed in 18.57s, 0 skipped

Ruff on the 3 changed files:
All checks passed

mypy on promotion.py:
Success: no issues found

git diff --check:
exit 0
```

#### 未通過

```text
tests/test_promotion_pipeline.py:
77 passed, 3 failed
```

失敗案例：

- `test_invalid_current_point_geometry_is_terminal[coordinates2]`：NaN longitude
- `test_invalid_current_point_geometry_is_terminal[coordinates3]`：Inf latitude
- `test_invalid_explicit_cap_area_geometry_is_terminal_before_lifecycle_effects[geometry4]`：MultiPolygon 含 NaN

失敗原因：新的完整 staging payload authorization 使用 `json.dumps(..., allow_nan=False)`；NaN/Inf 不是合法 JSON/JSONB，因此 authorization 在 geometry terminal-rejection 前 fail closed，測試卻仍期待 staging 被 terminally rejected。

建議下一個 Agent 不要把 `allow_nan=False` 改回寬鬆模式。較安全的處理方式是明確決定契約：

- NaN/Inf 不可能存在於合法 persisted JSONB staging payload；帶合法 staging UUID 的 forged non-JSON payload應 authorization fail closed，且不得修改該 staging row。
- 使用 finite 但 out-of-range、malformed ring、自交 polygon 等「可存在於 JSONB」的 accepted staging fixture，驗證 promotion 會 terminal reject 並保留舊 latest。
- 對沒有 staging metadata 的 direct-writer invalid geometry，維持 fail closed、不得 insert/retire；沒有受授權 row 時不應假造 terminal mutation。
- 若規格堅持 NaN/Inf 也必須 terminalize，必須先說明如何在真 PostgreSQL JSONB 建立並授權該 staging row；不要只修改 fake 讓不可能狀態看似通過。

### 6.3 Task 8 接手步驟

1. 在 `.worktrees/v1-task8` 先執行 `git status --short` 與 `git diff --check`，確認上述三檔仍在。
2. 讀取 `task-8-spec-rereview.md` 與目前 `git diff`。
3. 釐清並修正上述 3 個 NaN/Inf unit expectations；保留 exact payload binding 與 `allow_nan=False`。
4. 重跑 focused unit + required live PostGIS。
5. 重跑完整 workers、API、Ruff、worker/API mypy、diff-check。
6. 更新 `.superpowers/sdd/task-8-report.md`；該目錄被 ignore，不能把存在視為 git artifact。
7. 建立新 commit，原定訊息：`fix: bind promotion to validated staging content`。
8. 交給獨立 reviewer 複查四項 DB finding，不可由實作者自行核准。
9. Reviewer APPROVED 後，將 Task 8 rebase/cherry-pick 到 `codex/v1-official-community` HEAD `124a59d`。
10. 解 conflicts 後重跑整合 API/worker/full live DB。特別注意 Task 7 與 Task 8 都碰到 runtime-related tests，不能用 `ours/theirs` 粗暴覆蓋。
11. 整合分支通過後才更新 progress ledger 並開始 Task 9。

Task 8 cumulative committed files可用：

```bash
git diff --name-status 8a0bcb0..684468a
```

目前未提交部分可用：

```bash
git diff --name-status 684468a
git diff --stat 684468a
git diff 684468a -- apps/workers/app/pipelines/promotion.py
```

## 7. Remaining Core 工作設計

### Task 9 — `no_active_event` 與來源健康

- 合法 empty CWA/NCDR warning poll 是 succeeded/no-active，不是 transport/parse failure。
- 只 retire 同 adapter 的 warning latest，且 generation 必須防止 older empty poll 刪 newer Alert，或 newer empty poll 後 older Alert resurrection。
- station source 用 catalog freshness threshold；event source 的 recent no-active poll可顯示 operational，但不偽造附近 station coverage。
- 必須只透過 Task 7 的 `run_v1_baseline_adapter_cycle` scoped seam，generic facade保持 frozen。

### Task 10 — WRA 歷史淹水 metadata → KML

- Metadata JSON只是 index，不是 evidence。
- 只接受 HTTPS、exact `opendata.wra.gov.tw` KML URL。
- 使用 `defusedxml`，支援有效 Point/Polygon/MultiPolygon，拒絕非法/超出台灣範圍座標。
- 必須有 source-provided historical timestamp，不可用 fetched time假造事件時間。
- `evidence_scope=historical`、source gates全部預設 false。
- worktree已存在，但尚無任何實作。

### Task 11 — CWA heavy-rain CAP

- 正式 CWA CAP adapter、shared CAP identity、area/message semantics。
- active window、references、source timestamp、boundary geometry、no-active poll皆需接上 Task 8/9 contract。

### Task 12 — NCDR datastore → dump CAP

- 不再依賴舊 Atom runtime path。
- datastore index不是 alert；需解析 dump CAP。
- 與 CWA共用 identity/lifecycle，但 adapter-specific evidence仍物理分離。

### Task 13 — Flood-potential production manifest

- 官方 dataset 25766 是多個縣市 archive，不是一個全臺 GeoJSON。
- Production artifact必須量測 metadata index SHA、完整 resource IDs、每個 archive checksum/CRS/count/coverage，以及 deterministic merged output。
- covered + known-gap 必須精確涵蓋 22 jurisdiction；gap不能解讀為低風險。
- 若官方 artifact或轉檔 toolchain不可用，gates保持 false並停止完成聲明；不可捏造 evidence。

### Task 14 — v1 baseline/migration

- 建立唯一 per-source managed wrapper、CLI、scheduler path與 migration 0038。
- 所有 catalog row migration後預設 `is_enabled=false`。
- 每個來源先 isolated staging proof，再由 operator transaction逐一啟用 catalog row與runtime/API gate。
- Rollback先關 catalog row，再關 gates。

### Task 15 — Web rolling fallback

- additive fields在 TypeScript暫為 optional。
- 只有 `overall` 與 `dominant_mode` 同時有效才走新 presentation；否則完整走 legacy fallback。
- unknown永不顯示 low。
- 移除 public diagnostics/profile/query-heat依賴，但保留 rollback modules。

### Task 16 — Acceptance/deployment docs

- Full API/worker/root/web unit/typecheck/lint/build/E2E。
- 空 DB、0037→0038 upgrade、API live evidence與worker concurrency mandatory DB suites全都 zero skips。
- 每個 source逐一 disabled proof、operator activation、assessment、rollback。
- 更新 API/worker/web README、source catalog與scheduler deployment runbook。

## 8. Community 工作進度與未來項目

Community plan 尚未開始，Task 1–11 全部 pending：

1. Exact metadata-only schema、seeds、contracts。
2. Keyed fingerprints 與 controlled matching。
3. Metadata-only repository、kill switch、work recovery、suppression。
4. Strict official Threads adapter 與 hard gates。
5. User report 單一 transaction promotion 與 immediate suppression。
6. Stable origin groups、clusters、corroboration、fixture integration。
7. Sanitized reads、assessment association、唯一 uplift seam、operator suppression。
8. Canonical search requests 與 adaptive loop。
9. Exact source policy 與 quarantined browser discovery。
10. Web sanitized community state 與權威標籤。
11. Full privacy、fixture、integration、operational acceptance。

推薦在 Core Task 16通過後才開始 Community Task 1；若要平行，只能做不碰 core schema/runtime的 read-only規格/fixture準備，不要提前接入 scoring。

## 9. 測試與驗證命令

### Task 8 目前 focused unit

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python \
  -m pytest tests/test_promotion_pipeline.py -q
```

目前預期：`77 passed, 3 failed`，直到 NaN/Inf contract被正確處理。

### Task 8 mandatory PostGIS

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
PROMOTION_TEST_DATABASE_URL='postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk' \
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 \
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python \
  -m pytest tests/test_promotion_monotonicity_postgres.py -q -rs
```

目前實測：`49 passed, 0 skipped`。

### Task 8 靜態檢查

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python \
  -m ruff check app/pipelines/promotion.py tests/test_promotion_pipeline.py tests/test_promotion_monotonicity_postgres.py
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python \
  -m mypy app/pipelines/promotion.py
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8
git diff --check
```

目前均通過。

### 完整 gate（Task 8修正後）

```bash
cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/workers
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python -m pytest -q
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/workers/bin/python -m ruff check app tests
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m mypy app

cd /Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-task8/apps/api
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m pytest -q
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m ruff check app tests
/Users/marcus/Documents/ChatGPT/flood-risk/.worktrees/v1-official-community/.venv/api/bin/python -m mypy app
```

## 10. 測試報告與本機文件索引

主要規格與計畫：

- `docs/superpowers/specs/2026-08-24-v1-flood-risk-community-signals-design.md`
- `docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md`
- `docs/superpowers/plans/2026-08-24-v1-community-signals.md`

整合 worktree本機 SDD資料：

- `.superpowers/sdd/progress.md`
- `.superpowers/sdd/task-7-report.md`
- `.superpowers/sdd/task-7-final-rereview.md`
- `.superpowers/sdd/task-7-release-review.md`
- `.superpowers/sdd/task-8-brief.md`
- `.superpowers/sdd/task-8-controller-decisions.md`
- `.superpowers/sdd/task-8-preflight.md`

Task 8 worktree本機 SDD資料：

- `.superpowers/sdd/task-8-report.md`
- `.superpowers/sdd/task-8-spec-review.md`
- `.superpowers/sdd/task-8-spec-rereview.md`
- `.superpowers/sdd/review-8a0bcb0..f70b34e.diff`

注意：`.superpowers/sdd` 被 local `.gitignore` 忽略，這些檔案不一定會隨 commit/push 到另一台機器。若交接不是同一 workspace，必須另行複製。

部署與操作參考：

- `docs/runbooks/deploy-zeabur.md`
- `docs/runbooks/production-readiness.md`
- `docs/runbooks/worker-scheduler-deployment.md`
- `docs/runbooks/zeabur-single-service-env.md`

現有 Zeabur runbook仍描述舊 generic ingestion startup；Task 7 已凍結該產品面，Task 14/16尚未更新正式 v1 entry與operator rollout。因此**不可直接照舊 runbook啟用 production ingestion**。

## 11. 上線判斷

### 現在可以做

- 繼續本機/隔離 PostGIS開發與測試。
- 以 Task 1–7 branch作 code review。
- 完成 Task 8，之後開始 per-source adapter工作。
- 準備 Zeabur staging project與 secrets checklist，但不要部署未整合 Task 8 branch。

### 現在不可以宣稱

- 不可宣稱完整官方資料基線已完成。
- 不可宣稱社群爬文/Threads/Browser Agent已可用。
- 不可宣稱 production ready。
- 不可把目前 Task 8 dirty worktree rebase、force checkout或清掉。
- 不可自動啟用任何來源 catalog row。

### 最快且安全的上線路徑

1. 完成並核准 Task 8。
2. 整合到 `124a59d`，跑 integrated full/live suites。
3. 完成 Task 9。
4. Task 10/11/12可用隔離 worktree平行；Task 13只在真 artifact/toolchain可用時完成。
5. 完成 Task 14，部署時所有 source仍 disabled。
6. 完成 Task 15。
7. Task 16在 staging逐來源 proof與operator activation，通過後才談 production beta。
8. 社群功能另外逐 Task 1–11 rollout；Threads缺核准時保持 disabled，不阻塞官方 baseline。

若政府時程只允許較早展示，可做「staging technical preview」，但 UI/API必須明確標示未啟用來源與 data gaps；這不等於 production baseline acceptance。

## 12. 建議與風險排序

### P0 — 立即處理

- 保住 Task 8 dirty diff。
- 解決 3 個 focused unit failures，不弱化 exact staging payload authorization。
- full verification、commit、independent rereview。
- rebase到 Task 7 final並做 integrated verification。

### P1 — 官方 baseline關鍵路徑

- Task 9 generation/no-active semantics。
- Task 10/11/12官方 adapters。
- Task 14唯一 v1 managed entry/migration。
- Task 15/16 UI與上線驗收。

### P2 — 可被外部 artifact阻擋

- Task 13淹水潛勢 measured manifest。若阻擋，保持 feature gates off並公開 known gap，不能造假完成。

### P3 — Community未來路徑

- 先 metadata-only/user report，再正式 Threads API，最後才是 quarantined browser discovery。
- 不要為了趕時程改成登入式或任意網站爬蟲。

主要技術風險：

- Task 8涉及 lifecycle、identity、authorization與concurrency，passing test count不等於安全；必須保留真 DB reproduction與獨立 reviewer。
- Task 8分支基礎落後 Task 7 final，整合時易在 runtime/frozen tests發生語意衝突。
- Task 13依賴外部官方 archive與轉檔工具，可能是非程式 blocker。
- 舊部署文件可能重開已凍結 generic ingestion，必須由 Task 14/16更新。
- 社群平台政策/permission/token是外部核准，不可用 browser scraping繞過。

## 13. 下一個 Agent 的第一個回合

建議第一回合只做以下事項：

1. 完整閱讀本報告、Task 8兩份 review與 `git diff 684468a`。
2. 確認 Task 8 worktree仍是三個 modified files、HEAD仍是 `684468a`。
3. 重現 `77 passed, 3 failed` 與 `49 passed`。
4. 以 TDD處理 NaN/Inf authorization-vs-terminal contract。
5. 不開始 Task 9/10、不 rebase、不更新 ledger，直到 Task 8 full green + independent APPROVED。

達成後才進入 commit、rereview、integration。
