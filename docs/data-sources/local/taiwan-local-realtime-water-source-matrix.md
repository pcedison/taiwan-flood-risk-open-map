# 台灣 22 縣市地方即時水情來源矩陣

日期：2026-06-28
狀態：初版盤點中；已納入 data.gov.tw 全站資料集匯出、實際 endpoint
smoke、以及分區 subagent 查核工作。此文件用來追蹤「地方政府補強層」，
不得取代中央全台主幹 Civil IoT、WRA、CWA、NCDR。
最新逐項 smoke 與 data.gov.tw export 掃描紀錄見
`docs/data-sources/local/2026-06-28-local-source-verification-log.md`。
金門與連江的外部授權/資料釋出請求包見
`docs/data-sources/local/official-request-packets.md`。
Admin API 可用 `GET /admin/v1/local-source-action-plan` 讀取同一份剩餘
授權、資料釋出、contract review 與 live smoke 工作佇列。

## 判讀原則

- `ready`：官方 landing page 或 data catalog 可追溯，endpoint 可機器讀取，
  smoke 顯示有近期 `observed_at` 或等價觀測時間，欄位足以正規化。
- `central_aggregated_ready`：地方政府與中央合建或委託的感測資料已在
  Civil IoT/WRA 等中央公開 API 中可機器讀取；這可補足查詢覆蓋，但不等於
  該縣市有地方政府直出的 open-data API。
- `candidate`：官方來源存在，但仍缺少座標 join、freshness、授權、schema
  或 live smoke 的其中一項。
- `metadata_only`：只有站點、抽水站、水門、易淹區或圖資清冊，不能當作
  即時水情。
- `non_qualifying`：官方水資訊線索已查核，但因為不是即時 read API、不是
  水位/淹水/下水道/抽水站/水門觀測，或缺少必要欄位，必須明確排除，不能
  降低缺漏訊號或風險分數。
- `needs_review`：endpoint 可打通，但目前觀測時間 stale、欄位語意不清，
  或疑似地方水情網站衍生資料，需要再查核。
- `not_found`：目前尚未找到可穩定公開、可機器讀取的地方即時水情 API。
  此狀態不代表該縣市沒有即時風險資料；中央主幹仍可能覆蓋。

## 不可破壞的中央主幹

地方來源只做補強與交叉驗證，不覆蓋中央主幹：

| 主幹來源 | adapter | 用途 | 保護規則 |
| --- | --- | --- | --- |
| CWA 自動雨量 | `official.cwa.rainfall` | 全台雨量驅動訊號 | 使用既有 `CWA_API_AUTHORIZATION`；地方雨量不得取代 CWA，只能補足空間密度。 |
| CWA 潮位 | `official.cwa.tide_level` | 沿海/離島潮位水位脈絡 | 使用 CWA `O-B0075-001` + `O-B0076-001`；可補足連江等離島最低水文脈絡，但只代表 coastal tide level，不可誤當內陸排水、淹水深度、下水道、抽水站或水門量測。 |
| WRA 即時水位 | `official.wra.water_level` | 中央管河川與區排水位 | 地方水位與 WRA/Civil IoT 重疊時必須去重，不可 double-count。 |
| WRA IoW 淹水深度 | `official.wra_iow.flood_depth` | 全台 IoW 路面淹水深度最新值 | 使用 latest dataset `142980` join basic dataset `142979`；缺座標或停用感測器不得 normalized。 |
| Civil IoT 淹水感測 | `official.civil_iot.flood_sensor` | 全台道路淹水深度主幹 | 地方淹水感測器只能補強或校驗，不可覆寫 L1。 |
| Civil IoT 雨水下水道 | `official.civil_iot.sewer_water_level` | 跨縣市雨水下水道水位 SensorThings | 不需 token；使用 `STA_RainSewer`，作為地方都市排水補強，不取代淹水警戒。 |
| Civil IoT 抽水站水位 | `official.civil_iot.pump_water_level` | 跨縣市抽水站水位 SensorThings | 不需 token；查詢 stationName 含「抽水」且 datastream 含「水位」，優先外水位、fallback 一般水位。 |
| Civil IoT 閘門外水位 | `official.civil_iot.gate_water_level` | 跨縣市閘門/水門外水位 SensorThings | 不需 token；只讀 `閘門外水位`，屬基礎設施脈絡訊號，不是官方淹水警戒。 |
| NCDR CAP | `official.ncdr.cap` | 官方警戒 | 地方來源不能降低 CAP 警戒，只能提供附近觀測脈絡。 |

## 已實測可進第一批實作的地方來源

