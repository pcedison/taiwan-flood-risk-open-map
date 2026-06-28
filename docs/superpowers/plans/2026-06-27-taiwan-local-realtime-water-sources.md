# 台灣地方即時水情補強層實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補上 22 縣市地方即時水情補強層，並維持 Civil IoT、WRA、CWA、NCDR 中央全台主幹健康運作。

**Architecture:** 延續 worker-first ingestion。中央彙整地方感測器先由 Civil IoT/WRA IoW 補齊 county coverage；地方政府直出來源以 `local.<county>.<signal>` adapter 補強，全部預設關閉並進入既有 raw snapshot、staging、promotion、`official_realtime_latest` pipeline。

**Tech Stack:** Python worker adapters、pytest、PostGIS latest read model、FastAPI admin freshness diagnostics、data.gov.tw / Civil IoT SensorThings / WRA OpenData / local JSON/XML/CSV endpoints。

## Global Constraints

- 不破壞既有中央主幹：`official.cwa.rainfall`、`official.wra.water_level`、`official.ncdr.cap`、`official.civil_iot.*`。
- Public hosted API 不得 request-time 直接抓地方或中央上游；只能讀 worker 持久化後的 latest/evidence。
- 地方來源不得覆蓋中央主幹，只能補強、交叉驗證或降低 uncertainty。
- 地方政府直出 adapter 使用 `local.<county>.<signal>`；中央彙整地方感測器仍使用 `official.*`。
- 每個 live adapter 預設關閉；必須有 source gate + API gate；`WORKER_ENABLED_ADAPTER_KEYS` 不得繞過 gate。
- 新增 parser/adapter 必須 TDD：先寫失敗測試，再寫 production code。
- 缺座標且無官方 metadata 可 join 的資料，不得 normalized，不得 upsert latest。
- 每筆 normalized evidence 必須有 `station_id`、`observed_at`、WGS84 Point、source URL、attribution、quality flags。
- Civil IoT 預設 endpoint 優先 `https://sta.colife.org.tw/...`；舊 `sta.ci.taiwan.gov.tw` 僅作 explicit override/fallback。
- 22 縣市 coverage matrix 必須保留 `ready`、`central_aggregated_ready`、`candidate`、`metadata_only`、`not_found` 狀態，不得移除無地方 API 的縣市。

---

## File Structure

- Modify: `apps/workers/app/adapters/civil_iot/sta_client.py`
  - Civil IoT base URL default、health/fallback metadata、STA RainSewer base。
- Modify: `apps/workers/app/adapters/civil_iot/flood_sensor.py`
  - 更新 `resource_url` 與 county/authority metadata。
- Modify: `apps/workers/app/adapters/civil_iot/sta_water_level.py`
  - 將 sewer source 改成 `STA_RainSewer`，保留 water-resource source for pond/pump/gate。
- Create: `apps/workers/app/adapters/wra_iow/flood_depth.py`
  - WRA IoW 淹水深度 latest + basic join adapter。
- Create: `apps/workers/app/adapters/local_taipei/water.py`
  - 臺北 sewer/river/pump parsers and adapters。
- Create: `apps/workers/app/adapters/local_taoyuan/water.py`
  - 桃園 flood sensor and water-level XML parsers/adapters。
- Create: `apps/workers/app/adapters/local_chiayi_city/water.py`
  - 嘉義市 water-level CSV parser/adapter。
- Create: `apps/workers/app/adapters/local_taichung/water.py`
  - 臺中 water-level JSON parser/adapter using official live URL。
- Modify: `apps/workers/app/adapters/registry.py`
  - Register new metadata and gate behavior。
- Modify: `apps/workers/app/config.py`
  - Add env vars, URLs, timeouts, gates。
- Modify: `apps/workers/app/jobs/runtime.py`
  - Build new live adapters only when both gates pass。
- Modify: `apps/api/app/api/routes/admin.py`
  - Add adapters to freshness diagnostics and gate names。
- Create: `infra/migrations/0019_wra_iow_flood_depth_source.sql`
  - Seed data_sources rows for new adapters.
- Add: `infra/migrations/0024_civil_iot_gate_water_level_source.sql`
  - Seed Civil IoT gate external water level and update pump station metadata.
- Modify: `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`
  - Keep 22-city matrix current with implementation status.
