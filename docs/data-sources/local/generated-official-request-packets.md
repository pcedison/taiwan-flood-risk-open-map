# 地方即時水情官方請求包

此文件由 local-source action plan 產生，用於追蹤尚需人工授權或官方資料釋出的地方即時水情缺口。

## 連江縣：連江縣地方即時水情資料釋出請求

- 類型：metadata_release_request
- 需要人工介入：是
- 追蹤對象：連江縣政府公開資料或防災水利窗口
- 追蹤狀態：monitoring_open_data_release
- 整合優先序：#1 / P0 / monitor_open_data_release
- 來源：
  - https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5
  - https://www.matsu.gov.tw/upload/f-20230922134042.ods
- 靜態 metadata 線索：連江縣大潮、豪雨易淹水地區 ODS
- 靜態 metadata URL：
  - https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5
  - https://www.matsu.gov.tw/upload/f-20230922134042.ods
- 已排除官方線索：連江自來水廠水庫水位月報、連江縣資訊公開查詢系統即時監測值
- 已排除官方線索 URL：
  - https://www.matsuwater.gov.tw/load_page/reservoir_water_level_page
  - http://erbwater.matsu.gov.tw/PUBLIC/RealTime/Get_AVGR.aspx
- 排除原因：
  - 公開水庫水位為月報 PDF，沒有 observed_at/station_id/measurement_value 的即時 read API。
  - 公開即時監測頁為放流水環保 CEMS，不是淹水、水位、雨水下水道、抽水站或水門觀測。
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補地方直連訊號：flood_depth、sewer_water_level、pump_or_gate_status
- 排入此順位原因：local_direct_source is not complete
- 完成門檻：完成地方直出 production adapter，或留下含 required_read_api_fields 的官方授權/釋出請求並可追蹤 follow-up 狀態。

目前連江縣已由中央主幹補足最低水文脈絡，但地方公開資料仍只有靜態或 metadata 類資料。請協助釋出南竿、北竿、莒光、東引的雨水下水道水位、道路淹水感測器、抽水站或水門水位、易淹區鄰近水位站等地方直連 read API。 已查核但排除的官方線索：公開水庫水位為月報 PDF，沒有 observed_at/station_id/measurement_value 的即時 read API；公開即時監測頁為放流水環保 CEMS，不是淹水、水位、雨水下水道、抽水站或水門觀測。目前中央最低水文骨幹已補足；仍需補足地方直連訊號：flood_depth、sewer_water_level、pump_or_gate_status。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認是否可提供地方最新觀測 read API
- [ ] 取得站點 ID、觀測時間、測值、單位與座標
- [ ] 確認短期無感測器時的建置計畫或資料釋出時程
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 金門縣：金門縣 KWIS 即時水情 read API 授權請求

- 類型：authorization_request
- 需要人工介入：是
- 追蹤對象：金門縣政府 / KWIS 維運窗口
- 追蹤狀態：needs_authorization_request
- 整合優先序：#2 / P0 / request_official_authorization
- API contract 風險：token_gated_read_methods_require_authorization
- 不足用途：credentialed_read_api_without_authorized_token、device_upload_api、third_party_upload_integration
- 必要 API 用途：latest_observation_read_api
- 需釐清事項：公開文件仍包含第三方設備 upload-only 介接流程，公開服務另已列出 token-gated read API methods，但空 Token smoke 只回 Data: []；production adapter 仍需縣府核發正式 Token、可讀範圍、rate limit 與 response schema。
- Credential requirements: KWIS_key, account, password, Token
- Known token-gated read methods: KWIS_Get_Rain_Gauge_Basic_Unit_Data, KWIS_Get_Water_Level_Gauge_Basic_Unit_Data, KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data, KWIS_Get_Pump_Basic_Unit_Data, KWIS_Get_Monitoring_Station_Sensor_Device_List
- Known read endpoint references:
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?WSDL
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Rain_Gauge_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Water_Level_Gauge_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Pump_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Monitoring_Station_Sensor_Device_List
- Unauthorized smoke result: Blank-token GET smoke against KWIS_Get_Pump_Basic_Unit_Data, KWIS_Get_Water_Level_Gauge_Basic_Unit_Data, and KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data returned ErrMsg (7) invalid Token with Data: [].
- 來源：
  - https://kwis.kinmen.gov.tw/
  - https://docs.google.com/forms/d/e/1FAIpQLSdjBEvTNQyORMrkNdsJfs4KV5RUulRZF4hp2V3QhF5rGLUJYA/viewform
  - https://kwis.kinmen.gov.tw/KWIS/Doc/%E9%87%91%E9%96%80%E7%B8%A3%E6%94%BF%E5%BA%9C%E7%AC%AC%E4%B8%89%E6%96%B9%E5%96%AE%E4%BD%8D%E8%B3%87%E6%96%99%E4%B8%8A%E5%82%B3%5B%E9%87%91%E9%96%80%E6%B0%B4%E6%83%85%E7%B3%BB%E7%B5%B1%5D%E4%B9%8BAPI%E4%BB%8B%E6%8E%A5%E7%94%B3%E8%AB%8B%E5%8F%8A%E4%BD%BF%E7%94%A8%E8%AA%AA%E6%98%8E.pdf
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?WSDL
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Rain_Gauge_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Water_Level_Gauge_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Pump_Basic_Unit_Data
  - https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?op=KWIS_Get_Monitoring_Station_Sensor_Device_List
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 排入此順位原因：local_direct_source is not complete；official authorization is required before a production read API can run
- 完成門檻：完成地方直出 production adapter，或留下含 required_read_api_fields 的官方授權/釋出請求並可追蹤 follow-up 狀態。