| 縣市 | 類型 | 來源 | endpoint 形式 | 觀測時間 | 認證 | 狀態 | 實測摘要 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 全台 | 中央彙整地方淹水感測 | WRA IoW 淹水深度最新資料 dataset `142980` + 基本資料 dataset `142979` | JSON API latest：`https://opendata.wra.gov.tw/api/v2/1b991bbb-ad85-4e7a-b931-06ce8749d3ed?format=JSON&sort=_importdate%20asc`；basic：`https://opendata.wra.gov.tw/api/v2/21c50be1-7c4a-4fdf-a386-790625e984e7?format=JSON&sort=_importdate%20asc` | `timestamp` | 不需 token | `central_aggregated_ready_implemented` | 已新增 `official.wra_iow.flood_depth` adapter；以 `sensorid` join `longitude`/`latitude`、`countyname`、`townname`，補齊多縣市淹水深度。 |
| 全台 | 中央彙整雨水下水道水位 | Civil IoT / 國土管理署 `nlma1` 雨水下水道水位 | SensorThings JSON：`https://sta.colife.org.tw/STA_RainSewer/v1.0/Things?...` | `phenomenonTime` | 不需 token | `central_aggregated_ready_implemented` | 已新增 `official.civil_iot.sewer_water_level`；使用 STA JSON API，不需人工申請。2026-06-28 live smoke 確認新北、基隆、新竹市、新竹縣、苗栗、宜蘭、花蓮、臺東、澎湖、金門均有近期觀測；金門 29 站、連江 0 站。 |
| 全台 | 中央彙整抽水站水位 | Civil IoT `water_14` / WRA 與地方政府合建抽水站 | SensorThings JSON：`https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Things?...$filter=substringof('抽水',properties/stationName) and substringof('水位',Datastreams/name)` | `phenomenonTime` | 不需 token | `central_aggregated_ready_implemented` | 已修正 `official.civil_iot.pump_water_level`；優先 `外水位`，若縣市只提供 `水位` 則 fallback。 |
| 全台 | 中央彙整閘門外水位 | Civil IoT `water_15` / WRA 與地方政府合建水門閘門 | SensorThings JSON：`https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/Things?...$filter=substringof('閘門外水位',Datastreams/name)` | `phenomenonTime` | 不需 token | `central_aggregated_ready_implemented` | 已新增 `official.civil_iot.gate_water_level`；只納入外水位，不把閘門開度誤當水位。 |
| 全台 | 官方淹水警戒 | NCDR 民生示警 CAP `AlertType=8` | Atom/CAP：`https://alerts.ncdr.nat.gov.tw/RssAtomFeed.ashx?AlertType=8` | feed `updated` 與 CAP 時間欄位 | 不需 token | `ready` | 事件層來源，不是感測器；需遵守 NCDR 取用限制並與既有 `official.ncdr.cap` 對齊。 |
| 多縣市 | 地方政府供應淹水感測器 | FHY Broker / 防災協作平台 | SOAP/ASMX JSON POST：station `https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorStationByCityCode`，realtime `https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt` | `.NET /Date(ms)/` `SourceTime` | 不需 token | `ready_implemented` | 已新增新竹縣、苗栗、彰化、屏東、花蓮、臺東 local FHY flood adapters；只保留 `Supplier` 為該縣市政府的站點，排除水利署分署 supplier，避免把中央資料偽裝成地方直連。 |
| 臺北市 | 雨水下水道水位 | 臺北市資料大平臺「臺北市雨水下水道水位即時資訊」 | JSON API：`https://wic.gov.taipei/OpenData/API/Sewer/Get?stationNo=&loginId=sewer01&dataKey=BD3E513A`；座標 join：dataset `121643` | `recTime`，格式 `YYYYMMDDHHMM` | 官方頁公開 dataKey；無額外人工申請 | `ready_implemented` | 已新增 `local.taipei.sewer_water_level`；2026-06-27 smoke：233 筆，時間約 23:40。 |
| 臺北市 | 河川水位 | 臺北市資料大平臺「臺北市河川水位即時資訊」 | JSON API：`https://wic.gov.taipei/OpenData/API/Water/Get?stationNo=&loginId=river&dataKey=9E2648AA`；座標 join：dataset `138171` | `recTime`，格式 `YYYYMMDDHHMM` | 官方頁公開 dataKey；無額外人工申請 | `ready_implemented` | 已新增 `local.taipei.river_water_level`，含逐站 stale row rejection；2026-06-27 smoke：31 筆，多數約 23:40。 |
| 臺北市 | 抽水站內外水位/狀態 | 臺北市資料大平臺「臺北市抽水站即時資訊」 | JSON API：`https://heopublic.gov.taipei/taipei-heo-api/openapi/pumb/latest` | `obs_time` | 不需 token | `ready_implemented` | 已新增 `local.taipei.pump_station`；2026-06-27 smoke：含 `lon`、`lat`、`inner_value`、`outer_value`、`pumb_status`。 |
| 臺北市 | 疏散門/水門狀態 | 臺北市資料大平臺「臺北市疏散門即時監測」 | JSON API：`https://wic.gov.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6`；`wic.heo.taipei` timeout 時改用官方公開 mirror | `recTime`，官方欄位說明 | 官方頁公開 loginId/dataKey；無額外人工申請 | `status_only_verified` | 2026-06-30 smoke 契約確認 mirror 可提供站號、時間、座標與 `fo/fc/flt` 啟閉欄位；這只作水門狀態線索，不納入水位、雨量或淹水深度，臺北市仍追蹤 `flood_depth` 缺口。 |
| 新北市 | 水位站 | 新北市 WaveGIS 委外智慧水情平台 | JSON API：`https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/flood/getFloodListData?...org_id=110...type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W&unit=1` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.new_taipei.water_level`；2026-06-28 smoke：73 筆、normalized 55、stale reject 18，含警戒值與 WGS84 座標。 |
| 新北市 | 淹水感測器 | 新北市 WaveGIS 委外智慧水情平台 | JSON API：`https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/flood/getFloodListData?...org_id=110...type=flood&unit=1` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.new_taipei.flood_sensor`；2026-06-28 smoke：147 筆、normalized 147，`water_inner` 以公分淹水深度解讀。 |
| 新北市 | 雨量 | 新北市 WaveGIS 委外智慧水情平台 | JSON API：`https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/rain/getRainFallBaseData?org_id=110&org_data=ALL` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.new_taipei.rainfall`；2026-06-28 smoke：123 筆、normalized 114、stale reject 9，保留 10/30 分鐘與 3/6/12/24 小時雨量窗格。 |
| 新北市 | 排水水位 | 新北市 WaveGIS 委外智慧水情平台 | JSON API：`https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/water/getDrainage?org_id=110&org_data=ALL` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.new_taipei.drainage_water_level`；2026-06-28 smoke：40 筆、normalized 40，含排水水位、警戒值、CCTV URL 與 WGS84 座標。 |
| 基隆市 | 水位站 | 基隆市智慧防汛網平台 | JSON API：`https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/flood/getFloodListData?...type=radar%2Cwater%2CWT_RR_W%2CWG_RR_W&unit=1` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.keelung.water_level`；2026-06-28 smoke：11 筆，含 `water_inner`、`warn_lv1/2`、`town/village` 與 WGS84 座標。 |
| 基隆市 | 淹水感測器 | 基隆市智慧防汛網平台 | JSON API：`https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/flood/getFloodListData?...type=flood&unit=1` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.keelung.flood_sensor`；2026-06-28 smoke：49 筆，`water_inner` 以公分淹水深度解讀。 |
| 基隆市 | 雨量 | 基隆市智慧防汛網平台 | JSON API：`https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/rain/getRainFallBaseData?org_id=58&org_data=ALL` | `datatime` | 不需 token | `ready_implemented` | 已新增 `local.keelung.rainfall`；2026-06-28 smoke：18 筆，保留 `rain`、10/30 分鐘與 3/6/12/24 小時雨量；stale 站保留 raw 但 normalized reject。 |
| 桃園市 | 水位站水情 | data.gov.tw dataset `31299` | XML：`https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERLEVEL.xml` | `DATATIME` | 不需 token | `ready_implemented` | 已新增 `local.taoyuan.water_level`；2026-06-27 smoke：126 筆，含 `WATERHEIGHT_M`、紅黃警戒、WGS84 座標。 |
| 桃園市 | 路面淹水感測 | data.gov.tw dataset `152941` | XML：`https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERFLOOD.xml` | `DATA_TIME`，中文 AM/PM | 不需 token | `ready_implemented` | 已新增 `local.taoyuan.flood_sensor`；2026-06-27 smoke：210 筆，含 `HEIGHT`、`LON`、`LAT`、`ADDRESS`。 |
| 桃園市 | 雨量 | data.gov.tw dataset `46407` | XML：`https://opendata.tycg.gov.tw/api/dataset/eabd93d1-d526-4de0-b378-b529aa61a4be/resource/6a555cf5-ccc9-4706-9cb6-62c25f23ec4e/download` | root `Time` | 不需 token | `ready_implemented` | 已新增 `local.taoyuan.rainfall`；2026-06-28 smoke：root `Time=2026-06-28 00:10`，含站點座標與 `Rainfall`。官方欄位未明示累積窗格，程式保留為 `rainfall_mm`，不硬轉 10 分鐘或 1 小時。 |
| 臺中市 | 水位站水情 | 臺中市資料開放平臺 | JSON：`https://wrbeocin.taichung.gov.tw/TCSAFE/UploadFile/WATERLEVEL/WATERLEVEL_NEW.JSON` | `日期時間`，中文 AM/PM | 不需 token | `ready_implemented` | 已新增 `local.taichung.water_level`；2026-06-27 smoke：73 筆、72 筆 normalized，官方 live URL 新鮮，stale row 會被拒絕。 |
| 嘉義市 | 水位站水位 | data.gov.tw dataset `52584` | CSV：`https://data.chiayi.gov.tw/opendata/api/getResource?oid=df063695-0076-4dd6-9237-39c5f8ae6b4a&rid=d4c7da5c-b08f-4fd1-97c0-913c949c4613` | `資料時間` | 不需 token | `ready_implemented` | 已新增 `local.chiayi_city.water_level`；2026-06-27 smoke：25 筆，含一級/二級警戒值。 |
| 嘉義市 | 雨量 | data.gov.tw dataset `52585` | CSV：`https://data.chiayi.gov.tw/opendata/api/getResource?oid=0c766c28-c16e-4eaa-8520-f7ffeee3776b&rid=5ad1cdc5-6a8a-48d4-b6b4-7edb9b384e1a` | `資料時間` | 不需 token | `ready_implemented` | 已新增 `local.chiayi_city.rainfall`；2026-06-28 smoke：含 10 分鐘、1/3/6/12 小時雨量。live CSV 有重複 `12小時雨量-mm` header 時，第二欄保守保存為 24 小時雨量。 |
| 新竹市 | 雨水下水道水位 | 新竹市雨水下水道水情 API | JSON API：base `https://swc.hccg.gov.tw/api/map/sewer/base`；realtime `https://swc.hccg.gov.tw/api/map/sewer/rt` | `Time` | 不需 token | `ready_implemented` | 已新增 `local.hsinchu_city.sewer_water_level`；以 `Dev_UUID` join base metadata，保留水深、警戒水深、電壓與 WGS84 座標。 |
| 新竹市 | 淹水感測器 | FHY Broker 新竹市站點與即時資料 | SOAP/ASMX JSON POST：station `GetFHYFloodSensorStationByCityCode`、realtime `GetFHYFloodSensorInfoRt` | `.NET /Date(ms)/` `SourceTime` | 不需 token | `ready_implemented` | 已新增 `local.hsinchu_city.flood_sensor`；依 `CityCode=10018` 過濾新竹市站點後 join 即時水深。 |
| 南投縣 | 雨水下水道水位 | 南投雨水下水道即時水情監測系統 | KML：`https://dpinfo.nantou.gov.tw/Api/Proxy/GetKML` | description JSON `更新時間` | 不需 token | `ready_implemented` | 已新增 `local.nantou.sewer_water_level`；KML Placemark description 內嵌 JSON，保留水位高度與時雨量。 |
| 雲林縣 | 水位站 | 雲林水情災情監控系統 | JSON API：`https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5` | `latestUpdateTime` | 不需 token | `ready_implemented` + `needs_review` | 已新增 `local.yunlin.water_level`；2026-06-28 smoke：totalCount 2473，stationType 水位 161 站；adapter 取 102 筆具 `levelHeight/latestUpdateTime` 與座標的水位資料，normalized 101、stale reject 1。淹水感測 173 站目前未曝露 depth，不以 `alarmState` 偽造淹水深度。 |
| 嘉義縣 | 淹水感測器 | 嘉義縣智慧防汛公開 RFD API | JSON：`https://api.floodsolution.aiot.ing/api/public/devices/RFD` | `latest.time` | 不需 token | `ready_implemented` | 已新增 `local.chiayi_county.flood_sensor`；公開端點 253 站，保留 `waterDepth`、電池、鄉鎮村里與 WGS84 座標。登入型 `/api/v1` 管理端點不納入。 |
| 高雄市 | 雨水下水道水位 | 高雄市智慧水利監測密網平台 | JSON：`https://wrbswi.kcg.gov.tw/SFC/api/sewer/rt` | `time` | 不需 token | `ready_implemented` | 已新增 `local.kaohsiung.sewer_water_level`；2026-06-28 smoke 296 筆，含 `stage`、警戒值與 WGS84 座標；其中 1 筆 2027 未來時間保留 raw 但 normalized reject。 |
| 高雄市 | 淹水感測器 | 高雄市智慧水利監測密網平台 | JSON：`https://wrbswi.kcg.gov.tw/SFC/api/khfloodinfo/sta_info/lastest/wrs_flooding_sensor` | `time` | 不需 token | `ready_implemented` | 已新增 `local.kaohsiung.flood_sensor`；2026-06-28 smoke 171 筆，含 `obs_value`、站名、鄉鎮與 WGS84 座標。 |
| 高雄市 | 雨量 | 高雄市智慧水利監測密網平台 | JSON：realtime `https://wrbswi.kcg.gov.tw/SFC/api/rain/rt`；metadata `https://wrbswi.kcg.gov.tw/SFC/api/rain/base` | `DATE` | 不需 token | `ready_implemented` | 已新增 `local.kaohsiung.rainfall`；2026-06-29 live adapter：rain/rt 87 筆 normalized，rain/base 88 筆 metadata，`ST_NO` join 可取得站名、地址與座標，站數會隨平台即時狀態浮動；保留 `M10`、`M20`、`H1`、`H3`、`H6`、`H12`、`H24`；只補強 CWA 空間密度，不取代 CWA。 |
| 宜蘭縣 | 淹水感測器 | 宜蘭縣防汛儀表板 ArcGIS REST layer 0 | JSON：`https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/防汛儀表板/MapServer/0/query?where=1=1&outFields=*&f=json` | `write_date` epoch milliseconds | 不需 token | `ready_implemented` | 已新增 `local.yilan.flood_sensor`；2026-06-28 smoke 85 筆，`water_inner` 以公分淹水深度解讀。 |
| 宜蘭縣 | 水位計 | 宜蘭縣防汛儀表板 ArcGIS REST layer 2 | JSON：`https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/防汛儀表板/MapServer/2/query?where=1=1&outFields=*&f=json` | `write_date` epoch milliseconds | 不需 token | `ready_implemented` | 已新增 `local.yilan.water_level`；2026-06-28 smoke 154 筆，`water_inner` 以公尺水位解讀，保留 `war_ele` 警戒水位。 |
| 澎湖縣 | 智慧水位計 | 澎湖縣 ArcGIS REST layer 6 | JSON：`https://ph3dgis.penghu.gov.tw/server/rest/services/SewerNew/PHSewer_Basemap/MapServer/6/query?where=1%3D1&outFields=*&f=json&returnGeometry=true&outSR=4326` | `measure_time` epoch milliseconds（台灣 wall-clock 編碼） | 不需 token | `ready_implemented` | 已新增 `local.penghu.water_level`；2026-06-28 smoke 38 筆、normalized 38；`water_level` 以毫米曝露並轉公尺，`measure_time` 需扣 8 小時後做 freshness check。 |
| 臺南市 | 淹水感測器 | data.gov.tw dataset `128983` | JSON API：`https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c`；metadata：`https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864` | `InfoTime` | 不需 token | `ready_implemented` | 已有 `local.tainan.flood_sensor`。2026-06-30 另查水位站、抽水站、水門靜態資料與區域排水即時影像；這些只作 metadata 或 non-qualifying 線索，不補 `sewer_water_level`、`pump_or_gate_status`。 |

