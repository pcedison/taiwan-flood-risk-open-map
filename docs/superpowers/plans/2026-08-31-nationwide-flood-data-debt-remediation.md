# 全台淹水歷史與感測資料技術債修正計畫

日期：2026-08-31

狀態：待實作；本文件只記錄唯讀查核、工程決策與驗收標準，不代表來源已啟用或正式環境已完成

## 結論

本專案不應再以單一地點、單一縣市或單篇官方新聞作為淹水資料修繕單位。
後續完成單位改為：

1. 全台 22 縣市都可查詢；
2. 每個縣市的歷史年份覆蓋狀態可被驗證；
3. 每個縣市的即時訊號類型都有明確的可用、過期、未公開或失敗狀態；
4. public query path 只讀取已持久化且通過資料契約的資料；
5. 背景 worker 持續擷取、驗證、去重、累積與監控官方資料。

「全台可查詢」不等於政府已在每個縣市公開每一類感測器。若某縣市沒有公開道路淹水深度、
下水道或抽水站 read API，產品必須顯示來源缺口，不能以遠處站點、警戒、潛勢圖或舊事件
冒充現地量測。

## 本次唯讀查核範圍

本次查核以 `main` SHA `ab1d53ab4491d2e6de216895d81f86fa7774a3ef` 為基準，沒有讀取或
輸出任何 secret 值，也沒有更動正式環境。

查核內容：

- `PROJECT_STATUS.md`、`README.md`、`.env.example`；
- 官方與地方來源 catalog、22 縣市來源矩陣、近期歷史來源設計；
- API 查詢時近期歷史補強路徑；
- worker adapter registry、managed runtime allowlist、scheduler 與持久化 schema；
- 正式站 `https://floodrisk.cc/health`、`/ready` 與未授權 admin route 的公開行為；
- 水利署、中央氣象署、NCDR、政府資料開放平臺的官方資料說明；
- 水利署公開 SOAP/ASMX 服務的唯讀 smoke。

## 查核發現

### 1. 查詢仍承擔資料發現與寫入責任

`apps/api/app/api/services/official_history.py` 的 `OfficialRecentHistoryLookup` 會在使用者查詢時
呼叫官方引用搜尋，再以 `upsert_public_evidence` 寫入資料庫。這條路徑可以暫時補到個案，
但無法證明其他縣市、其他年份已被涵蓋，也讓外部搜尋可用性直接影響 public request latency。

修正方向：public query path 改為 DB-only；搜尋只能產生背景 discovery job 或人工審核項目，
不能成為主要 ingestion。

### 2. 舊的歷史來源本來就不是完整事件庫

水利署資料集 `25770` 的官方說明指出：

- 更新頻率為不定期；
- 只呈現大尺度淹水調查；
- 局部、零星、都市道路、低窪農漁塭積水不在調查範圍。

因此在地址查詢中只出現 2016 年，不是 UI 年齡說明可以解決的問題；根因是 ingestion
沒有建立多來源、跨年度、持續累積的官方事件庫。

國科會資料集 `130016` 可作近年基線，但官方頁面同樣標示不定期更新及「2023 年產製」，
不能代表 2023 年以後持續有新事件。

### 3. WRA 最新事件來源已有 adapter，但正式啟用條件未完成

`official.wra.flood_incident` 已能解析水利署
`GET /OpenApiv3/v2/Disaster/Flooding`，但目前 catalog 為 `disabled_by_default`，且需要：

- source gate；
- API gate；
- contract gate；
- deployment secret manager 中的 API key；
- worker allowlist；
- production catalog enablement。

官方 API 說明也表明該 operation 只取得「最後事件」淹水災情，不是歷史 archive。
即使取得 key，也必須由 scheduler 輪詢並永久保存唯一事件，才能從啟用日開始累積歷史。

### 4. 即時感測 adapter 並非從零開始，但程式存在不等於正式運轉

目前中央骨幹包括：

- CWA 全台逐 10 分鐘雨量；
- WRA 河川／區排即時水位；
- WRA IoW 淹水深度；
- Civil IoT 淹水、下水道、抽水站、閘門與河川水位；
- NCDR CAP 警戒。

地方矩陣已有 20 縣市的 production adapter 實作。金門存在 KWIS 授權型 adapter，但需要正式
token／契約；連江目前只找到中央雨量、潮位與警戒等最低脈絡，沒有地方道路淹水深度或
下水道 live read API。