- Test: `apps/workers/tests/test_wra_iow_flood_depth_adapter.py`
- Test: `apps/workers/tests/test_local_taipei_water_adapters.py`
- Test: `apps/workers/tests/test_local_taoyuan_water_adapters.py`
- Test: `apps/workers/tests/test_local_chiayi_taichung_water_adapters.py`
- Test: `apps/workers/tests/test_adapter_registry_config.py`
- Test: `apps/api/tests/test_admin_contract.py`

---

### Task 1: Civil IoT Endpoint And Coverage Metadata Guardrail

**Files:**
- Modify: `apps/workers/app/adapters/civil_iot/sta_client.py`
- Modify: `apps/workers/app/adapters/civil_iot/flood_sensor.py`
- Modify: `apps/workers/app/adapters/civil_iot/sta_water_level.py`
- Test: `apps/workers/tests/test_civil_iot_adapters.py`
- Test: `apps/workers/tests/test_civil_iot_water_levels.py`
- Docs: `docs/runbooks/civil-iot-live-enablement.md`

**Interfaces:**
- Produces: `STA_WATER_RESOURCE_BASE = "https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/"`
- Produces: `STA_RAIN_SEWER_BASE = "https://sta.colife.org.tw/STA_RainSewer/v1.0/"`
- Preserves: `CIVIL_IOT_FLOOD_SENSOR_URL`, `CIVIL_IOT_RIVER_URL`, `CIVIL_IOT_SEWER_URL` overrides.

- [x] **Step 1: Write failing tests for endpoint defaults**

Add tests:

```python
def test_civil_iot_sta_defaults_use_colife_endpoint() -> None:
    from app.adapters.civil_iot.sta_client import STA_RAIN_SEWER_BASE, STA_WATER_RESOURCE_BASE

    assert STA_WATER_RESOURCE_BASE == "https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/"
    assert STA_RAIN_SEWER_BASE == "https://sta.colife.org.tw/STA_RainSewer/v1.0/"


def test_sewer_water_level_uses_rain_sewer_service_not_water_resource() -> None:
    from app.adapters.civil_iot import SEWER_WATER_LEVEL

    assert "STA_RainSewer" in SEWER_WATER_LEVEL.sta_url
    assert "STA_WaterResource" not in SEWER_WATER_LEVEL.sta_url
```

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
cd apps/workers
source /tmp/flood-risk-task4-py312/bin/activate
PYTHONPATH=. python -m pytest tests/test_civil_iot_adapters.py::test_civil_iot_sta_defaults_use_colife_endpoint tests/test_civil_iot_water_levels.py::test_sewer_water_level_uses_rain_sewer_service_not_water_resource -q
```

Expected: FAIL because current base URL is `sta.ci.taiwan.gov.tw` and sewer uses water-resource base.

- [x] **Step 3: Implement minimal endpoint changes**

Change `sta_client.py`:

```python
STA_WATER_RESOURCE_BASE = "https://sta.colife.org.tw/STA_WaterResource_v2/v1.0/"
STA_RAIN_SEWER_BASE = "https://sta.colife.org.tw/STA_RainSewer/v1.0/"
```

Change `sta_water_level.py` so only `SEWER_WATER_LEVEL` uses:

```python
from app.adapters.civil_iot.sta_client import STA_RAIN_SEWER_BASE

def _build_rain_sewer_url(*, top: int = 2000) -> str:
    return (
        f"{STA_RAIN_SEWER_BASE}Things"
        "?$expand=Locations,Datastreams($expand=Observations("
        "$orderby=phenomenonTime desc;$top=1))"
        f"&$top={top}"
    )
```

- [x] **Step 4: Run focused tests**

Run:

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_civil_iot_adapters.py tests/test_civil_iot_water_levels.py -q
```

Expected: PASS.

- [x] **Step 5: Update runbook**

Update `docs/runbooks/civil-iot-live-enablement.md` to mention `sta.colife.org.tw`, env override, and 2026-12-01 endpoint migration monitoring.

- [ ] **Step 6: Commit**

```bash
git add apps/workers/app/adapters/civil_iot apps/workers/tests/test_civil_iot_adapters.py apps/workers/tests/test_civil_iot_water_levels.py docs/runbooks/civil-iot-live-enablement.md
git commit -m "fix: update Civil IoT SensorThings endpoints"
```

---

### Task 2: WRA IoW Flood Depth Join Adapter

