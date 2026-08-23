# Flood Risk v1 核心重構與社群混合訊號設計

日期：2026-08-24
狀態：設計已核准；待規格審閱後進入 implementation planning

## 摘要

Flood Risk v1 只解決一個清楚的使用者問題：使用者輸入地址、地標或地圖點位，
選擇半徑後，系統以官方即時資料、官方歷史資料、淹水潛勢與經交叉佐證的社群
訊號，回傳可解釋的即時風險、歷史風險、信心程度、證據與資料缺口。

第一版採以下已核准決策：

- 全臺以 CWA、WRA／IoW、NCDR、WRA 歷史淹水與淹水潛勢建立中央基線。
- 南高屏優先補充地方政府直接開放的即時資料；沒有正式機器介面時明確揭露缺口，
  不以瀏覽器爬取冒充正式來源。
- 社群採自適應混合模式：正式 API 自動擷取、使用者查詢提高道路級搜尋優先度、
  瀏覽器 Agent 只作受監督的來源探索與複核。
- 單一社群文章不改變風險；兩個獨立社群來源，或一個社群來源加一項官方異常，
  才能形成交叉佐證。
- 社群只能提高警戒，不能降低風險；過期、失敗或缺失的官方資料不能被解讀為
  低風險。

## 與既有設計的關係

本文件是第一版產品範圍的主設計。它縮限而不抹除既有研究：

- `2026-06-27-taiwan-realtime-source-backbone-design.md` 保留作來源研究與欄位參考，
  但第一版不保留多層 raw snapshot、staging、promotion 與 public query fallback
  的全部複雜度。
- `2026-06-27-taiwan-local-realtime-water-sources-design.md` 與
  `2026-06-29-local-source-blocker-resolution-design.md` 保留作地方來源清冊；第一版
  不以 22 縣市地方直連完成為上線前提。
- `codex/v2-risk-engine-rebuild` 分支不合併為第一版基礎。其「缺資料不得判低風險」
  與 latest monotonicity 原則保留；batch manifest、sighting graph、snapshot
  publication、query heat、precomputed profiles 與多層 replay infrastructure 凍結。
- 舊 NCDR AtomFeed 路徑已不作新實作依賴；第一版使用現行民生示警 API／CAP
  文件所描述的介接方式。

## 目標

1. 保留簡單的地址／地標／地圖點位加半徑查詢流程。
2. 分開呈現即時風險與歷史風險，不用歷史資料假裝現在正在淹水。
3. 讓官方即時資料成為基線，社群資料成為較早但較不確定的補充訊號。
4. 每個結果都能說明來源、觀測時間、距離、信心、資料新鮮度與限制。
5. 上游來源故障時仍能快速回應，且不得把故障或缺資料顯示成低風險。
6. 第一版元件小而清楚，可個別測試、停用及回退。

## 非目標

- 不在第一版完成 22 縣市所有地方資料直連。
- 不以登入、個人帳號、Cookie、CAPTCHA 或反爬繞過取得社群或地方資料。
- 不保存社群作者身分、完整文章、留言、HTML、Cookie、截圖或原始媒體。
- 不讓單一社群文章直接宣稱已確認淹水。
- 不以淹水潛勢圖作為即時淹水證明或土地利用判定。
- 不建立通用 Agent 平台、任意網站爬蟲、向量搜尋或大型內容審核系統。
- 不在 public assessment request 期間同步等待外部政府或社群網站。

## 使用者流程

1. 使用者輸入地址、地標、道路名稱或選取地圖點位。
2. 使用者選擇搜尋半徑。
3. Geocoder 回傳候選點位、座標精度、縣市、行政區、道路與常見別名。
4. `AssessmentService` 從已保存的最新官方、歷史與社群資料做有界空間查詢。
5. 系統分開計算即時與歷史風險，再產生整體摘要與主導模式。
6. UI 顯示風險、信心、證據預覽、來源健康與缺失訊號。
7. 查詢同時只會提高道路級社群搜尋的背景優先度；初次回應不等待該搜尋完成。
8. 背景搜尋完成後，使用者重新整理或再次查詢即可看到較新的社群訊號。

## 地域與來源範圍

### 全臺中央基線

