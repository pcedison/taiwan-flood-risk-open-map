# Flood Risk 專案架構/可維護性稽核

分支：`audit/sustainability-2026-07-06`（= 最新 origin/main）
稽核日期：2026-07-06
稽核範圍：apps/api、apps/workers、apps/web、docs、packages、infra、CI、依賴
稽核方法：實際讀檔＋行數/計數統計（非印象）。node_modules / .next / *_cache 已排除。

目標情境提醒：公益開放地圖，要讓陌生 fork 貢獻者快速理解並安全修改，維運 10–15 年。
以下每個 finding 的「代價」都以「10 年維護 / 陌生貢獻者」為量尺。

---

## 總覽數字

| App | 原始碼檔數 | 前一名檔案 | 測試數 |
|---|---|---|---|
| apps/api | 59 py | local_source_action_plan.py 1479 | 336（31 檔）|
| apps/workers | 104 py | jobs/runtime.py 1278 | 421（46 檔）|
| apps/web | 25 ts/tsx | lib/risk-display.ts 1186 | 單元+e2e 見下 |

- 跨 app import：**無**（`grep "from apps\."` 在非測試碼 0 命中）—— 分層邊界在「app 之間」是乾淨的。
- 死碼標記：`TODO/FIXME/NotImplementedError` 在 api+workers 產碼中 **0 命中**。
- 依賴：Python/Node 都現代且精簡，無 EOL 套件（詳見面向 7）。

---

## 面向 1：檔案規模

各 app 前 5 大（行數，排除快取/建置產物）：

**apps/api**
1. `apps/api/app/domain/realtime/local_source_action_plan.py` — 1479
2. `apps/api/app/domain/history/news_enrichment.py` — 1288
3. `apps/api/app/domain/geocoding/providers.py` — 1263
4. `apps/api/app/domain/evidence/repository.py` — 1216
5. `apps/api/app/api/routes/admin.py` — 1084

**apps/workers**
1. `apps/workers/app/jobs/runtime.py` — 1278
2. `apps/workers/app/jobs/profiles.py` — 854
3. `apps/workers/app/config.py` — 794
4. `apps/workers/app/ops/local_source_candidate_smoke.py` — 789
5. `apps/workers/app/adapters/local_taipei/water.py` — 759

**apps/web**
1. `apps/web/app/lib/risk-display.ts` — 1186
2. `apps/web/app/lib/basemap-style.ts` — 539
3. `apps/web/app/page.tsx` — 393
4. `apps/web/app/lib/api-client.ts` — 378
5. `apps/web/app/components/diagnostics-section.tsx` — 245

### F1-A（高）governance 三件套灌爆 API domain
`apps/api/app/domain/realtime/local_source_action_plan.py:1`（1479）
+ `.../local_source_coverage.py:1`（933）
+ `.../local_source_request_packets.py:1`（1066）= 約 3478 行。
讀內容後性質是**專案治理 / 內部營運排程**（production gate、workstream 優先序、dispatch
follow-up、counterparty 授權請求），不是淹水風險計算本身。action_plan 有 48 個 top-level
def，幾乎全部回傳 `dict[str, Any]`（該檔 33 處 `dict[str,Any]`）。
- 為什麼是問題：陌生貢獻者打開 `domain/realtime/` 想理解「即時淹水判定」，卻先撞上 3500 行的
  內部 ops 機器；altitude 錯位（營運治理混進領域層），且 dict 流沒有型別護欄，改一個欄位名不會
  被編譯器/type checker 擋下。10 年內是最容易腐爛的一塊。
- 建議：(a) 整組移出 `domain/`，改放 `app/ops/` 或獨立套件，與風險領域清楚分家；
  (b) 把 dict 出入口換成 dataclass/TypedDict；(c) action_plan 依「audit / priority / gate」
  切 3 個模組。規模：**L**。

### F1-B（中）news_enrichment / providers / evidence repository 過大
`news_enrichment.py:1`（1288, 62 defs）、`geocoding/providers.py:1`（1263, 86 defs）、
`evidence/repository.py:1`（1216）。providers.py 86 個 def 明顯是「多家 geocoder 塞一檔」。
- 代價：單檔 review/測試阻力大，merge conflict 熱點。
- 建議：providers.py 按 provider 拆檔（每家一檔 + 共用介面）；repository.py 按 aggregate 拆
  讀/寫。規模：**M**（各檔）。