目前金門縣地方直連即時水情來源仍需要官方授權。請確認 KWIS 既有 read API methods 的正式 Token、可讀範圍與 production 使用條款；不要將設備上傳 API 當作查詢 API。請協助提供正式 API contract、申請方式、授權條款、rate limit、測站清冊、座標 metadata 與範例 response。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認是否可提供最新觀測 read API
- [ ] 確認 API contract、授權條款與 rate limit
- [ ] 取得測站清冊、座標 metadata 與範例 response
- [ ] 確認資料欄位可滿足 production adapter 必備欄位
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求

- 類型：authorization_request
- 需要人工介入：是
- 追蹤對象：花蓮縣政府 / Senslink 行動水情維運窗口
- 追蹤狀態：needs_authorization_request
- 整合優先序：#3 / P1 / request_official_authorization
- 來源：
  - https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index
  - https://www.hl.gov.tw/News_Content.aspx?n=32725&s=116294
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 排入此順位原因：official authorization is required before a production read API can run
- 完成門檻：取得官方授權或公開 read API contract，確認用途不是設備上傳 API。

目前花蓮縣地方直連即時水情來源仍需要官方授權。請確認 Senslink/行動水情 是否可提供最新觀測 read API，不是設備上傳 API。若可提供，請協助提供正式 API contract、申請方式、授權條款、rate limit、測站清冊、座標 metadata 與範例 response。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認是否可提供最新觀測 read API
- [ ] 確認 API contract、授權條款與 rate limit
- [ ] 取得測站清冊、座標 metadata 與範例 response
- [ ] 確認資料欄位可滿足 production adapter 必備欄位
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 臺東縣：臺東縣地方即時水情 read API contract 請求