## 22 縣市地方來源覆蓋矩陣

| 縣市 | 目前地方來源狀態 | 最佳候選 | 缺口 / 下一步 |
| --- | --- | --- | --- |
| 臺北市 | `ready_implemented` + `status_only_verified` | 雨水下水道水位、河川水位、抽水站即時資訊；疏散門/水門啟閉狀態 OpenAPI | 已新增三個 local adapter，含 metadata join、逐站 stale filter、抽水站外水位 metric。疏散門 mirror 已確認只能作 `gate_status` status-only 線索，不能補 `flood_depth`；後續 request packet 追蹤淹水深度 read API 或官方不可得證明。 |
| 新北市 | `ready_implemented` + `central_aggregated_ready` | 新北 WaveGIS 水位、淹水感測、雨量、排水水位 JSON API；Civil IoT `water_12` 新北淹水感測器；Civil IoT/STA_RainSewer 雨水下水道水位；新北資料平台抽水站/水門清冊 | 已新增 `local.new_taipei.water_level`、`local.new_taipei.flood_sensor`、`local.new_taipei.rainfall`、`local.new_taipei.drainage_water_level`；四個端點均免 token，含 `datatime` 與 WGS84 座標。data.ntpc.gov.tw 抽水站/水門資料仍為靜態 metadata 背景。 |
| 基隆市 | `ready_implemented` + `central_aggregated_ready` | 基隆智慧防汛網水位、淹水感測、雨量 JSON API；Civil IoT `water_12` 基隆淹水感測器；Civil IoT/STA_RainSewer 雨水下水道水位 | 已新增 `local.keelung.water_level`、`local.keelung.flood_sensor`、`local.keelung.rainfall`；三個端點均免 token。2026-06-28 smoke：water 11 筆、flood 49 筆、rain 18 筆；live adapter normalized rain 16、stale reject 2。pump station 狀態另案建模，不在本輪轉成 water evidence。RainSewer live smoke：25 站。 |
| 桃園市 | `ready_implemented` | 水位站、路面淹水感測器、雨量站 XML | 已新增水位、路面淹水感測與雨量 adapter；雨量欄位保留原始 `Rainfall` 語意，不推定累積窗格。 |
| 新竹市 | `ready_implemented` + `central_aggregated_ready_implemented` | 新竹市 sewer base/rt API、FHY Broker 新竹市淹水感測器；Civil IoT `water_12`、STA_RainSewer、`water_14`、`water_15` | 已新增 `local.hsinchu_city.sewer_water_level` 與 `local.hsinchu_city.flood_sensor`；sewer 以 `Dev_UUID` join station metadata，FHY 依 `CityCode=10018` 過濾。地方靜態抽水站/區排清冊仍作 metadata 背景。 |
| 新竹縣 | `ready_implemented` + `central_aggregated_ready` | FHY Broker 新竹縣政府淹水感測器；Civil IoT `water_12` 新竹縣淹水感測器；Civil IoT/STA_RainSewer 雨水下水道水位 | 已新增 `local.hsinchu_county.flood_sensor`；FHY CityCode 10004、Supplier=新竹縣政府 22 站，2026-06-28 live adapter fetched 22、normalized 20、stale reject 2。 |
| 苗栗縣 | `ready_implemented` + `candidate_contract_blocker` + `central_aggregated_ready` | FHY Broker 苗栗縣政府淹水感測器；Civil IoT `water_12` 苗栗淹水感測器；Civil IoT/STA_RainSewer 雨水下水道水位；雨水下水道水位監測計畫 | 已新增 `local.miaoli.flood_sensor`；FHY CityCode 10005、Supplier=苗栗縣政府 42 站，2026-06-28 live adapter fetched 42、normalized 40、stale reject 2。2026-06-30 官方成果頁確認 10 個鄉鎮市都市計畫區設置 58 處雨水下水道水位監測站，且有每月維護/月報，但公開內容只有 HTML 文章與 JPG 會議圖片，缺 `observed_at`、站點 ID、測值、單位與可 join WGS84 metadata；未公開 read API contract 前不納入 production ingestion。 |
| 臺中市 | `ready_implemented` + `central_aggregated_ready` | 臺中市水位站水情 JSON；WRA IoW 淹水深度 | 已新增 `local.taichung.water_level`，使用官方 live URL 並拒絕 stale row。 |
| 彰化縣 | `ready_implemented` + `central_aggregated_ready` | FHY Broker 彰化縣政府淹水感測器；WRA IoW 淹水深度；Civil IoT 淹水深度、STA_RainSewer、閘門外水位；縣管區排/抽水站年度統計 | 已新增 `local.changhua.flood_sensor`；FHY CityCode 10007、Supplier=彰化縣政府 70 站，2026-06-28 live adapter fetched/normalized 70。縣府 ArcGIS 水位計圖資目前只作 metadata。 |
| 南投縣 | `ready_implemented` + `central_aggregated_ready` | 南投雨水下水道 KML；WRA IoW 淹水深度、WRA 即時水位、Civil IoT/STA_RainSewer 雨水下水道水位 | 已新增 `local.nantou.sewer_water_level`；KML Placemark description 內含水位高度、時雨量與更新時間。 |
| 雲林縣 | `ready_implemented` + `needs_review` + `central_aggregated_ready_implemented` | 雲林 iflood station API 水位站；WRA IoW 淹水深度；Civil IoT 淹水深度、STA_RainSewer、抽水站水位、閘門外水位；地方淹水感測器/抽水站/水門清冊 | 已新增 `local.yunlin.water_level`；公開 station API 免 token，水位類 161 站中 102 筆具備可用水位觀測，live adapter normalized 101、stale reject 1。同一 API 的淹水感測 173 站目前只有 `alarmState` 與警戒門檻、沒有 depth 欄位，維持 `needs_review`，不得偽造淹水深度。 |
| 嘉義市 | `ready_implemented` | 水位、雨量即時 CSV | 已新增 `local.chiayi_city.water_level` 與 `local.chiayi_city.rainfall`；雨量只作 CWA 補強，不取代 CWA。 |
| 嘉義縣 | `ready_implemented` + `central_aggregated_ready_implemented` | 嘉義縣公開 RFD API；WRA IoW 淹水深度；Civil IoT/SensorThings 淹水、STA_RainSewer、抽水站、閘門；地方轄內抽水站 CSV | 已新增 `local.chiayi_county.flood_sensor`；公開 RFD API 含 253 站、`latest.time`、`waterDepth`、座標與鄉鎮村里。登入型 `/api/v1` 管理端點仍需授權，不列 production。 |
| 臺南市 | `ready_implemented` + `metadata_only` + `non_qualifying` | 淹水感測器 JSON；區域排水水位站、抽水站、水門靜態資料；區域排水即時影像；水利署與臺南市合建淹水感測器資料 | 已接入 `local.tainan.flood_sensor`。2026-06-30 查核：水位站/抽水站/水門資料為靜態 metadata，可作站點線索但缺即時觀測值；區域排水即時影像只回 CCTV `ImageUrl`，不是水位或抽水/水門狀態；合建淹水感測端點 live smoke 回 `data:null`。臺南市仍缺 `sewer_water_level`、`pump_or_gate_status` production read API。 |
| 高雄市 | `ready_implemented` + `central_aggregated_ready_implemented` | 高雄 SFC sewer/rt、SFC 淹水感測、SFC rain/rt + rain/base；Civil IoT 淹水感測器、STA_RainSewer、Civil IoT 抽水站；高雄閘門及抽水站靜態清冊 | 已新增 `local.kaohsiung.sewer_water_level`、`local.kaohsiung.flood_sensor` 與 `local.kaohsiung.rainfall`；rain/rt 以 `ST_NO` join rain/base 取得站名、地址與 WGS84 座標。抽水站/水門靜態清冊仍作 metadata 背景。 |
| 屏東縣 | `ready_implemented` + `central_aggregated_ready_implemented` + `candidate` + `needs_review` | FHY Broker 屏東縣政府淹水感測器；Civil IoT 淹水感測器、STA_RainSewer、Civil IoT 抽水站/閘門；屏東防災平台 `/RainStation`、`/River`、`/Flood`、`/Crawler` | 已新增 `local.pingtung.flood_sensor`；FHY CityCode 10013、Supplier=屏東縣政府 20 站，2026-06-28 live adapter fetched/normalized 20。2026-06-30 查核：PTEOC `/RainStation/Details/*` 可讀雨量值但缺 `observed_at` 與可 join 座標 metadata；`/Flood/Details/*` 是雨量警戒門檻，不是淹水深度；`/Crawler/Details/*` 是 CCTV 影像，不是水位量測；未取得官方 read API 前不納入 production。 |
| 宜蘭縣 | `ready_implemented` + `central_aggregated_ready` | 宜蘭防汛儀表板 ArcGIS REST layer 0/2；Civil IoT 淹水深度、Civil IoT/STA_RainSewer 雨水下水道水位、WRA 即時水位 | 已新增 `local.yilan.flood_sensor` 與 `local.yilan.water_level`；layer 0 `water_inner` 解讀為公分淹水深度，layer 2 `water_inner` 解讀為公尺水位。 |
| 花蓮縣 | `ready_implemented` + `central_aggregated_ready_implemented` + `needs_application` | FHY Broker 花蓮縣政府淹水感測器；Civil IoT 淹水深度、Civil IoT/STA_RainSewer 雨水下水道水位、閘門外水位；花蓮行動水情登入型儀表板 | 已新增 `local.hualien.flood_sensor`；FHY CityCode 10015、Supplier=花蓮縣政府 13 站，2026-06-28 live adapter fetched/normalized 13。Senslink 儀表板仍需授權才可確認更完整 read API contract。 |
| 臺東縣 | `ready_implemented` + `central_aggregated_ready` + `candidate_contract_blocker` | FHY Broker 臺東縣政府淹水感測器；Civil IoT 淹水深度、Civil IoT/STA_RainSewer 雨水下水道水位、WRA 即時水位；臺東洪水/淹水預警系統、審計部水情預警系統說明 | 已新增 `local.taitung.flood_sensor`；FHY CityCode 10014、Supplier=臺東縣政府 2 站，2026-06-28 live adapter fetched/normalized 2。2026-06-30 縣府新聞頁只證實水情監測系統使用淹水感測、水位站、雨量站與即時影像；審計部頁證實已介接 CWA 49 雨量站、WRA 9 水位站。兩者都未公開 latest-observation read API、觀測列或站點 metadata contract，未取得前不納入 production ingestion。 |
| 澎湖縣 | `ready_implemented` + `central_aggregated_ready` | 澎湖 ArcGIS REST 智慧水位計 layer 6；STA_RainSewer；區域排水疏濬工程靜態資料 | 已新增 `local.penghu.water_level`；ArcGIS REST 免 token，含 `measure_time`、`water_level`、`water_level_percent`、`battery`、`rssi` 與 WGS84 geometry。`measure_time` 為台灣 wall-clock epoch 編碼，adapter 會扣 8 小時後做 freshness check。 |
| 金門縣 | `central_aggregated_ready` + `needs_application` | Civil IoT 淹水感測器、STA_RainSewer；KWIS SOAP/ASMX token-gated read methods | 2026-06-30 查核：KWIS ASMX/WSDL 列出 `KWIS_Get_Rain_Gauge_Basic_Unit_Data`、`KWIS_Get_Water_Level_Gauge_Basic_Unit_Data`、`KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data`、`KWIS_Get_Pump_Basic_Unit_Data` 與 station sensor list；空 Token smoke 回 `ErrMsg (7)`、`Data: []`。因此可申請 read-side 授權，但未取得正式 Token 前不作 production ingestion。Civil IoT live smoke：淹水感測 7 站、RainSewer 29 站，可作中央主幹補強但不等於地方政府 read API。 |
| 連江縣 | `not_found` + `metadata_only` + `central_aggregated_ready` + `non_qualifying` | CWA 雨量、CWA 潮位（馬祖潮位站）、NCDR CAP；大潮、豪雨易淹水地區 ODS；連江自來水廠水庫水位月報；連江縣資訊公開查詢系統即時監測值 | 2026-06-28 嚴格查核：只找到靜態 ODS/防災資料，無地方 live API；RainSewer live smoke count=0。2026-06-30 追加查核：CWA `O-B0075-001` + `O-B0076-001` 可取得馬祖潮位站沿海水位與座標，已補足最低中央 hydrologic backbone；但它是 coastal tide level，不是地方直連的道路淹水、雨水下水道、抽水站或水門量測。自來水廠水庫水位月報與 `erbwater` 放流水 CEMS 仍列 `non_qualifying`。 |

