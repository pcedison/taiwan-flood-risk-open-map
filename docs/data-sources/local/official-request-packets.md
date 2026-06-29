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

- 連江縣：即時水文觀測資料釋出或納入 Civil IoT / WRA 主幹。
- 金門縣：KWIS read API 授權。
- 花蓮縣：Senslink / 行動水情 read API 授權。
- 臺北市、雲林縣：live smoke / status-only 欄位語意複核。
- 臺東縣、苗栗縣、屏東縣：public read API contract 與站點 metadata。
- 嘉義市、桃園市、澎湖縣、臺中市、臺南市、南投縣、基隆市、宜蘭縣、
  新北市、新竹縣：既有 production adapter 之外的水資訊訊號缺口補齊。

各類請求包都會列出 production read API 必備欄位；signal-gap 請求包會明確
要求不要把 `status-only` 資料當成水位、雨量、淹水深度或下水道水位量測。

2026-06-29 版 action plan 已產生的正式請求包涵蓋：

- 花蓮縣：Senslink / 行動水情 read API 授權。
- 金門縣：KWIS read API 授權。
- 連江縣：即時水文觀測資料釋出或納入 Civil IoT / WRA 主幹。
- 苗栗縣：雨水下水道即時水情 read API contract。
- 屏東縣：PTEOC RainStation / River / Flood / Crawler read API contract 與站點 metadata。
- 臺東縣：洪水與淹水預警系統 read API contract。

舊版未將臺北疏散門、雲林 iflood 淹水感測狀態或已上線縣市的 signal-gap
reviews 輸出成請求包；新版已納入，但仍維持欄位語意隔離，避免把可技術解項目、
授權/契約請求與 `status-only` 診斷線索混為正式量測值。

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

整合優先序：`#2 / P0 / request_official_authorization`。目前公開文件的
API contract 風險標記為 `known_public_docs_are_upload_or_application_focused`：
`device_upload_api` 與 `third_party_upload_integration` 不足以支撐 production
read adapter；仍需確認是否有 `latest_observation_read_api` 可查詢最新觀測值。
正式回覆需包含 `observed_at`、`station_or_device_id`、`measurement_value`、
`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`
與官方來源/授權資訊。

已查核來源：

- 金門水情系統入口：`https://kwis.kinmen.gov.tw/`
- KWIS ASMX / WSDL：`https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx`
- 介接申請 PDF：`https://kwis.kinmen.gov.tw/KWIS/Doc/%E9%87%91%E9%96%80%E7%B8%A3%E6%94%BF%E5%BA%9C%E7%AC%AC%E4%B8%89%E6%96%B9%E5%96%AE%E4%BD%8D%E8%B3%87%E6%96%99%E4%B8%8A%E5%82%B3%5B%E9%87%91%E9%96%80%E6%B0%B4%E6%83%85%E7%B3%BB%E7%B5%B1%5D%E4%B9%8BAPI%E4%BB%8B%E6%8E%A5%E7%94%B3%E8%AB%8B%E5%8F%8A%E4%BD%BF%E7%94%A8%E8%AA%AA%E6%98%8E.pdf`

目前阻塞：

- 公開文件顯示需要帳密、key 或 token。
- 已知公開介接用途偏第三方設備資料上傳，不足以確認有最新觀測 read API。
- 未取得縣府授權前，不應把 KWIS 實作成 production local adapter。

請求重點：

- 請金門縣政府確認是否可提供「最新即時水情查詢 read API」，不是設備上傳 API。
- 若可提供，請提供正式 API contract、申請方式、授權條款、rate limit、測站清冊與
  範例 response。
- 需要的資料類型優先序：淹水感測器、雨水下水道水位、水位站、抽水站內外水位、
  水門或閘門外水位。

目前可替代但不可算地方直連的中央主幹：

- Civil IoT `official.civil_iot.flood_sensor`：2026-06-28 live smoke 金門 7 站。
- Civil IoT `official.civil_iot.sewer_water_level`：2026-06-28 live smoke 金門 29 站。

## 連江縣：即時水文觀測資料釋出請求

目前狀態：`metadata_only` + `not_found`，地方直連尚未完成；中央主幹也缺
`hydrologic_observation`。

整合優先序：`#1 / P0 / restore_hydrologic_backbone`。此請求包直接對應
`integration_priority_queue[0]`，完成門檻是取得至少一個可公開追溯的水位、
淹水深度、雨水下水道、抽水站或水門即時 read API，且欄位需包含
`observed_at`、`station_or_device_id`、`measurement_value`、
`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`
與官方來源/授權資訊。

已查核來源：

- 連江縣開放資料查詢：`https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5`
- 連江縣大潮、豪雨易淹水地區 ODS：`https://www.matsu.gov.tw/upload/f-20230922134042.ods`
- data.gov.tw dataset `165820`
- Civil IoT `STA_RainSewer`、`STA_WaterResource_v2`
- WRA IoW、WRA 即時水位、NCDR CAP、CWA 雨量

目前阻塞：

- 地方公開資料只找到靜態易淹區 metadata，沒有即時觀測時間、站點 ID、測值或座標。
- 2026-06-28 查核：Civil IoT 雨水下水道、水資源、WRA IoW、WRA 即時水位均無連江
  水文觀測站點。
- CWA 雨量與 NCDR CAP 可提供雨量或事件脈絡，但不能替代水位、淹水深度、雨水下水道、
  抽水站或水門觀測。

請求重點：

- 請連江縣政府釋出可機器讀取的即時水文觀測 read API，或確認是否可加入 Civil IoT /
  WRA 公開 SensorThings 主幹。
- 需要的資料類型優先序：南竿、北竿、莒光、東引等地區的雨水下水道水位、道路淹水
  感測器、抽水站或水門水位、易淹區鄰近水位站。
- 若短期無感測器，請提供官方站點建置計畫或資料釋出時程，讓 coverage catalog 從
  `not_found` 改為可追蹤的 `candidate`。
