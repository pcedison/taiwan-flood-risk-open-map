# 2026-06-28 地方即時水情來源查核紀錄

本紀錄用來追蹤 22 縣市地方政府直連來源的「可實作性」查核。判讀上，
中央主幹 Civil IoT、WRA、CWA、NCDR 可作全台基礎即時水情，不代表地方政府
直出 API 已完成。

## 查核方法

- 下載政府資料開放平臺官方清單：
  `https://data.gov.tw/api/front/dataset/export?format=json`
- 以 17 個未完成地方直連縣市搭配關鍵字掃描：即時水情、水位監測、淹水感測、
  水情監測、抽水站水位、河川水位、雨量站、水門、雨水下水道、防汛、防災。
- 對候選 URL 做 live smoke：確認 HTTP 可讀、是否免登入、格式是 JSON/XML/CSV
  或 HTML、是否含 `observed_at` 等等價觀測時間、WGS84 座標與水情數值。
- 只把地方政府、地方政府資料平台、地方水利/防災機關或其明確委外平台列入
  地方直連候選。中央來源只列為 fallback/backbone。

## 本輪新增查核結論

| 縣市 | 來源 | smoke 結果 | 判讀 | 下一步 |
| --- | --- | --- | --- | --- |
| 新北市 | `https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/flood/getFloodListData?...org_id=110...type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W`、`...type=flood`、`/rain/getRainFallBaseData?org_id=110&org_data=ALL`、`/water/getDrainage?org_id=110&org_data=ALL` | 免 key JSON；2026-06-28 smoke：water 73 筆 normalized 55、flood 147 筆 normalized 147、rain 123 筆 normalized 114、drainage 40 筆 normalized 40，均含 `datatime` 與 WGS84 座標；stale 站保留 raw 但 normalized reject。 | `ready_implemented` | 已新增 `local.new_taipei.water_level`、`local.new_taipei.flood_sensor`、`local.new_taipei.rainfall`、`local.new_taipei.drainage_water_level`。data.ntpc.gov.tw 抽水站/水門清冊仍只作 metadata 背景。 |
| 基隆市 | `https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/flood/getFloodListData?...type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W`、`...type=flood`、`https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/rain/getRainFallBaseData?org_id=58&org_data=ALL` | 免 key JSON；2026-06-28 smoke：water 11 筆、flood 49 筆、rain 18 筆，均含 `datatime` 與 WGS84 座標。live adapter normalized water 11、flood 49、rain 16，雨量 2 站 stale reject。 | `ready_implemented` | 已新增 `local.keelung.water_level`、`local.keelung.flood_sensor`、`local.keelung.rainfall`；stale/future observation 保留 raw 但 normalized reject。 |
| 新竹市 | `https://swc.hccg.gov.tw/api/map/sewer/base`、`/api/map/sewer/rt`；FHY Broker `GetFHYFloodSensorStationByCityCode`、`GetFHYFloodSensorInfoRt` | sewer base/rt API 免 key；base 50 站、rt 50 筆，含 `Time`、`WaterDepth`、WGS84 metadata。FHY Broker station/realtime 免 key，依 `CityCode=10018` 過濾新竹市。 | `ready_implemented` | 已新增 `local.hsinchu_city.sewer_water_level` 與 `local.hsinchu_city.flood_sensor`。 |
| 新竹縣 | FHY Broker `GetFHYFloodSensorStationByCityCode` + `GetFHYFloodSensorInfoRt` | 免 key SOAP/ASMX JSON；CityCode `10004`，Supplier=`新竹縣政府` 22 站；2026-06-28 smoke：fetched 22、normalized 20、stale reject 2，含 `.NET /Date(ms)/` `SourceTime` 與 WGS84 座標。 | `ready_implemented` | 已新增 `local.hsinchu_county.flood_sensor`；只保留地方政府 supplier，水利署分署 supplier 不納入 local adapter。 |
| 苗栗縣 | FHY Broker `GetFHYFloodSensorStationByCityCode` + `GetFHYFloodSensorInfoRt`；官方雨水下水道即時水情監測新聞/成果說明 | 免 key SOAP/ASMX JSON；CityCode `10005`，Supplier=`苗栗縣政府` 42 站；2026-06-28 smoke：fetched 42、normalized 40、stale reject 2。2026-06-30 curl smoke：官方成果頁為 HTML 文章，說明 10 個鄉鎮市都市計畫區已設置 58 處水位監測站，且有每月維護與月報，但未曝露 latest-observation read API、站點 metadata 檔或機器可讀觀測 endpoint。 | `ready_implemented` + `candidate_contract_blocker` | 已新增 `local.miaoli.flood_sensor`；苗栗雨水下水道系統仍等待公開 read API contract。HTML/JPG 成果頁不可滿足 `sewer_water_level` 或 `pump_or_gate_status` production ingestion。 |
| 彰化縣 | FHY Broker `GetFHYFloodSensorStationByCityCode` + `GetFHYFloodSensorInfoRt`；data.gov.tw `41415`、`28916` | FHY 免 key SOAP/ASMX JSON；CityCode `10007`，Supplier=`彰化縣政府` 70 站；2026-06-28 smoke：fetched/normalized 70。data.gov.tw 資料仍為靜態清冊/年度統計。 | `ready_implemented` | 已新增 `local.changhua.flood_sensor`；彰化 ArcGIS 水位計圖資目前只作 metadata，不產生 realtime evidence。 |
| 南投縣 | `https://dpinfo.nantou.gov.tw/Api/Proxy/GetKML` | 免 key KML；2026-06-28 回傳 69 個 Placemark，description 內嵌 JSON，含水位高度、時雨量、更新時間與 WGS84 coordinates。 | `ready_implemented` | 已新增 `local.nantou.sewer_water_level`。 |
| 雲林縣 | `https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5` | 免 key JSON；2026-06-28 smoke：totalCount 2473。stationType 水位 161 站；live adapter 取 102 筆具 `levelHeight/latestUpdateTime` 與座標的水位資料，normalized 101、stale reject 1。淹水感測 173 站未曝露 depth。2026-06-30 補強：`alarmState` 會保留為低權重 `status_only` 狀態線索，但不抵扣 `flood_depth` 缺口。 | `ready_implemented` + `needs_review` | 已新增 `local.yunlin.water_level`。淹水感測不以 `alarmState` 偽造水深；附近觀測可顯示為狀態線索，仍需追前端細節 API 或官方欄位文件取得 depth。 |
| 雲林縣 | data.gov.tw `156080` 淹水感測器、`163147` 淹水感測器(白金)、`156083` 水位計、`161651` 水情監測設備座標 | JSON 可讀且含 WGS84 座標，但主要是站點/設備清冊 | `metadata_only` | 可作未來 station metadata join，不單獨作 realtime evidence。 |
| 嘉義縣 | `https://api.floodsolution.aiot.ing/api/public/devices/RFD` | 免 key JSON；2026-06-28 回傳 253 站，`latest.time`、`latest.data.waterDepth`、`lon`、`lat`、鄉鎮村里可讀。`/api/v1` 管理端點仍需登入，不納入。 | `ready_implemented` | 已新增 `local.chiayi_county.flood_sensor`；靜態抽水站 CSV 保留 metadata 候選。 |
| 高雄市 | `https://wrbswi.kcg.gov.tw/SFC/api/sewer/rt`、`https://wrbswi.kcg.gov.tw/SFC/api/khfloodinfo/sta_info/lastest/wrs_flooding_sensor`、`https://wrbswi.kcg.gov.tw/SFC/api/rain/rt`、`https://wrbswi.kcg.gov.tw/SFC/api/rain/base` | 免 key JSON；sewer/rt 回傳 296 筆下水道水位，含 `time`、`stage`、警戒值、座標；wrs_flooding_sensor 回傳 171 筆淹水感測，含 `time`、`obs_value`、座標。sewer/rt live payload 混入 1 筆 2027 未來時間，adapter 保留 raw 但 normalized reject。2026-06-29 補查：rain/rt live adapter 87 筆 normalized、rain/base 88 筆 metadata，`ST_NO` join 可取得 `DATE`、站名、地址與 WGS84 座標；站數會隨平台即時狀態浮動。 | `ready_implemented` | 已新增 `local.kaohsiung.sewer_water_level`、`local.kaohsiung.flood_sensor` 與 `local.kaohsiung.rainfall`；地方雨量只補強 CWA 空間密度，不取代 CWA。 |
| 宜蘭縣 | `https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/防汛儀表板/MapServer/{layer}/query?where=1=1&outFields=*&f=json` | 免 key ArcGIS REST JSON；layer 0 回傳 85 筆淹水感測、layer 2 回傳 154 筆水位計，含 `write_date` epoch milliseconds、`water_inner`、WGS84 座標。 | `ready_implemented` | 已新增 `local.yilan.flood_sensor` 與 `local.yilan.water_level`。 |
| 臺南市 | `https://soa.tainan.gov.tw/Api/Service/Get/6c525fc0-f70a-433e-8529-8e11e65e85e9`、`https://soa.tainan.gov.tw/Api/Service/Get/d9311994-b4c3-4952-8493-b7e49d17fbd3`、`https://soa.tainan.gov.tw/Api/Service/Get/3be620b5-4381-4195-bc2f-2eff62a46291` | 2026-06-30 live smoke：三個 SOA endpoint 可讀，分別回 102 筆水位站 metadata、66 筆抽水站基本資料、26 筆水門基本資料；資料性質為站碼、站名、行政區、座標、設施基本資料或區別統計，未提供 `observed_at` 與即時 `measurement_value`。 | `metadata_only` | 可作 station/facility metadata 線索，但不可抵扣臺南市仍缺的 `sewer_water_level` 或 `pump_or_gate_status` production read API。 |
| 臺南市 | `https://soa.tainan.gov.tw/Api/Service/Get/427a8287-0bc1-4b45-92ac-53eb858b5b9c`、`https://soa.tainan.gov.tw/Api/Service/Get/537b469d-e8c5-42ca-835e-bdde93bc61be` | 2026-06-30 live smoke：區域排水即時影像回 127 筆 `GroupStationID`、`CameraID`、`Point`、`ImageUrl`，為 image-only CCTV；水利署與臺南市合建淹水感測器端點回 `data:null`。 | `non_qualifying` | CCTV 影像不是下水道水位或抽水站/水門狀態量測；`data:null` 端點目前無 station/device observation rows，不列 production ingestion。 |
| 屏東縣 | `https://pteoc.pthg.gov.tw/RainStation` | HTML 可讀；2026-06-30 重查 `RainStation/Details/C0R190`、`RainStation/Details/01Q610`，表格含站名、雨量(mm)、10 分鐘、1/3/6/12/24 小時雨量值，但缺明確 `observed_at` 與可 join WGS84 站點 metadata。 | `needs_review` 候選，不可 production | 不把 `fetched_at` 偽裝成 `observed_at`；需找到有 timestamp/coordinate 的 read API 或官方 metadata join。 |
| 屏東縣 | `https://pteoc.pthg.gov.tw/River`、`/Flood`、`/Crawler` | HTML 可讀；2026-06-30 重查 `Flood/Details/900` 是雨量警戒狀態與 1H/3H/6H 門檻，不是淹水深度；`Crawler/Details/1` 是河川監測 CCTV 影像，不是水位量測。 | `candidate_contract_blocker` | 不 scrape 成 production realtime evidence；請求官方 JSON/CSV/XML/ArcGIS/SensorThings read API contract 與 station metadata。 |
| 屏東縣 | FHY Broker `GetFHYFloodSensorStationByCityCode` + `GetFHYFloodSensorInfoRt` | 免 key SOAP/ASMX JSON；CityCode `10013`，Supplier=`屏東縣政府` 20 站；2026-06-28 smoke：fetched/normalized 20。 | `ready_implemented` | 已新增 `local.pingtung.flood_sensor`；PTEOC HTML 仍不可 production。 |
| 花蓮縣 | FHY Broker `GetFHYFloodSensorStationByCityCode` + `GetFHYFloodSensorInfoRt`；`https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index` | FHY 免 key SOAP/ASMX JSON；CityCode `10015`，Supplier=`花蓮縣政府` 13 站；2026-06-28 smoke：fetched/normalized 13。Senslink 首頁 200，但水情/路淹/抽水站/看板頁 302 到登入。 | `ready_implemented` + `needs_application` | 已新增 `local.hualien.flood_sensor`；Senslink 更完整 read API 仍需帳密或官方授權。 |
| 臺東縣 | FHY Broker `GetFHYFloodSensorStationByCityCode` + `GetFHYFloodSensorInfoRt`；臺東縣府防汛新聞、審計部臺東水情預警系統說明 | FHY 免 key SOAP/ASMX JSON；CityCode `10014`，Supplier=`臺東縣政府` 2 站；2026-06-28 smoke：fetched/normalized 2。2026-06-30 curl/web review：縣府新聞頁是防洪/河道清疏新聞，提及水情監測系統使用淹水感測、水位站、雨量站、即時影像監視器；審計部頁證實洪水與淹水預警系統並已介接 CWA 49 雨量站、WRA 9 水位站。兩者都未曝露 latest-observation read API/schema。 | `ready_implemented` + `candidate_contract_blocker` | 已新增 `local.taitung.flood_sensor`；臺東預警系統仍等待公開 read API contract，且不得把新聞/稽核摘要或即時影像視為量測資料。 |
| 澎湖縣 | `https://ph3dgis.penghu.gov.tw/server/rest/services/SewerNew/PHSewer_Basemap/MapServer/6/query?where=1%3D1&outFields=*&f=json&returnGeometry=true&outSR=4326` | 免 key ArcGIS REST JSON；2026-06-28 smoke：38 筆 normalized、0 筆 rejected，含 `measure_time`、`water_level`、`water_level_percent`、`battery`、`rssi` 與 WGS84 geometry。`measure_time` 為台灣本地 wall-clock epoch 編碼，adapter 會扣 8 小時後做 freshness check。 | `ready_implemented` | 已新增 `local.penghu.water_level`。`https://sewer.penghu.gov.tw/` 登入型儀表板不納入 production。 |
| 金門縣 | KWIS 介接文件、ASMX/WSDL；Civil IoT `water_12` / `STA_RainSewer` | 2026-06-30 KWIS WSDL 查核：service listing 有雨量、水位、淹水感測、抽水機與 station sensor list 的 token-gated read methods；空 Token smoke 回 `ErrMsg (7)`、`Data: []`。2026-06-28 Civil IoT live smoke：淹水感測 7 站、RainSewer 29 站。 | `needs_application` + `central_aggregated_ready` | 已確認 read method 名稱，但未申請或未取得官方 Token/可讀範圍/response schema 前不實作地方 adapter；中央主幹可補足金門即時水文觀測。 |
| 連江縣 | data.gov.tw / 連江縣開放資料；CWA `O-B0075-001` + `O-B0076-001` | 只找到易淹水 ODS 與防災靜態資料；2026-06-30 追加查核 CWA 馬祖潮位站可提供沿海水位觀測與站點 metadata。 | `metadata_only` + `not_found` + `central_aggregated_ready` | 中央最低 hydrologic backbone 已由 CWA 潮位補足；地方 live API 仍未找到，仍缺 `flood_depth`、`sewer_water_level`、`pump_or_gate_status` 地方直連訊號。 |
| 連江縣 | 連江自來水廠 `水庫水位`；`http://erbwater.matsu.gov.tw/PUBLIC/RealTime/Get_AVGR.aspx` | 2026-06-30 追加查核：自來水廠水庫水位頁為月報 PDF；`erbwater` 公開即時監測值頁可進入，但欄位與選單顯示為放流水環保 CEMS，非淹水、水位、雨水下水道、抽水站或水門觀測。 | `non_qualifying` | 兩者只作已排除官方線索，不列 production adapter，不降低地方直連缺口；不可抵扣 `flood_depth`、`sewer_water_level` 或 `pump_or_gate_status`。 |