## 第二輪嚴格地方直連查核摘要

查核時間：2026-06-28。判準：只有地方政府 open data、data.gov.tw、
地方水利/防災機關官方文件或公開 API landing page 明列的可機器讀取
live endpoint 才能列為 `ready`。HTML 前台、未文件化前端 API、中央資料
不列為地方直出 production adapter。

| 縣市 | 嚴格查核狀態 | 可追溯官方來源 | API / 格式 | 認證 | 即時性判斷 | ingestion 決策 |
| --- | --- | --- | --- | --- | --- | --- |
| 新北市 | `ready_implemented` | 新北 WaveGIS 委外智慧水情平台；新北市各抽水站資訊、新北市水門資料 | WaveGIS JSON API；data.ntpc.gov.tw JSON/CSV/XML 靜態資料 | 不需 | 2026-06-28 smoke：water 73 筆 normalized 55、flood 147 筆 normalized 147、rain 123 筆 normalized 114、drainage 40 筆 normalized 40，均含 `datatime` 與 WGS84 座標 | 已新增 `local.new_taipei.water_level`、`local.new_taipei.flood_sensor`、`local.new_taipei.rainfall`、`local.new_taipei.drainage_water_level`；靜態清冊只作 metadata 背景。 |
| 基隆市 | `ready_implemented` | 基隆市智慧防汛網平台 | JSON API：`water_extra_api/flood/getFloodListData`、`water_extra_api/rain/getRainFallBaseData` | 不需 | 2026-06-28 smoke：water 11 筆、flood 49 筆、rain 18 筆，均含 `datatime` 與 WGS84 座標；rain 2 站 stale reject | 已新增 `local.keelung.water_level`、`local.keelung.flood_sensor`、`local.keelung.rainfall`。 |
| 新竹市 | `ready_implemented` | 新竹市 sewer base/rt API；FHY Broker 新竹市淹水感測 | JSON GET；ASMX JSON POST | 不需 | 2026-06-28 smoke：sewer rt 含 `Time`、`WaterDepth`；FHY `SourceTime` 為 epoch ms | 已新增 `local.hsinchu_city.sewer_water_level`、`local.hsinchu_city.flood_sensor`。 |
| 新竹縣 | `ready_implemented` | FHY Broker 新竹縣政府淹水感測器；新竹縣防災資訊網監控資訊、新竹縣開放資料專區 | SOAP/ASMX JSON POST；其他地方資料多為入口/靜態 | FHY 不需 | 2026-06-28 smoke：CityCode 10004，Supplier=新竹縣政府 22 站，normalized 20、stale reject 2 | 已新增 `local.hsinchu_county.flood_sensor`；只保留地方政府 supplier。 |
| 苗栗縣 | `ready_implemented` + `candidate_contract_blocker` | FHY Broker 苗栗縣政府淹水感測器；苗栗縣水利處雨水即時水情監測成果 | SOAP/ASMX JSON POST；雨水下水道監測目前只有 HTML 成果說明與 JPG 圖片 | FHY 不需 | 2026-06-28 smoke：CityCode 10005，Supplier=苗栗縣政府 42 站，normalized 40、stale reject 2；2026-06-30 curl smoke：成果頁說明 58 處水位監測站、10 個鄉鎮市都市計畫區、每月維護與月報，但未公開 latest-observation read API 或站點 metadata 檔。 | 已新增 `local.miaoli.flood_sensor`；雨水下水道監測系統等待公開 API。 |
| 彰化縣 | `ready_implemented` | FHY Broker 彰化縣政府淹水感測器；data.gov.tw dataset `41415`、`28916`；彰化 ArcGIS 水位計 layer | SOAP/ASMX JSON POST；CSV/BIG5 靜態清冊；ArcGIS metadata | FHY/metadata 不需 | 2026-06-28 smoke：CityCode 10007，Supplier=彰化縣政府 70 站，normalized 70；ArcGIS layer 缺 observed_at/即時水位值 | 已新增 `local.changhua.flood_sensor`；ArcGIS 只作 metadata。 |
| 南投縣 | `ready_implemented` | 南投雨水下水道即時水情監測系統 | KML | 不需 | 2026-06-28 smoke：69 個 Placemark，內嵌 JSON 含水位、時雨量、更新時間 | 已新增 `local.nantou.sewer_water_level`。 |
| 雲林縣 | `ready_implemented` + `needs_review` | 雲林水情災情監控系統、雲林縣淹水感測器/抽水站/水門 open data | JSON API：`/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5`；靜態清冊 JSON/CSV/XML | 不需 | 2026-06-28 smoke：totalCount 2473，水位類 161 站；102 筆具可用水位觀測，normalized 101、stale reject 1；淹水感測 173 站未曝露 depth | 已新增 `local.yunlin.water_level`；淹水感測僅保留待查，不以 `alarmState` 偽造淹水深度。 |
| 嘉義縣 | `ready_implemented` | 嘉義縣公開 RFD API、嘉義縣水利處 open data、data.gov.tw dataset `99764` | JSON；抽水站 CSV 靜態清冊 | RFD public 不需；`/api/v1` 管理端點需登入 | 2026-06-28 smoke：RFD public 253 站，含 latest time、waterDepth、座標 | 已新增 `local.chiayi_county.flood_sensor`；管理 API 不納入。 |
| 高雄市 | `ready_implemented` | 高雄市智慧水利監測密網平台、水情 e 點靈 | JSON | 不需 | 2026-06-28 smoke：sewer/rt 296 筆、wrs_flooding_sensor 171 筆，均含時間與座標；2026-06-29 live adapter：rain/rt 87 筆 normalized，join rain/base 88 筆 metadata 取得站名與 WGS84 座標 | 已新增 `local.kaohsiung.sewer_water_level`、`local.kaohsiung.flood_sensor`、`local.kaohsiung.rainfall`。 |
| 屏東縣 | `ready_implemented` + `candidate` + `needs_review` | FHY Broker 屏東縣政府淹水感測器；屏東防災資訊整合平台、縣府智慧防災新聞 | SOAP/ASMX JSON POST；HTML/平台服務；`/RainStation` 可讀雨量表但缺觀測時間與座標；`/Flood` 為警戒門檻；`/Crawler` 為 CCTV 影像 | FHY 不需；PTEOC 未公開 API | 2026-06-28 smoke：FHY CityCode 10013，Supplier=屏東縣政府 20 站，normalized 20；2026-06-30 PTEOC 查核確認缺 `observed_at`、座標 metadata，且部分頁面非量測 | 已新增 `local.pingtung.flood_sensor`；PTEOC 只列 public API contract blocker，不得以 `fetched_at` 偽裝觀測時間。 |
| 宜蘭縣 | `ready_implemented` | 宜蘭縣防汛儀表板 ArcGIS REST | ArcGIS REST JSON layer 0/2 | 不需 | 2026-06-28 smoke：layer 0 85 筆、layer 2 154 筆，含 write_date epoch ms、water_inner、座標 | 已新增 `local.yilan.flood_sensor`、`local.yilan.water_level`。 |
| 花蓮縣 | `ready_implemented` + `needs_application` | FHY Broker 花蓮縣政府淹水感測器；花蓮行動水情首頁、花蓮縣府防汛整備新聞 | SOAP/ASMX JSON POST；Senslink 內頁登入導向 | FHY 不需；Senslink 需要帳密或官方授權 | 2026-06-28 smoke：FHY CityCode 10015，Supplier=花蓮縣政府 13 站，normalized 13；Senslink 首頁 200 但內頁 302 login | 已新增 `local.hualien.flood_sensor`；Senslink 需授權後再確認 read API。 |
| 臺東縣 | `ready_implemented` + `candidate_contract_blocker` | FHY Broker 臺東縣政府淹水感測器；臺東縣府防汛新聞、審計部臺東水情預警系統說明 | SOAP/ASMX JSON POST；縣府新聞/審計摘要未公開 read API endpoint | FHY 不需 | 2026-06-28 smoke：FHY CityCode 10014，Supplier=臺東縣政府 2 站，normalized 2；2026-06-30 查核：新聞頁提及淹水感測、水位站、雨量站與即時影像，審計部頁證實 CWA 49 雨量站與 WRA 9 水位站 integration，但缺 `observed_at`、站點 ID、測值、單位與可 join WGS84 metadata | 已新增 `local.taitung.flood_sensor`；臺東預警系統等待公開 API contract，新聞/稽核摘要與影像線索不可作 realtime measurements。 |
| 澎湖縣 | `ready_implemented` | 澎湖縣 ArcGIS REST 智慧水位計 layer 6；data.gov.tw dataset `156926` | ArcGIS REST JSON；靜態 JSON/CSV/XML | 不需 | 2026-06-28 smoke：38 筆 normalized、0 筆 rejected，含 `measure_time`、`water_level`、`water_level_percent`、WGS84 geometry；`measure_time` 需扣 8 小時後解讀 | 已新增 `local.penghu.water_level`；登入型下水道儀表板與靜態資料不納入 realtime evidence。 |
| 金門縣 | `needs_application` | 金門水情系統、API 介接申請及使用說明 PDF、KWIS ASMX/WSDL | SOAP/ASMX token-gated read methods + 上傳服務 | 需縣府審核 `KWIS_key`、帳密與 Token；空 Token 不可讀 | read methods 需回 `observed_at`、station/device id、measurement value、unit/type、座標或測站清冊 | 已確認 read method 名稱，但仍非免授權 open API；需人工申請正式 Token、rate limit 與 response schema。 |
| 連江縣 | `metadata_only` + `central_aggregated_ready` | 連江縣開放資料查詢、防救災資訊網；CWA `O-B0075-001` + `O-B0076-001` | ODS 靜態易淹水地區資料；CWA 馬祖潮位站沿海水位觀測與站點 metadata | CWA 需 `CWA_API_AUTHORIZATION` | 地方資料無即時欄位；CWA 潮位為中央沿海水位脈絡 | 不新增 local adapter。中央最低 hydrologic backbone 已由 CWA 潮位補足；地方 live API 仍未找到，仍缺 `flood_depth`、`sewer_water_level`、`pump_or_gate_status`。 |