**Files:**
- Create: `apps/workers/app/adapters/wra_iow/__init__.py`
- Create: `apps/workers/app/adapters/wra_iow/flood_depth.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Test: `apps/workers/tests/test_wra_iow_flood_depth_adapter.py`
- Test: `apps/workers/tests/test_adapter_registry_config.py`

**Interfaces:**
- Adapter key: `official.wra_iow.flood_depth`
- Event type: `flood_report`
- Required live gates: `SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED=true` and `SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED=true`
- Optional URLs: `WRA_IOW_FLOOD_DEPTH_API_URL`, `WRA_IOW_FLOOD_SENSOR_METADATA_API_URL`
- Timeout: `WRA_IOW_FLOOD_DEPTH_TIMEOUT_SECONDS`, default `8`

- [x] **Step 1: Write failing parser/join tests**

Create `apps/workers/tests/test_wra_iow_flood_depth_adapter.py` with:

```python
from datetime import UTC, datetime

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.wra_iow import WraIowFloodDepthApiAdapter

FETCHED_AT = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _latest_payload() -> dict:
    return {
        "records": [
            {
                "sensorid": "YL-FD-001",
                "latestvalue": "12.5",
                "timestamp": "2026-06-27T19:55:00+08:00",
                "countycode": "10009",
                "areacode": "10009010",
            },
            {
                "sensorid": "YL-FD-002",
                "latestvalue": "0",
                "timestamp": "2026-06-27T19:56:00+08:00",
                "countycode": "10009",
                "areacode": "10009020",
            },
        ]
    }


def _metadata_payload() -> dict:
    return {
        "records": [
            {
                "sensorid": "YL-FD-001",
                "orgname": "雲林縣政府",
                "countyname": "雲林縣",
                "townname": "斗六市",
                "stationname": "斗六市測站",
                "longitude": "120.5401",
                "latitude": "23.7072",
                "isenable": "Y",
            },
            {
                "sensorid": "YL-FD-002",
                "orgname": "雲林縣政府",
                "countyname": "雲林縣",
                "townname": "虎尾鎮",
                "stationname": "虎尾鎮測站",
                "longitude": "120.4310",
                "latitude": "23.7090",
                "isenable": "Y",
            },
        ]
    }


def test_wra_iow_flood_depth_join_outputs_flood_report() -> None:
    calls = []

    def fetch_json(url: str, timeout_seconds: int) -> dict:
        calls.append((url, timeout_seconds))
        return _metadata_payload() if "basic" in url else _latest_payload()

    adapter = WraIowFloodDepthApiAdapter(
        api_url="https://example.test/latest",
        metadata_api_url="https://example.test/basic",
        fetched_at=FETCHED_AT,
        timeout_seconds=5,
        fetch_json=fetch_json,
    )

    result = adapter.run()

    assert result.adapter_key == "official.wra_iow.flood_depth"
    assert len(result.normalized) == 2
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert evidence.properties["station_id"] == "YL-FD-001"
    assert evidence.properties["flood_depth_cm"] == 12.5
    assert evidence.properties["county"] == "雲林縣"
    assert evidence.properties["town"] == "斗六市"
```

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_wra_iow_flood_depth_adapter.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.wra_iow'`.

- [x] **Step 3: Implement adapter**

Implement `WraIowFloodDepthApiAdapter` following `local_tainan/flood_sensor.py` patterns:

- Fetch metadata first, latest second.
- Parse payloads from `records`, `Record`, `data`, or list root.
- Join by `sensorid`.
- Parse `timestamp` as observed time.
- Convert `latestvalue` cm into `flood_depth_cm`.
- Include `station_id`, `station_name`, `authority`, `county`, `town`, `quality_flags`.
- Reject missing coordinates, disabled sensors, stale/invalid numeric values.

- [x] **Step 4: Add registry/config/runtime tests**

Add to `test_adapter_registry_config.py`:

```python
def test_wra_iow_flood_depth_requires_both_gates() -> None:
    adapter_key = "official.wra_iow.flood_depth"
    api_only = load_worker_settings({
        "WORKER_ENABLED_ADAPTER_KEYS": adapter_key,
        "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED": "true",
    })
    live = load_worker_settings({
        "WORKER_ENABLED_ADAPTER_KEYS": adapter_key,
        "SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED": "true",
        "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED": "true",
    })

    assert adapter_key not in enabled_adapter_keys(api_only)
    assert enabled_adapter_keys(live) == (adapter_key,)
```

