# 地方即時水情官方請求包

日期：2026-06-29

用途：追蹤目前 22 縣市地方即時水情尚未完成 production local adapter，或雖已有
局部 local adapter 但仍缺更完整 read API contract / 授權的官方請求。此文件只處理
地方政府直出或授權 read API；中央全台主幹 Civil IoT、WRA、CWA、NCDR 仍由既有
official adapters 維持。

資料釋出監看可重跑：

```bash
PYTHONPATH=apps/workers python scripts/local-source-discovery-monitor.py
```

此工具會掃 data.gov.tw 全站匯出，只針對金門縣與連江縣的水情關鍵字輸出
`candidate_live_read_api` 或 `metadata_only`。它不會自動把候選來源升級為
production adapter；候選仍需人工檢查 API contract、freshness、座標與授權。
輸出的 `summary.by_county` 會將每個監看縣市標成 `live_candidate_found`、
`metadata_only` 或 `no_candidate`，並提供
`candidate_live_read_api_count_by_county`、`metadata_only_count_by_county` 與
`target_counties_without_candidates`，可直接用於連江縣資料釋出監看與排程告警。

官方請求包也可由 action plan 重建：

```bash
python scripts/local-source-request-packets.py --format markdown
python scripts/local-source-request-packets.py --format json
python scripts/local-source-request-packets.py --format markdown --output docs/data-sources/local/generated-official-request-packets.md
python scripts/local-source-request-packets.py --format json --output docs/data-sources/local/generated-official-request-packets.json
```

目前已產生的流轉檔：

- `docs/data-sources/local/generated-official-request-packets.md`
- `docs/data-sources/local/generated-official-request-packets.json`

2026-06-30 action plan 產生的正式請求包已改用 `integration_priority_queue`
排序，涵蓋四類缺口：

- 連江縣：地方即時水情資料釋出；中央最低水文骨幹已由 CWA 潮位補足。
- 金門縣：KWIS read API 授權。
- 花蓮縣：Senslink / 行動水情 read API 授權。
- 臺北市：疏散門 live smoke / 欄位語意複核。
- 臺東縣、苗栗縣、屏東縣：public read API contract 與站點 metadata；臺東縣府
  防汛新聞/審計部頁可證明洪水與淹水預警系統、淹水感測、水位站、雨量站、
  即時影像，以及 CWA 49 雨量站 / WRA 9 水位站 integration，但未公開
  latest-observation read API 或 station metadata contract；苗栗官方
  成果頁已證實 10 個鄉鎮市都市計畫區設置 58 處雨水下水道水位監測站，且有
  每月維護/月報，但公開頁只有 HTML 文章與 JPG 會議圖片，缺
  `observed_at`、站點 ID、測值、單位與可 join WGS84 metadata；屏東 PTEOC
  已補上 2026-06-30 查核事實，`/RainStation` 缺 `observed_at` 與可 join
  座標 metadata，`/Flood` 為雨量警戒門檻，`/Crawler` 為 CCTV 影像，不可當
  淹水深度或水位量測。
- 嘉義市、桃園市、澎湖縣、臺中市、臺南市、南投縣、基隆市、宜蘭縣、
  新北市、新竹縣、雲林縣：既有 production adapter 之外的水資訊訊號缺口補齊；
  雲林 iflood `alarmState` 已保留為 status-only 診斷線索，不作淹水深度。臺南市
  signal-gap request 也已列出區域排水水位站、抽水站、水門靜態 metadata，以及
  即時影像 `ImageUrl` / 合建淹水端點 `data:null` 的 non-qualifying 理由。

各類請求包都會列出 production read API 必備欄位；signal-gap 請求包會明確
要求不要把 `status-only` 資料當成水位、雨量、淹水深度或下水道水位量測。
候選系統若只有 HTML、警戒狀態或影像，也會列出缺少欄位與不可當量測的理由；
未取得官方 read API 或可 join station metadata 前，不得以 `fetched_at` 偽裝
`observed_at`。

2026-06-29 版 action plan 已產生的正式請求包涵蓋：

- 花蓮縣：Senslink / 行動水情 read API 授權。
- 金門縣：KWIS read API 授權。
- 連江縣：地方即時水情資料釋出；中央最低水文骨幹已由 CWA 潮位補足。
- 苗栗縣：雨水下水道即時水情 read API contract；現有成果頁只可證明監測站
  與維護/月報制度存在，不能作 latest-observation read API。
- 屏東縣：PTEOC RainStation / River / Flood / Crawler read API contract 與站點 metadata。
- 臺東縣：洪水與淹水預警系統 read API contract；縣府新聞/審計摘要只能證明
  系統與 CWA/WRA 站點介接脈絡，仍缺公開觀測時間、站點 ID、測值、單位與
  可 join WGS84 metadata。

舊版未將臺北疏散門、雲林 iflood 淹水感測狀態或已上線縣市的 signal-gap
reviews 輸出成請求包；新版已納入，且雲林已從 live-smoke retry 轉入
signal-gap/status-only 追蹤，避免把 `status-only` 診斷線索混為正式量測值。

## Production read API 必備欄位

地方來源若要進 production adapter，至少需要：

1. `observed_at`：觀測時間，需能判斷 freshness。
2. `station_or_device_id`：穩定測站或設備 ID。
3. `measurement_value`：水位、水深、雨量或狀態測值。
4. `measurement_unit_or_type`：單位或量測類型，例如公分、公尺、雨量窗格。
5. `longitude_latitude_or_joinable_station_metadata`：WGS84 座標，或可用官方站點
   metadata join 出座標。
