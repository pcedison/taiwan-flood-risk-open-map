# 地方即時水情官方請求包

此文件由 local-source action plan 產生，用於追蹤尚需人工授權或官方資料釋出的地方即時水情缺口。

## 花蓮縣：花蓮縣 Senslink/行動水情 即時水情 read API 授權請求

- 類型：authorization_request
- 需要人工介入：是
- 追蹤對象：花蓮縣政府 / Senslink 行動水情維運窗口
- 追蹤狀態：needs_authorization_request
- 來源：
  - https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index
  - https://www.hl.gov.tw/News_Content.aspx?n=32725&s=116294
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`

目前花蓮縣地方直連即時水情來源仍需要官方授權。請確認 Senslink/行動水情 是否可提供最新觀測 read API，不是設備上傳 API。若可提供，請協助提供正式 API contract、申請方式、授權條款、rate limit、測站清冊、座標 metadata 與範例 response。

待辦：
- [ ] 確認是否可提供最新觀測 read API
- [ ] 確認 API contract、授權條款與 rate limit
- [ ] 取得測站清冊、座標 metadata 與範例 response
- [ ] 確認資料欄位可滿足 production adapter 必備欄位

## 金門縣：金門縣 KWIS 即時水情 read API 授權請求

- 類型：authorization_request
- 需要人工介入：是
- 追蹤對象：金門縣政府 / KWIS 維運窗口
- 追蹤狀態：needs_authorization_request
- 來源：
  - https://kwis.kinmen.gov.tw/
  - https://kwis.kinmen.gov.tw/KWIS/Doc/%E9%87%91%E9%96%80%E7%B8%A3%E6%94%BF%E5%BA%9C%E7%AC%AC%E4%B8%89%E6%96%B9%E5%96%AE%E4%BD%8D%E8%B3%87%E6%96%99%E4%B8%8A%E5%82%B3%5B%E9%87%91%E9%96%80%E6%B0%B4%E6%83%85%E7%B3%BB%E7%B5%B1%5D%E4%B9%8BAPI%E4%BB%8B%E6%8E%A5%E7%94%B3%E8%AB%8B%E5%8F%8A%E4%BD%BF%E7%94%A8%E8%AA%AA%E6%98%8E.pdf
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`

目前金門縣地方直連即時水情來源仍需要官方授權。請確認 KWIS 是否可提供最新觀測 read API，不是設備上傳 API。若可提供，請協助提供正式 API contract、申請方式、授權條款、rate limit、測站清冊、座標 metadata 與範例 response。

待辦：
- [ ] 確認是否可提供最新觀測 read API
- [ ] 確認 API contract、授權條款與 rate limit
- [ ] 取得測站清冊、座標 metadata 與範例 response
- [ ] 確認資料欄位可滿足 production adapter 必備欄位

## 連江縣：連江縣即時水文觀測資料釋出請求

- 類型：metadata_release_request
- 需要人工介入：是
- 追蹤對象：連江縣政府公開資料或防災水利窗口
- 追蹤狀態：monitoring_open_data_release
- 來源：
  - https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5
  - https://www.matsu.gov.tw/upload/f-20230922134042.ods
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`
- 待補中央主幹訊號：hydrologic_observation

目前連江縣僅找到靜態或 metadata 類公開資料，尚未找到可機器讀取的即時水文觀測 read API。請協助釋出南竿、北竿、莒光、東引的雨水下水道水位、道路淹水感測器、抽水站或水門水位、易淹區鄰近水位站等資料，或確認是否可加入 Civil IoT / WRA 等中央公開 SensorThings 主幹。

待辦：
- [ ] 確認是否可提供最新觀測 read API
- [ ] 確認是否可加入 Civil IoT 或 WRA 公開主幹
- [ ] 取得站點 ID、觀測時間、測值、單位與座標
- [ ] 確認短期無感測器時的建置計畫或資料釋出時程

## 苗栗縣：苗栗縣地方即時水情 read API contract 請求

- 類型：public_api_contract_request
- 需要人工介入：是
- 追蹤對象：苗栗縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_public_read_api_contract
- 來源：
  - https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx?n=563&s=922337&sms=9560
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`

目前苗栗縣已有官方系統或成果頁線索，但尚未找到可公開機器讀取的最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、站點 metadata 與範例 response。

待辦：
- [ ] 確認公開 read API URL 與 response 格式
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認授權條款、rate limit 與維運窗口
- [ ] 取得可重跑 live smoke 的範例 response

## 屏東縣：屏東縣地方即時水情 read API contract 請求

- 類型：public_api_contract_request
- 需要人工介入：是
- 追蹤對象：屏東縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_public_read_api_contract
- 來源：
  - https://pteoc.pthg.gov.tw/
  - https://pteoc.pthg.gov.tw/RainStation
  - https://pteoc.pthg.gov.tw/River
  - https://pteoc.pthg.gov.tw/Flood
  - https://pteoc.pthg.gov.tw/Crawler
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`

目前屏東縣已有官方系統或成果頁線索，但尚未找到可公開機器讀取的最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、站點 metadata 與範例 response。

待辦：
- [ ] 確認公開 read API URL 與 response 格式
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認授權條款、rate limit 與維運窗口
- [ ] 取得可重跑 live smoke 的範例 response

## 臺東縣：臺東縣地方即時水情 read API contract 請求

- 類型：public_api_contract_request
- 需要人工介入：是
- 追蹤對象：臺東縣政府公開資料或水利防災維運窗口
- 追蹤狀態：needs_public_read_api_contract
- 來源：
  - https://www.taitung.gov.tw/News_Content.aspx?n=13370&s=131527&sms=12652
- Production read API 必備欄位：`observed_at`、`station_or_device_id`、`measurement_value`、`measurement_unit_or_type`、`longitude_latitude_or_joinable_station_metadata`、`official_source_url_and_license`

目前臺東縣已有官方系統或成果頁線索，但尚未找到可公開機器讀取的最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、站點 metadata 與範例 response。

待辦：
- [ ] 確認公開 read API URL 與 response 格式
- [ ] 確認觀測時間、站點 ID、測值、單位與座標欄位
- [ ] 確認授權條款、rate limit 與維運窗口
- [ ] 取得可重跑 live smoke 的範例 response