- [x] **Step 5: Run focused tests**

Run:

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_wra_iow_flood_depth_adapter.py tests/test_adapter_registry_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/workers/app/adapters/wra_iow apps/workers/app/adapters/registry.py apps/workers/app/config.py apps/workers/app/jobs/runtime.py apps/workers/tests/test_wra_iow_flood_depth_adapter.py apps/workers/tests/test_adapter_registry_config.py
git commit -m "feat: add WRA IoW flood depth adapter"
```

---

### Task 3: Taipei Local Water Adapters

**Files:**
- Create: `apps/workers/app/adapters/local_taipei/__init__.py`
- Create: `apps/workers/app/adapters/local_taipei/water.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/jobs/freshness.py`
- Create: `infra/migrations/0020_taipei_local_water_sources.sql`
- Test: `apps/workers/tests/test_local_taipei_water_adapters.py`
- Test: `apps/workers/tests/test_adapter_registry_config.py`
- Test: `apps/workers/tests/test_freshness_monitoring.py`

**Interfaces:**
- Adapter keys:
  - `local.taipei.sewer_water_level`
  - `local.taipei.river_water_level`
  - `local.taipei.pump_station`
- Event type: `water_level`
- Gates:
  - `SOURCE_TAIPEI_SEWER_WATER_LEVEL_ENABLED`, `SOURCE_TAIPEI_SEWER_WATER_LEVEL_API_ENABLED`
  - `SOURCE_TAIPEI_RIVER_WATER_LEVEL_ENABLED`, `SOURCE_TAIPEI_RIVER_WATER_LEVEL_API_ENABLED`
  - `SOURCE_TAIPEI_PUMP_STATION_ENABLED`, `SOURCE_TAIPEI_PUMP_STATION_API_ENABLED`

- [x] **Step 1: Write failing parser tests**

Test cases:

- Sewer live payload joins station metadata CSV by `stationNo` and outputs `water_level_m = levelOut`.
- River live payload joins station metadata CSV by `stationNo`.
- Pump payload uses embedded `lon/lat`, `obs_time`, `inner_value`, `outer_value`, `max_allowable_water_level`.
- Stale station row is rejected if `recTime` is older than max age in test fixture.

Expected RED command:

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_local_taipei_water_adapters.py -q
```

Expected: FAIL with missing module.

- [x] **Step 2: Implement Taipei shared helpers**

Implement:

```python
def parse_taipei_rec_time(value: object) -> datetime | None:
    # accepts 202606272304

def parse_taipei_obs_time(value: object) -> datetime | None:
    # accepts 2026-06-27 23:00:00 as Asia/Taipei
```

Implement three adapter classes with raw/rejected behavior matching Tainan.

- [x] **Step 3: Add runtime wiring and gate tests**

Add registry metadata and config settings. Explicit allowlist must not enable adapter without both source and API gates.

