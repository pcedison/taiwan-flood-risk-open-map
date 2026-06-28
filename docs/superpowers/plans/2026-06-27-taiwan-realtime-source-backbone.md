# 全台即時資料源主幹實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan.

**目標：** 將目前偏向 CWA/WRA 近站資料的即時水情能力，升級為 Worker 優先、全台可擴充、可監測鮮度的官方即時資料源主幹。第一階段先補上時間語意、官方最新值 read model、Civil IoT 淹水感測器主幹、API 查詢路徑，以及 NCDR CAP 警戒整合；台南開放資料作為地方備援 POC。

**架構原則：**

- Worker 負責抓取、正規化、落庫、品質標記；公開 API 預設只讀資料庫，不在使用者查詢時對上游來源發出即時請求。
- `observed_at` 一律代表來源觀測時間；`fetched_at` 代表本系統抓取時間；`ingested_at` 代表寫入或 promoted 時間。
- Civil IoT `water_12` 淹水感測器作為全台淹水深度主幹；WRA/CWA/NCDR 作為官方水位、雨量、警戒脈絡；地方資料源只在完成來源審核後作為補強。
- 預設 production gates 保守關閉，新來源必須有明確環境變數、來源登錄、測試與健康狀態後才啟用。

## Task 1：修正即時資料時間語意與淹水深度 metric

**檔案：**

- `apps/workers/app/pipelines/staging.py`
- `apps/workers/tests/test_staging_pipeline.py`
- `apps/workers/app/adapters/civil_iot/flood_sensor.py`
- `apps/workers/tests/test_civil_iot_adapters.py`

**實作：**

1. 在 `OfficialSourceEvidence` 進入 staging 時，將 `observed_at` 改為 `evidence.source_timestamp`。
2. 保留 `occurred_at=evidence.source_timestamp`，因為目前事件發生時間與觀測時間在官方即時資料中相同。
3. `raw_snapshots.fetched_at` 繼續使用 `evidence.fetched_at`。
4. 將 `_REALTIME_METRIC_KEYS` 加入 `flood_depth_cm`，讓淹水深度可以進入標準 metric 管線。
5. `FloodSensorStaApiAdapter` 正規化時，在 raw payload properties 加入：
   - `flood_depth_cm`
   - `station_id`
   - `station_name`
   - `authority`
   - `datastream_name`
   - `source_url`

**測試先行：**

在 `apps/workers/tests/test_staging_pipeline.py` 新增測試：

```python
def test_build_staging_batch_uses_source_timestamp_as_observed_at() -> None:
    source_ts = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    fetched_at = datetime(2026, 6, 27, 10, 5, tzinfo=timezone.utc)
    evidence = OfficialSourceEvidence(
        source_id="official.civil_iot.flood_sensor",
        event_type="flood_report",
        source_timestamp=source_ts,
        fetched_at=fetched_at,
        title="淹水感測器",
        summary="depth 12cm",
        location=PointGeometry(type="Point", coordinates=(120.2, 23.0)),
        raw_payload={"source_id": "FS-001", "flood_depth_cm": 12.0},
    )

    batch = build_staging_batch([evidence])

    assert batch.evidence[0].observed_at == source_ts
    assert batch.evidence[0].occurred_at == source_ts
    assert batch.raw_snapshots[0].fetched_at == fetched_at
```

在 `apps/workers/tests/test_civil_iot_adapters.py` 增加 assertion，確認淹水感測器 normalized evidence 的 raw payload 含 `flood_depth_cm`，且值為來源 `value` 轉成 `float` 後的公分數。

**驗證指令：**

```bash
cd apps/workers
python -m pytest tests/test_staging_pipeline.py tests/test_civil_iot_adapters.py
```

## Task 2：新增官方即時最新值 read model 與資料源種子

**檔案：**

- `infra/migrations/0018_official_realtime_latest.sql`
- `infra/migrations/README.md`

**新增 migration：**

建立 `official_realtime_latest`，用每個來源、事件類型、測站保留最新官方觀測值。建議 SQL：

