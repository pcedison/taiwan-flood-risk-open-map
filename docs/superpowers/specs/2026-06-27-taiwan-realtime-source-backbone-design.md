# 台灣即時資料來源主幹設計

日期：2026-06-27
狀態：方向已確認，待撰寫實作計畫

## 目的

Flood Risk 必須能回答全台各縣市、各區、各村里與鄰里的即時淹水風險，
不能過度依賴距離查詢點偏遠的 CWA 或 WRA 測站。新的資料來源主幹會以
worker 定期擷取並可稽核的官方資料作為正式來源，其中 Civil IoT
淹水深度感測器是最貼近鄰里與路口的主要訊號，CWA、WRA、NCDR 則提供
官方輔助脈絡。

## 決策

採用方案 A：worker-first 的全台即時資料來源主幹。

Hosted public API 不應在使用者查詢期間直接擷取上游即時資料。Worker
負責排程擷取、正規化、驗證並保存官方資料。Public API 先讀取精簡的
latest observation model，再連回 evidence 與 raw snapshots 保留可稽核性。

## 目標

- 以道路淹水深度感測器與查詢點附近的水資源感測器提升即時空間相關性。
- 透過 raw snapshots、staging、promotion、source health 與 data
  freshness 保存官方來源 ingestion 的可稽核性。
- Public risk query 讀取最新站點狀態，避免掃描完整 evidence 歷史資料，
  讓查詢保持快速且有界。
- 對使用者明確揭露 stale、missing、low-confidence 或 distant source
  data，不把資料缺口默默當成低風險。
- 除非後續有獨立 calibration review，否則維持目前 scoring model 與
  event-type vocabulary。

## 非目標

- 不把未文件化的地方政府地圖內部 API 當成全台 canonical source。
- 不在 hosted API 環境加入 request-time upstream fetching。
- 不因為目前水深低或雨量低，就推論該地點歷史淹水風險低。
- 不用 latest rows 取代完整 raw evidence history。
- 除非既有 `rainfall`、`water_level`、`flood_warning`、`flood_potential`
  與 `flood_report` 無法表達來源語意，否則不新增 event type。

## 資料來源分層

### 第 0 層：語意前置條件

加入新的即時資料來源前，必須先修正並測試 timestamp semantics：

- `observed_at`：來源實際觀測時間。
- `fetched_at`：adapter 擷取時間與 raw snapshot 擷取時間。
- `ingested_at`：系統保存或 promotion 時間。
- `source_timestamp_min` 與 `source_timestamp_max`：同一 adapter batch 內
  上游觀測時間的最小值與最大值。

目前 staging code 將 `observed_at` 對應成 `evidence.fetched_at`，但 API
freshness logic 把 `observed_at` 視為來源觀測時間。這必須先修正，否則
source freshness 不可信。

### 第 1 層：全台正式即時感測來源

使用 Civil IoT Taiwan WaterResource SensorThings 作為近地面水情的全台主幹。

主要資料集：

- Civil IoT 淹水感測器，dataset `water_12`
- 官方頁面：`https://ci.taiwan.gov.tw/dsp/Views/dataset/detail.aspx?id=water_12`
- SensorThings base：`https://sta.ci.taiwan.gov.tw/STA_WaterResource_v2/v1.0/`
- 主要 event type：超過門檻的道路淹水深度作為 `flood_report`
- 輔助 metrics：`flood_depth_cm`、signal quality、station authority、
  station code、station name、geometry、latest observation time

Adapter 應只擷取相關 datastream，例如 `淹水深度`，並處理 SensorThings
pagination、拒絕 invalid 或 stale observations，同時保留 station authority
供 attribution 與 deduplication 使用。

### 第 2 層：全台輔助官方來源

以下來源作為官方脈絡，不應成為唯一即時證據：

- WRA 即時水位，dataset `25768`：
  `https://data.gov.tw/dataset/25768`
- WRA 水位站 metadata：
  `https://opendata.wra.gov.tw/api/v2/c4acc691-7416-40ca-9464-292c0c00da92`
- CWA 自動雨量，dataset `9177`，endpoint `O-A0002-001`；需要 CWA
  authorization。
- NCDR CAP disaster alerts：
  `https://alerts.ncdr.nat.gov.tw/JSONAtomFeed.ashx`
- WRA 淹水潛勢圖，dataset `25766`：
  `https://data.gov.tw/dataset/25766`

這些來源提供降雨驅動、河川與區排脈絡、官方警戒，以及規劃層級的易淹
潛勢。它們不應覆蓋查詢點附近的直接淹水深度觀測。

### 第 3 層：經審核的地方政府備援來源