## 已落地 production adapter

截至 2026-06-28，本文件對應的地方與中央補強 adapter 已落地如下：

1. `local.taipei.sewer_water_level`（已實作）
2. `local.taipei.river_water_level`（已實作）
3. `local.taipei.pump_station`（已實作）
4. `local.taoyuan.flood_sensor`（已實作）
5. `local.taoyuan.water_level`（已實作）
6. `local.taoyuan.rainfall`（已實作；保留 Rainfall 原始窗格語意）
7. `local.chiayi_city.water_level`（已實作）
8. `local.chiayi_city.rainfall`（已實作）
9. `local.taichung.water_level`（已實作）
10. `official.wra_iow.flood_depth`（已實作 latest + basic metadata join）
11. `local.tainan.flood_sensor`（既有 adapter，已納入 coverage catalog）
12. `local.hsinchu_city.sewer_water_level`（已實作）
13. `local.hsinchu_city.flood_sensor`（已實作）
14. `local.nantou.sewer_water_level`（已實作）
15. `local.chiayi_county.flood_sensor`（已實作）
16. `local.kaohsiung.sewer_water_level`（已實作）
17. `local.kaohsiung.flood_sensor`（已實作）
18. `local.kaohsiung.rainfall`（已實作；rain/rt join rain/base，地方雨量只補強 CWA）
19. `local.yilan.flood_sensor`（已實作）
20. `local.yilan.water_level`（已實作）
21. `local.keelung.water_level`（已實作）
22. `local.keelung.flood_sensor`（已實作）
23. `local.keelung.rainfall`（已實作；stale 站保留 raw、normalized reject）
24. `local.yunlin.water_level`（已實作；淹水感測 depth 欄位仍待查）
25. `local.new_taipei.water_level`（已實作）
26. `local.new_taipei.flood_sensor`（已實作）
27. `local.new_taipei.rainfall`（已實作；stale 站保留 raw、normalized reject）
28. `local.new_taipei.drainage_water_level`（已實作）
29. `local.penghu.water_level`（已實作；ArcGIS epoch 需扣 8 小時後判讀）
30. `local.hsinchu_county.flood_sensor`（已實作；FHY local-government supplier only）
31. `local.miaoli.flood_sensor`（已實作；FHY local-government supplier only）
32. `local.changhua.flood_sensor`（已實作；FHY local-government supplier only）
33. `local.pingtung.flood_sensor`（已實作；FHY local-government supplier only）
34. `local.hualien.flood_sensor`（已實作；FHY local-government supplier only）
35. `local.taitung.flood_sensor`（已實作；FHY local-government supplier only）
36. `official.cwa.tide_level`（已實作；CWA `O-B0075-001` + `O-B0076-001`，沿海潮位水位脈絡）