- [x] **Step 4: Run focused tests**

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_local_taipei_water_adapters.py tests/test_adapter_registry_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/workers/app/adapters/local_taipei apps/workers/app/adapters/registry.py apps/workers/app/config.py apps/workers/app/jobs/runtime.py apps/workers/tests/test_local_taipei_water_adapters.py apps/workers/tests/test_adapter_registry_config.py
git commit -m "feat: add Taipei realtime water adapters"
```

---

### Task 4: Taoyuan Local Flood And Water-Level Adapters

**Files:**
- Create: `apps/workers/app/adapters/local_taoyuan/__init__.py`
- Create: `apps/workers/app/adapters/local_taoyuan/water.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/jobs/freshness.py`
- Create: `infra/migrations/0021_taoyuan_local_water_sources.sql`
- Test: `apps/workers/tests/test_local_taoyuan_water_adapters.py`
- Test: `apps/workers/tests/test_adapter_registry_config.py`
- Test: `apps/workers/tests/test_freshness_monitoring.py`

**Interfaces:**
- Adapter keys:
  - `local.taoyuan.flood_sensor`
  - `local.taoyuan.water_level`
- Events:
  - flood sensor: `flood_report`, `flood_depth_cm`
  - water level: `water_level`, `water_level_m`, `warning_level_m`

- [x] **Step 1: Write failing XML parser tests**

Use fixture snippets:

```xml
<Root><Data><ID>20180510120206</ID><NAME>樹仁三街、桃鶯路口</NAME><LON>121.323435</LON><LAT>24.975086</LAT><ADDRESS>樹仁三街、桃鶯路口</ADDRESS><HEIGHT>7</HEIGHT><DATA_TIME>2026/6/27 下午 11:00:00</DATA_TIME></Data></Root>
```

```xml
<ROOT><DATA><DATATIME>2026-06-27 22:50:00</DATATIME><LON>121.30874</LON><LAT>24.9582</LAT><STATION>DR0-102-大灣溝</STATION><STATION_ID>1032598727</STATION_ID><TOWN>八德區</TOWN><WATERHEIGHT_M>0.75</WATERHEIGHT_M><RedAlertLevel>2.08</RedAlertLevel><YellowAlertLevel>1.56</YellowAlertLevel></DATA></ROOT>
```

Expected RED: missing module.

- [x] **Step 2: Implement XML parser**

Use `xml.etree.ElementTree`, not regex. Parse Chinese AM/PM time as Asia/Taipei.

- [x] **Step 3: Add gates/runtime**

Add settings and builder injection fetchers for Taoyuan flood and water-level adapters.

- [x] **Step 4: Run focused tests**

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_local_taoyuan_water_adapters.py tests/test_adapter_registry_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/workers/app/adapters/local_taoyuan apps/workers/app/adapters/registry.py apps/workers/app/config.py apps/workers/app/jobs/runtime.py apps/workers/tests/test_local_taoyuan_water_adapters.py apps/workers/tests/test_adapter_registry_config.py
git commit -m "feat: add Taoyuan realtime water adapters"
```

---

### Task 5: Chiayi City And Taichung Water-Level Adapters

**Files:**
- Create: `apps/workers/app/adapters/local_chiayi_city/__init__.py`
- Create: `apps/workers/app/adapters/local_chiayi_city/water.py`
- Create: `apps/workers/app/adapters/local_taichung/__init__.py`
- Create: `apps/workers/app/adapters/local_taichung/water.py`
- Modify: registry/config/runtime
- Modify: `apps/workers/app/jobs/freshness.py`
- Create: `infra/migrations/0022_chiayi_taichung_local_water_sources.sql`
- Test: `apps/workers/tests/test_local_chiayi_taichung_water_adapters.py`
- Test: `apps/workers/tests/test_adapter_registry_config.py`
- Test: `apps/workers/tests/test_freshness_monitoring.py`

**Interfaces:**
- `local.chiayi_city.water_level`: CSV, `資料時間`, `水位-m`, `一級警戒`, `二級警戒`
- `local.taichung.water_level`: JSON, `資料時間`, `水位高m`, `黃色警戒值m`, `紅色警戒值m`

- [x] **Step 1: Write failing tests**

CSV parser test must verify UTF-8 BOM, Chinese headers, station id `代號`, WGS84 coordinate, warning level choice.

Taichung parser test must use official live URL shape and reject stale mirror data when observed time is too old.

- [x] **Step 2: Implement parsers/adapters**

Use `csv.DictReader` for Chiayi; JSON mapping for Taichung. Both adapters must set `station_id` in evidence properties.

- [x] **Step 3: Add gates/runtime**

Add:

- `SOURCE_CHIAYI_CITY_WATER_LEVEL_ENABLED`
- `SOURCE_CHIAYI_CITY_WATER_LEVEL_API_ENABLED`
- `SOURCE_TAICHUNG_WATER_LEVEL_ENABLED`
- `SOURCE_TAICHUNG_WATER_LEVEL_API_ENABLED`

- [x] **Step 4: Run focused tests**

```bash
cd apps/workers
PYTHONPATH=. python -m pytest tests/test_local_chiayi_taichung_water_adapters.py tests/test_adapter_registry_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/workers/app/adapters/local_chiayi_city apps/workers/app/adapters/local_taichung apps/workers/app/adapters/registry.py apps/workers/app/config.py apps/workers/app/jobs/runtime.py apps/workers/tests/test_local_chiayi_taichung_water_adapters.py apps/workers/tests/test_adapter_registry_config.py
git commit -m "feat: add Chiayi City and Taichung water adapters"
```

---

### Task 6: Admin Freshness, Source Catalog, And Migration Seeds

