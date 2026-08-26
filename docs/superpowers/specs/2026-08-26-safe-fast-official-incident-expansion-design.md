# Flood Risk v1 安全快速官方事件來源擴充設計

日期：2026-08-26
狀態：書面規格已於 2026-08-26 經使用者核准

## 摘要

本設計是 `2026-08-24-v1-flood-risk-community-signals-design.md` 的第一個
安全快速增量。它不重做既有 49 個水情 adapter，也不改變第一版「官方即時資料
主導、歷史資料分開、社群只能提高警戒」的產品邊界。

本輪先完成同一個子系統：**官方警戒與即時事件 ingestion**。執行順序為：

1. 完成 Core Task 11 的 CWA 豪大雨 CAP transport、parser、生命週期與 audit，
   但在鄉鎮邊界未經審核前不進評分。
2. 依 2026-08-26 現行契約修正 Core Task 12 的 NCDR datastore → dump CAP，
   但在 Circle／精確空間支援未經審核前不進評分。
3. 新增警廣即時路況的積淹水事件 adapter，作為會顯示但不計分的近期事件脈絡。
4. 新增 WRA 淹水、河川、水庫與淹水災情 KML 的受限 adapter；在取得真實 active
   fixture、完成重複辨識與空間審核前，只保存 audit/context，不進評分。
5. 產生 NCDR 公民災情／SitRep、地方政府缺口與 Waze for Cities 的申請包；不擅自
   送件、不使用登入 session，也不把未取得的資料假裝成已串接。
6. 既有即時來源仍走 Core Task 14/16 的逐來源 isolated acceptance；repository
   預設與 checked-in gates 全部維持關閉。

WRA 攝影機、LINE 自有回報、Waze ingestion、TDX 道路事件與任意社群關鍵字搜尋
各自涉及影像、個資、合作條款、成本或新的 public contract，因此拆成後續獨立
規格，不混入這個上線關鍵路徑。

## 與既有規格的優先關係

- `docs/superpowers/plans/2026-08-24-v1-core-official-baseline.md` 仍是 Core
  Task 11–16 的主要實作計畫。
- 本文件覆蓋該計畫中已被 2026-08-26 live contract 證據推翻的 Task 11/12
  transport 與 scoring 假設。
- `docs/reviews/remote-integration-2026-08-25.md` 所記錄的下列現況是本輪權威前提：
  CWA 主要為鄉鎮 geocode、NCDR 使用 `/api/datastore` 與
  `/api/dump/datastore`、NCDR 常見 Circle、Civil IoT 新 host 當日不可連線。
- Community Tasks 1–11 仍不在 Core Task 16 之前接入官方風險分數。
- 三份既有未追蹤交接文件屬使用者資料，本輪不得修改或納入提交。

## 目標

1. 用正式、可稽核、可獨立停用的來源補足固定感測器以外的即時事件資訊。
2. 讓警廣積淹水通報在附近證據中可見，同時保證它不會單獨提高或降低風險。
3. 讓 CWA 與 NCDR 使用目前正確的 API 契約，且憑證不出現在 URL、log、錯誤或
   raw snapshot。
4. 讓 WRA KML 僅從核准 host/path 取得，拒絕任意 NetworkLink、redirect、外部
   entity、超大 XML 與不具來源時間的事件。
5. 所有新來源預設關閉；沒有 active fixture、授權、station/jurisdiction proof、
   hosted persisted smoke 與 rollback proof 時不得聲稱 production ready。
6. Public `/v1/risk/assess` 只讀已保存資料，永不在 request path 等候任何上游。

## 非目標