`V1_BASELINE_ADAPTER_KEYS` 已列入中央與地方 adapter，但 `.env.example` 的
`REALTIME_BACKBONE_ADAPTER_KEYS`／`WORKER_ENABLED_ADAPTER_KEYS` 範例仍只有 10 個來源。
這只證明部署契約可能漂移，不能單靠範例檔推定正式環境實際開啟哪些來源。

### 5. 正式 readiness 沒有證明 ingestion 健康

2026-08-31 唯讀 smoke 顯示：

- `/health` 回傳 200 且 deployment SHA 為本次基準 SHA；
- `/ready` 回傳 200，但 dependencies 只有 database 與 Redis；
- `/admin/v1/sources` 與 `/admin/v1/local-source-coverage` 未帶 admin credential 時正確回傳 401。

因此公開 readiness 目前不能證明 scheduler 正在執行、22 縣市來源已啟用，或最新觀測已寫入。
後續需要 public-safe、不可洩密的 ingestion readiness 摘要。

### 6. 另有官方歷史查詢候選，但尚未通過可用性驗證

水利署仍公開 `wsFloodEventQuery(startDate, endDate)` 的「淹水災情處置查詢」服務描述。
本次用 2026-08-24 至 2026-08-31、2025-07-01 至 2025-07-10 做唯讀 POST smoke，兩次皆
回傳 HTTP 200 但資料集為空。

水利署 `wsFloodings`「淹水災情（七天內）」目前可回傳 schema，但本次 smoke 無事件列。
在取得日期格式、涵蓋範圍、授權、空集合語意與真實 active fixture 前，兩者只能列為
contract-review candidate，不能宣稱已能回補歷史。

## 不可混用的資料類型

所有來源進 staging 前必須分類，且 API/UI 不得使用同一個「官方公開資料」標籤掩蓋差異。

| 類型 | 意義 | 可否當作歷史淹水 | 可否當作即時量測 |
| --- | --- | --- | --- |
| `observed_event` | 官方調查、災情或可追溯事件紀錄 | 是 | 否 |
| `sensor_observation` | 雨量、水位、淹水深度、下水道等儀器值 | 正值可保留為量測歷史 | 是 |
| `official_warning` | CAP、淹水警戒、河川警戒 | 否；只能當事件背景 | 否 |
| `planning_potential` | 設計降雨與水理模型模擬 | 否 | 否 |
| `corroboration` | 媒體、警廣、民眾通報或其他佐證 | 未複核前否 | 否 |

任何來源即使由官方平台彙整，仍必須保留原始 category。若 WRA 事件列來源是媒體或 APP 通報，
不能因為由官方 API 回傳就顯示成官方儀器量測。

## 目標資料流

```text
中央／地方官方來源
        ↓ 每來源獨立排程與 timeout
raw_snapshots（保留原始回應、擷取時間與 checksum）
        ↓ schema、時間、座標、單位、freshness、異常值檢查
staging_evidence（accepted / rejected + reason）
        ↓ 來源 ID 優先去重；必要時使用穩定 fallback identity
evidence（歷史） + official_realtime_latest（最新觀測）
        ↓
public API 只讀資料庫 → 網站
        ↘ source health、縣市／年份 coverage ledger、告警
```

現有 `raw_snapshots`、`staging_evidence`、`evidence`、`official_realtime_latest`、
`ingestion_jobs`、`adapter_runs` 與 realtime jurisdiction tables 應優先沿用。
只新增無法由現有 schema 表達的歷史覆蓋狀態，不重建第二套平行 ingestion framework。

## 全台完成契約

### 行政區範圍

必須固定覆蓋下列 22 縣市：

臺北市、新北市、桃園市、臺中市、臺南市、高雄市、基隆市、新竹市、嘉義市、新竹縣、
苗栗縣、彰化縣、南投縣、雲林縣、嘉義縣、屏東縣、宜蘭縣、花蓮縣、臺東縣、澎湖縣、
金門縣、連江縣。

### 歷史覆蓋

第一個可驗收窗口固定為 2018–2026，共 `22 × 9 = 198` 個縣市年度格。每格必須有以下
其中一種狀態，不能是未定義空白：

- `unassessed`：尚未執行該縣市年度查核；這是初始 fail-closed 狀態，完成驗收時不得殘留；
- `complete`：已跑完核准來源，資料與來源範圍相符；
- `partial`：只完成部分官方來源或行政區；
- `official_checked_empty`：核准來源成功回應且明確為空；
- `not_published`：官方確認沒有公開可讀來源；
- `stale`：來源存在但更新已超過契約；
- `failed`：本次 ingestion 失敗，不能解讀成無災情。