地方來源只能在具備官方 landing page、清楚 license 或 terms review、穩定
machine-readable API、schema contract 與 health checks 時，補充 Civil IoT。

台南 proof-of-concept：

- 優先正式 fallback：台南開放資料平台資料集
  `https://data.tainan.gov.tw/DataSet/Detail/03dd4536-3fe7-46ec-9920-a120cb5c502c`
- 即時 API：
  `https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c`
- 站點 metadata API：
  `https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864`

台南 WMap 與其內部端點可用來理解 derived overlay，但它們沒有作為公開 API
被獨立文件化，因此不是 canonical source。

## 架構

### Worker 資料擷取

Workers 維持為 production 中唯一擷取上游即時來源的路徑。Workers 應：

1. 透過 registry 與 environment gates 選擇啟用的 adapters。
2. 使用來源專屬 timeout 與 pagination 擷取上游資料。
3. 保存 raw snapshots 與 adapter run summaries。
4. 將 records 正規化為既有 evidence event types。
5. 驗證 schema、coordinates、timestamp semantics 與 source freshness。
6. Promote accepted staging evidence。
7. Upsert latest official observations，供 public lookup 快速讀取。
8. 輸出 freshness metrics 與 source-health diagnostics。

Civil IoT 淹水感測器應從 opt-in experimental support 往 primary enabled
production candidate 前進，但在 terms、TLS、cadence 與 hosted egress 接受前，
仍必須放在明確 source gates 後面。

### 最新觀測讀取模型

實作既有規劃中的 `official_realtime_latest` table 作為 public hot path。

每一列保存單一 provider/event/station 的最新 accepted observation：

- `source_id`
- `adapter_key`
- `event_type`
- `station_id`
- `station_name`
- `authority`
- `observed_at`
- `ingested_at`
- `geom`
- 正規化 metric columns，例如 `rainfall_mm_1h`、`water_level_m`、
  `warning_level_m` 與 `flood_depth_cm`
- `confidence`
- `freshness_score`
- `source_weight`
- `risk_factor`
- `evidence_id`
- 精簡 attribution 與 source URL
- JSON metadata 內的 source quality flags

Public risk assessment 應先查詢這張 table，再 fallback 到 historical
evidence。完整的 `evidence`、`raw_snapshots` 與 `adapter_runs` tables 仍作為
audit trail。

### API 流程

Public API 應：

1. 解析 query point 與 radius。
2. 以 source-specific relevance radii 查詢 `official_realtime_latest` 中
   查詢點附近的近期 official observations。
3. 優先採用 nearby flood-depth observations，而不是 distant rainfall 或
   river-level observations。
4. 將 latest realtime observations 與 historical evidence、planning layers
   合併。
5. 回傳每個 enabled official source 的 source freshness，包含 healthy、
   stale、disabled、degraded 與 failed states。
6. 只把 direct CWA/WRA bridge 作為 local diagnostic fallback，並與 ADR-0010
   保持一致。

### 融合規則

使用 deterministic rules，讓結果可解釋：

- 查詢點附近的直接淹水深度具有最強 realtime relevance。
- Official CAP warnings 依其宣告的 alert area 生效；即使附近 sensor 未顯示
  淹水，也應作為 warning evidence 顯示。
- Rainfall 與 water level 是 driver 或 context，除非它們直接鄰近查詢點。
- Planning-layer flood potential 影響 historical 或 susceptibility context，
  不代表目前正在淹水。
- Local fallback 只有在經正式 review、更新、schema-valid 且未標示 doubtful
  時，才能 override central Civil IoT。
- WRA 與 Civil IoT 的 duplicates 依 station code、location、authority、
  observation time 與 metric type 解決。Duplicate evidence 不得在 scoring 中
  double-count。

## 資料品質關卡

每個 production source 都必須通過：

- Official landing page 或 public catalog URL。
- License 或 terms review。
- 明確 source owner 與 attribution。
- 具備 stable schema contract 的 machine-readable endpoint。
- 必要欄位：station id、observation time、metric value、coordinate 或可 join
  的 station metadata，以及可用時的 status 或 quality flag。
- 使用來源觀測時間進行 timestamp validation。
- 依來源 cadence 設定 staleness threshold。
- Coordinates 必須位於台灣 bounds 內。
- 拒絕 invalid values，包含 sentinel values 與不合理深度。
- Pagination completeness checks。
- Hosted egress 與 TLS verification。
- Source-health metrics 與 disable switch。

Civil IoT 在本機 curl 已顯示 certificate-chain verification 風險。Production
implementation 不應默默使用 unverified TLS。它應文件化 trusted CA path，在
hosted production fail closed，並只允許既有規則下的 explicit local diagnostic
bypass。

