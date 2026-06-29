# 地方即時水情卡點分流解法設計

日期：2026-06-29
狀態：設計稿；本文件只規劃，不執行、不新增 adapter、不改 production 資料流

## 背景

2026-06-29 的候選來源 live smoke 已把尚未接上的地方來源拆出幾種不同阻塞：

- 臺北疏散門：官方 host timeout，但來源頁與欄位線索存在。
- 苗栗：目前找到的是 HTML / 成果頁，缺公開 read API contract。
- 雲林：水位已接，淹水感測類有站點與時間，但缺水深測值。
- 屏東：PTEOC `/RainStation` 可讀 HTML，且不需登入，但缺觀測時間、站點 id、座標。
- 臺東：預警系統線索 timeout；FHY 地方淹水感測已接。
- 花蓮、金門：更完整系統仍屬登入、申請或授權型。
- 連江：目前只找到靜態資料，地方 live API 仍未找到，中央水文觀測也偏弱。

這些卡點不能都用「再爬一次」處理。若把 HTML、登入頁、設備上傳 API 或狀態欄位硬包成即時水情，會讓使用者誤以為系統已掌握鄰里真實淹水情況。

## 設計目標

1. 將地方來源阻塞分成可技術解、需資料契約、需人工授權/政策合作三類。
2. 對每類定義可升級 production adapter 的最低門檻。
3. 在無法立即接上的縣市，仍提供清楚的 coverage 說明與可追蹤下一步。
4. 不讓低可信訊號污染高可信淹水深度、水位與雨量證據。
5. 讓後續實作可以分批推進，而不是一次卡在所有縣市。

## 核心判準

Production 即時來源至少需要：

- `observed_at`：可判斷 freshness 的觀測時間。
- `station_or_device_id`：穩定測站、設備或資料列 ID。
- `measurement_value`：水位、水深、雨量或明確狀態測值。
- `measurement_unit_or_type`：單位與語意，例如公分、公尺、雨量窗格、閘門開閉。
- `longitude_latitude_or_joinable_station_metadata`：WGS84 座標，或可用官方 metadata join。
- `official_source_url_and_license`：官方來源、授權、維運單位與更新頻率線索。

不可升級 production 的情況：

- 只有 HTML 展示，缺觀測時間或座標。
- 只有新聞、成果頁、系統介紹頁。
- 只有設備清冊、抽水站/水門位置、易淹區靜態資料。
- 需要登入、captcha、帳密、key、token，但尚未取得授權。
- API 是設備上傳用途，不能確認有 read API。
- 只有 `alarmState` 但沒有水深時，不可偽造成淹水深度。

## 三類處理方式

### A. 可技術解

適用於 endpoint 或欄位已存在，但目前因 timeout、host 差異、欄位語意、parser 或 fallback 策略尚未完成而卡住。

處理策略：

- 建立 endpoint fallback 與 mirror host 檢查。
- 將 timeout、HTTP status、content type、資料 freshness 納入每日 smoke。
- 只在欄位語意確認後建立 adapter。
- 若資料是設施狀態，建立低權重 `infrastructure_status` 或等價事件，不混入水深。

候選：

| 縣市 | 來源 | 現況 | 解法 |
| --- | --- | --- | --- |
| 臺北市 | 疏散門即時監測 | 官方 API 線索存在，但 `wic.heo.taipei` live smoke timeout | 測試 `wic.gov.taipei` mirror、確認 `fo/fc/flt` 語意；若穩定，作為疏散門/水門狀態 adapter |
| 嘉義縣 | 管理型智慧防汛線索 | 查核頁 SSL `DH_KEY_TOO_SMALL`，但公開 RFD API 已 production | 不阻塞；只保留管理型 API 為後續授權候選 |

成功門檻：

- 連續多次 smoke 可讀。
- 有穩定觀測時間。
- 有穩定 ID 與座標或 metadata join。
- 事件類型語意不混淆，例如疏散門狀態不當作淹水深度。

### B. 需資料契約

適用於官方頁面或系統線索存在，但目前只有 HTML、新聞、成果頁、前台視覺化，沒有公開、穩定、可機器讀取的 read API contract。

處理策略：