## 2026-06-29 候選來源 smoke 補充

本補充使用 `scripts/local-source-candidate-smoke.py --timeout-seconds 20 --format json`
重跑尚待判讀的地方候選，目標是把「尚未接上」拆成可執行原因，而不是統一視為未完成。

| 縣市 | 候選來源 | 2026-06-29 live smoke | 判讀 | 下一步 |
| --- | --- | --- | --- | --- |
| 臺北市 | 疏散門即時監測 `wic.heo.taipei/OpenData/API/Evacuate/Get` / mirror `wic.gov.taipei/OpenData/API/Evacuate/Get` | 2026-06-30 已補 smoke fallback：`wic.heo.taipei` timeout 時會重試官方公開 mirror `wic.gov.taipei` 同路徑，並以單元測試確認 mirror payload 的 `stationNo`、`recTime`、`lng/lat` 與 `fo/fc/flt` 只作疏散門/水門啟閉狀態，不升級成水位或淹水深度。 | `status_only_verified` | 移出 live-smoke blocker；coverage catalog 改列 `臺北市水門啟閉狀態` / `gate_status` status-only。臺北市仍缺 `flood_depth`，由 signal-gap request 追蹤公開 read API 或官方不可得證明。 |
| 苗栗縣 | 雨水下水道即時水情監測成果頁 | 2026-06-30 curl smoke：HTTP 200 HTML；頁面說明「114年度雨水下水道即時水情監測系統建置計畫」在 10 個鄉鎮市都市計畫區設置 58 處水位監測站，並有每月水位計維護與月報。公開頁只連到會議 JPG 圖片，未曝露 `observed_at`、`station_or_device_id`、`measurement_value`、單位或可 join WGS84 metadata。 | `needs_public_read_api_contract` | 需要公開 read API contract 或可 join 的 station metadata；HTML 文章/JPG 不可當成 `sewer_water_level` read API，也不能補 `pump_or_gate_status`。 |
| 雲林縣 | iflood station API 的淹水感測類 | 200 JSON，具 `latestUpdateTime`、站點與座標，但未曝露淹水深度測值；2026-06-30 已改為 `status_only` 事件類型，source weight 低且沒有 realtime risk factor。 | `status_only_ready` + `needs_measurement_value` | 保留既有 `local.yunlin.water_level`；淹水感測可作附近狀態線索，但仍需找 depth/detail API 或官方欄位文件才可補 `flood_depth`。 |
| 嘉義縣 | 智慧防汛管理型線索 | 查核頁在目前 runtime 觸發 `DH_KEY_TOO_SMALL` SSL 錯誤；公開 RFD API 已 production | `needs_observed_time` / 非阻塞 | 不依賴管理型 `/api/v1`；繼續操作已落地 `local.chiayi_county.flood_sensor`。 |
| 高雄市 | SFC `rain/rt` + `rain/base` | 200 JSON；live adapter fetched/normalized 87、rejected 0，metadata 88 筆 | `promotion_ready` → `ready_implemented` | 已新增 `local.kaohsiung.rainfall`；地方雨量只補強 CWA。 |
| 屏東縣 | PTEOC `/RainStation`、`/Flood`、`/Crawler` | 200 HTML；`/RainStation/Details/*` 有雨量窗格但缺明確觀測時間與座標；`/Flood/Details/*` 為雨量警戒門檻；`/Crawler/Details/*` 為 CCTV 影像。 | `needs_public_read_api_contract` | 不把 `fetched_at` 當 `observed_at`；需要公開 API 或官方 metadata join，並將非量測頁面保留為 contract blocker 證據。 |
| 臺東縣 | 洪水與淹水預警系統線索 | 2026-06-30 curl/web review：縣府新聞頁 200 HTML，證實水情監測系統含淹水感測、水位站、雨量站與即時影像；審計部頁證實已介接 CWA 49 雨量站與 WRA 9 水位站，但未提供觀測時間、站點 ID、測值、單位或可 join WGS84 metadata 的公開 read API。 | `needs_public_read_api_contract` | 保留既有 `local.taitung.flood_sensor`；其他系統需公開 latest-observation read API contract。 |