## 下一批候選

1. 屏東 PTEOC 來源：`/RainStation/Details/*` 可讀雨量窗格但缺 `observed_at`
   與可 join 座標 metadata；`/Flood/Details/*` 是雨量警戒門檻，不是淹水深度；
   `/Crawler/Details/*` 是 CCTV 影像，不是水位量測。未取得官方 read API 或
   station metadata 前維持 `needs_review` / public API contract blocker。
2. 雲林淹水感測：同一 station API 目前只曝露 `alarmState` 與警戒門檻，未曝露 depth；需找前端細節 API 或官方欄位文件。
3. 花蓮、金門：花蓮 FHY local adapter 已可運作，但 Senslink 登入型儀表板仍需帳密、
   key、token 或官方授權；金門 KWIS 已確認 token-gated read methods，仍需人工申請正式 read-side Token、可讀範圍與 response schema。
4. 苗栗、臺東：FHY local adapter 已可運作；苗栗官方成果頁已證實雨水下水道
   58 處水位監測站存在，但目前只公開 HTML/JPG 成果說明，仍缺 read API
   contract；臺東官方說明中的其他系統仍未找到公開 API contract。
5. 連江：CWA 馬祖潮位站已補足最低中央水文骨幹；連江自來水廠水庫水位月報與
   `erbwater` 即時監測頁已查核，前者是月報 PDF，後者是放流水環保 CEMS，
   均列為 `non_qualifying`，不可轉作 production adapter 或補足地方直連的
   `flood_depth`、`sewer_water_level`、`pump_or_gate_status`。