```sql
CREATE TABLE IF NOT EXISTS official_realtime_latest (
    source_id text NOT NULL,
    adapter_key text NOT NULL,
    event_type text NOT NULL,
    station_id text NOT NULL,
    station_name text,
    authority text,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point, 4326) NOT NULL,
    rainfall_mm_1h double precision,
    rainfall_mm_24h double precision,
    water_level_m double precision,
    warning_level_m double precision,
    flood_depth_cm double precision,
    confidence numeric(6, 3),
    freshness_score numeric(6, 3),
    source_weight numeric(6, 3),
    risk_factor numeric(6, 3),
    evidence_id uuid REFERENCES evidence(id) ON DELETE SET NULL,
    source_url text,
    attribution text,
    quality_flags jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (adapter_key, event_type, station_id)
);

CREATE INDEX IF NOT EXISTS idx_official_realtime_latest_geom
    ON official_realtime_latest USING gist (geom);

CREATE INDEX IF NOT EXISTS idx_official_realtime_latest_event_observed
    ON official_realtime_latest (event_type, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_official_realtime_latest_source_observed
    ON official_realtime_latest (source_id, observed_at DESC);
```

同一 migration 補 seed：

- `official.civil_iot.flood_sensor`
- `official.civil_iot.river_water_level`
- `official.civil_iot.pond_water_level`
- `official.civil_iot.sewer_water_level`
- `official.civil_iot.pump_water_level`
- `official.ncdr.cap`
- `local.tainan.flood_sensor`

每筆 `data_sources` 至少包含：

- `label_zh`
- `owner_authority`
- `update_cadence='near_realtime'` 或 CAP 對應的事件型更新說明
- `license_name`
- `source_url`
- `is_enabled=false`
- `tier='L1'` 或地方來源 `tier='L3'`
- `notes` 記錄 gates 與審核狀態

**驗證：**

若專案尚無 migration runner，至少以 SQL parser 或現有 migration 測試檢查：

```bash
rg "official_realtime_latest|official.civil_iot.flood_sensor|official.ncdr.cap" infra/migrations
```

## Task 3：promotion 階段 upsert 官方最新值

**檔案：**

- `apps/workers/app/pipelines/promotion.py`
- `apps/workers/tests/test_promotion_pipeline.py`

**實作：**

1. `PostgresEvidencePromotionWriter.write_evidence` 成功寫入 `evidence` 後，若 payload 是官方即時事件，呼叫 `_upsert_official_realtime_latest(...)`。
2. 官方即時事件初始支援：
   - `rainfall`
   - `water_level`
   - `flood_report`
   - `flood_warning`
3. 從 `payload.properties` 取：
   - `station_id`
   - `station_name`
   - `authority`
   - `source_url`
   - `rainfall_mm_1h`
   - `rainfall_mm_24h`
   - `water_level_m`
   - `warning_level_m`
   - `flood_depth_cm`
4. 若 `station_id` 不存在，使用 `payload.source_id` 的穩定測站段落；仍不存在就跳過 latest upsert，避免寫入不可追蹤資料。
5. 只在 `EXCLUDED.observed_at >= official_realtime_latest.observed_at` 時更新，避免舊資料覆蓋新觀測。
6. `risk_factor` 初始規則：
   - rainfall：沿用 API 現有 `rainfall_realtime_risk_factor` 門檻。
   - water level：若有 `water_level_m` 與 `warning_level_m`，用 `water_level_m / warning_level_m` 對應 0.25、0.5、0.8、1.0；缺 warning level 則為 `NULL`。
   - flood depth：`>= 50cm -> 1.0`，`>= 30cm -> 0.8`，`>= 15cm -> 0.5`，`>= 3cm -> 0.25`，否則 `0.0`。
   - flood warning：警戒事件為 `1.0`，過期 CAP 不應 promotion。

**測試先行：**

在 `test_promotion_pipeline.py` 使用現有 fake connection/cursor pattern 新增：

- `test_write_evidence_upserts_official_realtime_latest_for_flood_depth`
- `test_write_evidence_skips_latest_when_station_id_missing`
- `test_write_evidence_does_not_overwrite_newer_latest_with_older_observation`

測試要確認 SQL 目標表為 `official_realtime_latest`，且參數含 `flood_depth_cm`、`observed_at`、`evidence_id`。

**驗證指令：**

```bash
cd apps/workers
python -m pytest tests/test_promotion_pipeline.py tests/test_staging_pipeline.py tests/test_civil_iot_adapters.py
```

## Task 4：API 優先讀取官方最新值

**檔案：**

- `apps/api/app/domain/evidence/repository.py`
- `apps/api/app/api/services/public_evidence.py`
- `apps/api/app/api/routes/public.py`
- `apps/api/tests/test_evidence_repository.py`
- `apps/api/tests/test_realtime_intensity.py`

**實作：**

1. `EvidenceRecord` 增加欄位：
   - `water_level_m`
   - `warning_level_m`
   - `flood_depth_cm`
   - `realtime_risk_factor`