- 不一次啟用全部 49 個既有官方／地方 adapter。
- 不把缺資料、空 feed、來源故障或 Civil IoT 移轉失敗解讀為低風險。
- 不把警廣民眾通報、Waze、LINE 或單篇社群文章當成已確認淹水。
- 不以縣市 polygon 代替 CWA 鄉鎮警戒，也不以 Circle 中心點代替 NCDR 影響範圍。
- 不在本輪加入 CCTV 電腦視覺、圖片保存或自動影像判讀。
- 不在本輪送出 NCDR、地方政府、Waze、TDX 或其他外部申請。
- 不反向工程 LINE mini-app、地方儀表板、Waze Live Map 或登入型網站。
- 不改寫既有 risk weights、thresholds 或 community uplift 規則。

## 來源與精確行為

### 1. CWA 豪大雨 CAP

- Adapter key：`official.cwa.heavy_rain_warning`
- 正式來源：`W-C0033-003` CAP。
- 認證：既有 `CWA_API_AUTHORIZATION` 以獨立參數／header 傳入，禁止拼入 loggable
  URL。
- 每個 CAP message 保存 sender、identifier、sent、references、status、msgType、
  effective/onset、expires、areaDesc 與來源 geocode。
- Alert、Update、Cancel 與 valid empty poll 沿用 Task 8/9 的 canonical lifecycle、
  generation anti-resurrection 與 audit retention。
- 只有 reviewed boundary snapshot 能把 admin code 轉成 geometry。第一版現有
  snapshot 只有 22 縣市，而 CWA 主要提供鄉鎮 geocode；無精確 reviewed geometry
  的 row 只保存 raw snapshot、source-specific rejection 與 ingestion run audit，
  不可寫入 accepted staging、`evidence`、`official_realtime_latest`、附近 coverage
  或 scoring。
- 禁止把鄉鎮向上轉成整個縣市後評分，也禁止製造 centroid。

### 2. NCDR datastore → dump CAP

- Adapter key：`official.ncdr.cap`
- Index endpoint：`https://alerts.ncdr.nat.gov.tw/api/datastore`
- CAP endpoint：`https://alerts.ncdr.nat.gov.tw/api/dump/datastore`
- 認證參數名稱：`apikey`。
- Index 必須傳小寫 `format=json`；無真實憑證的 query shape 為
  `/api/datastore?apikey=REDACTED&format=json&limit=1`。
- Dump 必須傳小寫 `format=xml` 與 `capid`；無真實憑證的 query shape 為
  `/api/dump/datastore?apikey=REDACTED&capid=REDACTED&format=xml`。
- `/api/dump`、`key` 與舊 Atom runtime path 不得進 production builder；舊 Atom
  fixture 只保留 parser regression。
- Datastore 只提供 index/transport identity；跨來源 canonical identity 必須取自
  dump CAP 的 `(sender, identifier, sent)`，不得用 `capid` 冒充事件 identity。
- CAP ID 數量有硬上限、排序 deterministic、重複 ID 只 fetch 一次；任一 dump
  failure 必須產生 source-specific partial/failed audit，不得改成 healthy empty。
- FloodSensor、HighWater 與地方警戒的 Circle 必須保留原始 center/radius 語意。
  在 promotion/query 尚未完整支援 reviewed Circle geometry 前，只保存 raw
  snapshot、source-specific rejection 與 ingestion run audit，不可寫入 accepted
  staging／`evidence`，也不可用中心點計分。
- API key 只能存在記憶體與 secret store；錯誤、log、raw snapshot、run summary、
  report 只可顯示 `[REDACTED]` 或 safe key ID。

### 3. 警廣即時路況

- Adapter key：`official.npa.police_radio_traffic`
- 官方資料集：`https://data.gov.tw/dataset/15221`
- Read endpoint：
  `https://rtr.pbs.gov.tw/NMP103_PbsWS/resources/roadData/opendata`
- Adapter 只接受明確積淹水語句，例如「淹水」「積水」「水淹」「道路淹水」；
  單獨出現「大雨」「豪雨」「下雨」不得成為淹水事件。
- `UID` 是來源 ID。事件時間由 `happendate` + `happentime` 解析；`modDttm` 是
  upstream update time。不得以 `fetched_at` 偽造發生時間。
