# 地方政府資料來源授權條款盤點

日期：2026-07-07
稽核依據：`docs/reviews/audit-2026-07-06-open-source-sustainability.md` finding **F4**
（「35+ 個地方政府 API adapter 完全沒有授權條款文件」）。
盤點範圍：`apps/workers/app/adapters/local_*/` 底下所有 `local.*` adapter，
對應來源矩陣 `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`
「已實測可進第一批實作的地方來源」表格（第 51–87 行）中的地方政府項目。

## 0. 目的

中央政府來源中的 CWA 雨量、WRA 水位與地理編碼在
`docs/data-sources/official/official-source-catalog.yaml` 有完整記載，每筆都附
`data_gov_dataset_id`、`data_gov_url`、`license` 三個可追溯欄位。（**注意**：
Civil IoT SensorThings 的下水道／抽水站／閘門水位 adapter 與 NCDR CAP 目前**未**
收錄於該 catalog，見第 8 節的附帶觀察；啟用這些來源前不可視為授權已審。）地方政府來源
沒有對等的文件：程式碼裡雖然每個 adapter 的 `AdapterMetadata` 都有一個
`license=` 欄位，但多數只是移植中央來源的預設字串，**沒有一個對應的、可獨立
查證的官方授權頁面連結**（沒有 `data_gov_dataset_id` 等價欄位）。本文件的目的
是把「程式碼假設的授權狀態」與「這次盤點實際查到的官方頁面內容」並列，讓接手
者一眼看出哪些來源可信、哪些只是預設值、哪些甚至與程式碼假設互相矛盾。

## 1. 法律免責聲明

**本文件是工程盤點，不是法律意見。** 撰寫者不是台灣政府資料開放或著作權法
的執業律師。文件內「已查證」欄位只代表「這次盤點時，在指定的官方網頁上看到
了某段文字」，不代表：

- 該文字構成可執行的授權契約；
- 該授權涵蓋本專案目前或未來的使用方式（快取、正規化、對外 API 轉發、地圖
  視覺化、可能的商業化）；
- 該授權狀態在盤點之後仍然有效（政府網站條款可隨時調整，且本次查證只做了
  一次性網頁擷取，未留存法律等級的存證）。

任何要「重新對外提供服務」或「把目前僅本機/內部使用的地方來源升級為
production 對外服務」的人，**必須**先完成第 2 節的查證步驟，並在必要時諮詢
熟悉台灣政府資料開放授權與著作權法的法律顧問，才能視為合法完成授權確認。

## 2. 啟用任何地方來源對外提供服務前必須完成的授權查證步驟

1. 向該地方政府開放資料平臺或主責機關（水利局/處、工務局、資訊處等）確認
   本文件對應列使用的具體端點/資料集，是否已正式登錄在該機關的開放資料
   目錄，並取得可回溯的 dataset 頁面連結（等同中央來源的 `data_gov_url`）。
2. 若查無登錄，需以正式管道（機關聯繫窗口、1999、data.gov.tw 建議留言、
   來源矩陣中已列出的「請提供正式 API contract、授權條款」等請求包，見
   `docs/data-sources/local/official-request-packets.md`）行文詢問，並取得
   書面或可稽核（含時間戳、發文者）的回覆。
3. 確認授權條款是否限制使用範圍（例如臺北市多筆資料集標註「僅供研究發展
   使用」）、是否要求回報加值應用成果、或是否禁止商業使用；若本專案的用途
   （對外公開服務、未來可能的加值/商業模式）超出授權範圍，需另行取得書面
   同意。
4. **若官方頁面出現版權保留或「未經允許請勿任意轉載、複製或做商業用途」等
   聲明**（本次盤點在南投縣、FHY Broker、高雄市水利局目前查到這類文字，見
   第 4 節），在取得書面授權前，**不得**將該來源用於 production 快取或對外
   轉發，且應評估是否需要維持停用狀態或主動下架既有 adapter。
5. 把查證結果（查證日期、查證人、佐證連結或截圖存檔路徑）更新回本文件對應
   列的「審查狀態」欄位，取代「待查證」。