2. 新增 repository 函式 `query_nearby_latest_official(...)`，查詢 `official_realtime_latest`，以 PostGIS 距離排序，支援：
   - rainfall radius：預設 10km
   - water level radius：預設 3km
   - flood depth radius：預設 1km
   - flood warning radius：預設 10km 或依 CAP polygon/point fallback
3. `_nearby_db_evidence` 先讀 `official_realtime_latest`，再讀歷史 `evidence`，合併時以 `(event_type, source_id)` 或 `(event_type, station_id)` 去重。
4. `_evidence_realtime_risk_factor` 改成：
   - 若 `record.realtime_risk_factor` 非 `None`，優先使用。
   - rainfall 缺 latest factor 時，用 `rainfall_mm_1h` fallback。
   - water level 用 `water_level_m / warning_level_m` fallback。
   - flood report 用 `flood_depth_cm` fallback。
5. 若 latest table 不存在，repository 要降級回現有 `evidence` 查詢，讓 migration 未套用的本地環境不會整個 API 壞掉。降級只捕捉 undefined table 類錯誤，不吞掉其他資料錯誤。

**測試先行：**

- `test_query_nearby_latest_official_uses_flood_depth_radius`
- `test_query_nearby_latest_official_falls_back_when_table_missing`
- `test_public_evidence_prefers_realtime_risk_factor`
- `test_public_evidence_computes_flood_depth_factor`

**驗證指令：**

```bash
cd apps/api
python -m pytest tests/test_evidence_repository.py tests/test_realtime_intensity.py tests/test_public_risk_service.py
```

## Task 5：Civil IoT 全台淹水感測器正式主幹化

**檔案：**

- `apps/workers/app/adapters/civil_iot/sta_client.py`
- `apps/workers/app/adapters/civil_iot/flood_sensor.py`
- `apps/workers/app/config.py`
- `apps/workers/app/jobs/runtime.py`
- `apps/workers/tests/test_civil_iot_adapters.py`
- `apps/workers/tests/test_ingestion_run_writer.py`

**實作：**

1. `StaApiClient` 或 adapter 支援 `@iot.nextLink` 分頁，避免 `$top=2000` 遺漏全台測站。
2. 保留 `FLOOD_SENSOR_MIN_DEPTH_CM`，但 latest read model 應允許 `0cm` 記錄健康狀態；風險 factor 為 0。
3. 新增或整理 gates：
   - `SOURCE_FLOOD_SENSOR_ENABLED`
   - `SOURCE_FLOOD_SENSOR_API_ENABLED`
   - `SOURCE_FLOOD_SENSOR_USE_LIVE`
   - `SOURCE_FLOOD_SENSOR_TIMEOUT_SECONDS`
4. runtime registry 明確標註 Civil IoT flood sensor 為全台官方主幹來源。
5. 若 Civil IoT upstream 暫時失敗，worker 記錄 ingestion run failure 與 freshness 狀態，不讓 API 查詢即時抓外部來源。

**測試先行：**

- 分頁 payload 有 `@iot.nextLink` 時會繼續抓第二頁。
- `0cm` 淹水深度會保留為觀測資料，但風險 factor 為 0。
- live gate 預設關閉，開啟時才會呼叫 live API。

**驗證指令：**

```bash
cd apps/workers
python -m pytest tests/test_civil_iot_adapters.py tests/test_ingestion_run_writer.py
```

## Task 6：整合 NCDR CAP 災防告警

**檔案：**

- `apps/workers/app/adapters/ncdr/__init__.py`
- `apps/workers/app/adapters/ncdr/cap_alerts.py`
- `apps/workers/app/config.py`
- `apps/workers/app/jobs/runtime.py`
- `apps/workers/tests/test_ncdr_cap_adapter.py`

**實作：**

1. 建立 `NcdrCapAlertAdapter`，抓取 CAP feed，支援 JSON/Atom 來源。
2. 解析欄位：
   - `identifier`
   - `sender`
   - `sent`
   - `effective`
   - `expires`
   - `status`
   - `msgType`
   - `scope`
   - `severity`
   - `certainty`
   - `urgency`
   - `areaDesc`
   - polygon/circle/geocode 若來源提供
3. 僅 promotion 未過期且與水災、淹水、豪雨相關的警戒。
4. 輸出 `event_type='flood_warning'`，`source_id='official.ncdr.cap'`。
5. latest read model 對 CAP 使用 `identifier` 或 area code 作為 station key；若只有區域文字，先使用行政區 centroid 進行近似，並標記 `quality_flags.location_inferred=true`。
6. 預設 gate 關閉：
   - `SOURCE_NCDR_CAP_ENABLED=false`
   - `SOURCE_NCDR_CAP_API_ENABLED=false`

**測試先行：**