- 只接受具有有效 WGS84 座標且位於 Taiwan bounds 的資料；缺座標不做地址推測或
  第三方 geocoding，只保留 rejection/audit。
- Normalized event 使用 `EventType.STATUS_ONLY`、`evidence_scope="context"`、
  `location_precision="road_or_lane"`，並帶
  `context_kind="reported_flood_road_incident"`、
  `verification_status="reported_unverified"` 與公開限制說明。
- 它不進 `official_realtime_latest`、不建立 rainfall/hydrology coverage、不滿足
  low-risk safety gate，也不進任何 risk weight。
- Assessment 只顯示 as-of 前六小時內的警廣事件；未來超過五分鐘、超過六小時、
  已被來源更新為解除／排除或重複 UID 的事件不得顯示為近期事件。
- 公開文案固定標示「警廣即時路況通報，尚未由淹水感測器確認」。

### 4. WRA 防災警戒與災情 KML

- Adapter key：`official.wra.flood_warning`
- Metadata/data catalog：`https://data.gov.tw/dataset/5982`、`5983`、`5984`。
- 核准 upstream 僅包含：
  - `opendata.wra.gov.tw` 的正式 metadata/index 與 wrapper KML；
  - `fhy.wra.gov.tw/pub_web_2011/kml/KmlShare/` 下經逐項列入 allowlist 的
    `NewstFloodWarm.kml`、`NewstWaterWarm.kml`、
    `NewstReservoirWarm.kml`、`AnnounceFlood.kml`。
- Wrapper 即使列出 `http`，只有 host/path 與 allowlist 完全相等時才可升級成同一
  exact host/path 的 HTTPS；禁止一般化 URL rewrite。
- Redirect 必須在跟隨前驗證；跨 host、未核准 path、userinfo、非預設 port、query
  注入與 fragment 一律拒絕。
- 使用 `defusedxml` 並限制 response bytes、XML depth、element count、Placemark
  count 與 coordinate count；KML NetworkLink 不得遞迴擴張。
- Healthy empty KML 是 `no_active_event`；transport、schema 或 boundary failure
  不是 empty。
- 第一版 normalized row 使用 `EventType.STATUS_ONLY` 與 context scope，保留官方
  警戒/災情種類、原始位置、來源時間、active window 與限制。
- 在取得真實 active fixture、完成與 NCDR/CWA 的來源 identity/dedupe review、
  證明 exact geometry，以及獨立核准前，不進 scoring 或 latest。

## 資料流

```text
scheduled worker
  -> exact source adapter
  -> bounded raw snapshot
  -> normalized evidence
  -> staging validation
  -> audit evidence
  -> reviewed promotion only when source-specific contract permits

public assessment request
  -> PostgresAssessmentRepository
  -> persisted official latest + persisted context/history
  -> non-scoring recent incident context filter
  -> existing scorer and safety gate
  -> evidence preview + explicit limitations
```

任何 upstream fetch 都不得出現在 public request path。警廣與 WRA context 即使顯示
在 evidence preview，也不得被轉成 `RiskEvidenceSignal` 的已加權 event type；既有
scorer 對 `status_only` 權重為零，測試必須鎖住這個邊界。

## 啟用與回退

- 每個新 adapter 有獨立的 `SOURCE_*_ENABLED` 與 `SOURCE_*_API_ENABLED` hard gate。
- `.env.example`、settings defaults、catalog migration 全部是 false/disabled。
- `WORKER_ENABLED_ADAPTER_KEYS` 不得繞過 source gate、API gate、credential gate、
  contract gate 或 catalog row。
- CWA/NCDR transport/parser 完成不等於 scoring enabled；空間支援未核准時，
  promotion/scoring gate 必須保持關閉。
- 警廣與 WRA context 只能在 Task 14 per-source runner 完成後逐一 isolated 啟用。
- 每次啟用需有 persisted raw/staging/run/evidence proof、freshness、來源數量、
  attribution、deploy SHA 與 public assessment 證據。