6. `official_source_url_and_license`：官方來源 URL、使用授權、更新頻率或維運單位。

## 金門縣：KWIS read API 授權請求

目前狀態：`needs_application`，地方直連尚未完成。

整合優先序：`#2 / P0 / request_official_authorization`。目前公開服務的
API contract 風險標記為 `token_gated_read_methods_require_authorization`：
KWIS ASMX/WSDL 已列出 token-gated read methods，但空 Token smoke 只回
`ErrMsg (7)` 與 `Data: []`；`device_upload_api` 與 `third_party_upload_integration`
仍不足以支撐 production read adapter，需正式核發 `latest_observation_read_api`
的 Token 與使用範圍。
正式回覆需包含 `observed_at`、`station_or_device_id`、`measurement_value`、
`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`
與官方來源/授權資訊。

已查核來源：

- 金門水情系統入口：`https://kwis.kinmen.gov.tw/`
- KWIS ASMX / WSDL：`https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx`
- KWIS WSDL：`https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?WSDL`
- KWIS read methods：`KWIS_Get_Rain_Gauge_Basic_Unit_Data`、`KWIS_Get_Water_Level_Gauge_Basic_Unit_Data`、`KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data`、`KWIS_Get_Pump_Basic_Unit_Data`、`KWIS_Get_Monitoring_Station_Sensor_Device_List`
- 介接申請 PDF：`https://kwis.kinmen.gov.tw/KWIS/Doc/%E9%87%91%E9%96%80%E7%B8%A3%E6%94%BF%E5%BA%9C%E7%AC%AC%E4%B8%89%E6%96%B9%E5%96%AE%E4%BD%8D%E8%B3%87%E6%96%99%E4%B8%8A%E5%82%B3%5B%E9%87%91%E9%96%80%E6%B0%B4%E6%83%85%E7%B3%BB%E7%B5%B1%5D%E4%B9%8BAPI%E4%BB%8B%E6%8E%A5%E7%94%B3%E8%AB%8B%E5%8F%8A%E4%BD%BF%E7%94%A8%E8%AA%AA%E6%98%8E.pdf`

目前阻塞：

- 公開文件顯示需要帳密、key 或 token。
- 已知公開介接文件仍含第三方設備資料上傳，但 WSDL 已確認讀取方法存在；缺正式 Token、可讀範圍、rate limit 與 response schema。
- 未取得縣府授權前，不應把 KWIS 實作成 production local adapter。

請求重點：

- 請金門縣政府核發 read-side Token，並確認上述 KWIS read methods 的 production 使用範圍，不把設備上傳 API 當作查詢 API。
- 請提供正式 API contract、申請方式、授權條款、rate limit、測站清冊與範例 response。
- 需要的資料類型優先序：淹水感測器、雨水下水道水位、水位站、抽水站內外水位、
  水門或閘門外水位。

目前可替代但不可算地方直連的中央主幹：

- Civil IoT `official.civil_iot.flood_sensor`：2026-06-28 live smoke 金門 7 站。
- Civil IoT `official.civil_iot.sewer_water_level`：2026-06-28 live smoke 金門 29 站。

## 連江縣：地方即時水情資料釋出請求

目前狀態：`metadata_only` + `not_found`，地方直連尚未完成；中央最低水文
骨幹已由 CWA `official.cwa.tide_level` 補足。

整合優先序：`#1 / P0 / monitor_open_data_release`。此請求包直接對應
`integration_priority_queue[0]`，完成門檻是完成地方直出 production adapter，
或留下含 required read API fields 的官方釋出請求並可追蹤 follow-up 狀態。
目前地方直連仍缺 `flood_depth`、`sewer_water_level`、`pump_or_gate_status`。

已查核來源：

- 連江縣開放資料查詢：`https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5`
- 連江縣大潮、豪雨易淹水地區 ODS：`https://www.matsu.gov.tw/upload/f-20230922134042.ods`
- data.gov.tw dataset `165820`
- CWA 潮位觀測 `O-B0075-001` 與測站 metadata `O-B0076-001`，其中馬祖潮位站可提供
  沿海水位脈絡。
- Civil IoT `STA_RainSewer`、`STA_WaterResource_v2`
- WRA IoW、WRA 即時水位、NCDR CAP、CWA 雨量

目前阻塞：

- 地方公開資料只找到靜態易淹區 metadata，沒有即時觀測時間、站點 ID、測值或座標。
- 2026-06-28 查核：Civil IoT 雨水下水道、水資源、WRA IoW、WRA 即時水位均無連江
  水文觀測站點。
- CWA 潮位可提供沿海水位脈絡並補足中央最低 backbone，但不能替代地方道路淹水、
  雨水下水道、抽水站或水門量測。
- 連江自來水廠水庫水位月報與 `erbwater` 放流水 CEMS 已列為 `non_qualifying`，
  不列 production adapter。

請求重點：

- 請連江縣政府釋出可機器讀取的地方即時水情 read API。
- 需要的資料類型優先序：南竿、北竿、莒光、東引等地區的雨水下水道水位、道路淹水
  感測器、抽水站或水門水位、易淹區鄰近水位站。
- 若短期無感測器，請提供官方站點建置計畫或資料釋出時程，讓 coverage catalog 從
  `not_found` 改為可追蹤的 `candidate`。