## 實作約束

- 每個地方 adapter 預設關閉，必須同時有 `SOURCE_LOCAL_<COUNTY>_*_ENABLED`
  與 `SOURCE_LOCAL_<COUNTY>_*_API_ENABLED`。
- `WORKER_ENABLED_ADAPTER_KEYS` 不得繞過地方 source gate 或 API gate。
- 每筆資料必須保存 raw snapshot、adapter run summary、staging rejection
  reason，並進入 `official_realtime_latest` 時保留獨立 `adapter_key`。
- 若 live payload 缺座標，必須 join 官方 metadata；join 失敗不得 normalized。
- 若 live payload 有 Point 座標但缺 `county`/`town`/`village`，promotion 會使用
  `admin_area_profiles` 既有 PostGIS 行政區資料做非覆寫式反查補強；原始 payload
  已有官方行政區欄位時不覆寫。
- Admin API `GET /admin/v1/local-source-coverage` 會輸出 22 縣市地方來源
  coverage catalog，包含 `ready_implemented`、`candidate`、`needs_review`、
  `metadata_only`、`not_found`、`needs_application`、已實作 local adapter、中央主幹 fallback
  adapter、候選來源與人工申請註記；此 catalog 用於監控和升級決策，不代表
  未公開 API 的縣市已完成地方直連。頂層 `summary` 可直接供 dashboard 和
  排程使用，包含 22 縣市總數、地方直連完成/未完成數、中央最低基線完成/未完成
  數、缺水文觀測的縣市，以及待授權、待 live smoke、待公開 API contract
  驗證的縣市數與縣市清單。summary 清單採多重歸類，若同一縣市同時是
  `metadata_only` 與 `not_found`，會同時出現在 metadata release monitoring
  和 official discovery queue；這是為了避免靜態 metadata 監看掩蓋真正的
  live API 探索缺口。每個縣市也會輸出
  `local_direct_complete` 與 `central_backbone_available`，明確區分「地方政府
  直出 live API 已接上」和「中央全台主幹可提供基礎即時水情」；
  `central_backbone_signal_types` 會列出去重後的中央訊號類型，例如
  `rainfall`、`river_water_level`、`flood_depth`、`sewer_water_level`、
  `pump_water_level`、`gate_water_level`、`cap_alert`；
  `central_backbone_minimum_complete`、`central_backbone_missing_signal_types`
  與 `central_backbone_coverage_level` 作為縣市級中央主幹健康門檻。最低基線
  需要官方雨量、官方 CAP 警戒脈絡，以及至少一種水位、淹水深度、下水道、
  抽水站、閘門或埤塘水位等水文觀測。連江目前 RainSewer count=0，地方直連仍缺；
  但 CWA 馬祖潮位站已提供官方沿海水位脈絡，使中央最低門檻達標。水庫水位月報與
  放流水 CEMS 只能作排除紀錄，不可抵扣地方直連缺口。coverage level 會顯示
  `minimum_met`，但 `missing_signal_types` 仍會保留地方缺少的淹水深度、雨水下水道與抽水/水門訊號；
  頂層 `central_backbone_required_families`、
  `central_backbone_missing_families`、`central_backbone_family_complete`、
  `central_backbone_required_adapter_keys` 與 `central_backbone_missing_adapter_keys`
  用於檢查全台中央主幹是否包含必要的 CWA、WRA、NCDR、Civil IoT family 與
  production adapter key；這些欄位只代表中央主幹健康，不代表 22 縣市地方政府
  直連資料源都已完成；
  `next_action_code`、`upgrade_priority`、`blocking_reason`，用於排序後續
  補齊工作，並附上 `production_source_urls`、`candidate_source_urls`、
  `metadata_source_urls`、`application_urls`，讓實作、監控與人工申請都能
  回到可追溯的官方來源。