**Files:**
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `apps/api/tests/test_admin_contract.py`
- Add: `infra/migrations/0019_wra_iow_flood_depth_source.sql`
- Add: `infra/migrations/0020_taipei_local_water_sources.sql`
- Add: `infra/migrations/0021_taoyuan_local_water_sources.sql`
- Add: `infra/migrations/0022_chiayi_taichung_local_water_sources.sql`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`

**Interfaces:**
- Admin `REALTIME_ADAPTER_KEYS` includes new official/local realtime adapters.
- `SOURCE_GATE_NAMES` includes each new source gate pair.
- `data_sources` rows seeded with `is_enabled=false`, source URLs, tier, review status.

- [x] **Step 1: Write failing admin/source tests**

Add tests asserting new adapter keys appear in source freshness sample/admin diagnostics and disabled gate names.

- [x] **Step 2: Add migrations**

Create migration seeds for WRA IoW, Taipei, Taoyuan, Chiayi City, and Taichung rows only. Do not alter `official_realtime_latest` schema unless a test proves it is needed.

- [x] **Step 3: Update docs/catalog**

Mark implemented adapters in local matrix; keep non-implemented counties visible as `central_aggregated_ready`, `metadata_only`, or `not_found`.

- [x] **Step 4: Run focused tests and migration validator**

```bash
cd apps/api
source /tmp/flood-risk-task4-py312/bin/activate
PYTHONPATH=. python -m pytest tests/test_admin_contract.py -q
cd ../..
python3 infra/scripts/validate_migrations.py
```

Expected: PASS and latest migration is `0024`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/routes/admin.py apps/api/tests/test_admin_contract.py infra/migrations/0019_wra_iow_flood_depth_source.sql infra/migrations/0020_taipei_local_water_sources.sql infra/migrations/0021_taoyuan_local_water_sources.sql infra/migrations/0022_chiayi_taichung_local_water_sources.sql docs/data-sources/official/official-source-catalog.yaml docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md
git commit -m "feat: expose local realtime sources in diagnostics"
```

---

### Task 7: Full Verification And Central Backbone Regression Guard

**Files:**
- Modify only docs if verification evidence needs a tracked note.

- [x] **Step 1: Run worker tests**

```bash
cd apps/workers
source /tmp/flood-risk-task4-py312/bin/activate
PYTHONPATH=. python -m pytest
```

Expected: all worker tests pass.

- [x] **Step 2: Run API tests**

```bash
cd apps/api
source /tmp/flood-risk-task4-py312/bin/activate
PYTHONPATH=. python -m pytest
```

Expected: all API tests pass. Existing deprecation warnings are acceptable only if unchanged.

- [x] **Step 3: Validate migrations**

```bash
cd /Users/marcus/Documents/Flood\ Risk
python3 infra/scripts/validate_migrations.py
```

Expected: valid, latest migration `0024`.

- [x] **Step 4: Smoke list adapters**

```bash
cd apps/workers
PYTHONPATH=. python -m app.main --list-adapters
```

Expected: default list still contains only safe default official adapters; new local adapters are present only when source gates are set.

- [x] **Step 5: Final review**

Check:

- Central mainline keys still exist.
- CWA requires `CWA_API_AUTHORIZATION` when enabled.
- WRA original adapter still works.
- NCDR adapter still works.
- Civil IoT adapters default off and use `sta.colife.org.tw`.
- 22-county matrix has no missing county row.

- [ ] **Step 6: Commit verification/doc updates if needed**

```bash
git add docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md
git commit -m "docs: update local realtime source coverage"
```

Only commit if docs changed after verification.

---

### Task 8: Second-Batch Local Rainfall And Coverage Plumbing

**Files:**
- Modify: `apps/workers/app/adapters/local_taoyuan/water.py`
- Modify: `apps/workers/app/adapters/local_taoyuan/__init__.py`
- Modify: `apps/workers/app/adapters/local_chiayi_city/water.py`
- Modify: `apps/workers/app/adapters/local_chiayi_city/__init__.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/jobs/freshness.py`
- Modify: `apps/workers/app/pipelines/staging.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Add: `infra/migrations/0023_taoyuan_chiayi_rainfall_sources.sql`
- Test: `apps/workers/tests/test_local_taoyuan_water_adapters.py`
- Test: `apps/workers/tests/test_local_chiayi_taichung_water_adapters.py`
- Test: `apps/workers/tests/test_staging_pipeline.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Adapter key: `local.taoyuan.rainfall`
- Adapter key: `local.chiayi_city.rainfall`
- Admin `DataSource` includes `covered_counties`, `covered_county_count`,
  `fresh_county_count`, `stale_county_count`, `station_count_by_county`,
  and `missing_counties`.