6. 每個地方 adapter 目前都需要兩道 gate flag 才會實際發送請求：
   `SOURCE_LOCAL_<COUNTY>_*_ENABLED` 與 `SOURCE_LOCAL_<COUNTY>_*_API_ENABLED`
   （見矩陣文件「實作約束」一節），且程式碼裡所有地方 adapter 目前都是
   `enabled_by_default=False`。在完成上述查證前，這兩道 flag 都不應該開啟。

## 3. 盤點方法與授權現況分類

- 依據：(a) 程式碼中 `AdapterMetadata.license`/`data_gov_url` 欄位（逐一
  `grep` 讀取 `apps/workers/app/adapters/local_*/*.py`）；(b) 對每個
  `data_gov_url` 指向的頁面，以一次性瀏覽（2026-07-07）確認頁面上是否有
  明確的授權/版權聲明文字。
- 分類（「授權條款現況」欄位使用的標籤）：
  - **已查證·政府資料開放授權條款**：官方開放資料平臺的 dataset 頁面（或
    平臺專屬授權頁）明確標示「政府資料開放授權條款」（含版本號）。
  - **已查證但有但書**：同上，但頁面同時附帶額外限制文字（例如「僅供研究
    發展使用」），需要進一步確認是否涵蓋本專案用途。
  - **平臺聲明存在，端點未逐筆核對**：資料開放平臺整體有獨立的授權條款頁面
    且明確採用政府資料開放授權條款，但本次盤點使用的具體 API 端點未在該
    平臺的 dataset catalog 中找到逐筆登記，因此無法確認「這個端點」與
    「平臺授權聲明」之間有正式的登記關聯。
  - **推定，待查證**：程式碼標註 `license="Government Open Data License,
    version 1.0"`，但這次盤點在對應的官方首頁/系統首頁找不到任何授權或
    開放資料聲明；此標籤等同承認「這是工程預設推定，不是查證結果」。
  - **與官方聲明衝突**：官方頁面出現版權保留、禁止未經授權轉載/複製/商業
    使用等文字，與程式碼假設的開放授權矛盾，風險最高，需要優先查證或下架。
  - **需機關授權（已知）**：官方來源本身就是 token-gated 或明說需要縣府/
    機關審核（例如金門 KWIS），程式碼裡的 `license` 欄位已經誠實反映這一點，
    不需要额外標「推定」。
  - **官方誠實標示未定位**：程式碼裡的 `license` 欄位本身就寫「未另外定位
    到開放資料授權」（例如新北市、澎湖縣），這次盤點的網頁查證與程式碼的
    誠實標示一致，仍是「待查證」，但沒有被程式碼誤標成已授權。

## 4. 總覽：本次盤點涵蓋的來源數量

程式碼中共有 **35 個** `local.*` adapter key（34 個 production + 1 個尚未
啟用的候選 `local.kinmen.kwis_pump_station`），對應來源矩陣「已實測可進
第一批實作的地方來源」表格中的地方政府項目。矩陣該表格本身是 35 列，但其中
5 列是中央主幹訊號（WRA IoW、Civil IoT STA_RainSewer/抽水站/閘門、NCDR
CAP），1 列是 FHY Broker 的彙總描述（依 CityCode 展開為 6 個縣市的獨立
adapter key；另有新竹市 flood_sensor 也走同一 broker，見 §5.8，故 FHY 這組
授權風險實際涵蓋 7 個 adapter）。本文件以程式碼實際存在的 35 個 `local.*`
adapter key 為準逐一列出，比矩陣原始列數在「地方政府項目」的顆粒度上更細，
因此本文件的地方來源列數與矩陣列數不會逐行對應，差異原因即在此；金門 KWIS 雖不在矩陣 51–87 行的「第一批」表格內（該表格只收錄已升級為
`ready_implemented` 的來源），但因為程式碼已有候選 adapter、且稽核 F4 明確
點名「金門 KWIS」，故一併納入。

授權現況分布（35 筆）：

| 分類 | 筆數 | adapter |
| --- | --- | --- |
| 已查證·政府資料開放授權條款 | 9 | 臺北市 3、桃園市 3、嘉義市 2、臺南市 1 |
| 平臺聲明存在，端點未逐筆核對 | 1 | 臺中市 1 |
| 推定，待查證 | 8 | 基隆市 3、新竹市 1（sewer）、雲林縣 1、嘉義縣 1、宜蘭縣 2 |
| 與官方聲明衝突 | 11 | 南投縣 1、FHY 廣播來源 7（新竹縣/苗栗/彰化/屏東/花蓮/臺東 flood_sensor＋新竹市 flood_sensor）、高雄市 3 |
| 官方誠實標示未定位（程式碼已誠實） | 5 | 新北市 4、澎湖縣 1 |
| 需機關授權（已知） | 1 | 金門縣 KWIS（候選，未啟用） |

