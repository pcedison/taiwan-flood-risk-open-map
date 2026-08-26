# Official incident source request packets

These packets are **generated for human review only**. Nothing in this
repository submits them. An operator reads each packet, confirms the current
public entry point, and applies through the organization's own official channel.

No packet contains a credential of any kind, and every contact field is
deliberately empty so a person fills it in at submission time.

Total packets: 9

## ncdr-citizen-disaster-report

- Title: NCDR 公民回報災情事件讀取申請
- Organization: National Science and Technology Center for Disaster Reduction（國家災害防救科技中心）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://alerts.ncdr.nat.gov.tw/
- Entry point verification: `unverified_pending_operator_confirmation`
- Expected cadence: polling every 5 to 15 minutes during flood events

用途：取得公民回報的淹水／道路積水事件，作為官方評估旁邊的顯示用脈絡，不用於計分，也不會單篇改變風險等級。

Requested fields:

- `event_id`
- `event_category`
- `reported_at`
- `location_point_wgs84`
- `administrative_area_code`
- `verification_state`
- `resolution_state`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 本專案已在來源目錄登錄 NCDR CAP 告警入口；公民回報災情事件屬不同資料集，需由承辦單位確認申請窗口與可讀欄位。
- 申請時應載明：不轉載通報全文、不保存回報者身分、不對外重製原始媒體。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## ncdr-edxl-sitrep

- Title: NCDR EDXL-SitRep 災情整合資料讀取申請
- Organization: National Science and Technology Center for Disaster Reduction（國家災害防救科技中心）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://alerts.ncdr.nat.gov.tw/
- Entry point verification: `unverified_pending_operator_confirmation`
- Expected cadence: on publication, polled at most every 5 minutes

用途：取得跨機關整合的災情摘要，用於顯示官方已彙整的事件脈絡與資料缺口說明，不進入風險計分。

Requested fields:

- `sitrep_id`
- `incident_category`
- `issued_at`
- `effective_window`
- `administrative_area_code`
- `reporting_agency`
- `status`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 需確認 EDXL-SitRep 的釋出對象是否限定政府單位；若限定，本專案不申請，改以既有公開 CAP 來源為準。
- 需確認是否含個人資料欄位；若含，申請時明確要求排除。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## kinmen-kwis-read-api

- Title: 金門縣水情系統 KWIS 讀取權限申請
- Organization: Kinmen County Government（金門縣政府）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://kwis.kinmen.gov.tw/
- Entry point verification: `repo_reviewed_local_source_evidence`
- Expected cadence: 10-minute polling, with the published rate limit confirmed in writing

用途：取得金門縣地方直出的雨量、水位、淹水感測與抽水站狀態讀值，補足中央聚合資料以外的地方即時觀測。

Requested fields:

- `station_id`
- `station_name`
- `coordinates_wgs84`
- `observed_at`
- `rainfall_mm`
- `water_level_m`
- `flood_depth_cm`
- `pump_station_state`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 2026-06-30 已對 KWIS ASMX/WSDL 做過公開服務清單檢視；本申請要求的是正式讀取核可、可讀欄位清單、速率限制與使用範圍的書面確認。
- 申請文件不得填入任何實際憑證字串；核發程序由縣府決定。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## hualien-senslink-read-api

- Title: 花蓮縣 SensLink 行動水情 M2M 讀取申請
- Organization: Hualien County Government（花蓮縣政府）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index
- Entry point verification: `repo_reviewed_local_source_evidence`
- Expected cadence: 10-minute polling

用途：取得花蓮縣地方水情儀表板背後的機器可讀讀值，補足中央聚合站點以外的覆蓋。

Requested fields:

- `station_id`
- `coordinates_wgs84`
- `observed_at`
- `water_level_m`
- `rainfall_mm`
- `sensor_health_state`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 2026-06-28 記錄：花蓮行動水情屬登入型儀表板，未經核可無法確認完整讀取契約。
- 本專案不會登入、不會使用個人帳號、不會繞過登入頁取得資料。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## miaoli-drainage-read-api

- Title: 苗栗縣雨水下水道即時水情讀取契約申請
- Organization: Miaoli County Government（苗栗縣政府）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx?n=563&s=922337&sms=9560
- Entry point verification: `repo_reviewed_local_source_evidence`
- Expected cadence: 10-minute polling