- [x] **Step 1: Write failing rainfall adapter tests**

Cover Taoyuan XML root `Time` + station `Rainfall`, Chiayi City CSV rainfall
windows, sentinel/negative rejection, runtime wiring, registry gates, freshness,
and admin gates.

- [x] **Step 2: Implement rainfall adapters**

Taoyuan preserves `Rainfall` as `rainfall_mm` because the official feed does not
document the accumulation window. Chiayi City preserves 10m/1h/3h/6h/12h/24h
windows and handles duplicate 12-hour headers in the live CSV.

- [x] **Step 3: Add data source seed migration and docs**

Add `0023_taoyuan_chiayi_rainfall_sources.sql` and update the 22-county local
source matrix from candidate to implemented.

- [x] **Step 4: Add coverage metadata plumbing tests**

Staging must pass through `station_name`, `authority`, `county`, `town`,
`county_code`, and `area_code`. Admin sources must expose per-adapter county
coverage summary fields.

- [x] **Step 5: Implement coverage metadata plumbing**

Staging now keeps coverage metadata from raw payloads. Admin aggregates county
coverage by joining `official_realtime_latest` to promoted evidence properties.

- [x] **Step 6: Run full verification**

Run worker/API tests, migration validator, runtime adapter smoke, and targeted
ruff after all Task 8 changes are complete.

---

### Task 9: Remaining 22-County Source Discovery And Enrichment