- 不硬 scrape HTML 成 production evidence。
- 將候選維持在 `needs_api_contract` 或 `needs_observed_time`。
- 產生官方請求包，明確要求欄位、格式、授權、rate limit 與 metadata。
- smoke 工具持續監看頁面是否出現 JSON、CSV、ArcGIS REST、SensorThings 或 data.gov.tw 資源。

候選：

| 縣市 | 來源 | 現況 | 需要的契約 |
| --- | --- | --- | --- |
| 苗栗縣 | 雨水下水道即時水情監測成果 | 目前是 HTML / 成果說明 | 雨水下水道水位 read API、觀測時間、測站 ID、座標 metadata |
| 屏東縣 | PTEOC `/RainStation`、`/River`、`/Flood`、`/Crawler` | HTML 可讀，但 `/RainStation` 缺 observed_at、station id、座標 | 雨量/河川/淹水警戒 read API 或站點 metadata join |
| 臺東縣 | 洪水與淹水預警系統線索 | live smoke timeout，未找到 read API | 預警系統 read API contract、站點 metadata、欄位語意 |
| 連江縣 | 地方防災與開放資料 | 目前是靜態資料 | 即時水文觀測 read API，或加入 Civil IoT / WRA 公開主幹 |

成功門檻：

- 官方或委外平台提供可追溯 read API。
- response 可在不登入、不執行瀏覽器狀態的情況下取得。
- 欄位可滿足 production 必備欄位。
- 授權可公開說明，並可被 runbook 追蹤。

### C. 需人工授權 / 政策合作

適用於系統明確需要帳密、key、token、登入、縣府審核，或目前資料在第三方平台但未公開 read API。

處理策略：

- 不繞過登入或逆向私人 API。
- 生成授權請求包與欄位需求表。
- 在 coverage catalog 顯示 `needs_application`，並提供目前中央主幹可補足的訊號。
- 若取得授權，先在 staging / disabled-by-default adapter 驗證，不直接進 production。

候選：

| 縣市 | 來源 | 現況 | 人工介入 |
| --- | --- | --- | --- |
| 花蓮縣 | Senslink / 行動水情 | 更完整儀表板需登入或授權；FHY 淹水感測已接 | 需縣府或平台授權 read API |
| 金門縣 | KWIS | ASMX/WSDL 已列出 token-gated read methods，但空 Token smoke 回 `ErrMsg (7)`、`Data: []`；介接文件仍包含第三方設備上傳 API | 需申請正式 Token、可讀範圍、rate limit 與 response schema，未授權前不實作 production adapter |
| 連江縣 | 地方即時水文觀測 | 目前未找到 live API，也未在中央主幹有足夠水文觀測 | 需資料釋出或加入 Civil IoT / WRA |

成功門檻：

- 取得正式授權或公開資料釋出。
- API 用途明確是 read，不是設備上傳。
- 有 rate limit、授權條款與維運窗口。
- 可以保留 raw snapshot、run summary、rejection reason。

## 低可信訊號的處理設計

### Status-only evidence

雲林 iflood 淹水感測類目前有 `latestUpdateTime`、站點與座標，但缺水深測值。這類資料不應被丟掉，也不能偽造成水深。

建議新增一種低權重 evidence 類型：

- 名稱：`flood_sensor_status` 或 `infrastructure_status`
- 來源：有官方站點、時間與狀態，但無水深或水位數值。
- 顯示：可在 UI 呈現「官方站點狀態：警戒/正常/未知」。
- 評分：不進入水深分數；只作輔助脈絡或輕量加權。
- 風險說明：必須寫明「此來源未提供水深，因此不能代表實際積淹水深度」。

第一個適用案例：

- 雲林 iflood 淹水感測類的 `alarmState`。

不適用：

- 沒有觀測時間的 HTML。
- 只有站點清冊。
- 只有新聞或歷史災害說明。

## Coverage 呈現改進

目前使用者真正需要知道的不是「有沒有資料」，而是「查詢點附近有哪些種類的即時水情」。

建議每個縣市與查詢結果輸出：

- `rainfall_available`
- `water_level_available`
- `flood_depth_available`
- `sewer_water_level_available`
- `pump_or_gate_status_available`
- `status_only_available`
- `local_direct_complete`
- `central_backbone_available`
- `missing_signal_types`
- `blocking_reason`
- `next_action_code`