註 1：臺北市 3 筆雖歸「已查證·開放授權」，其中 2 筆另有「僅供研究發展使用」
但書，細節見第 5.1 節，不另立分類以免重複計數。

註 2：**FHY 廣播來源共 7 個 adapter**——除了 §5.8 以 CityCode 展開的 6 個縣市
（新竹縣/苗栗/彰化/屏東/花蓮/臺東 flood_sensor）外，新竹市 flood_sensor
（`local.hsinchu_city.flood_sensor`，CityCode=10018）也走同一個
`dprcflood.org.tw` FHY broker，故一併計入此衝突類（見 §5.5 與 §5.8）。任何用
本表決定「哪些 adapter 需法律審查後才可啟用」的人，務必把新竹市 flood_sensor
納入 FHY 這一組。

不重複總數：已查證 9＋平臺聲明未核對 1＋推定待查證 8＋與官方聲明衝突 11＋
誠實標示未定位 5＋需機關授權 1＝**35**。

## 5. 逐項盤點

### 5.1 臺北市（3 個 adapter，資料來源：臺北市工務局水利處／`data.taipei`）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.taipei.sewer_water_level` | 臺北市雨水下水道水位即時資訊；`data.taipei` dataset `cd444840-bbfb-4b0a-bdfa-2a36d49b3794` | 已查證但有但書：dataset 頁「資料授權：公開」並連結「政府資料開放授權條款」，但備註「原則持開放態度」（水位資料語意上偏研究性質） | 待查證——需確認是否涵蓋公開服務（非純研究）用途 | 部分已查證（2026-07-07 一次性瀏覽），尚待正式行文確認使用範圍 |
| `local.taipei.river_water_level` | 臺北市河川水位即時資訊；`data.taipei` dataset `5b4b8ae1-9505-4a1a-8808-feea14e78130` | 已查證但有但書：頁面「資料授權：公開」＋政府資料開放授權條款連結；備註明確寫「僅供研究發展使用」，開發加值應用「應向工務局水利處提供相關成果」 | 待查證——「僅供研究發展使用」是否涵蓋本專案的公開風險地圖服務，需向水利處確認；若不涵蓋，需另外取得書面同意或回報加值應用成果 | 部分已查證，尚待正式行文確認 |
| `local.taipei.pump_station` | 臺北市抽水站即時資訊；`data.taipei` dataset `2bbfb30e-de58-43bd-9cc9-b56e9a6b5369` | 已查證但有但書：頁面「資料授權：公開」＋政府資料開放授權條款連結；備註「本處抽水站運轉狀態即時資料原則持開放態度」 | 較上兩筆寬鬆，但仍待查證正式授權文字 | 部分已查證，尚待正式行文確認 |

### 5.2 新北市（4 個 adapter，資料來源：新北市政府委外 WaveGIS 智慧水情平台）

程式碼已誠實標註 `license="Official public endpoint; explicit open-data
license not separately located"`。本次瀏覽 `https://newtaipei.wavegis.com.tw/`
首頁，內容過於精簡（僅系統標題），未見任何授權或開放資料聲明，與程式碼標示
一致。

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.new_taipei.water_level` | 水位站 `flood/getFloodListData`（type=radar,water,...） | 官方誠實標示未定位 | 待查證 | 待查證，未經法律審閱 |
| `local.new_taipei.flood_sensor` | 淹水感測器 `flood/getFloodListData`（type=flood） | 官方誠實標示未定位 | 待查證 | 待查證，未經法律審閱 |
| `local.new_taipei.rainfall` | 雨量 `rain/getRainFallBaseData` | 官方誠實標示未定位 | 待查證 | 待查證，未經法律審閱 |
| `local.new_taipei.drainage_water_level` | 排水水位 `water/getDrainage` | 官方誠實標示未定位 | 待查證 | 待查證，未經法律審閱 |

### 5.3 基隆市（3 個 adapter，資料來源：基隆市政府智慧防汛網）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.keelung.water_level` | `water_extra_api/flood/getFloodListData`（水位） | 推定，待查證：程式碼標「政府資料開放授權條款 v1.0」，但 `https://smartflood.klcg.gov.tw/keelung_web/` 首頁只有泛用著作權聲明「© 2026 - 版權所有」，未見開放資料授權文字 | 待查證 | 待查證，未經法律審閱 |
| `local.keelung.flood_sensor` | 同上 API，type=flood | 同上 | 待查證 | 待查證 |
| `local.keelung.rainfall` | `water_extra_api/rain/getRainFallBaseData` | 同上 | 待查證 | 待查證 |

