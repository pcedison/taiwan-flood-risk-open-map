# 測站清冊與行政區來源審核 Runbook

本文件說明 migration `0035_station_inventory_and_jurisdiction_proofs.sql`
建立的證據與人工審核流程。目標不是讓系統更容易回覆「附近沒有測站」，
而是確保只有在上游清冊、最新發布結果、行政區邊界及適用來源全部可證明時，
才允許輸出 `missing_cause=no_station_in_range`。

## 目前狀態與不可誤解的事項

套用 0035 後，資料庫只有審核所需的結構及候選 seed：

- `realtime_jurisdictions` 有臺灣 22 縣市的標準代碼與名稱。
- migration **沒有**匯入任何官方縣市邊界，也沒有建立 active boundary
  snapshot。
- `realtime_jurisdiction_signal_contracts` 建立 22 縣市 × 4 種訊號的
  88 筆契約，但初始 `catalog_status` 全部是 `unreviewed`。
- `realtime_source_jurisdictions` 的 national/local 對應是待審候選 catalog，
  不是來源完整性的核准紀錄。
- migration 不會將任何 `data_sources.station_inventory_reviewed` 設為 true，
  也不會替任何來源填入已核准 manifest checksum。

因此，僅套用 migration、看到 22 筆行政區代碼、看到來源對應 seed，或看到
`station_inventory_snapshots` 有資料，都不能據此宣稱附近沒有測站。

## 證據層次

absence proof 必須同時通過下列四層，任一層缺失都要 fail closed：

1. 每個適用來源的最新測站清冊是完整的上游全量結果。
2. 最新清冊與人工核准的版本及 checksum 完全相同，且同一 ingestion run
   的最新發布資料與清冊逐站一致。
3. 查詢點可由唯一、完整、已審核的 22 縣市官方邊界 snapshot 定位；15 公里
   查詢半徑接觸到的相鄰縣市也必須納入。
4. 每個納入縣市、每種必要訊號的來源 catalog 已逐項審核，所有 required
   來源皆正常運作並各自完成清冊證明。

`station_inventory_min_count` 只用來偵測異常大幅減少，是下限警報，不是
完整性證明。

## 一、上游總筆數與分頁終止證明

可接受的 live ingestion 必須保留上游自行宣告的總筆數，並抓取到終端頁：

- 請求必須要求上游回傳 count，例如 OGC SensorThings 的 `$count=true`。
- `upstream_total` 必須來自上游回應，例如 `@iot.count`；不得用目前抓到的
  record 數量自行推算。
- 必須沿著每一個 `@iot.nextLink` 讀取後續頁，直到回應不再提供 next link。
- `pages_fetched` 必須大於 0，且只有到達終端頁才可將
  `pagination_complete` 設為 true。
- next link 循環、抓取中斷、count 缺失/無效/前後矛盾，都不能形成完整
  inventory proof。
- `source_items_seen` 是所有頁面 Thing/item 的總數，包括沒有可用 observation
  的 Thing；不能只計算成功正規化或發布的 observation。

`station_inventory_snapshots.inventory_complete=true` 只可在以下條件同時成立：

- `upstream_total` 非 null。
- `pages_fetched > 0` 且 `pagination_complete=true`。
- `source_items_seen = station_ids_seen = upstream_total`。
- `missing_station_id_count = 0`。
- `duplicate_station_id_count = 0`。
- `jsonb_array_length(station_ids) = upstream_total`。
- `manifest_sha256` 非 null。

資料庫 CHECK constraint 是最低限度的防線；審核者仍須確認 count 的來源、
分頁請求紀錄及上游契約，而不是只相信資料列上的 boolean。

## 二、station ID manifest 與 checksum

每個上游 Thing/item 都必須有可跨執行穩定辨識的 station ID，即使該 Thing
目前沒有 observation、數值無效或缺少座標，也必須納入來源清冊。顯示名稱、
本次陣列索引或 observation ID 不可當作穩定 station ID。

目前唯一允許的 manifest 格式是 `station-id-json-v1`：

1. station ID 先去除首尾空白；空字串視為缺失。
2. 依 Unicode 字串順序升冪排序並去除重複值。
3. 序列化成頂層 JSON 字串陣列，使用 UTF-8、不 ASCII escape，且逗號與冒號
   周圍不加入空白。
4. 對上述 UTF-8 bytes 計算 SHA-256，保存 64 字元小寫十六進位字串。

範例 canonical bytes：

```json
["A-001","A-002","站-003"]
```

完整 station ID 陣列只存於 `station_inventory_snapshots.station_ids`。raw
snapshot metadata、adapter metrics 與公開診斷只能帶 count、版本、checksum
及完成狀態，不應複製完整 manifest。