對使用者的文字應分級：

- 高可信：附近有水深、水位、雨水下水道或雨量即時觀測。
- 中可信：只有警戒、狀態或設施運作資料。
- 低覆蓋：只有 CWA / NCDR 或靜態資料，缺地方水文觀測。

連江這類地區要明示「缺地方即時水文觀測」，不能因為有 CWA 雨量或 NCDR CAP 就顯示為完整。

## 排程與監控設計

候選來源不應只靠人工偶爾重查。建議建立三個監控隊列：

1. **Technical retry queue**
   - 臺北疏散門、臺東 timeout。
   - 每日 smoke endpoint。
   - 若連續成功，標記為 `candidate_ready_for_adapter_design`。

2. **Contract discovery queue**
   - 苗栗、屏東、臺東、連江。
   - 掃 data.gov.tw export、地方資料平台、ArcGIS REST、SensorThings、公開 JSON/CSV/XML。
   - 若新 endpoint 滿足欄位門檻，轉入 adapter 設計。

3. **Authorization queue**
   - 花蓮、金門、連江。
   - 維護 request packet、申請狀態、窗口、授權結果。
   - 取得授權後先進 staging，不自動 production。

## 建議優先順序

### 第一優先：不用人工授權即可提高覆蓋

1. 臺北疏散門 mirror/fallback + 欄位語意確認。
2. 雲林 `status-only evidence` 設計。
3. Candidate smoke 每日排程與 action plan 輸出。

原因：這三項不需要等縣府回覆，且可以立即提升透明度或覆蓋說明。

### 第二優先：需官方 API contract

1. 屏東 PTEOC API / station metadata request。
2. 苗栗雨水下水道監測 read API request。
3. 臺東預警系統 read API request。

原因：這些已有官方系統線索，但目前無法安全 production。

### 第三優先：需授權或政策合作

1. 金門 KWIS token-gated read API methods 已確認；下一步為正式 Token 與 response schema 授權。
2. 花蓮 Senslink read API 授權確認。
3. 連江即時水文觀測釋出或納入中央主幹。

原因：這些需要人工流程，不應阻塞可技術解項目，但要開始追蹤。

## 文件與產品呈現

需要同步維護：

- `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`
- `docs/data-sources/local/2026-06-28-local-source-verification-log.md`
- `docs/data-sources/local/official-request-packets.md`
- Admin API 的 local source coverage / action plan

Public API 與前端應避免二元說法：

- 不說「此縣市沒有資料」。
- 不說「此縣市即時水情完整」。
- 改說「目前有 CWA 雨量、NCDR 警戒、FHY 淹水感測，但缺地方雨水下水道水位」。

## 非目標

本設計不做以下事項：

- 不繞過登入、captcha、授權或 token。
- 不用 browser session scrape 私有 dashboard。
- 不把 HTML 頁面 fetched time 當作 observed_at。
- 不把 `alarmState` 當作水深。
- 不把中央彙整資料誤標為地方政府直出 API。
- 不在本文件階段改任何 production adapter 行為。

## 後續可拆成的實作計畫

若本設計通過，可拆為三個獨立 implementation plan：

1. **技術可解來源升級計畫**
   - 臺北疏散門 fallback / health check / adapter 設計。
   - timeout 類候選來源 retry policy。

2. **Status-only evidence 計畫**
   - 定義低權重狀態 evidence。
   - 雲林 iflood 淹水感測狀態作第一個案例。
   - API/UI 顯示「有狀態、無水深」。

3. **資料契約與授權工作流計畫**
   - 產生苗栗、屏東、臺東、花蓮、金門、連江 request packets。
   - 增加 action plan 欄位：窗口、申請狀態、最後追蹤時間、所需欄位。
   - smoke / discovery monitor 轉換規則。

## 驗收標準

本設計若進入實作，完成後應能驗收：

- 每個卡點都有唯一 `blocking_reason`，不再只寫「未完成」。
- 可技術解來源有 retry/fallback/health check 結果。
- 需契約來源有正式 request packet。
- 需授權來源不會被 production ingestion 使用。
- 使用者查詢時可看見缺哪些即時訊號，而不是只看見籠統的「即時水情」。
- 低可信狀態資料可被呈現，但不會污染水深、水位、雨量高可信分數。