年度狀態只描述 ingestion coverage，不代表該年有或沒有淹水。

### 即時感測覆蓋

每縣市需分別輸出下列 signal family 狀態：

1. rainfall；
2. river／drainage water level；
3. flood depth；
4. sewer water level；
5. pump／gate status or water level；
6. official warning。

允許狀態至少包括：`measured`、`central_fallback`、`local_direct`、`stale`、
`not_publicly_available`、`authorization_pending`、`failed`。

使用者查詢時必須看到最近站距離、觀測時間、來源類型與 freshness；若半徑內沒有感測器，
明確回傳「無公開感測器」，不得使用縣市中心點或其他類型來源補成量測值。

## 分階段實作

### PR 1：單一來源註冊表與覆蓋 ledger

目標：先消除 catalog、migration、runtime allowlist、部署設定與文件漂移。

- 建立單一 machine-readable source registry；
- 由 registry 驗證或產生 catalog／runtime／部署需要的 key；
- CI 失敗條件：adapter 存在但沒有明確的 enablement decision、source contract 或 runtime scope；
- 新增最小的 historical coverage persistence 與 admin/public-safe summary；
- 將 22 縣市與 2018–2026 視為固定 contract fixture。

退出條件：198 格都能被查詢且沒有 undefined；所有 adapter 都有一致 enablement decision。
`unassessed` 只允許作為實作期間的明確初始狀態，不算完成。

### PR 2：中央即時骨幹正式排程與可觀測性

目標：讓查詢依賴 worker-persisted evidence，而不是 API 即時橋接或查詢時外部 fetch。

- 依官方 cadence 排程 CWA、WRA、IoW、Civil IoT、NCDR；
- 每來源獨立 timeout、retry、raw snapshot 與 failure isolation；
- freshness 預設以來源 cadence 的三倍作 stale gate，另由來源契約覆寫；
- public-safe readiness 顯示 scheduler heartbeat、最近成功時間、stale source count、
  22 縣市最低覆蓋數，不公開 URL credential 或 secret metadata；
- 保留每來源 kill switch 與 rollback。

退出條件：正式環境可證明 raw、staging、promotion、latest 與 adapter run 持續寫入。

### PR 3：歷史事件基線與 2023–2026 回補

目標：建立真正可累積、可查核的事件庫。

- 重新匯入 WRA historical KML 與 NSTC 近五年點位，保留原始限制；
- 逐縣市、逐年份執行 2023–2026 backfill job；
- 優先使用穩定官方事件 ID；沒有 ID 時，使用
  `provider + occurred_at + admin_code + normalized_location + event_type`；
- 同一事件的多來源資料保留 provenance 與 corroboration 關係，不相互覆寫；
- WRA latest-event API 取得正式 credential／contract 後開始排程累積；
- 日期區間 SOAP、七天 feed 與地方官方頁面各自通過 contract review 後才啟用；
- 搜尋引擎僅作 discovery，不保存搜尋 redirect 為 citation，不在 request path 執行。

退出條件：198 格都有可追溯狀態；已知近期事件跨縣市 regression fixtures 通過；最新事件
離開 upstream latest feed 後仍可由資料庫查得。

### PR 4：地方感測補強與外部申請

目標：提高中央站網以外的空間密度，但不假裝不存在的地方資料已經存在。

- 20 縣市既有地方 adapter 逐來源完成 live smoke、license、schema、station inventory、
  freshness 與正式持久化證明；
- 金門 KWIS 完成 token／read contract 後才啟用；
- 連江正式送出 live water／flood-depth 資料釋出請求；
- 苗栗、花蓮、臺東等 contract 或授權候選持續追蹤，但中央 fallback 不得被地方缺口關閉；
- 中央與地方同站或同事件需要去重，不能 double-count 風險。

退出條件：22 縣市六類 signal family 全都有明確狀態；所有 `measured` 狀態都有近期 production row。

### PR 5：DB-only public query 與精簡 UI

目標：查詢快、資訊少而準，且不再以舊資料填補版面。

- public API 不執行外部 history search 或 ingestion write；
- request-time official search 先改為 feature-flagged fallback，再於 production coverage 達標後移除；
- UI 固定分成「近期實際淹水」、「附近即時感測」、「資料覆蓋與限制」；
- 每筆顯示時間、距離、來源、資料類型、位置精度、最後同步與限制；
- 若最新歷史很舊，優先顯示覆蓋狀態，不以長篇文字掩蓋 ingestion 缺口；
- desktop、390px mobile、文字溢出與來源連結需通過 E2E。

