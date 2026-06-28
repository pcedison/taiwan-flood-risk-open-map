# 台灣地方即時水情補強層設計

日期：2026-06-27
狀態：初版；正在依 22 縣市盤點與 subagent 查核結果擴充

## 目的

Flood Risk 的即時水情不能只停在中央全台主幹，也不能只用台南作為
地方來源代表。地方政府常掌握更靠近道路、雨水下水道、抽水站、地下道
與鄰里低窪點的即時或近即時資料。本設計把地方政府資料作為中央主幹
之外的補強層，逐步補齊 22 縣市。

## 核心修正

先前「全台主幹」只完成中央來源層與台南 POC。這不足以滿足「全台各
縣市、鄉鎮市區、村里/鄰里」的地方即時水情需求。本輪工作必須同時追蹤：

- 中央全台主幹是否健康：Civil IoT、WRA、CWA、NCDR。
- 22 縣市地方來源是否存在、是否可機器讀取、是否需要申請、是否 fresh。
- 每個查詢點附近能取得哪些站點、距離多遠、觀測時間多新、是否 stale。

## 分層

### L1：中央全台主幹

維持既有 worker-first 架構：

- `official.civil_iot.flood_sensor`
- `official.civil_iot.river_water_level`
- `official.civil_iot.pond_water_level`
- `official.civil_iot.sewer_water_level`
- `official.civil_iot.pump_water_level`
- `official.wra.water_level`
- `official.cwa.rainfall`
- `official.ncdr.cap`
- `official.flood_potential.geojson`

這一層是全台一致的 baseline。地方來源不得降低、覆蓋或移除 L1 證據。

### L2：地方政府即時補強層

地方來源分成兩種，不可混稱：

1. **地方政府直出 API**：由縣市資料平台、水利局或地方水情系統直接公開。
   這類來源以 `local.<county>.<signal>` adapter key 命名。
2. **中央彙整的地方感測器**：由縣市與中央合建或地方提供，但透過 Civil
   IoT/WRA 等中央 API 公開。這類資料仍使用 `official.civil_iot.*` 或
   `official.wra.*` adapter key，並用 metadata 標出 authority/county。

地方政府直出來源以 `local.<county>.<signal>` adapter key 命名，例如：

- `local.taipei.sewer_water_level`
- `local.taipei.river_water_level`
- `local.taipei.pump_station`
- `local.taoyuan.flood_sensor`
- `local.taoyuan.water_level`
- `local.chiayi_city.water_level`
- `local.tainan.flood_sensor`

地方來源的用途是提升空間相關性、補足中央站點稀疏處、以及交叉驗證
中央資料，不是把地方資料當成新的 canonical source。

若某縣市只有 Civil IoT 中的地方合建感測器，而沒有地方政府直出 API，
矩陣應標示為 `central_aggregated_ready`，不能標示為地方來源已完成。

### L3：地方靜態/規劃參考層

抽水站清冊、水門、低窪地區、易淹水地區、地下道清冊、雨水下水道管線
等資料可作為 context 或 future geocoder/profile input，但不可當作即時
水情觀測。

## 第一批實作範圍

第一批只實作已經 live smoke 通過、欄位足以正規化的來源：

1. 臺北市雨水下水道水位 JSON。
2. 臺北市河川水位 JSON。
3. 臺北市抽水站內外水位與運轉狀態 JSON。
4. 桃園市路面淹水感測 XML。
5. 桃園市水位站 XML。
6. 嘉義市水位站水位 CSV。
7. 既有台南淹水感測器 adapter 的 coverage metadata 對齊。

並行補強中央 Civil IoT county coverage metadata：

- 新北市、基隆市、新竹市、新竹縣、苗栗縣等縣市已有 Civil IoT
  `water_12` 淹水感測器覆蓋，但這屬於中央彙整路徑，不是地方直出 API。
- 宜蘭縣、花蓮縣、臺東縣等東部縣市可先由 Civil IoT `water_12` 與
  `STA_RainSewer` 補足淹水深度與雨水下水道水位，但仍要標示地方直出 API
  尚未找到。