## 資料新鮮度政策

使用 per-source freshness thresholds，而不是單一 global threshold：

- Civil IoT flood sensors：目標 10 分鐘，30 分鐘 degraded，60 分鐘 failed
  或 stale alert。
- WRA 即時水位：目標 10 分鐘，30 分鐘 degraded，60 分鐘 stale alert。
- CWA 雨量：目標 10 分鐘，30 分鐘 degraded，60 分鐘 stale alert。
- NCDR CAP：依 CAP `sent`、`effective` 與 `expires` 評估；已過期 alerts
  不得當成 active 來源參與 scoring。
- 淹水潛勢圖：屬於 static 或 slow cadence 資料；使用 dataset build/update
  date，不使用 realtime stale thresholds。
- 地方備援來源：在 terms 與 operations review 期間設定來源專屬 thresholds。

資料新鮮度應從 source observation timestamps 計算，而不是從 fetch time 計算。

## 風險與信心

在另一個 calibration review 變更前，維持既有 scoring model。新的 backbone
改變 evidence quality 與 locality，不改變 public score levels 的語意。

實作時必須修正 persisted water-level 與 flood-depth risk factors，避免低水位
evidence 只因存在就變成 full-strength risk。每一筆 latest observation 都應攜帶
依來源 metric thresholds 計算的明確 `risk_factor`。

## 營運

Production traffic 啟用前，必須加入 source diagnostics：

- `--diagnose-source <adapter_key> --json`：gates、fetch status、
  normalized 與 rejected counts、timestamp min/max、raw ref、error code。
- `--source-status --adapter-key <adapter_key> --json`：data source state、
  latest adapter run、latest raw snapshot、latest evidence 與 latest
  read-model row。
- 指標：observed age、fetch lag、ingest lag、items fetched、items
  normalized、items rejected、latest-row count、source-health status。
- 警示：official source stale 或 failed state。

## 測試策略

CI 使用 fixtures 與 injected fetch clients。Live upstream smoke tests 必須明確
opt-in，且不得讓一般 CI 不穩定。

必要測試群組：

- Worker timestamp contract tests，覆蓋 `observed_at`、`fetched_at` 與
  `ingested_at`。
- Civil IoT parser tests，覆蓋 pagination、flood-depth observations、station
  metadata、invalid values、stale observations 與 quality flags。
- Adapter registry 與 runtime gate tests，覆蓋 national backbone sources。
- `official_realtime_latest` 的 promotion/upsert tests。
- Repository tests，覆蓋 spatial lookup、source-specific relevance radius、
  staleness filtering 與 duplicate suppression。
- API service tests，覆蓋 source freshness、displayed evidence、water-level
  與 flood-depth risk factor handling、cache behavior。
- Monitoring tests，覆蓋 Prometheus textfile output 與 freshness alert rules。
- 可選的 live smoke matrix，覆蓋 Civil IoT、WRA、CWA、NCDR 與一個經審核的
  local fallback。

## 推出順序

1. 修正 timestamp semantics 與 tests。
2. 為 Civil IoT backbone sources 加入 source catalog 與 seed data-source
   entries。
3. 實作 latest read model schema 與 worker upsert path。
4. 將 Civil IoT flood sensor ingestion 推進為 reviewed production candidate。
5. 更新 API lookup，優先讀取 latest model。
6. 加入 NCDR CAP warning ingestion。
7. 加入台南 open-data fallback 作為 reviewed local POC。
8. 加入 dashboards、alerts 與 opt-in live smoke tests。
9. 累積足夠 fixture 與 live observation evidence 後，才重新校準 scoring。

## OpenDesign 使用狀態

OpenDesign 已可在本機使用，但 research helper 目前需要 Tavily API key，
live artifact access 也需要 injected OpenDesign tool token。因此本設計以
repository markdown 作為 source of truth。若後續 OpenDesign project tools
可用，可將此 spec 鏡像成 artifact，呈現 source tiers、ingestion flow 與
freshness state machine。

## 審閱預設決策

- Civil IoT flood-depth sensors 在 terms、hosted egress、TLS 與 freshness
  monitoring 被接受前，維持 explicit production configuration。
- 第一個 local fallback rollout 限於具備清楚 license metadata 的正式 open-data
  APIs。官方但未文件化的 endpoints 在另行核准前，只能用於 derived overlays
  或 manual diagnostics。
- 第一版 production alert thresholds 使用本 spec 的 freshness policy。
  Threshold tuning 必須有 live smoke evidence，並更新 runbook entry。