| 來源 | 第一版用途 | 限制 |
| --- | --- | --- |
| CWA 自動雨量與豪大雨警特報 | 降雨觀測、累積雨量、氣象警特報 | 不是道路淹水深度 |
| WRA／IoW 水資源物聯網 | 淹水深度、河川／區排水位及可用的地方合建感測 | 站點分布與回傳品質不均 |
| WRA／NCDR 民生示警 | 淹水、河川高水位、淹水感測等 CAP 警戒 | 是警報匯流，不是完整原始感測網 |
| WRA 歷史淹水 | 大尺度歷史事件 | 不完整涵蓋局部都市道路積水 |
| WRA 淹水潛勢 | 背景易淹情境 | 是模型情境，不是即時狀況 |

主要官方參考：

- CWA 雨量：<https://opendata.cwa.gov.tw/dataset/observation/O-A0002-001>
- CWA 豪大雨 CAP：<https://opendata.cwa.gov.tw/dataset/warning/W-C0033-003>
- WRA IoW：<https://iot.wra.gov.tw/>
- 民生公共物聯網水資源資料：
  <https://ci.taiwan.gov.tw/dsp/Views/dataset/water.aspx>
- NCDR 示警 API：<https://alerts.ncdr.nat.gov.tw/web/developer/alerts-api>
- NCDR CAP 文件：<https://alerts.ncdr.nat.gov.tw/web/developer/cap-docs>
- WRA 歷史淹水：<https://data.gov.tw/dataset/25770>
- WRA 淹水潛勢：<https://data.gov.tw/dataset/25766>

### 南高屏地方深化

- 臺南第一優先使用臺南市政府水利局正式開放的淹水感測器基本資料與即時資訊。
- 高雄與屏東優先使用中央 IoW／NCDR 已匯流資料；地方人讀網站、LINE 或儀表板
  只有在取得正式 read API、授權與可判斷的觀測時間後，才升級為 production
  adapter。
- 若地方來源只有人讀頁面，第一版顯示 `local_machine_feed_missing`，而不是顯示
  地方資料已完整。
- 地方來源不得覆寫中央來源；同一站點、時間與量測值只算一次證據。

臺南官方資料頁：
<https://data.tainan.gov.tw/DataSet/Detail/03dd4536-3fe7-46ec-9920-a120cb5c502c>

## 社群與瀏覽器存取政策

### Production 自動來源

Production ingestion 只允許以下存取方式：

- 平台正式 API。
- RSS／Atom／CAP／SensorThings 等已公開介面。
- 有明確授權的 bulk data 或 repository release。
- 已取得書面授權的機器介面。

第一個正式社群 adapter 是 Threads keyword search API。使用者回報是另一個獨立
來源類型。YouTube 與 X 在完成各自政策、成本、保存與刪除同步設計後再個別啟用；
Dcard 未取得書面同意前不自動化；PTT 只在 Atom 或其他正式路徑獲得核准後試點。

Threads live mode 仍需正式 App、權限、App Review 與 token。未取得任一條件時，
adapter 保持 disabled，只允許 sanitized fixture／contract tests；這不阻塞全臺
官方基線與使用者回報功能上線，也不得以 browser scraping 代替缺少的核准。

### 受監督的瀏覽器 Agent

瀏覽器 Agent 可用於：

- 發現新的官方或社群來源。
- 人工要求的事件複核。
- 確認公開頁面是否仍存在、是否已刪除或是否改版。

瀏覽器 Agent 不可：

- 使用個人帳號或登入 session 作背景擷取。
- 繞過 CAPTCHA、年齡限制、反爬、付費牆或存取限制。
- 將發現結果直接寫入已確認事件或直接改變公開風險。
- 保存完整頁面、作者資料、留言串、Cookie 或原始媒體。

Agent 發現結果先進隔離狀態；只有符合 production 存取政策的來源才可升級為自動
adapter，個別事件則必須通過相同匹配、去重與佐證規則。

## 架構

### `Geocoder`

職責：

- 將地址、地標或道路轉成座標候選。
- 輸出縣市、行政區、道路名稱、常見別名與精度。
- 第一版保留 local／PostGIS gazetteer 與一個受控外部 fallback，逐步移除七層
  fallback chain。

它不擷取風險資料，也不決定風險。

### `OfficialIngestion`

職責：

- 按來源 cadence 擷取全臺中央基線與已核准地方來源。
- 驗證 schema、座標、觀測時間、單位與 freshness。
- 每個來源獨立記錄成功、部分成功或失敗。
- 只讓較新的有效觀測更新 `realtime_latest`。