### F1-C（中）路由檔肥大、分層下沉
`apps/api/app/api/routes/public.py:1`（1062）與 `routes/admin.py:1`（1084, 34 defs）是兩個
離群值（其餘 health 140 / reports 191 / tiles 69 都正常）。public.py 直接 import domain 18 次，
且 40 欄位 DI 的組裝、`_official_realtime_bundle_for_risk` 等業務邏輯都寫在路由層。
- 代價：路由層變成隱形的 service 層，違反自稱的 routes/services/domain 分層；新人不知道邏輯
  該加在哪。
- 建議：public.py 的 `_*` 私有 helper（含 DI 組裝）下沉到 `api/services/`；路由只留 IO 綁定。
  規模：**M**。

### F1-D（中）workers 設定表面過大
`apps/workers/app/config.py:1`（794 行、183 個設定欄位）＋根目錄 `.env.example`（195 個環境
變數）。
- 代價：陌生貢獻者上手第一關就是 195 個 env var；config drift 難追。
- 建議：按子系統分組（ingestion / scheduler / monitoring / geocoder）拆成多個 settings
  dataclass，`.env.example` 對應分段並標「本地跑最小集」。規模：**M**。

### F1-E（中）web risk-display.ts 是 god-module
`apps/web/app/lib/risk-display.ts:1`（1186）混了 type 定義、風險等級邏輯、座標/距離/時間
formatting、nearby coverage、user report、source health、evidence 連結——51 個 export 於一檔。
- 代價：前端唯一最大檔，任何 UI 顯示改動都碰它；測試 `risk-display.test.ts` 755 行綁死它。
- 建議：拆 `types.ts` / `format.ts` / `risk.ts` / `coverage.ts` / `evidence.ts`。規模：**M**。

---

## 面向 2：分層與耦合

- **跨 app import：零**（正面，已驗證）。三個 app 靠 HTTP/DB 契約解耦，符合 monorepo 分治。
- **routes → domain 直穿**：public.py 有 18 條 `from app.domain...`，繞過 services 層（見 F1-C）。
  services/ 目錄存在（11 檔）但路由不一致地有時走 service、有時直穿 domain。邊界是「軟」的。

### F2-A（高，但已被 ADR 承認）CWA/WRA 雙軌解析
API 端 `apps/api/app/domain/realtime/official.py:19-21` 直接持有 CWA `O-A0002-001`、WRA
`73c4c3de...` / `c4acc691...` 三個 upstream URL 與解析邏輯；workers 端
`apps/workers/app/adapters/cwa/rainfall.py:31`、`adapters/wra/water_level.py:33-38` 持有**同一組
URL 與各自的解析**。兩邊平行維護。
- 現況：`docs/adr/0010-realtime-bridge-as-local-diagnostic.md` **明確承認**此雙軌，判定 API bridge
  為「本地診斷工具」，hosted runtime 由 `fetch_official_realtime_bundle`（official.py:99, 269-273
  的 `HOSTED_RUNTIME_ENVS` guard）強制只走 worker 持久化證據。收斂成共用套件被**刻意延後**，理由
  是 path-dependency 套件會破壞 `pip install -e .`（Docker/Zeabur/CI 都靠它）。README:70/256 與
  ADR 一致（文件同步良好，見面向 6）。
- 為什麼仍是 10 年風險：ADR 自己寫「upstream schema 改變必須同時改兩處」。這是一條**靠人記得**的
  規則，10 年 + 陌生貢獻者環境下必然有人只改一邊。guard 防的是「hosted 誤打 upstream」，不防
  「解析 drift」。
- 建議（不必推翻 ADR 的延後決定）：加一個**共用 fixture 契約測試**——同一份 CWA/WRA 原始回應
  分別餵進 bridge 與 worker 兩邊解析，斷言關鍵欄位（站名、座標、觀測值、時間）一致。schema drift
  就會在 CI 立刻爆，而不是等線上。共用小工具（TWD97 轉換、float 脅制）可先抽到既有
  `apps/workers/app/adapters/_helpers.py` 的對應，但 api 端沒有等價共用檔——目前只能靠測試把兩邊
  綁住。規模：**M**。