- 有效 CAP 產生 `flood_warning`。
- 過期 CAP 不 promotion。
- 非水災類型被略過。
- polygon/geocode 缺失時會標記 inferred location，而不是假裝高精度。

**驗證指令：**

```bash
cd apps/workers
python -m pytest tests/test_ncdr_cap_adapter.py tests/test_promotion_pipeline.py
```

## Task 7：台南地方開放資料備援 POC

**檔案：**

- `apps/workers/app/adapters/local_tainan/__init__.py`
- `apps/workers/app/adapters/local_tainan/flood_sensor.py`
- `apps/workers/app/config.py`
- `apps/workers/app/jobs/runtime.py`
- `apps/workers/tests/test_tainan_flood_sensor_adapter.py`
- `docs/superpowers/specs/2026-06-27-taiwan-realtime-source-backbone-design.md`

**可用來源：**

- 台南市政府資料開放平台資料集頁：`https://data.tainan.gov.tw/DataSet/Detail/03dd4536-3fe7-46ec-9920-a120cb5c502c`
- 即時 API：`https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c`
- 測站 metadata API：`https://soa.tainan.gov.tw/Api/Service/Get/cdc1ead4-d56a-4092-8e1c-e1f2fa9ee864`

**實作：**

1. 僅以正式開放資料 API 作為 POC，不使用網頁內部 undocumented endpoint 作為 production 來源。
2. 輸出 `source_id='local.tainan.flood_sensor'`，`event_type='flood_report'`。
3. location accuracy、授權、更新頻率、欄位 mapping 必須寫入 spec。
4. 預設 gate 關閉：
   - `SOURCE_TAINAN_FLOOD_SENSOR_ENABLED=false`
   - `SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED=false`
5. 若 Civil IoT 同測站或同區域已提供資料，台南地方資料僅作為補強，不覆蓋 L1 官方主幹。

**測試先行：**

- metadata + realtime payload 合併後可產生測站點位。
- 缺座標資料不 promotion，並記錄 quality flag。
- gate 預設關閉。

**驗證指令：**

```bash
cd apps/workers
python -m pytest tests/test_tainan_flood_sensor_adapter.py tests/test_civil_iot_adapters.py
```

## Task 8：鮮度監測、診斷與文件更新

**檔案：**

- `apps/workers/app/jobs/freshness.py` 或既有 freshness 模組
- `apps/workers/tests/test_freshness_monitoring.py`
- `apps/api/app/api/routes/admin.py` 或既有 admin route
- `apps/api/tests/test_admin_contract.py`
- `README.md`
- `docs/reviews/optimization-focus-worklist-2026-06-27.md`
- `docs/superpowers/specs/2026-06-27-taiwan-realtime-source-backbone-design.md`

**實作：**

1. 每個來源輸出 freshness state：
   - `fresh`
   - `degraded`
   - `stale`
   - `failed`
2. 初始門檻：
   - Civil IoT/WRA/CWA：10 分鐘內 fresh，30 分鐘 degraded，60 分鐘 stale/failed。
   - NCDR CAP：依 `effective/expires` 判斷有效性。
   - flood potential：標記為 static/slow cadence，不納入即時鮮度失敗。
3. Admin/diagnostic endpoint 顯示：
   - source id
   - latest observed_at
   - latest fetched/ingested time
   - lag seconds
   - row count
   - upstream status
   - enabled gates
4. README 說明新的即時資料源架構、預設關閉 gates、如何本地啟用 smoke test。
5. 更新八個優化重點工作整理 markdown，加入此主幹設計的狀態與後續工作。

**測試先行：**

- freshness threshold 轉換正確。
- admin contract 包含每個來源必要欄位。
- disabled source 不被誤判為 failed。

**驗證指令：**

```bash
cd apps/workers
python -m pytest tests/test_freshness_monitoring.py

cd ../api
python -m pytest tests/test_admin_contract.py tests/test_public_freshness.py
```

## 完成標準

- 所有新增來源都有來源登錄、預設 gate、測試、授權/歸屬註記。
- API 查詢使用資料庫最新值，不再依賴 request-time 上游 fetch 作為主要路徑。
- 即時資料的 `observed_at`、`fetched_at`、`ingested_at` 語意清楚且有測試保護。
- Civil IoT 淹水深度資料可以支援全台查詢，並與雨量、水位、CAP 警戒共同進入風險評分。
- 台南地方資料源只作為審核後地方補強，不凌駕全台官方主幹。
- worker 與 API 測試通過，至少包含：

```bash
cd apps/workers
python -m pytest

cd ../api
python -m pytest
```