### 每次執行的人工檢視

先以唯讀查詢檢查最新清冊及其 ingestion outcome：

```sql
SELECT
    snapshot.adapter_key,
    snapshot.captured_at,
    snapshot.upstream_total,
    snapshot.pages_fetched,
    snapshot.pagination_complete,
    snapshot.source_items_seen,
    snapshot.station_ids_seen,
    snapshot.missing_station_id_count,
    snapshot.duplicate_station_id_count,
    snapshot.manifest_version,
    snapshot.manifest_sha256,
    snapshot.inventory_complete,
    job.status AS ingestion_status,
    job.items_fetched,
    job.items_promoted,
    job.items_rejected
FROM station_inventory_snapshots snapshot
JOIN ingestion_jobs job ON job.id = snapshot.ingestion_job_id
WHERE snapshot.adapter_key = '<adapter-key>'
ORDER BY snapshot.captured_at DESC, snapshot.id DESC
LIMIT 10;
```

需要檢查 manifest diff 時，另行匯出完整 ID；不要將清冊加入公開 log：

```sql
SELECT station_id
FROM station_inventory_snapshots snapshot
CROSS JOIN LATERAL jsonb_array_elements_text(snapshot.station_ids)
    AS manifest(station_id)
WHERE snapshot.id = '<snapshot-id>'
ORDER BY station_id;
```

審核附件至少要記錄：adapter key、上游 endpoint 與 source revision、抓取時間、
上游總筆數、頁數、manifest 版本/checksum、前一版 diff、審核人、審核時間、
不可變更的 ticket 或文件連結，以及異常時的 rollback 依據。

### 核准來源清冊

只有在至少一次受控 live run 的上游總數、終端分頁、完整 station ID 清冊與
最新發布結果都被獨立覆核後，才能更新該來源的：

- `station_inventory_reviewed=true`
- `station_inventory_min_count`：依已審證據設定的正整數異常下限
- `approved_station_manifest_version='station-id-json-v1'`
- `approved_station_manifest_sha256`：人工核准 manifest 的 checksum
- `station_inventory_reviewed_at`
- `station_inventory_review_ref`

更新必須在 transaction 中完成，並於 commit 前重新查詢目標來源與 checksum。
不得以「自動接受最新 snapshot」的排程覆寫核准值，也不得因 count 高於
minimum 就自動核准。

清冊有新增、移除或 ID 變更時，最新 checksum 會與核准值不同，系統必須立即
回到 fail-closed。操作人員須判斷這是官方變更、暫時截斷、分頁錯誤或 ID
不穩定；只有重新完成 diff 與審核，才可核准新 checksum。變更 checksum
算法時必須使用新的 manifest version 與 schema/code migration，不可沿用
`station-id-json-v1` 名稱。

### 清冊完整仍不等於可反證附近無站

Thing 清冊可能完整，但部分 Thing 沒有 observation、可用座標或成功發布結果。
目前 API 仍要求同一最新 ingestion run：

- run 成功且 final pipeline outcome 完整成功。
- `items_fetched = items_promoted = upstream_total` 且 `items_rejected = 0`。
- `official_realtime_latest` 的 station count 等於 `upstream_total`。
- manifest 中沒有缺少 latest row 的 ID，latest table 也沒有 manifest 外的 ID。

所以「清冊完整但某站沒有可用 observation」仍不能授權
`no_station_in_range`。未來若要放寬，必須先建立獨立、完整且具座標的 station
inventory spatial table 與相應審核契約。

## 三、官方 22 縣市邊界審核