---

## 面向 3：重複與死碼

### F3-A（中）packages/ 是空殼 scaffolding
`packages/` 底下全是 README 與 `*.placeholder.yml`（`packages/shared/keywords/*.placeholder.yml`、
`packages/shared/risk-rules/risk-v0.placeholder.yml`、`packages/geo/**/README.md`），唯一實體是
`packages/contracts/fixtures/risk-assess-response.json`。宣稱的 monorepo 共用套件工作區實際上不存在。
- 代價：新人以為有共用套件層去找，浪費時間；「假結構」比「沒結構」更誤導。
- 建議：要嘛把 contracts fixture 真正接進 web/api 契約測試並補實 shared，要嘛把純 placeholder 目錄
  降級為 `docs/planned/` 並在 README 標「尚未實作」。規模：**S**。

### F3-B（低/中）adapter 風格不一致
16 個 `local_*` adapter 都有 run/class 入口（`registry.py`+`contracts.py` Protocol 有定義介面，
正面）。但實作風格分歧：`local_taipei/water.py` 用一堆 `parse_taipei_*` 模組函式，
`local_new_taipei/water.py` 用 class（`fetch/normalize/run`）。兩檔共用函式名只有 11 個交集。
- 代價：每加一個縣市，貢獻者不知道該抄哪種範式；review 成本隨縣市數線性上升（未來要涵蓋全台）。
- 建議：定一個 adapter 樣板（class-based，配合 contracts.Protocol），把 taipei 對齊；文件化「新增
  一個 local source 的步驟」。規模：**M**。

### F3-C（正面聲明）tmp/ 與 test-results/ 未進 repo
`git ls-files tmp/` 只有 `.gitkeep` + `README.md`；`test-results/` 追蹤數 0。`.gitignore` 正確排除
`test-results/`、`tmp/*`（保留 .gitkeep/README）、各種 cache、`.worktrees/`。此面向**無 finding**。
（註：工作目錄有 `.mypy_cache/`、`.next/`、`.worktrees/` 等，但都已 gitignore，非 repo 內容。）

### F3-D（正面聲明）無殘留 stub / 死碼標記
api+workers 產碼 `TODO/FIXME/NotImplementedError` 0 命中；feature gate 後面沒有空 stub。
bridge 仍在使用中（非死碼），角色由 ADR-0010 明確定義。

---

## 面向 4：型別與介面

### F4-A（中/高）40 欄位手工 DI dataclass
`apps/api/app/api/services/public_risk.py:224` `RiskAssessmentDependencies` 有約 40 個 callable
欄位（每個都有具名 type alias，型別強度高——正面），組裝點
`apps/api/app/api/routes/public.py:588-626` 逐一綁 40 個 `_helper`，其中多數是包一層 domain 呼叫
的單行 wrapper。
- 代價：型別很強但**儀式極重**。要看懂 `assess_risk` 得穿越 40 層 indirection；要呼叫它得先接好
  40 個依賴。這是「為了可測試性」的過度抽象——對陌生貢獻者是高牆。測試端也得
  `RiskAssessmentDependencies(**values)`（test_public_risk_service.py:188）湊齊全部。
- 建議：把只有一種真實實作、且只是轉呼叫 domain 的欄位直接內聯，DI 只保留真正需要在測試替身的
  少數 seam（網路、DB、時鐘、快取）。目標砍到 <10 欄。規模：**M**。

### F4-B（中）dict[str, Any] 集中在 governance 模組
api 全域 `dict[str, Any]` 115 處、workers 126 處；熱點是
`local_source_request_packets.py`（33）與 `local_source_action_plan.py`（33），其餘檔案多在個位數。
- 代價：public API/內部資料在這兩檔幾乎無型別，欄位改名/漏欄 type checker 不擋（見 F1-A）。
- 建議：與 F1-A 一起處理，換 dataclass/TypedDict。規模：併入 F1-A。

（正面）adapters `contracts.py` 用 Enum + `@dataclass(frozen=True)` + Protocol 定義 `AdapterMetadata`
/ `RawSourceItem` / `NormalizedEvidence`，ingestion 側的型別介面是強的。