它不在使用者請求內執行，也不計算最終風險。

### `CommunityIngestion`

職責：

- 使用核准 API 做背景關鍵字搜尋。
- 接收去識別化的使用者回報。
- 在記憶體內做文字、標籤與地點分析，輸出 sanitized `CommunitySignal`。
- 將 query request 排入一個有 TTL、去重且不保存使用者身分的最小工作清單。

第一版不建立通用 runtime queue。背景工作清單只保存 normalized query key、縣市、
道路或地點、半徑、優先度、請求時間與到期時間；相同 query key 在 TTL 內合併。

### `EvidenceRepository`

職責：

- 提供最新官方、歷史、社群與來源狀態的有界空間／時間查詢。
- 隔離各來源 schema，讓 scoring 不依賴上游 payload。
- 保證 latest update monotonicity 與 suppressed URL 排除。

它不呼叫外部網路，也不自行決定權重。

### `CorroborationService`

職責：

- 依時間、距離、行政區、道路、內容指紋與原始 URL 建立事件群組。
- 將轉貼、引用同一新聞、相同 canonical URL 或近似內容視為同一原始來源。
- 計算獨立社群來源數，以及是否存在相容的官方異常。
- 輸出 `unverified`、`community_corroborated` 或
  `officially_corroborated`。

它不提高或降低分數；只提供可重現的佐證狀態。

### `AssessmentService`

職責：

- 解析 point 與 radius。
- 從 `EvidenceRepository` 取得官方即時、歷史、潛勢與社群事件。
- 使用既有雙風險 scorer，套用 freshness safety gate 與 community uplift。
- 回傳風險、信心、主導模式、證據與資料缺口。

Public route 只依賴 `AssessmentService(repository, scorer)`，不再組裝大型 callable
dependency bag，也不在 request time 直連官方或社群上游。

## 自適應社群排程

排程有三種狀態，cadence 是可設定預設值：

| 狀態 | 預設 cadence | 行為 |
| --- | --- | --- |
| 平時 | 30 分鐘 | 搜尋全臺一般淹水詞，並輪替縣市／行政區詞組 |
| 事件模式 | 5 分鐘 | 只提高受影響縣市及鄰近行政區的搜尋頻率 |
| 使用者道路查詢 | 立即提高優先度，15 分鐘 TTL | 補入道路、地標、行政區與淹水詞的 bounded query |

事件模式可由下列任一條件啟動：

- CWA 豪大雨或颱風相關警特報。
- WRA／NCDR 淹水或河川高水位警戒。
- 已核准淹水深度、水位或雨量來源超過各來源既有警戒條件。

所有啟動條件解除後，受影響區域保留兩小時 cooldown 再回到平時模式。每個
adapter 仍受自己的 API quota、rate limit 與退避策略限制；事件模式不能繞過
平台限制。

## 關鍵字與地點匹配

Query planner 使用受控詞彙，不做任意生成式擴張：

- 核心淹水詞：`淹水`、`積水`、`水災`、`道路積水`、`地下道積水`、
  `排水不及` 等。
- 地點詞：查詢點縣市、行政區、道路全名、常見道路別名、地標與相鄰行政區。
- 候選文章必須同時符合淹水語意與可接受的地點匹配。
- 道路匹配必須有相容行政區脈絡，避免同名道路跨縣市誤判。
- 只有縣市級匹配時，geometry 使用行政區代表範圍，precision 標為
  `admin_area`，不得偽造成門牌點位。

## 最小資料模型

以下是 logical model，不要求為同一概念建立第二套資料表。實作應先盤點並重用既有
`source_catalog`／run records、`official_realtime_latest` 與 historical evidence
tables；`EvidenceRepository` 對外使用本文件的名稱與契約即可。只有既有 schema
無法安全表達的新社群欄位才新增 migration，第一版不為了重新命名而搬移資料。

### `source_catalog`

- `source_key`
- `source_family`
- `authority`
- `access_mode`
- `license_url`
- `default_cadence`
- `freshness_threshold`
- `enabled`
- `config_version`

### `source_runs`

- `id`
- `source_key`
- `started_at`
- `completed_at`
- `status`：`success | partial | failed`
- `fetched_at`
- `max_observed_at`
- `accepted_count`
- `rejected_count`
- `error_summary`
- optional sanitized payload hash／object URI；社群來源不得保存 raw body object