- 類型：public_api_contract_request
- 需要人工介入：是
- 追蹤對象：臺東縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_public_read_api_contract
- 整合優先序：#4 / P2 / verify_public_read_api_contract
- 來源：
  - https://www.taitung.gov.tw/News_Content.aspx?n=13370&s=131527&sms=12652
  - https://www.audit.gov.tw/p/406-1000-9612%2Cr12.php?Lang=zh-tw
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 候選系統缺少欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`
- 候選系統查核事實：
  - 2026-06-30 curl smoke: Taitung County Government news page is a public HTML flood-control article citing WRA Eighth River Management Office; it says flood hotspots use a water-monitoring system with flood sensors, water-level stations, rain gauges, and realtime cameras, but exposes no public read API, observation rows, or station metadata file.
  - 2026-06-30 official audit review: Audit Office page says Taitung County Government built a flood and inundation warning system and later integrated 49 CWA rainfall stations plus 9 WRA water-level stations; this confirms system context but not a local-government latest-observation read API contract.
- 候選系統不可當量測來源：
  - 2026-06-30 review: the Taitung evidence is a news article/audit summary, not a latest-observation read API; realtime camera references are image-only context, and central CWA/WRA station integration does not satisfy local pump_or_gate_status production ingestion.
- 排入此順位原因：candidate source needs a public read API contract review
- 完成門檻：公開 read API contract 補齊 observed_at、station id、measurement_value、單位與座標 metadata。

目前臺東縣已有官方系統或成果頁線索，但尚未找到可公開機器讀取的最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、站點 metadata 與範例 response。 已查核頁面事實：2026-06-30 curl smoke: Taitung County Government news page is a public HTML flood-control article citing WRA Eighth River Management Office; it says flood hotspots use a water-monitoring system with flood sensors, water-level stations, rain gauges, and realtime cameras, but exposes no public read API, observation rows, or station metadata file.；2026-06-30 official audit review: Audit Office page says Taitung County Government built a flood and inundation warning system and later integrated 49 CWA rainfall stations plus 9 WRA water-level stations; this confirms system context but not a local-government latest-observation read API contract. 目前缺少 production 必備欄位：observed_at、station_or_device_id、measurement_value、measurement_unit_or_type、longitude_latitude_or_joinable_station_metadata 不可當量測來源：2026-06-30 review: the Taitung evidence is a news article/audit summary, not a latest-observation read API; realtime camera references are image-only context, and central CWA/WRA station integration does not satisfy local pump_or_gate_status production ingestion.；在取得官方 read API 或可 join metadata 前，不得以 fetched_at 偽裝觀測時間。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認公開 read API URL 與 response 格式
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認授權條款、rate limit 與維運窗口
- [ ] 取得可重跑 live smoke 的範例 response
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 苗栗縣：苗栗縣地方即時水情 read API contract 請求

- 類型：public_api_contract_request
- 需要人工介入：是
- 追蹤對象：苗栗縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_public_read_api_contract
- 整合優先序：#5 / P2 / verify_public_read_api_contract
- 來源：
  - https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx?n=563&s=922337&sms=9560
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 候選系統缺少欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`
- 候選系統查核事實：
  - 2026-06-30 curl smoke: official Miaoli page is a public HTML results-review article for the 114年度雨水下水道即時水情監測系統建置計畫; it states 58 water-level monitoring stations across 10 town/city urban-planning areas.
  - 2026-06-30 curl smoke: the 114年度雨水下水道即時水情監測系統建置計畫 article says water gauges receive monthly maintenance and monthly reports track uptime, abnormalities, and improvements, but it exposes no latest-observation read API or station metadata file.
- 候選系統不可當量測來源：
  - 2026-06-30 curl smoke: the public page exposes only an HTML article/JPGs; it is not a sewer_water_level read API and cannot satisfy pump_or_gate_status.
- 排入此順位原因：candidate source needs a public read API contract review
- 完成門檻：公開 read API contract 補齊 observed_at、station id、measurement_value、單位與座標 metadata。

目前苗栗縣已有官方系統或成果頁線索，但尚未找到可公開機器讀取的最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、站點 metadata 與範例 response。 已查核頁面事實：2026-06-30 curl smoke: official Miaoli page is a public HTML results-review article for the 114年度雨水下水道即時水情監測系統建置計畫; it states 58 water-level monitoring stations across 10 town/city urban-planning areas.；2026-06-30 curl smoke: the 114年度雨水下水道即時水情監測系統建置計畫 article says water gauges receive monthly maintenance and monthly reports track uptime, abnormalities, and improvements, but it exposes no latest-observation read API or station metadata file. 目前缺少 production 必備欄位：observed_at、station_or_device_id、measurement_value、measurement_unit_or_type、longitude_latitude_or_joinable_station_metadata 不可當量測來源：2026-06-30 curl smoke: the public page exposes only an HTML article/JPGs; it is not a sewer_water_level read API and cannot satisfy pump_or_gate_status.；在取得官方 read API 或可 join metadata 前，不得以 fetched_at 偽裝觀測時間。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認公開 read API URL 與 response 格式
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認授權條款、rate limit 與維運窗口
- [ ] 取得可重跑 live smoke 的範例 response
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 屏東縣：屏東縣地方即時水情 read API contract 請求

- 類型：public_api_contract_request
- 需要人工介入：是
- 追蹤對象：屏東縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_public_read_api_contract
- 整合優先序：#6 / P2 / verify_public_read_api_contract
- 來源：
  - https://pteoc.pthg.gov.tw/
  - https://pteoc.pthg.gov.tw/RainStation
  - https://pteoc.pthg.gov.tw/River
  - https://pteoc.pthg.gov.tw/Flood
  - https://pteoc.pthg.gov.tw/Crawler
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 候選系統缺少欄位：`observed_at`、`longitude_latitude_or_joinable_station_metadata`
- 候選系統查核事實：
  - 2026-06-30 smoke: RainStation/Details/C0R190 and RainStation/Details/01Q610 are public HTML pages; the table exposes 雨量(mm), 10分鐘雨量, 1小時雨量, 3小時雨量, 6小時雨量, 12小時雨量, and 24小時雨量.
  - 2026-06-30 smoke: RainStation detail pages identify station names such as 赤山站 and 古夏站, but the public HTML did not expose an observed_at timestamp or joinable WGS84 station metadata.