### 5.4 桃園市（3 個 adapter，資料來源：桃園市政府開放資料平臺）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.taoyuan.water_level` | dataset `31299`；`opendata.tycg.gov.tw/datalist/e3b34ba5-e8ff-4b21-b7a3-4b6f3bfed650` | 已查證·政府資料開放授權條款-第1版（2026-07-07 直接讀取 dataset 頁面「授權方式」欄位確認） | 依政府資料開放授權條款可再利用/散布，惟仍需依條款要求標示來源與版本資訊 | 已查證（一次性瀏覽），建議定期複查條款是否變動 |
| `local.taoyuan.flood_sensor` | dataset `152941`；`opendata.tycg.gov.tw/datalist/414be64a-c861-4c08-a94f-96fd7884fdbb` | 已查證·政府資料開放授權條款-第1版 | 同上 | 已查證 |
| `local.taoyuan.rainfall` | dataset `46407`；`opendata.tycg.gov.tw/datalist/eabd93d1-d526-4de0-b378-b529aa61a4be` | 已查證·政府資料開放授權條款-第1版 | 同上 | 已查證 |

### 5.5 新竹市（2 個 adapter：1 個自有平台、1 個經 FHY Broker）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.hsinchu_city.sewer_water_level` | 新竹市雨水下水道水情 API `swc.hccg.gov.tw` | 推定，待查證：程式碼標政府資料開放授權條款 v1.0，但 `https://swc.hccg.gov.tw/` 首頁未見任何授權或開放資料聲明 | 待查證 | 待查證，未經法律審閱 |
| `local.hsinchu_city.flood_sensor` | FHY Broker，`CityCode=10018` | 見 5.8 節「FHY Broker 共用風險」 | 待查證，見 5.8 | 待查證，見 5.8 |

### 5.6 臺中市（1 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.taichung.water_level` | 臺中市水位站水情 JSON `wrbeocin.taichung.gov.tw/TCSAFE/UploadFile/WATERLEVEL/WATERLEVEL_NEW.JSON` | 平臺聲明存在，端點未逐筆核對：`opendata.taichung.gov.tw/license-terms` 明確標示「政府資料開放授權條款－第1版」（2026-07-07 已讀取原文），但實際抓取水位資料的網域是 `wrbeocin.taichung.gov.tw`，不是 `opendata.taichung.gov.tw`，未確認此端點是否登記在同一開放資料目錄下 | 待查證——需確認 `wrbeocin.taichung.gov.tw` 端點與 `opendata.taichung.gov.tw` 平臺授權聲明的登記關聯 | 部分已查證，尚待跨網域關聯確認 |

### 5.7 嘉義市（2 個 adapter，`data.gov.tw` 正式登錄）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.chiayi_city.water_level` | `data.gov.tw/dataset/52584` | 已查證·政府資料開放授權條款-第1版（2026-07-07 直接讀取 data.gov.tw dataset 頁面確認） | 依政府資料開放授權條款可再利用/散布 | 已查證 |
| `local.chiayi_city.rainfall` | `data.gov.tw/dataset/52585` | 已查證·政府資料開放授權條款-第1版（同上方式確認） | 同上 | 已查證 |

### 5.8 FHY Broker 共用來源（7 個 adapter：新竹縣、苗栗、彰化、屏東、花蓮、臺東，＋新竹市 flood_sensor）