### `realtime_latest`

每個 `(source_key, event_type, station_id)` 只保存最新 accepted observation：

- `station_id`、`station_name`、`authority`
- `event_type`
- `observed_at`、`ingested_at`
- `geom`
- normalized metrics
- `confidence`
- `quality_flags`
- `source_run_id`
- `source_url`

更新必須只接受較新的 `observed_at`；相同時間的 conflicting value 進入 rejected
紀錄，不靜默覆寫。

### `historical_evidence`

- `source_key`
- `event_type`
- `occurred_at` 或事件期間
- `geom`
- `location_text`
- `severity`／`depth`（若來源提供）
- `source_run_id`
- `source_url`
- `quality_flags`

### `community_signals`

- `id`：由 canonical public URL 與來源產生，不由作者產生
- `source_key`
- `source_url`
- `channel`
- `published_at`、`ingested_at`
- `matched_flood_terms`
- bounded derived summary；預設不引用原文
- canonical location、admin code、geometry、precision、match basis
- `confidence`
- `moderation_state`：`unverified | accepted | rejected | suppressed`
- `event_cluster_id`
- `retention_expires_at`

明確禁止欄位：作者／帳號／handle／user id／avatar／profile、完整文章、完整留言、
HTML、媒體、截圖、聯絡方式、私人地址與 raw storage reference。

### `event_clusters`

- canonical area／geometry
- time window
- flood term classes
- distinct original source count
- compatible official evidence references
- corroboration state
- first／last observed time

每個 community signal 至多屬於一個 active cluster，避免重複計分。

### `suppressed_sources`

- canonical URL hash
- source key
- suppression reason
- suppressed at
- optional expires at

### `community_search_requests`

這是有界 operational work list，不是一般化 queue：

- normalized query key
- county／district／road or landmark
- radius
- priority
- requested at／expires at
- status

不保存使用者 id、IP、原始搜尋字串或個人化紀錄；完成或到期後刪除。

## 社群保存與刪除

- 原文只存在於 adapter 的短生命週期記憶體中。
- 未驗證或已交叉佐證的 sanitized community signal 最多保存 30 天；若來源政策
  要求更短保存、refresh 或刪除同步，以較嚴格期限為準。
- 被來源刪除、收到申訴或判定誤報時立即 suppressed，並排除評分。
- 只有獲得官方資料或人工審核確認的事件，才能另存為去識別化長期
  `historical_evidence`；原社群 signal 仍按 30 天政策到期。
- 公開 API 的 social evidence `raw_ref` 必須為 `null`。

## 評分模型

### 分開的輸出

Assessment 必須同時輸出：

- `realtime`：官方即時資料主導的 current risk。
- `historical`：歷史事件與潛勢主導的 background risk。
- `community`：未驗證或已交叉佐證的群眾警戒。
- `overall`：對使用者的保守摘要，不隱藏任一資料缺口。
- `dominant_mode`：`realtime | historical_context | community_warning | unknown`。

### 即時安全規則

- Fresh、qualifying 的官方即時資料存在時，沿用既有 realtime scorer。
- Stale、failed、missing 或無 coverage 的必要官方來源不能支持低風險。
- 單一社群文章不改變 `realtime` 或 `overall`。
- 兩個獨立社群來源，或一個社群來源加相容官方異常，形成 corroborated cluster。
- Corroborated community cluster 最多使 `overall` 提高一個風險等級，不能降低。
- 同一官方異常若已進入 base realtime score，不得因同時用於 corroboration 再加權；
  多個相近 corroborated clusters 也不疊加超過一次 community uplift。
- 沒有官方確認時，由社群造成的 overall confidence 上限為 `medium`。
- 若官方 realtime 為 `unknown` 而社群已交叉佐證，`realtime` 仍顯示
  `unknown`，`community` 顯示警戒，`overall` 可顯示 `medium` 並以
  `community_warning` 為主導模式；UI 必須同時顯示官方即時資料不足。

### 歷史規則

- 已確認歷史事件依距離、事件數、時間與來源品質影響 historical risk。
- 淹水潛勢只能作背景 context，不能單獨判定現在正在淹水。
- Historical high 不得偽裝成 current high；沒有 current evidence 時，current
  維持 `unknown`。

### Overall 主導順序

`overall` 是可解釋的顯示摘要，不是把所有來源做不透明平均：