## 可實作性門檻

本專案不得把下列來源升級為 `ready_implemented`：

- 只有站點、設備、抽水站、水門、易淹區或防災地圖清冊。
- HTML 頁面雖有數值，但沒有可追溯觀測時間，且無官方座標 join。
- 前台看得到圖表或地圖，但沒有公開 API contract 或穩定 endpoint。
- SOAP/ASMX 或 dashboard 需要帳密、key、token、captcha 或人工審核。
- 中央來源彙整地方感測器；它可作中央主幹或 fallback，但不算地方政府直出。

## 後續工作排序

1. **屏東縣**：優先找 `pteoc.pthg.gov.tw` 是否有非 HTML 的雨量/水位 JSON API，
   或官方 station metadata 可 join。已確認 `/Flood/Details/*` 與
   `/Crawler/Details/*` 不可當量測；若只有 HTML 且無時間戳，
   維持 `needs_public_read_api_contract`。
2. **雲林縣淹水感測**：追查是否有 station detail / measure API 曝露 depth；
   未確認前不得以 `alarmState` 當作淹水深度。`alarmState` 目前只作
   `status_only` 狀態線索與覆蓋診斷。
3. **苗栗縣、臺東縣**：FHY 地方政府 supplier 已可運作；苗栗成果頁已證實
   58 處雨水下水道水位監測站存在，但目前只公開 HTML/JPG 成果說明，仍需
   API contract 後才可另增 adapter；臺東縣府新聞與審計部頁可證明預警系統、
   影像/感測線索與 CWA/WRA station integration，但仍缺公開 read API contract。
4. **花蓮縣、金門縣**：目前屬授權/登入型；金門已確認 KWIS token-gated read methods，仍需要人工申請正式 Token、可讀範圍、rate limit 與 response schema。
5. **彰化、連江**：目前主要是靜態 open data；連江水庫水位月報與
   `erbwater` 放流水 CEMS 已列為 `non_qualifying`，持續監看 metadata
   release，不列 production adapter。