退出條件：外部來源中斷不影響 public query latency；舊紀錄不再被呈現為近期風險代理。

### PR 6：正式驗收、監控與舊路徑退役

- 每縣市至少 3 個 canary，共 66 個地址，涵蓋都市、低窪／沿海與偏遠位置；
- 每個 canary 驗證行政區、歷史 coverage、即時 signal family、站距、freshness 與直接來源；
- 正式 scheduler 連續 7 日成功，且故障注入證明單一來源不會拖垮其他來源；
- migration、worker、API、Web、OpenAPI、Postgres integration 與 hosted smoke 全部通過；
- `/health`、`/ready` 與 public-safe ingestion readiness 回報同一個 merged main SHA；
- production 證據完成後移除 request-time upsert 主路徑與不再使用的個案 adapter。

退出條件：部署 SHA、CI、來源 freshness、198 格歷史覆蓋、22 縣市即時訊號與 66 個 canary
均通過；任何未完成外部授權仍以明確 pending／unavailable 顯示，不阻止其他縣市提供真實資料。

## 優先級

### P0：立即停止擴大技術債

1. 單一來源 registry 與 drift test；
2. historical coverage ledger；
3. 中央 worker persistence 與 ingestion readiness；
4. public query DB-only 邊界；
5. WRA latest-event API credential／contract 申請。

### P1：補齊近期年份與地方運轉證據

1. 2023–2026 全台回補；
2. 20 縣市既有地方 adapter 正式啟用與監控；
3. 金門授權與連江資料釋出；
4. 66 個 production canary。

### P2：佐證與擴充

- 警廣、媒體、使用者回報或查核平台只作 corroboration；
- 不得取代官方事件或量測；
- 在隱私、授權、去重與 false-positive review 完成前不影響主要風險分數。

## 外部依賴與不能虛假承諾的部分

- WRA FHY API 官方說明要求 API key，且建議非政府機關優先使用政府開放資料；申請可能需要
  書面核可，不能假裝 credential 已存在。
- 金門 KWIS 需要正式 token／用途核可。
- 連江目前沒有找到合格地方 live API；在官方釋出前，只能提供中央可驗證脈絡與公開缺口。
- 官方感測值仍可能因儀器或傳輸異常而錯誤；「官方」不等於不需 QA。
- `not_published`、`official_checked_empty` 與 `failed` 必須是不同狀態，缺資料永遠不等於安全。

## 官方參考

- 水利署歷史淹水資料：<https://data.gov.tw/dataset/25770>
- 國科會近 5 年淹水災點：<https://data.gov.tw/dataset/130016>
- CWA 雨量觀測站資料：<https://data.gov.tw/dataset/9177>
- WRA 即時水位：<https://data.gov.tw/dataset/25768>
- WRA IoW 淹水深度基本資料：<https://data.gov.tw/dataset/142979>
- WRA IoW 淹水深度最新資料：<https://data.gov.tw/dataset/142980>
- WRA FHY General API v2：<https://fhy.wra.gov.tw/Api>
- WRA 七天內淹水災情服務描述：
  <https://fhy.wra.gov.tw/dmchy/wra/GeneralWS/ws/wsgeneral.asmx?op=wsFloodings>
- WRA 日期區間淹水災情處置服務描述：
  <https://fhy.wra.gov.tw/dmchy/wra/WebCIAComponent/WebService/wraformalwsall.asmx?op=wsFloodEventQuery>
- NCDR CAP 文件：<https://alerts.ncdr.nat.gov.tw/web/developer/cap-docs>

## 完成定義

本計畫不能因新增一筆事件、完成一個縣市、merge 一個 PR 或讓 UI 顯示更多文字而宣稱完成。
只有同時符合以下條件才算完成：

- 22 縣市皆可查詢；
- 198 個歷史覆蓋格皆有證據狀態；
- 22 縣市六類即時 signal family 皆有真實、可追溯狀態；
- 所有 public evidence 來自已持久化資料，並保留來源、時間、距離、精度與限制；
- 正式環境來源 freshness 與 scheduler health 可被監控；
- 66 個地址 canary 與跨縣市近期事件 regression 通過；
- 無資料、過期、來源失敗與官方未公開不再被產品解讀成低風險或沒有淹水。