- 回退順序固定為：先停用 catalog row，再停 runtime/API gates；保留 audit rows。
- Civil IoT 目前是 degraded/migration dependency，不是本輪上線的單點必要條件。

## 外部申請包

本輪只產生不含 secret、可供人工送件的 request packet：

1. NCDR「公民回報災情事件」與 EDXL-SitRep 政府單位申請。
2. 金門 KWIS read token 與可讀欄位／rate limit／授權範圍確認。
3. 花蓮 Senslink、苗栗雨水下水道、屏東 PTEOC、臺東水情系統與連江地方 live
   feed 的正式 M2M/read API 請求。
4. Waze for Cities 合作資格與 flood/road incident feed 使用條款確認。

Packet 可包含公開資料集名稱、需要的欄位、用途、預期 cadence、保存/刪除政策與
聯絡窗口欄位，但不得包含真實 token、帳密、私人證據 URL 或自動送出功能。

## 錯誤與健康語意

- `no_active_event`：來源成功、schema 合法、這次沒有生效事件。
- `partial`：index 成功但部分子資源／CAP dump 失敗；成功資料可稽核，不能宣稱
  完整。
- `failed`：transport、TLS、auth、schema、host/path、XML bounds 或必填 identity
  失敗。
- `stale`：來源時間存在但超過 source-specific threshold。
- `disabled`：任一 hard gate 或 catalog row 關閉。
- Healthy empty warning 不建立 query-local coverage，也不證明附近安全。
- 上游返回 429 時遵守 bounded Retry-After/cooldown；不在同一 cycle 無限重試。

## 測試與驗收

每個 production change 必須先看見預期 RED，再做最小 GREEN。最低測試矩陣：

1. CWA：active、Update、Cancel、valid empty、expired/future、multi-area、鄉鎮無
   reviewed boundary 不進 latest/scoring、secret redaction。
2. NCDR：正確 `/api/datastore` + `format=json` 與 `/api/dump/datastore` +
   `format=xml`、`apikey`/`capid`、bounded IDs、duplicate IDs、Circle preservation、
   partial dump、valid empty、legacy contract rejection、secret redaction。
3. 警廣：積淹水 keyword、rain-only rejection、中文日期時間、invalid/future/stale
   time、Taiwan bounds、missing coordinates、duplicate/update UID、六小時 display
   window、scoring invariance。
4. WRA：exact metadata resolution、四個 allowlisted KML、HTTP→HTTPS exact upgrade、
   redirect rejection、arbitrary NetworkLink rejection、XML/geometry bounds、healthy
   empty、active fixture gate、scoring invariance。
5. Registry/config：unknown key fail closed、所有新 defaults false、allowlist 不繞過
   hard gates、credential/contract gates 不可由 fixture flag取代。
6. Persistence/API：context row可稽核、只顯示近期事件、evidence preview 有限制、
   status-only 事件加入或移除前後 realtime/historical/overall score 完全相同。
7. Full acceptance：Worker/API unit、Ruff、mypy、migration、mandatory Postgres、API
   contract、Web build/E2E 與 `git diff --check`；不得以 skip 規避必要 DB 測試。

## 完成定義

只有同時符合以下條件，才可把這個子專案標記完成：

- Task 11/12 使用本文件的現行 contract，transport/parser/audit tests 全通過。
- 警廣與 WRA adapters 已完成 TDD、獨立 task review 與 whole-branch review。
- 所有新 gates 與 catalog rows 預設 disabled。
- 警廣/WRA context 的 scoring invariance 有 unit 與 repository/service 證據。
- 無 secret、任意 redirect、任意 NetworkLink、未受限 XML 或 fetched-time 假造。
- External request packets 可供人工審閱，但沒有自動送件或憑證內容。
- Task 14/16 仍負責實際逐來源 production activation；在其 acceptance 前只能說
  「code landed/default off」，不能說「已上線」。