`FHY_DATA_URL = "https://www.dprcflood.org.tw/SGDS/"`（財團法人成大水利研究
中心受經濟部水利署委託建置的「防災協作平台」廣播端點）。這些 adapter 共用
同一個 SOAP/ASMX 廣播來源，只是依 `CityCode` 與 `Supplier` 過濾出各縣市政府
自己的測站，因此授權狀況一併討論。**新竹市 flood_sensor
（`local.hsinchu_city.flood_sensor`，CityCode=10018，見 §5.5）也走同一個
`dprcflood.org.tw` FHY broker，同屬此衝突組**，故本組實際涵蓋 7 個 adapter。

程式碼統一標註 `license="Government Open Data License, version 1.0"`，但
2026-07-07 瀏覽 `https://www.dprcflood.org.tw/SGDS/` 首頁後，看到的是：

> 本網站全部圖文版權係屬經濟部水利署所有

這是**版權保留聲明**，不是開放資料授權聲明，與程式碼假設**直接矛盾**。可能
的合理解釋是：這個廣播端點的「資料轉發」本身是水利署對地方政府的內部/跨機關
分享機制，另有制度性授權文件（例如水利署與各縣市政府、或水利署與本專案之間
若曾申請過帳號），但本次盤點在公開網頁上找不到這類佐證。**在查證到具體授權
依據前，不應將這 7 個 adapter（含新竹市 flood_sensor）視為已授權的開放資料來源。**

| adapter key | 縣市 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.hsinchu_county.flood_sensor` | 新竹縣 | 與官方聲明衝突（見上） | 待查證，暫不應視為可任意快取轉發 | 待查證，未經法律審閱 |
| `local.miaoli.flood_sensor` | 苗栗縣 | 同上 | 同上 | 同上 |
| `local.changhua.flood_sensor` | 彰化縣 | 同上 | 同上 | 同上 |
| `local.pingtung.flood_sensor` | 屏東縣 | 同上 | 同上 | 同上 |
| `local.hualien.flood_sensor` | 花蓮縣 | 同上 | 同上 | 同上 |
| `local.taitung.flood_sensor` | 臺東縣 | 同上 | 同上 | 同上 |
| `local.hsinchu_city.flood_sensor` | 新竹市（CityCode=10018，另見 §5.5） | 同上（同一 FHY broker） | 同上 | 同上 |

### 5.9 南投縣（1 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.nantou.sewer_water_level` | 南投雨水下水道即時水情監測系統 KML `dpinfo.nantou.gov.tw/Api/Proxy/GetKML` | 與官方聲明衝突：程式碼標政府資料開放授權條款 v1.0，但 2026-07-07 瀏覽 `https://dpinfo.nantou.gov.tw/` 首頁看到明確聲明「本網站為南投縣政府版權所有，請尊重智慧財產權，未經允許請勿任意轉載、複製或做商業用途」 | **不應視為可快取/轉發**——官方聲明明確禁止未經允許的轉載、複製與商業使用，與程式碼假設矛盾，風險最高 | 待查證，建議優先向南投縣政府正式行文確認（或評估是否需要下架此 adapter 的啟用路徑） |

### 5.10 雲林縣（1 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.yunlin.water_level` | 雲林水情災情監控系統 `yliflood.yunlin.gov.tw/api/v1/IfloodStation/...` | 推定，待查證：程式碼標政府資料開放授權條款 v1.0，2026-07-07 瀏覽 `https://yliflood.yunlin.gov.tw/ifloodboard/` 首頁內容過於精簡，未見授權文字 | 待查證 | 待查證，未經法律審閱 |

### 5.11 嘉義縣（1 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.chiayi_county.flood_sensor` | 嘉義縣智慧防汛公開 RFD API `https://api.floodsolution.aiot.ing/api/public/devices/RFD` | 推定，待查證：程式碼標政府資料開放授權條款 v1.0，但 (a) 2026-07-07 瀏覽程式碼引用的 `cyhg.gov.tw` 新聞頁未提及授權，只連結到一般「政府網站資料開放宣告」；(b) **實際 API 主機 `api.floodsolution.aiot.ing` 是第三方廠商網域，不是 `.gov.tw`**，需額外確認嘉義縣政府與該廠商之間的資料釋出授權關係，以及廠商自身的 API 使用條款 | 待查證，且需一併確認第三方廠商（非縣府本身）的授權範圍 | 待查證，未經法律審閱；建議向嘉義縣政府水利處確認委外廠商授權範圍 |