`realtime_jurisdictions` 的 22 筆代碼/名稱不是幾何邊界。正式匯入必須來自
可追溯的官方資料集，並建立新的 inactive snapshot；不要直接修改已核准的
active snapshot。可從國土測繪中心的
[行政區域及界線下載頁](https://maps.nlsc.gov.tw/pro/download.jsp) 取得候選資料，
但仍須在審核附件中保存實際檔名、發布版本、下載時間與原始檔 checksum。

### 匯入證據

每個 `realtime_jurisdiction_boundary_snapshots` 必須記錄：

- `source_name`、官方 `source_url` 與不可混淆的 `source_revision`。
- `expected_count=22`。
- importer 使用的座標轉換與 MultiPolygon 正規化規格。
- 每個縣市 geometry 的 `geom_sha256`：對資料庫實際保存的 EPSG:4326
  MultiPolygon 執行 `ST_AsEWKB(geom)`，再計算 SHA-256。
- snapshot 的 `manifest_sha256`：依 `jurisdiction_code` 排序，將每筆
  `[jurisdiction_code, geom_sha256]` 組成 PostgreSQL `jsonb_agg` 陣列，取其
  `::text` UTF-8 bytes 後計算 SHA-256。此格式是資料庫契約的一部分，不可改用
  原始 SHP bytes 或不同 JSON serializer 的輸出。

`realtime_jurisdiction_boundaries` 必須恰好有 22 個不同 canonical
`jurisdiction_code`，每個 geometry 都是非空、有效的 EPSG:4326 MultiPolygon。
另須檢查離島、多部件 polygon、縣市交界、重疊/縫隙及抽樣座標；僅通過欄位
型別與 row count 不足以證明幾何正確。

資料庫會重新核對每筆 EWKB checksum 及整份 snapshot manifest。snapshot 一旦
標成 `is_complete=true` 或 active，其審核 metadata 與 boundary rows 便不可
改寫或刪除；只允許切換 `is_active` 以撤銷或原子換版。官方改版只能建立新的
snapshot。

唯讀盤點查詢：

```sql
SELECT
    snapshot.id,
    snapshot.source_name,
    snapshot.source_url,
    snapshot.source_revision,
    snapshot.expected_count,
    snapshot.imported_count,
    count(boundary.snapshot_id) AS boundary_rows,
    count(DISTINCT boundary.jurisdiction_code) AS jurisdiction_count,
    bool_and(ST_IsValid(boundary.geom)) AS all_valid,
    bool_and(NOT ST_IsEmpty(boundary.geom)) AS all_nonempty,
    snapshot.manifest_sha256,
    snapshot.approved_manifest_sha256,
    snapshot.is_complete,
    snapshot.reviewed_at,
    snapshot.review_ref,
    snapshot.is_active
FROM realtime_jurisdiction_boundary_snapshots snapshot
LEFT JOIN realtime_jurisdiction_boundaries boundary
    ON boundary.snapshot_id = snapshot.id
GROUP BY snapshot.id
ORDER BY snapshot.created_at DESC;
```

### 核准與啟用

先保持 `is_active=false`，完成雙人或等效獨立審核後才可填入：

- `imported_count=22`
- `manifest_sha256`
- 與審核附件一致的 `approved_manifest_sha256`
- `is_complete=true`
- `reviewed_at` 與 `review_ref`

只有 checksum 相等且上述欄位完整的 snapshot 才能設為 active。切換版本時應在
同一 transaction 內停用舊 snapshot、啟用新 snapshot，並確認最後恰好一筆
`is_active=true`。部分匯入、兩個 active candidate、查詢點沒有唯一 home
county，或查詢半徑內行政區無法完整解析時，都必須視為
`jurisdiction_unverified`/其他不確定狀態。

目前 repository 會用 `ST_Covers` 找唯一 home county，並以完整 15 公里查詢
半徑將相鄰縣市納入 considered jurisdictions。因此不能只審核查詢點名義上的
單一縣市。

## 四、逐縣市、逐訊號來源 catalog 審核

`realtime_jurisdiction_signal_contracts` 對每個縣市分別追蹤：

- `rainfall`
- `water_level`
- `flood_depth`
- `sewer_water_level`

狀態意義：

- `unreviewed`：尚未證明來源清單完整；預設值，必須 fail closed。
- `known_gap`：已知來源、授權或整合有缺口；仍必須 fail closed，不能把已知
  缺口解讀成附近無站。
- `reviewed_complete`：該縣市/訊號所有適用來源與互補網路已完成審核；必須有
  `reviewed_at`、`review_ref`、正數 `approved_mapping_count` 與核准的 mapping
  manifest checksum。

每個縣市/訊號契約使用 `jurisdiction-source-jsonb-v1` mapping manifest。它包含
所有適用的 national mapping，以及該縣市的 local mapping；每列依固定順序表示為：

```text
[adapter_key, signal_type, coverage_scope, jurisdiction_code,
 requirement_role, redundancy_of_adapter_key, mapping_revision]
```

依 adapter、scope、jurisdiction、role、redundancy parent、revision 排序後，以
PostgreSQL `jsonb_agg(... )::text` 的 UTF-8 bytes 計算 SHA-256。API 每次查詢都會
重算實際筆數與 checksum，並要求所有 mapping revision 與 contract revision
一致；刪除、增加、改版或改變 required/redundant 關係都會立即使舊核准失效。

每一格縣市 × 訊號的審核都要：

1. 從官方機關、資料平台及縣市公開資料逐項盤點來源，不以目前程式 registry
   或 seed 清單作為完整性的唯一依據。
2. 驗證資料授權、更新頻率、空間範圍、訊號語意、station ID 穩定性及 live
   endpoint。
3. 將全國來源以 `coverage_scope='national'`、`jurisdiction_code='TW'` 對應；
   地方來源使用 `coverage_scope='local'` 及標準 8 碼縣市代碼。
4. 預設使用 `requirement_role='required'`。只有能以清冊與空間範圍證明完全被
   另一來源涵蓋的真子集，才可標為 `redundant_subset`。
5. `redundant_subset` 必須填 `redundancy_of_adapter_key`、`reviewed_at` 與
   `review_ref`；名稱相似、部分重疊或同一主管機關都不構成冗餘證明。
6. 更新 `mapping_revision`，並將盤點清單、缺口、冗餘 diff 與審核人保存到
   review artifact。
7. 從資料庫重算 `jurisdiction-source-jsonb-v1` 的實際筆數與 checksum，寫入
   `approved_mapping_count`、`approved_mapping_manifest_sha256`。
8. 只有所有 required/互補來源已納入且沒有未處理缺口，才把該 contract 設為
   `reviewed_complete`。API 還會確認每個 `redundant_subset` 的 parent 是同訊號、
   適用該縣市且角色為 required；只填一個存在的 adapter key 並不足夠。

盤點目前狀態：

```sql
SELECT catalog_status, count(*)
FROM realtime_jurisdiction_signal_contracts
GROUP BY catalog_status
ORDER BY catalog_status;

SELECT
    contract.jurisdiction_code,
    jurisdiction.jurisdiction_name,
    contract.signal_type,
    contract.catalog_status,
    contract.mapping_revision,
    contract.reviewed_at,
    contract.review_ref
FROM realtime_jurisdiction_signal_contracts contract
JOIN realtime_jurisdictions jurisdiction
    ON jurisdiction.jurisdiction_code = contract.jurisdiction_code
WHERE contract.catalog_status <> 'reviewed_complete'
ORDER BY contract.jurisdiction_code, contract.signal_type;

SELECT *
FROM realtime_source_jurisdictions
ORDER BY coverage_scope, jurisdiction_code, signal_type, adapter_key;
```

新增 adapter、官方來源異動、訊號語意變更或 coverage map 改版時，應先將受影響
contract 降回 `unreviewed`，再做重新盤點；不可保留舊的
`reviewed_complete` 同時事後補文件。

## 五、`no_station_in_range` 最終門檻

空間查詢沒有找到 station row，只是「目前查不到」，不是 absence proof。
輸出 `no_station_in_range` 前，至少必須同時確認：

- 恰好一份完整、已審、checksum 相符且 active 的 22 縣市 boundary snapshot。
- 查詢點唯一落在一個 home county，且 15 公里範圍內所有 considered counties
  都能由該 snapshot 決定。
- considered counties 的必要訊號 contract 全為 `reviewed_complete`。
- 所有 national 與適用 local mapping 的實際筆數、manifest checksum、revision
  都與 contract 核准值一致；任何未審核、已知缺口、mapping drift 或未證實的
  冗餘關係都不存在。
- 每個 required source 已註冊、runtime 明確啟用且狀態新鮮，latest run 與
  final pipeline outcome 都成功並屬於同一批次。
- 每個 required source 的最新 station inventory proof 完整，manifest
  version/checksum 與人工核准值一致，總數不低於 reviewed minimum。
- ingestion、promotion、`official_realtime_latest` 與 manifest 的 station IDs
  逐項完全一致，沒有 reject、缺站或多站。
- 最後才是空間查詢在 15 公里內找不到該訊號的 station。

任一條件未完成、無法查詢或證據過期時，`inventory_complete` 必須為 false，
並回覆能描述不確定性的原因，例如 `inventory_unverified`、
`jurisdiction_unverified`、`source_not_configured`、`health_unknown` 或來源/
pipeline 故障；絕不能降級成 `no_station_in_range`。

## 六、變更、撤銷與稽核

- 不要就地改寫已核准 boundary snapshot 或歷史 station inventory snapshot。
- 上游 station manifest 漂移時，保留舊核准值，先 fail closed、調查 diff，
  再決定是否核准新版。
- 官方邊界改版時建立新 inactive snapshot，完成審核後原子切換。
- catalog 有新來源、來源停用或 coverage 改變時，先撤回受影響 contract 的
  complete 狀態。
- review reference 必須指向不可變更、可追溯的 ticket/簽核/稽核附件；不要
  填自由文字「已確認」。
- 發現誤核准時，先撤銷 `station_inventory_reviewed`、boundary active 狀態或
  affected catalog status，使公開 API fail closed，再進行根因分析與修正。
- 所有核准、撤銷、checksum 更新、boundary 切換及 redundancy 調整都應保存
  操作人、時間、理由、前後值與 rollback 計畫。

完成資料庫審核不代表來源授權、正式環境 egress、scheduler cadence、告警或
部署 SHA 已驗證；這些仍須依部署與 production readiness runbook 分別驗收。