**Files:**
- Modify: `apps/workers/app/adapters/civil_iot/sta_client.py`
- Modify: `apps/workers/app/adapters/civil_iot/sta_water_level.py`
- Modify: `apps/workers/app/adapters/civil_iot/__init__.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/jobs/freshness.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Add: `infra/migrations/0024_civil_iot_gate_water_level_source.sql`
- Modify: `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`
- Modify adapters only when an official, public, machine-readable live API is
  verified.

- [x] **Step 1: Integrate source discovery subagent results**

For each non-implemented county, keep only official, public, machine-readable
live sources. Do not add front-end private APIs or sources requiring manual
application as production adapters.

- [x] **Step 2: Fix Civil IoT live URL encoding and metadata pass-through**

`fetch_sta_json` now percent-encodes SensorThings URLs with Chinese filters and
`phenomenonTime desc` spaces before handing them to urllib. STA parsing now keeps
`county`, `town`, `county_code`, `area_code`, and conservatively infers county
from explicit 22-county names in `authority` or station text when the payload
lacks `city`/`CountyName`.

- [x] **Step 3: Correct pump station and add gate external water-level backbone**

`official.civil_iot.pump_water_level` now queries stationName containing `抽水`
and datastreams containing `水位`, preferring `外水位` and falling back to generic
`水位`. `official.civil_iot.gate_water_level` adds `閘門外水位` as a separate
SensorThings water-level source with source/API gates and admin/freshness wiring.

- [x] **Step 4: Update migrations and local source matrix**

Add `0024_civil_iot_gate_water_level_source.sql`. Matrix now distinguishes
central aggregated implemented coverage from true local-government direct APIs.

- [x] **Step 5: Add geometry-to-admin enrichment design if needed**

If central sources still lack structured county/town after raw payload pass-through,
add a tested enrichment layer using existing Taiwan admin geography assets instead
of guessing from free text.

Implemented in promotion: for official realtime Point station evidence that lacks
`county`/`town`/`village`, the writer queries `admin_area_profiles` with
`ST_Covers`, prefers village over town over county, and merges only missing
fields into `evidence.properties`.

- [ ] **Step 6: Continue official local-direct API discovery**

The remaining counties stay visible as `central_aggregated_ready`,
`metadata_only`, or `not_found` until an official public live API is verified.
Do not mark a county local-direct complete solely because Civil IoT central
aggregation covers it.

2026-06-28 progress:

- Northern strict re-check integrated: 新北 `metadata_only`、基隆 `candidate`
  without public API contract、新竹市 `metadata_only`、新竹縣 `not_found`、
  苗栗 `candidate` without public API contract.
- Central strict re-check integrated: 彰化 `metadata_only`、南投 `not_found`、
  雲林 `metadata_only`、嘉義縣 `candidate` + `metadata_only`.
- Southern/eastern/offshore strict re-check integrated: 高雄 `metadata_only`、
  屏東 `candidate` without public API contract、宜蘭 `not_found`、花蓮
  `candidate` without local API、臺東 `candidate` without public API endpoint、
  澎湖 `candidate` + `metadata_only`、金門 `needs_application` for upload API
  only、連江 `metadata_only`.
- Current conclusion: among the 17 non-implemented counties rechecked under the
  strict local-direct rule, no new `ready` local-government public live read API
  was found. Continue central-backbone coverage and wait for official API
  publication or explicit application/authorization.
- Admin 可視化已新增：`GET /admin/v1/local-source-coverage` 會以機器可讀 API
  輸出 22 縣市地方直連狀態 catalog。尚未完成地方直連的縣市會明確保留為
  `candidate`、`metadata_only`、`not_found` 或 `needs_application`，避免中央主幹
  coverage 被誤認為地方政府直連已完成。端點也分開輸出
  `local_direct_complete`、`central_backbone_available` 與
  `central_backbone_signal_types`，讓維運者能辨識縣市是否已有地方政府 live adapter，
  以及哪些中央基線訊號存在。另新增 `central_backbone_minimum_complete`、
  `central_backbone_missing_signal_types` 與 `central_backbone_coverage_level`，
  讓縣市級健康門檻能區分完整基線 coverage 與只有雨量/CAP 的縣市。
- Coverage summary 已新增：端點會輸出 22 縣市總數、地方直連完成/未完成數、
  中央主幹最低基線完成/未完成數、缺水文觀測主幹的縣市，以及待授權、
  待 live smoke、待公開 API contract 驗證等後續工作 bucket。summary queue
  也包含縣市清單並支援多重狀態，所以同時是 `metadata_only` 與 `not_found`
  的縣市會同時留在 metadata monitoring 與 official discovery queue。
- Coverage summary 另新增中央主幹 family/key 完整性欄位：
  `central_backbone_required_families`、`central_backbone_missing_families`、
  `central_backbone_family_complete`、`central_backbone_required_adapter_keys`、
  `central_backbone_missing_adapter_keys`。這些欄位只檢查全台中央主幹是否包含
  必要的 CWA、WRA、NCDR、Civil IoT family 與 production adapter key；它們
  不代表 22 縣市地方政府直連資料源都已完成。
- 同一端點也輸出 `next_action_code`、`upgrade_priority` 與 `blocking_reason`，
  將剩餘縣市轉成可排序的升級工作清單：需要申請授權優先，其次是公開 API
  contract 驗證、metadata-only 監控，以及 not-found 持續探索。
- Coverage record 會保留可追溯 URL 陣列：`production_source_urls`、
  `candidate_source_urls`、`metadata_source_urls` 與 `application_urls`，
  讓後續實作、監控、人工申請都能直接回到官方來源頁、API endpoint、
  metadata catalog 或授權文件。
- 臺北市疏散門來源已從模糊候選升級為 `needs_review`：臺北資料大平台公開
  official OpenAPI URL、loginId 與 dataKey，但 2026-06-28 在此環境 live smoke
  30 秒逾時，因此在 availability 與 freshness 驗證前，仍不接入 production
  adapter。
- 第三輪來源探索已整合：北區、中南區、東部離島 subagents 確認許多剩餘縣市
  有可用的中央官方 SensorThings 或 WRA/CWA read API，但沒有找到縣市政府直營、
  可公開讀取的地方直連 open API。2026-06-28 RainSewer live smoke 確認新北
  110、基隆 25、新竹市 50、新竹縣 68、苗栗 57、宜蘭 62、花蓮 80、臺東 41、
  澎湖 34、金門 29 個測站有近期觀測；連江 RainSewer count=0，目前仍是
  雨量/CAP 基線加地方靜態 metadata。coverage API 會將連江標為
  `needs_hydrologic_backbone`，直到找到公開官方水文觀測來源。
- 中央主幹保護已新增：promotion 會把 `local.*` official realtime Point evidence
  與同 event type、150 m 內、±30 分鐘內的非 local `official_realtime_latest`
  資料比對。命中時標為 `duplicate_candidate`，附上中央 adapter/station id，
  並將 local latest `source_weight` 降至 0.45，避免地方補強訊號和
  Civil IoT/WRA/CWA/NCDR 中央基線重複計分。