### 5.12 臺南市（1 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.tainan.flood_sensor` | `data.tainan.gov.tw/DataSet/Detail/03dd4536-3fe7-46ec-9920-a120cb5c502c` | 已查證·政府資料開放授權條款第一版（2026-07-07 直接讀取臺南市開放資料平台 dataset 頁面確認） | 依政府資料開放授權條款可再利用/散布 | 已查證 |

### 5.13 高雄市（3 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.kaohsiung.sewer_water_level` | 高雄市智慧水利監測密網平台 `wrbswi.kcg.gov.tw/SFC/api/sewer/rt` | 與官方聲明衝突：程式碼標政府資料開放授權條款 v1.0，但 2026-07-07 瀏覽平台入口 `https://wrb.kcg.gov.tw/WRInfo/` 只看到「高雄市政府水利局 © 2019 Water Resources Bureau. Kaohsiung City Government. All Rights Reserved.」，未見開放資料授權文字 | 待查證——泛用著作權聲明常見於政府網站且不一定代表資料本身不可利用，但仍與程式碼假設矛盾，需正式查證 | 待查證，未經法律審閱 |
| `local.kaohsiung.flood_sensor` | `wrbswi.kcg.gov.tw/SFC/api/khfloodinfo/...` | 同上 | 同上 | 同上 |
| `local.kaohsiung.rainfall` | `wrbswi.kcg.gov.tw/SFC/api/rain/rt` + `rain/base` | 同上 | 同上 | 同上 |

### 5.14 宜蘭縣（2 個 adapter）

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.yilan.flood_sensor` | 宜蘭縣防汛儀表板 ArcGIS REST layer 0 `wragis.e-land.gov.tw` | 推定，待查證：程式碼標政府資料開放授權條款 v1.0，2026-07-07 瀏覽 `https://wra.e-land.gov.tw/IlanHsdsMap/` 首頁未見授權文字 | 待查證 | 待查證，未經法律審閱 |
| `local.yilan.water_level` | 同平台 layer 2 | 同上 | 同上 | 同上 |

### 5.15 澎湖縣（1 個 adapter）

程式碼已誠實標註 `license="Official public endpoint; explicit open-data
license not separately located"`；2026-07-07 瀏覽 `https://ph3dgis.penghu.gov.tw/`
首頁內容過於精簡（僅平台標題），未見授權文字，與程式碼標示一致。

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.penghu.water_level` | 澎湖縣 ArcGIS REST layer 6 `ph3dgis.penghu.gov.tw/.../SewerNew/PHSewer_Basemap/MapServer/6/query` | 官方誠實標示未定位 | 待查證 | 待查證，未經法律審閱 |

### 5.16 金門縣（1 個候選 adapter，尚未啟用）

程式碼已誠實標註 `license="Official KWIS endpoint; production license
requires county authorization"`。矩陣文件與
`docs/data-sources/local/official-request-packets.md` 皆已記載：金門 KWIS
（`kwis.kinmen.gov.tw`）是 token-gated SOAP/ASMX 服務，空 Token 測試回
`ErrMsg (7)`；「未取得縣府授權前，不應把 KWIS 實作成 production local
adapter」。2026-07-07 瀏覽 `https://kwis.kinmen.gov.tw/` 首頁本身沒有授權或
申請流程資訊，需依既有 request packet 走正式申請流程。

| adapter key | 資料集/端點 | 授權條款現況 | 再散布/快取權利 | 審查狀態 |
| --- | --- | --- | --- | --- |
| `local.kinmen.kwis_pump_station` | KWIS ASMX read methods（含 `KWIS_Get_Pump_Basic_Unit_Data` 等） | 需機關授權（已知）：官方明確要求縣府審核 Token，程式碼已誠實標示 | 未取得正式 Token/書面授權前不得用於 production；目前 `enabled_by_default=False` 且未列入「已落地 production adapter」清單 | 已知需人工申請，尚未申請完成；候選狀態 |

## 6. 中央主幹訊號（僅供對照，不在本文件範圍）

以下訊號在矩陣文件的「已實測可進第一批實作的地方來源」表格中與地方來源並列，
但屬於中央主幹（`official.*` adapter key），F4 finding 明確指出中央來源授權
文件已完整，因此不重複收錄在本文件，僅列出交叉參照：