- Public API 的 `nearby_realtime_coverage` 是查詢點半徑內的 realtime coverage
  評估，不是縣市級 catalog 的同義詞。即使某縣市在本矩陣中是 `ready_implemented`
  或中央主幹可用，查詢點附近仍可能缺 fresh sensor；API/UI 必須分開說明
  「縣市有來源」與「附近真的有資料」，並回報最近感測器距離、500m / 1km /
  3km / 5km 站數、缺哪些 required hydrologic signals，以及 repository
  unavailable 時不可誤稱附近沒有感測器。
- 地方資料與 Civil IoT/WRA/CWA 同站或同座標重疊時，必須標記
  `duplicate_candidate` 並降低 `source_weight`，不得重複計分。目前 promotion
  對 `local.*` 官方即時 Point 資料，會查詢 150 公尺、前後 30 分鐘內同
  event type 的非 local 中央 latest；命中時寫入
  `quality_flags.duplicate_candidate=true`、`duplicate_of_adapter_key`、
  `duplicate_of_station_id`，並將 local `source_weight` 壓到 0.45。
- stale、invalid、sentinel value、座標超出台灣 bounds 的資料不得 promotion。
- Civil IoT 端點應優先使用 `https://sta.colife.org.tw/...`，保留舊
  `https://sta.ci.taiwan.gov.tw/...` 只作 explicit override 或回退候選，並建立
  endpoint health check，因官方服務可能於 2026-12-01 前後移轉。

## 待完成查核

- 第二輪嚴格查核已覆蓋新北、基隆、新竹縣市、苗栗、彰化、南投、
  雲林、嘉義縣、高雄、屏東、宜花東、澎湖、金門、連江；其中新北、
  基隆、新竹市、新竹縣、苗栗、彰化、南投、雲林、嘉義縣、高雄、
  屏東、宜蘭、花蓮、臺東、澎湖已升級為 `ready_implemented` 並完成 adapter。
  仍未完成地方直連的縣市為金門與連江；其他已完成縣市若仍列
  `candidate`、`needs_review` 或 `needs_application`，表示還有更完整的地方平台
  可追，但已有可運作的地方補強 adapter。
- `GET /admin/v1/local-source-coverage` 的 action code 用於下一輪排序：
  `request_official_authorization` 表示需要人工申請或合作授權；
  `verify_public_api_contract` 表示已有官方候選系統但缺 API 文件；
  `verify_live_smoke` 表示官方 API contract 已知，但 live smoke、freshness、
  座標或欄位語意仍需複核；
  `monitor_open_data_release` 表示目前只有靜態 metadata；
  `continue_official_discovery` 表示尚未找到候選來源；
  `operate_adapter` 表示已有 production adapter，需要持續 freshness 和
  中央主幹去重監控。
- 將 `candidate` 來源維持為觀察清單；只有官方釋出 API 文件、open-data
  landing page，或使用者完成人工申請/合作授權後，才可進入 adapter
  TDD 實作。
- 若來源只存在於地方水情網站前端，必須找到官方 API 文件或 open-data
  landing page；否則只可列為觀察，不可進 production adapter。