---

## 面向 5：測試品質

- 數量：backend 757 測試（api 336 / workers 421），web 有 unit（`node --test` strip-types）＋
  playwright e2e（`map-risk.spec.ts` 738、`open-basemap-smoke.spec.ts` 311）。密度充足。
- CI（`.github/workflows/ci.yml`）：ruff → mypy（api+workers）→ pytest（含「空套件」明示 gate）→
  web `npm ci`/`lint`/`typecheck`。另有 4 個 hosted-monitoring / watchdog workflow。硬性要求
  lockfile 存在。**CI 覆蓋面札實**（正面）。

### F5-A（中）測試大量 monkeypatch，脆弱度中等（比帳面樂觀）
全 backend `monkeypatch/setattr` 865 次 / 757 測試。集中在
`apps/api/tests/test_public_contract.py`（128）、
`apps/workers/tests/test_worker_entrypoints.py`（91）、`test_reports_contract.py`（40）。
- 細看 seam：workers 端大宗是 patch `"urlopen"`（網路邊界，**合理** seam）與 CLI 入口
  （`run_maintenance_once` 等 public 函式）。這類不算綁死內部實作。
- 真正的脆弱點在 api contract 測試把 route module 的內部屬性直接 setattr
  （`test_admin_contract.py:78` `monkeypatch.setattr(admin_route.psycopg, "connect", ...)` 等），
  以及 `RiskAssessmentDependencies(**values)` 要求測試跟 40 欄位 DI 同步演化——DI 一改欄位，
  一票測試跟著改。
- 代價：重構內部結構時測試會大面積紅，違反「測試綁行為不綁實作」。但因為多數 patch 落在網路/入口
  邊界，整體比 865 這數字看起來的健康。
- 建議：(a) 把 `psycopg.connect` 這類改成注入的 DB 依賴而非 patch 模組屬性；(b) DI 瘦身（F4-A）
  後測試 setup 自然變短；(c) 保留 urlopen-boundary patch（那是對的）。規模：**M**。

---

## 面向 6：文件與程式碼同步（抽查驗證）

抽查 5 個關鍵聲明，實際比對程式碼：

1. **ADR-0010「hosted guard 在 fetch_official_realtime_bundle 內部強制」** → 驗證通過。
   `official.py:99` 函式簽名收 `app_env`/`diagnostic_fallback_enabled`，`:269-273` 解析 env 並比對
   `HOSTED_RUNTIME_ENVS`（:23）。guard 確實在 domain 邊界，非 route wrapper。
2. **ADR-0010「兩處 URL 重複」** → 通過。official.py:19-21 與 workers cwa/wra adapter URL 一字不差。
3. **README:256 「bridge 角色已決定：本地診斷」** → 通過，與 ADR-0010 一致，README 已無「open
   decision」殘留。
4. **README「無跨 app 耦合的分層」隱含聲明** → 通過（跨 app import 0）。
5. **README:139 Development Status「worker official path partial、live 為 opt-in gate」** →
   與 workers adapter 的 `enabled_by_default` metadata + gated live client 結構一致。

結論：**抽查的文件與程式碼同步度良好，此面向無實質 finding**。ADR/README/runbooks（86 個 md，
10 個 ADR、10+ runbooks）是這個 repo 的相對強項——雙軌解析這種債務是「寫在 ADR 裡的明債」而非
隱性耦合。唯一小落差：`.env.example` 195 個變數缺「本地最小必要集」的分層指引（併入 F1-D）。

---

## 面向 7：相依健康

- **apps/api**：fastapi>=0.115、psycopg[binary]>=3.2、redis>=5.0、uvicorn>=0.30；dev 才有
  httpx/mypy/pytest/ruff。全部現代，無 EOL。
- **apps/workers**：只有 `psycopg[binary]>=3.2` + `PyYAML>=6`。HTTP 全用 stdlib `urllib`（api
  的 official.py 亦同）——**刻意極簡**，正面（供應鏈面積極小，10 年好維護）。
- **apps/web**：next ^15、react ^19、react-dom ^19、maplibre-gl ^5、pmtiles ^4.4；tooling
  eslint ^9 / typescript ^5.6 / playwright ^1.59。全部當前主線，無棄置套件。
