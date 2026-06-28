# 地方即時水情官方請求包

此文件由 local-source action plan 產生，用於追蹤尚需人工授權或官方資料釋出的地方即時水情缺口。

## 金門縣：金門縣 KWIS 即時水情 read API 授權請求

- 類型：authorization_request
- 需要人工介入：是
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
- 來源：
  - https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5
  - https://www.matsu.gov.tw/upload/f-20230922134042.ods
- 待補中央主幹訊號：hydrologic_observation

目前連江縣僅找到靜態或 metadata 類公開資料，尚未找到可機器讀取的即時水文觀測 read API。請協助釋出南竿、北竿、莒光、東引的雨水下水道水位、道路淹水感測器、抽水站或水門水位、易淹區鄰近水位站等資料，或確認是否可加入 Civil IoT / WRA 等中央公開 SensorThings 主幹。

待辦：
- [ ] 確認是否可提供最新觀測 read API
- [ ] 確認是否可加入 Civil IoT 或 WRA 公開主幹
- [ ] 取得站點 ID、觀測時間、測值、單位與座標
- [ ] 確認短期無感測器時的建置計畫或資料釋出時程