1. 有 fresh qualifying official realtime 時，由 realtime 主導，再套用至多一次
   community uplift。
2. Official realtime 為 unknown、但 community 已交叉佐證時，overall 為
   `medium`、主導模式為 `community_warning`，並保留 official data gap。
3. 沒有 current evidence、但 historical evidence 足夠時，overall 可採 historical
   level、主導模式為 `historical_context`；UI 文案必須稱為「歷史背景風險」，不得
   稱為「目前淹水風險」。
4. Current 與 historical evidence 都不足時，overall 與 dominant mode 都是
   `unknown`。

## API 設計

保留既有 `/v1` public route，採 additive evolution。`POST /v1/risk/assess`
回應至少包含：

```json
{
  "location": {"lat": 22.99, "lng": 120.20},
  "radius_m": 1000,
  "as_of": "2026-08-24T00:00:00Z",
  "expires_at": "2026-08-24T00:10:00Z",
  "score_version": "risk-v1",
  "dominant_mode": "realtime",
  "realtime": {"level": "medium", "confidence": "high", "reasons": []},
  "historical": {"level": "medium", "confidence": "medium", "reasons": []},
  "community": {"state": "corroborated", "level": "medium", "reasons": []},
  "overall": {"level": "medium", "confidence": "high", "reasons": []},
  "evidence": [],
  "data_status": {"sources": [], "missing": []},
  "community_refresh": {"state": "prioritized", "last_completed_at": null}
}
```

正常回應包含 5–10 筆證據預覽。完整證據只在使用者展開時以既有 evidence route
分頁取得。第一版不建立 SSE、WebSocket 或持續輪詢；背景社群更新在重新整理或再次
查詢時呈現。

## UI 設計

第一版保留搜尋、地圖、半徑、風險摘要與證據列表，移除一般使用者不需要的深層
診斷面板。結果清楚區分：

- 官方感測
- 官方警戒
- 歷史事件
- 淹水潛勢
- 群眾未驗證
- 群眾已交叉佐證

每張證據卡顯示來源、觀測／發布時間、距離、位置精度、信心與限制。若道路級
社群搜尋仍在背景優先處理，顯示「已排入更新；目前結果更新於……」，不阻塞主要
風險結果。

## 失敗、降級與安全處理

- 每個 source run 獨立；一個來源失敗不回滾其他來源成功資料。
- 保留最後 accepted 值，但依 observed time 顯示 `fresh | degraded | stale |
  failed | disabled | not_applicable`。
- Malformed、未來時間、非法座標、單位未知或 conflicting latest 進 rejected，
  不更新 latest。
- API 限流使用來源專屬 backoff 與 cadence 降級，不用 browser scraping 補洞。
- 每個官方、地方、社群與 browser-discovery source 都有獨立 feature flag 與
  kill switch。
- Public assessment 不快取 dependency-failure 為成功低風險結果。
- API credentials 只由 secrets／environment 注入，不寫入 repository、log 或
  response。
- Browser discovery 與 community ingestion 不得使用個人帳號或保存可識別資料。

## 重構邊界

### 保留

- 現有地址／地標搜尋與 map interaction。
- 現有 dual risk scorer 與 golden fixtures。
- 現有 `未知` safety behavior。
- 既有 official realtime latest 概念與 worker adapter contracts。
- 現有 evidence card 與 attribution 基礎。

### 簡化

- Public route dependency bag 收斂為 `AssessmentService(repository, scorer)`。
- 官方即時資料只從 worker-fed persisted latest read model 讀取。
- Geocoder 收斂為 local／PostGIS 加一個受控 fallback。
- 一般使用者 UI 只顯示資料狀態摘要；深層 diagnostics 移到 admin／ops。

### 凍結

- v2 batch manifests、sighting graph、snapshot finalization 與 shadow publication。
- Precomputed risk profiles、profile refresh 與 embeddings。
- Query heat 作為產品功能；只保留本設計的短期、去識別
  `community_search_requests`。
- 通用 runtime queue／replay、tile cache、PMTiles 與 22 縣市 proof machinery。
- Dcard／Meta browser scraping 與任何登入式社群擷取。

凍結功能的既有資料表不在第一個 migration 直接刪除。先停止新增產品依賴與寫入，
待新 vertical slice 驗證後再另案處理資料保存與移除。

## 測試策略