- WRA IoW 淹水深度最新資料與基本資料可作為 Civil IoT 淹水感測器的
  official join/cross-check path，尤其在縣市直出 API 缺乏時補齊 `countyname`、
  `townname` 與座標。
- Civil IoT adapter 應保留 authority、station code、county hint 與 source
  URL，讓 API 能向使用者解釋「由 Civil IoT 取得的地方合建感測器」。

桃園與嘉義市雨量可列為第二批 rainfall supplement，因為 CWA 已是全台
canonical rainfall source，地方雨量需先定義時間窗與去重規則。

## 22 縣市矩陣

來源盤點與 smoke 狀態維護於：

`docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`

該矩陣是 implementation planning 的輸入。狀態為 `not_found` 或
`metadata_only` 的縣市仍需保留在矩陣中，不能從工作範圍消失。

## 資料取得與認證

- CWA 需要 `CWA_API_AUTHORIZATION`；使用者已提供，不再是阻塞點。
- 本輪已實測的臺北、桃園、嘉義市、臺南地方來源不需要額外人工申請。
- 臺北市 API URL 內含官方資料頁公開的 `loginId` 與 `dataKey`，視為公開
  endpoint 參數；仍需在 production 前保留來源頁與授權紀錄。
- 若後續查到需申請的地方 API，必須在矩陣中標示 `requires_application`，
  並且 adapter 預設關閉。

## 正規化規則

- 淹水深度使用 `event_type=flood_report`，metric 為 `flood_depth_cm`。
- 水位使用 `event_type=water_level`，metric 優先為 `water_level_m`，
  並保留 `warning_level_m`、`inner_water_level_m`、`outer_water_level_m`
  等 metadata。
- 雨量使用 `event_type=rainfall`，但地方雨量只能補強 CWA，不能取代 CWA。
- 抽水站若只有位置與設備資訊，屬 `metadata_only`；若有內外水位與觀測時間，
  可輸出 `water_level` evidence，並以 raw metadata 保存泵浦與閘門狀態。

## 安全閘與去重

每個地方 live adapter 必須：

- 預設關閉。
- 有 source gate 與 API gate。
- 不可被 `WORKER_ENABLED_ADAPTER_KEYS` 單獨繞過。
- 有來源專屬 timeout。
- 有 station-level freshness validation。
- 缺座標且無法 join 官方 metadata 時只保留 raw/rejection，不 normalized。
- 與 L1 同站、近座標、同時間、同 metric 的資料必須去重或降低權重。

Civil IoT 端點健康保護：

- 預設 base URL 應優先使用 `https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/`；
  舊 `https://sta.ci.taiwan.gov.tw/STA_WaterResource_v2/v1.0/` 只可作 explicit
  override 或短期 fallback。
- `STA_RainSewer` 應使用 `https://sta.colife.org.tw/STA_RainSewer/v1.0/`。
- Source health diagnostics 必須揭露 endpoint URL、last success、last failure、
  pagination completeness 與 observation freshness。
- 若官方公告服務於 2026-12-01 前後移轉，runbook 必須能在不改 code 的情況下
  以 env override 切換 endpoint。

## API 呈現

Public API 應能在每次查詢中呈現：

- 哪些中央主幹來源健康、stale、disabled 或 failed。
- 查詢點附近有哪些地方來源。
- 地方來源與查詢點距離、觀測時間、資料 freshness。
- 若某縣市沒有地方公開 API，明確揭露依中央主幹與鄰近站點判斷，不把
  資料缺口說成低風險。

## 測試策略

- 先以 fixture 寫 parser tests，確認 CSV/XML/JSON 來源能被正規化。
- 每個 adapter 都要測 default-off、gate 不能被 allowlist 繞過、缺座標拒絕、
  stale observation 拒絕或降級。
- 第一批地方 adapter 完成後必跑：
  - `apps/workers` pytest。
  - `apps/api` pytest 中官方 realtime/admin/data freshness 相關 tests。
  - migrations validation。
- 新增地方 adapter 不得改變中央主幹預設啟用與現有官方 adapter metadata。