- 候選系統不可當量測來源：
  - 2026-06-30 smoke: Flood/Details/900 is not_flood_depth_measurement; it reports rainfall warning status and 1H/3H/6H thresholds, not a current flood-depth observation.
  - 2026-06-30 smoke: Crawler/Details/1 is image_only_cctv; it exposes CCTV image URLs for river monitoring, not a water-level measurement value.
- 排入此順位原因：candidate source needs a public read API contract review
- 完成門檻：公開 read API contract 補齊 observed_at、station id、measurement_value、單位與座標 metadata。

目前屏東縣已有官方系統或成果頁線索，但尚未找到可公開機器讀取的最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、站點 metadata 與範例 response。 已查核頁面事實：2026-06-30 smoke: RainStation/Details/C0R190 and RainStation/Details/01Q610 are public HTML pages; the table exposes 雨量(mm), 10分鐘雨量, 1小時雨量, 3小時雨量, 6小時雨量, 12小時雨量, and 24小時雨量.；2026-06-30 smoke: RainStation detail pages identify station names such as 赤山站 and 古夏站, but the public HTML did not expose an observed_at timestamp or joinable WGS84 station metadata. 目前缺少 production 必備欄位：observed_at、longitude_latitude_or_joinable_station_metadata 不可當量測來源：2026-06-30 smoke: Flood/Details/900 is not_flood_depth_measurement; it reports rainfall warning status and 1H/3H/6H thresholds, not a current flood-depth observation.；2026-06-30 smoke: Crawler/Details/1 is image_only_cctv; it exposes CCTV image URLs for river monitoring, not a water-level measurement value.；在取得官方 read API 或可 join metadata 前，不得以 fetched_at 偽裝觀測時間。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認公開 read API URL 與 response 格式
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認授權條款、rate limit 與維運窗口
- [ ] 取得可重跑 live smoke 的範例 response
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 嘉義市：嘉義市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：嘉義市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#7 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.chiayi_city.water_level、local.chiayi_city.rainfall
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：flood_depth、sewer_water_level、pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前嘉義市既有 production adapter 仍未覆蓋所有必要水資訊訊號：flood_depth、sewer_water_level、pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 桃園市：桃園市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：桃園市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#8 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.taoyuan.flood_sensor、local.taoyuan.water_level、local.taoyuan.rainfall
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：sewer_water_level、pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前桃園市既有 production adapter 仍未覆蓋所有必要水資訊訊號：sewer_water_level、pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 澎湖縣：澎湖縣缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：澎湖縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#9 / P2 / fill_sensor_signal_gap
- 靜態 metadata 線索：澎湖縣區域排水疏濬工程
- 靜態 metadata URL：
  - https://data.gov.tw/dataset/156926
- 既有 production adapters：local.penghu.water_level
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：flood_depth、pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前澎湖縣既有 production adapter 仍未覆蓋所有必要水資訊訊號：flood_depth、pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 臺中市：臺中市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：臺中市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#10 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.taichung.water_level
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：sewer_water_level、pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前臺中市既有 production adapter 仍未覆蓋所有必要水資訊訊號：sewer_water_level、pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 臺南市：臺南市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：臺南市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#11 / P2 / fill_sensor_signal_gap
- 靜態 metadata 線索：臺南市管區域排水之水位站名稱及位置、114年度抽水站基本資料、114年度水門基本資料
- 靜態 metadata URL：
  - https://soa.tainan.gov.tw/Api/Service/Get/6c525fc0-f70a-433e-8529-8e11e65e85e9
  - https://soa.tainan.gov.tw/Api/Service/Get/d9311994-b4c3-4952-8493-b7e49d17fbd3
  - https://soa.tainan.gov.tw/Api/Service/Get/3be620b5-4381-4195-bc2f-2eff62a46291
- 已排除官方線索：臺南市管區域排水即時影像、水利署與台南市合建淹水感測器感測資料
- 已排除官方線索 URL：
  - https://soa.tainan.gov.tw/Api/Service/Get/427a8287-0bc1-4b45-92ac-53eb858b5b9c
  - https://soa.tainan.gov.tw/Api/Service/Get/537b469d-e8c5-42ca-835e-bdde93bc61be
- 排除原因：
  - 2026-06-30 live smoke: regional-drainage CCTV returns GroupStationID, CameraID, Point, and ImageUrl only; image-only CCTV has no observed_at, measurement_value, or measurement_unit_or_type and cannot satisfy sewer_water_level or pump_or_gate_status.
  - 2026-06-30 live smoke: WRA/Tainan joint flood-sensor endpoint returned data:null, so no station/device observation rows are available for production ingestion.