### Characterization 與 scorer tests

- 保留既有 realtime／historical golden fixtures。
- 驗證無 evidence、stale、failed 與 missing coverage 仍為 unknown，不是 low。
- 驗證潛勢圖只影響 historical context。

### Adapter contract tests

- CWA、WRA／IoW、NCDR、臺南與 Threads 使用固定 sanitized payload fixtures。
- 測試 pagination、timeout、rate limit、malformed schema、missing coordinate、
  stale observed time 與 unit conversion。
- 所有 live adapters 預設關閉，且不能只靠 allowlist 繞過 source gate。

### Community matching tests

- Flood term 加正確行政區／道路才接受。
- 同名道路跨縣市不誤配。
- 轉貼、canonical URL、新聞引用與近似內容不重複計數。
- 單一訊號不改分。
- 兩個獨立訊號可形成 `community_corroborated`。
- 社群加官方異常可形成 `officially_corroborated`。
- Suppressed 或 expired signal 不參與 cluster 或 scoring。

### Privacy tests

- Persisted payload、database rows、API response 與 logs 不包含 author、username、
  user id、body、HTML、Cookie、profile、media 或 raw social object reference。
- 刪除／suppression 後對 public API 不可見。

### Repository 與 integration tests

- Spatial radius query 有界且使用正確 geometry。
- Latest upsert 只接受較新 observation。
- Source failure 不覆蓋既有 accepted row。
- Community search request 在 TTL 內去重，且不保存使用者身分。
- Assessment response 同時揭露 source states 與 missing signals。

### End-to-end tests

- 地址搜尋、候選選擇、半徑查詢與地圖標記。
- 即時、歷史、社群及 overall 結果與標籤。
- 官方來源故障時仍可回應，且不顯示低風險。
- 背景社群 refresh 不阻塞首次 assessment。

## 交付順序

1. 凍結 v2 合併路徑，為現有核心流程補 characterization tests。
2. 建立最小資料模型與 `EvidenceRepository`。
3. 將 public assessment 收斂成 `AssessmentService`。
4. 讓 CWA、WRA／IoW、NCDR、歷史淹水與潛勢形成全臺 persisted baseline。
5. 保留臺南正式地方 adapter；為高雄、屏東輸出中央覆蓋與地方機器介面缺口。
6. 接入 Threads 正式 API 與使用者回報的 sanitized ingestion。
7. 實作 event clustering、corroboration 與 community uplift。
8. 實作 adaptive scheduler 與 bounded community search work list。
9. 精簡 public API／UI，加入資料狀態與社群標籤。
10. 加入受監督 browser discovery 與 admin kill switches。

每一步都由 feature flag 控制並通過對應測試後再啟用。第一版不以取得高雄、屏東
未公開地方 API 或後續社群平台核准作為全臺中央基線上線的阻塞條件。

## 驗收標準

- 全臺任一可 geocode 的點位都能取得中央基線結果或明確的 unknown／data gap。
- 南高屏查詢清楚顯示中央、地方直出與缺失訊號，不誤稱地方資料完整。
- Public assessment 不在 request time 等待任何上游網站。
- 任何來源中斷、過期或無 coverage 都不會錯報低風險。
- 單一社群文章不改分；轉貼不算獨立來源。
- 兩個獨立社群訊號，或社群加官方異常，最多提高 overall 一級。
- 社群沒有官方確認時，overall confidence 不高於 medium。
- 每筆證據可看到來源、時間、距離、位置精度、信心與限制。
- 社群原文與作者身分不進 database、API 或 logs。
- 來源可獨立停用，且停用後不影響其他來源查詢。
- 既有 realtime／historical scorer 行為與核准的 golden fixtures 維持相容。

## 已解決的產品決策

- 地域策略：全臺中央基線＋南高屏地方深化。
- 社群存取：正式介面自動化＋使用者回報＋受監督 browser discovery。
- 排程：平時低頻、災害事件高頻、道路查詢提高背景優先度。
- 社群評分：採交叉佐證模式；單篇不改分。
- 儲存：社群 metadata-only，預設 30 天，確認歷史事件另存去識別紀錄。
- 上線策略：分階段 feature flags，不等待 22 縣市全部地方直連。

本設計沒有尚待決定的產品行為；新增平台、取得地方授權、調整 source weights 與
數值 calibration 均屬後續獨立 review，不在第一版自行擴張。