| 訊號 | adapter key | 授權記載位置 |
| --- | --- | --- |
| WRA IoW 淹水深度 | `official.wra_iow.flood_depth` | `docs/data-sources/official/official-source-catalog.yaml`（已有 `license`/`data_gov_url`） |
| CWA 潮位 | `official.cwa.tide_level` | 同上 |
| Civil IoT 雨水下水道水位 | `official.civil_iot.sewer_water_level` | **附帶觀察**：未見於 `official-source-catalog.yaml`，建議另案盤點（不在本次 F4 地方來源範圍內） |
| Civil IoT 抽水站水位 | `official.civil_iot.pump_water_level` | 同上附帶觀察 |
| Civil IoT 閘門外水位 | `official.civil_iot.gate_water_level` | 同上附帶觀察 |
| NCDR CAP | `official.ncdr.cap` | 同上附帶觀察 |

## 7. 高風險摘要（建議優先處理順序）

1. **南投縣** `local.nantou.sewer_water_level`——官方首頁明確禁止「未經允許
   任意轉載、複製或做商業用途」，與程式碼假設直接矛盾，且已在 production
   adapter 清單中（矩陣列為 `ready_implemented`）。建議立即向南投縣政府正式
   查證，查證完成前應評估是否暫停對外服務路徑（目前 `enabled_by_default`
   仍為 `False`，尚未預設開啟，緊急程度可控，但不應在未查證前手動開啟）。
2. **FHY Broker 共用來源（7 個 adapter：新竹縣/苗栗/彰化/屏東/花蓮/臺東
   ＋新竹市 flood_sensor）**——官方聲明版權保留，涉及面最廣（一次影響 7 個
   縣市級 flood_sensor 訊號；新竹市 flood_sensor 走同一 broker，勿遺漏，見 §5.8）。
3. **高雄市（3 個 adapter）**——泛用著作權聲明，風險低於前兩項但仍需查證。
4. **嘉義縣**——實際 API 主機是第三方廠商網域，需額外釐清廠商與縣府的授權
   鏈，而不只是縣府本身的開放資料政策。
5. 其餘「推定，待查證」與「官方誠實標示未定位」的來源，法律風險相對均質，
   建議按第 2 節查證步驟排入下一輪治理待辦，優先順序可依「已在 production
   清單中啟用」與「查詢流量大小」排序。

## 8. 已有明確授權記載、可視為相對安全的來源

以下 9 個 adapter 在本次盤點中，於官方開放資料平台的 dataset 頁面（或平臺
專屬授權頁）**直接讀取到**「政府資料開放授權條款」字樣，是本文件中證據力
最強的一組（仍建議依第 2 節第 3 點確認使用範圍是否涵蓋公開服務用途，尤其是
臺北市三筆帶有「僅供研究發展使用」但書的資料集）：

- `local.taoyuan.water_level`、`local.taoyuan.flood_sensor`、
  `local.taoyuan.rainfall`
- `local.chiayi_city.water_level`、`local.chiayi_city.rainfall`
- `local.tainan.flood_sensor`
- `local.taipei.sewer_water_level`、`local.taipei.river_water_level`、
  `local.taipei.pump_station`（均有「僅供研究發展使用」或需回報加值應用
  成果的但書，見 5.1 節）

## 9. 後續維護

- 每次新增地方 adapter，請在本文件同步新增一列，並在 PR 描述中註明授權查證
  方式（官方頁面連結或截圖存檔路徑），不要只複製既有 adapter 的 `license`
  預設字串。
- 若既有來源的官方網站內容改版，第 4～5 節的查證結果可能過期，建議每次
  「地方來源升級為 production」或「新增地方縣市補強來源」時，順便重新確認
  對應列的授權文字是否仍然一致。
- 本文件不會自動與 `apps/workers/app/adapters/local_*/*.py` 的 `license=`
  欄位保持同步；若未來要落地自動化檢查（例如比照
  `infra/scripts/validate_source_allowlist.py` 對 news/forum 來源的作法），
  可以考慮把本文件的查證結果轉成一份可被 CI 驗證的 manifest（例如
  `docs/data-sources/local/local-source-license-manifest.yaml`），但這超出
  本次盤點（純文件、不改動任何程式碼或啟用狀態）的範圍。