- Node 測試用 `--experimental-strip-types`（原生 TS 執行），無額外 test runner 依賴——精簡。

結論：**依賴健康，無 EOL/棄置套件，無 finding**。唯一觀察（非問題）：全靠 stdlib urllib 而非
httpx，重試/逾時/連線池要自己顧；official.py:29-30 在 module import 時建立兩個
`ThreadPoolExecutor`，屬輕微資源味道，但因 FastAPI route 全是 `def`（同步、跑在 threadpool，
不阻塞 event loop），不構成 async 阻塞問題（已驗證 public.py 所有 handler 為 `def` 非 `async def`）。

---

## 若只能做 5 件事（優先序）

1. **【L】拆解並降 altitude：local_source 治理三件套**
   `apps/api/app/domain/realtime/local_source_action_plan.py:1`（+coverage:1 +request_packets:1，
   約 3500 行、dict[str,Any] 66 處）。移出 domain 層、切模組、換型別。這是最大的腐爛面，也是陌生
   貢獻者最容易迷路的地方。
2. **【M】用共用 fixture 契約測試綁住 CWA/WRA 雙軌解析**
   `official.py:19` ↔ `adapters/cwa/rainfall.py:31` / `adapters/wra/water_level.py:33`。不必推翻
   ADR-0010 的延後決定，但要把「靠人記得改兩處」換成「CI 會爆」。
3. **【M】DI 瘦身：40 欄位 RiskAssessmentDependencies**
   `apps/api/app/api/services/public_risk.py:224` / 組裝 `routes/public.py:588`。內聯單實作
   wrapper，DI 只留真 seam（DB/網路/時鐘/快取），順帶讓 F5-A 的測試 setup 變短。
4. **【M】恢復分層：肥路由檔下沉**
   `apps/api/app/api/routes/public.py:1`（1062）與 `admin.py:1`（1084）。把業務 helper 移進
   `api/services/`，路由只留 IO 綁定，讓 routes/services/domain 邊界名實相符。
5. **【M】拆 web god-module + 統一 adapter 範式**
   `apps/web/app/lib/risk-display.ts:1`（1186，51 exports）按關注點拆檔；
   `apps/workers/app/adapters/local_taipei/water.py` 對齊 class-based 範式並補「新增 local source」
   文件——直接降低未來擴充全台縣市的邊際成本。

---

## Finding 索引（問題 11 項，其中 F4-B 併入 F1-A 處理；正面聲明 4 項）

| ID | 面向 | 嚴重度 | 位置 | 規模 |
|---|---|---|---|---|
| F1-A | 檔案規模/altitude | 高 | domain/realtime/local_source_action_plan.py:1 (+2) | L |
| F1-B | 檔案規模 | 中 | history/news_enrichment.py:1；geocoding/providers.py:1；evidence/repository.py:1 | M |
| F1-C | 檔案規模/分層 | 中 | routes/public.py:1；routes/admin.py:1 | M |
| F1-D | 設定表面 | 中 | workers/app/config.py:1；.env.example | M |
| F1-E | 前端 god-module | 中 | web/app/lib/risk-display.ts:1 | M |
| F2-A | 雙軌解析 | 高(已承認) | official.py:19 ↔ adapters/cwa,wra | M |
| F3-A | 空殼 scaffolding | 中 | packages/**（純 placeholder） | S |
| F3-B | adapter 風格不一 | 低/中 | adapters/local_taipei vs local_new_taipei | M |
| F4-A | 過重手工 DI | 中/高 | public_risk.py:224；public.py:588 | M |
| F4-B | dict[str,Any] 流 | 中 | local_source_request_packets.py；local_source_action_plan.py | (併 F1-A) |
| F5-A | 測試 monkeypatch | 中 | test_public_contract.py；test_admin_contract.py:78 | M |
| F3-C | tmp/test-results | 正面 | 已正確 gitignore | — |
| F3-D | 死碼/stub | 正面 | 0 TODO/NotImplemented | — |
| F6  | 文件同步 | 正面 | ADR-0010 ↔ README ↔ code 抽查 5 項通過 | — |
| F7  | 依賴健康 | 正面 | api/workers/web 皆現代無 EOL | — |