用途：取得苗栗縣雨水下水道即時水情監測系統的公開讀取契約，補足都市排水積淹水訊號。

Requested fields:

- `station_id`
- `coordinates_wgs84`
- `observed_at`
- `water_level_m`
- `flood_depth_cm`
- `station_operational_state`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 2026-06-28 記錄：苗栗雨水下水道即時水情監測系統尚未公開讀取契約；縣府站點目前經由 FHY Broker 提供中央聚合讀值。
- 本申請只要求公開契約文件與欄位定義，不要求任何私有介面。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## pingtung-pteoc-read-api

- Title: 屏東縣防災平台 PTEOC 讀取契約申請
- Organization: Pingtung County Government（屏東縣政府）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://pteoc.pthg.gov.tw/
- Entry point verification: `repo_reviewed_local_source_evidence`
- Expected cadence: 10-minute polling

用途：取得屏東防災平台雨量、河川與淹水頁面背後的機器可讀讀值，特別是明確的觀測時間與官方座標。

Requested fields:

- `station_id`
- `coordinates_wgs84`
- `observed_at`
- `rainfall_mm`
- `river_stage_m`
- `flood_depth_cm`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 2026-06-28 記錄：PTEOC 的 HTML 頁面可讀，雨量表格有數值，但缺明確observed_at 與官方座標對應；本專案不會用抓取時間冒充觀測時間。
- 缺少可信觀測時間時，本專案寧可顯示資料缺口，也不產生風險數值。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## taitung-water-read-api

- Title: 臺東縣洪水與淹水預警系統讀取契約申請
- Organization: Taitung County Government（臺東縣政府）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://www.taitung.gov.tw/News_Content.aspx?n=13370&s=131527&sms=12652
- Entry point verification: `repo_reviewed_local_source_evidence`
- Expected cadence: 10-minute polling

用途：取得臺東縣地方水情與淹水預警的公開讀取契約，補足目前僅有極少數中央聚合站點的覆蓋。

Requested fields:

- `station_id`
- `coordinates_wgs84`
- `observed_at`
- `water_level_m`
- `flood_depth_cm`
- `warning_stage`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 2026-06-28 記錄：臺東縣經 FHY Broker 僅有 2 站；地方讀取契約仍未公開。
- 覆蓋不足時，本專案對該轄區維持 unknown，不以鄰近站點外推。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## lienchiang-live-water-feed

- Title: 連江縣即時水情資料讀取申請
- Organization: Lienchiang County Government（連江縣政府）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5
- Entry point verification: `repo_reviewed_local_source_evidence`
- Expected cadence: 10-minute polling if a live feed exists

用途：詢問連江縣是否存在可公開讀取的即時水情資料，作為目前完全缺乏地方即時來源的補充。

Requested fields:

- `station_id`
- `coordinates_wgs84`
- `observed_at`
- `water_level_m`
- `rainfall_mm`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 2026-06-30 記錄：目前只查到水庫水位月報 PDF 與放流水環保監測，兩者都不能當作水文觀測風險量測。
- 若確認沒有即時來源，本專案將持續在該轄區揭露資料缺口，而非改用替代推估。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None

## waze-for-cities-flood-incidents

- Title: Waze for Cities 淹水與道路事件合作資格詢問
- Organization: Waze for Cities Program（Waze for Cities 計畫）
- Submission mode: `manual_only`
- Requires human intervention: true
- Public entry point: https://www.waze.com/wazeforcities
- Entry point verification: `unverified_pending_operator_confirmation`
- Expected cadence: to be defined by the program terms

用途：確認本專案是否具備合作資格，以及淹水／道路事件資料的使用條款，作為顯示用道路事件脈絡。

Requested fields:

- `incident_id`
- `incident_category`
- `reported_at`
- `location_point_wgs84`
- `road_segment_reference`
- `confidence_or_report_count`

保存政策：僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、HTML、截圖或原始媒體。

刪除政策：來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生evidence，並保留刪除稽核紀錄。

備註：

- 先確認資格與使用條款；在條款明確允許之前，本專案不接入、不快取、也不顯示任何 Waze 資料。
- 不逆向 Waze Live Map、不繞過反爬機制、不使用個人帳號。

Contact fields left empty on purpose:

- contact_name: None
- contact_email: None