- 既有 production adapters：local.tainan.flood_sensor
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：sewer_water_level、pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前臺南市既有 production adapter 仍未覆蓋所有必要水資訊訊號：sewer_water_level、pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 南投縣：南投縣缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：南投縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#12 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.nantou.sewer_water_level
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前南投縣既有 production adapter 仍未覆蓋所有必要水資訊訊號：pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 基隆市：基隆市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：基隆市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#13 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.keelung.water_level、local.keelung.flood_sensor、local.keelung.rainfall
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前基隆市既有 production adapter 仍未覆蓋所有必要水資訊訊號：pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 宜蘭縣：宜蘭縣缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：宜蘭縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#14 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.yilan.flood_sensor、local.yilan.water_level
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前宜蘭縣既有 production adapter 仍未覆蓋所有必要水資訊訊號：pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 新北市：新北市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：新北市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#15 / P2 / fill_sensor_signal_gap
- 靜態 metadata 線索：新北市各抽水站資訊、新北市水門資料
- 靜態 metadata URL：
  - https://data.ntpc.gov.tw/datasets/3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296
  - https://data.ntpc.gov.tw/datasets/bf784279-31aa-44bc-a210-33151d03e7ab
- 既有 production adapters：local.new_taipei.water_level、local.new_taipei.flood_sensor、local.new_taipei.rainfall、local.new_taipei.drainage_water_level
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前新北市既有 production adapter 仍未覆蓋所有必要水資訊訊號：pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 新竹縣：新竹縣缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：新竹縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#16 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.hsinchu_county.flood_sensor
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：pump_or_gate_status
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前新竹縣既有 production adapter 仍未覆蓋所有必要水資訊訊號：pump_or_gate_status。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 臺北市：臺北市缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：臺北市政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#17 / P2 / fill_sensor_signal_gap
- 既有 production adapters：local.taipei.sewer_water_level、local.taipei.river_water_level、local.taipei.pump_station
- 既有 status-only 來源：臺北市水門啟閉狀態
- 既有 status-only 訊號：gate_status
- status-only 來源 URL：
  - https://wic.gov.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：flood_depth
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前臺北市既有 production adapter 仍未覆蓋所有必要水資訊訊號：flood_depth。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path

## 雲林縣：雲林縣缺漏水資訊訊號補齊請求

- 類型：signal_gap_request
- 需要人工介入：是
- 追蹤對象：雲林縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_signal_gap_review
- 整合優先序：#18 / P2 / fill_sensor_signal_gap
- 靜態 metadata 線索：雲林縣淹水感測器座標、雲林縣抽水站資料、雲林縣水門點位
- 靜態 metadata URL：
  - https://opendata.yunlin.gov.tw/OpenDataContent.aspx?n=8350&s=1427
  - https://yliflood.yunlin.gov.tw/ifloodboard
- 既有 production adapters：local.yunlin.water_level
- 既有 status-only 來源：雲林 iflood 淹水感測狀態
- 既有 status-only 訊號：flood_sensor_status
- status-only 來源 URL：
  - https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- Production ops gates: freshness_policy, raw_snapshot_retention_policy, monitored_scheduler_cadence, hosted_egress_review, worker_persisted_evidence_path
- 待補水資訊訊號：flood_depth
- 排入此順位原因：existing adapters do not cover every required water signal family
- 完成門檻：補齊缺少的 signal families，或以官方證據記錄為無法取得；可用資料必須含 observed_at、station_or_device_id、measurement_value、measurement_unit_or_type 與座標。

目前雲林縣既有 production adapter 仍未覆蓋所有必要水資訊訊號：flood_depth。請協助確認是否有官方公開 read API、開放資料或可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或下水道水位量測。 Production 上線前也需確認 freshness policy、raw snapshot retention、scheduler cadence、hosted egress review，並走 worker-persisted evidence path。

待辦：
- [ ] 確認缺漏 signal families 是否存在官方 read API 或開放資料
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認 status-only 資料不會被當成水位、雨量或淹水深度
- [ ] 若官方確認不存在，記錄不可取得證據與後續追蹤窗口
- [ ] 確認 freshness policy 與 stale/degraded/failed 門檻
- [ ] 確認 raw snapshot retention policy 與可稽核保存位置
- [ ] 確認 scheduler cadence、重試策略與監控告警責任
- [ ] 確認 hosted egress review 與 worker-persisted evidence path
