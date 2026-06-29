# Coverage-Aware Beta Progress Handoff

日期：2026-06-29
分支：`codex/local-source-candidate-smoke`
階段判定：全台官方即時主幹 + 多縣市地方補強 adapter 的 coverage-aware beta / pre-production

## 結論

本專案已經不是早期只串 CWA 雨量的版本。現在已整合 CWA、WRA、NCDR、Civil IoT、
WRA IoW 與多縣市地方政府即時水情 adapter，並建立 coverage catalog、action plan、
request packets 和 candidate smoke，能告訴使用者「附近有哪些即時訊號」以及「缺哪些訊號」。

但目前不能宣稱「全台 22 縣市、所有鄉鎮、村里、鄰里都已有完整民間、官方、開放式
即時水情與即時水位感測器覆蓋」。目前比較準確的產品定位是：

> 全台官方與開放資料即時水情整合 beta；縣市級 coverage 盤點與多數地方 adapter
> 已落地，但尚未達到鄉鎮鄰里級完整即時感測覆蓋。

這個定位很重要。即時水位資料若距離查詢點太遠，對使用者當下所在鄰里就不一定有參考價值。
因此後續不能只看「縣市是否有資料」，必須繼續推進「查詢點附近是否有足夠密度與類型的
觀測訊號」。

## 目前量化狀態

依 `apps/api/app/domain/realtime/local_source_coverage.py` 與
`build_local_source_action_plan()` 重新盤點：

| 指標 | 目前值 | 解讀 |
| --- | ---: | --- |
| coverage catalog 縣市數 | 22 | 已有全台縣市級盤點。 |
| `local_direct_complete_count` | 20 | 20 個縣市至少有一種地方直連 production adapter 或地方供應資料 adapter。 |
| `local_direct_remaining_count` | 2 | 金門、連江仍沒有完整地方直連 read API adapter。 |
| `central_backbone_minimum_complete_count` | 21 | 21 個縣市具最低中央主幹 coverage。 |
| `central_backbone_remaining_count` | 1 | 連江仍缺中央水文觀測主幹。 |
| authorization queue | 花蓮、金門 | 需要官方授權或確認 read API。 |
| metadata release queue | 連江 | 需要即時水文觀測資料釋出或納入 Civil IoT / WRA。 |
| public API contract queue | 苗栗、屏東、臺東 | 有官方系統線索，但缺穩定公開 read API contract。 |
| live smoke / technical retry queue | 臺北、雲林 | 需要 live smoke、欄位語意或 status-only 策略追蹤。 |

## 已完成項目

### 1. 中央官方即時主幹

已建立或納入的中央主幹：

- `official.cwa.rainfall`：CWA 自動雨量。
- `official.wra.water_level`：WRA 即時水位。
- `official.ncdr.cap`：NCDR CAP 警戒。
- `official.wra_iow.flood_depth`：WRA IoW 淹水深度 latest + basic metadata join。
- `official.civil_iot.flood_sensor`：Civil IoT 淹水感測。
- `official.civil_iot.sewer_water_level`：Civil IoT 雨水下水道水位。
- `official.civil_iot.pump_water_level`：Civil IoT 抽水站水位。
- `official.civil_iot.gate_water_level`：Civil IoT 閘門外水位。

這些來源構成全台 baseline，但它們不代表每個查詢點附近都有足夠距離內的感測器。

### 2. 多縣市地方補強 adapter

目前已落地的地方 adapter 包含：

- 臺北：雨水下水道水位、河川水位、抽水站。
- 新北：水位、淹水感測、雨量、排水水位。
- 基隆：水位、淹水感測、雨量。
- 桃園：水位、路面淹水感測、雨量。
- 新竹市：雨水下水道水位、FHY 淹水感測。
- 新竹縣：FHY 淹水感測。
- 苗栗：FHY 淹水感測。
- 臺中：水位。
- 彰化：FHY 淹水感測。
- 南投：雨水下水道水位。
- 雲林：水位。
- 嘉義市：水位、雨量。
- 嘉義縣：公開 RFD 淹水感測。
- 臺南：淹水感測。
- 高雄：雨水下水道水位、淹水感測、雨量。
- 屏東：FHY 淹水感測。
- 宜蘭：淹水感測、水位。
- 花蓮：FHY 淹水感測。
- 臺東：FHY 淹水感測。
- 澎湖：ArcGIS 智慧水位。

這代表大多數縣市已有至少一種地方或地方供應的即時訊號，但不是每個縣市都具備雨量、
水位、淹水深度、雨水下水道、抽水站、水門等完整訊號族。

### 3. Coverage-aware API 與 action plan

已新增 / 強化：

- `rainfall_available`
- `water_level_available`
- `flood_depth_available`
- `sewer_water_level_available`
- `pump_or_gate_status_available`
- `status_only_available`
- `missing_signal_types`
- `blocking_reason`
- `next_action_code`
- `requested_counterparty`
- `tracking_status`
- `last_followed_up_at`

這讓 admin API 不再只回「有無資料」，而能說明每個縣市缺什麼訊號，以及下一步是技術 retry、
contract request、authorization request，或 metadata release monitoring。

### 4. Candidate smoke 與 status-only 分流

已新增 candidate smoke 工具與測試：

- `apps/workers/app/ops/local_source_candidate_smoke.py`
- `scripts/local-source-candidate-smoke.py`
- `apps/workers/tests/test_local_source_candidate_smoke.py`
- `tests/test_local_source_candidate_smoke_cli.py`

目前 candidate smoke 能區分：

- `promotion_ready`
- `status_only_ready`
- `blocked_timeout`
- `needs_authorization_or_session`
- `needs_api_contract`
- `needs_measurement_value`
- `needs_observed_time_and_metadata`
- `needs_observed_time`
- `needs_metadata`
- `not_checked`

雲林 iflood 淹水感測是第一個 status-only 案例：有 `latestUpdateTime`、站點、座標與
`alarmState`，但沒有水深測值，因此不能當作 flood depth。

### 5. 官方請求包與追蹤文件

已產生並更新：

- `docs/data-sources/local/official-request-packets.md`
- `docs/data-sources/local/generated-official-request-packets.md`
- `docs/data-sources/local/generated-official-request-packets.json`

目前正式請求包涵蓋：

- 花蓮：Senslink / 行動水情 read API 授權。
- 金門：KWIS read API 授權。
- 連江：即時水文觀測資料釋出或納入 Civil IoT / WRA 主幹。
- 苗栗：雨水下水道即時水情 read API contract。
- 屏東：PTEOC RainStation / River / Flood / Crawler read API contract 與站點 metadata。
- 臺東：洪水與淹水預警系統 read API contract。

### 6. 高雄雨量補強

已將高雄 SFC `rain/rt` + `rain/base` 納入 local rainfall adapter：

- `local.kaohsiung.rainfall`
- 以 `ST_NO` join station metadata。
- 保留 `M10`、`M20`、`H1`、`H3`、`H6`、`H12`、`H24`。
- 僅補足 CWA 空間密度，不取代 CWA。

相關 env gate 也已補到 `.env.example`。

## 尚未完成項目

### 1. 不能宣稱鄉鎮鄰里級完整即時覆蓋

原本 coverage catalog 是縣市級與訊號族級，不是「查詢點半徑內感測器密度」級。
2026-06-29 的 query-point nearby coverage 初版已把 public risk response、API contract、
Web panel、diagnostics 與 runtime smoke assertion 接上 `nearby_realtime_coverage`，
可以回報最近感測器距離、500m / 1km / 3km / 5km 站數、缺哪些水文訊號，
並明確區分「縣市有資料」和「查詢點附近真的有 fresh 即時資料」。
本機 Docker Desktop 啟動後，full Docker runtime smoke 已在 2026-06-29 通過，
證明 live Compose API 實際執行了 nearby coverage assertion。

尚未完成：

- 鄉鎮 / 村里 / 鄰里級 coverage heatmap。
- 依事件類型與地形情境校準有效半徑；目前初版採固定 500m / 1km / 3km / 5km
  bucket 與 signal-level coverage level，尚未建立水位站、雨量站、淹水感測器的
  差異化 production 門檻。

### 2. 金門地方直連 read API 尚未完成

目前狀態：

- Civil IoT 中央主幹可補金門部分即時水文訊號。
- KWIS 公開文件偏第三方設備上傳 API。
- 需要帳密、key 或 token。
- 尚未確認有可公開或授權使用的 latest read API。

下一步：

- 發送 KWIS read API 授權請求。
- 確認 API 是 read，不是設備上傳。
- 取得正式 contract、rate limit、授權條款與範例 response。

### 3. 連江即時水文觀測嚴重不足

目前狀態：

- 地方只找到靜態 ODS / 防災資料。
- 中央主幹目前也缺 hydrologic observation。
- 仍缺 water level、flood depth、sewer water level、pump/gate status。

下一步：

- 請求連江縣釋出即時水文觀測 read API。
- 或推動加入 Civil IoT / WRA 公開主幹。
- 若短期無感測器，至少取得建置計畫或資料釋出時程。

### 4. 苗栗、屏東、臺東仍缺公開 read API contract

苗栗：

- FHY 淹水感測已接。
- 雨水下水道監測目前只有 HTML / 成果說明。
- 缺雨水下水道水位 read API、observed time、station id、座標 metadata。

屏東：

- FHY 淹水感測已接。
- PTEOC `/RainStation`、`/River`、`/Flood`、`/Crawler` 有官方平台線索。
- HTML 不足以 production，缺 observed_at、station id、座標 metadata。

臺東：

- FHY 淹水感測已接。
- 洪水與淹水預警系統線索存在。
- 尚未找到公開 read API endpoint。

### 5. 花蓮更完整行動水情仍需授權

目前狀態：

- FHY 花蓮淹水感測已接。
- Senslink / 行動水情更完整儀表板需登入或授權。
- 不能繞過登入，也不能逆向私人 API。

下一步：

- 向花蓮縣政府或 Senslink 維運窗口申請 read API 授權。
- 取得授權後先進 staging / disabled-by-default adapter。

### 6. 臺北疏散門仍需技術 retry

目前狀態：

- 臺北雨水下水道、河川水位、抽水站已接。
- 疏散門 OpenAPI contract 線索存在。
- `wic.heo.taipei` smoke timeout。

下一步：

- 測試 `wic.gov.taipei` mirror。
- 確認 `fo` / `fc` / `flt` 欄位語意。
- 若穩定，建立 gate / infrastructure status adapter，不混入 flood depth。

### 7. 雲林淹水感測仍只是 status-only

目前狀態：

- 雲林水位已接。
- iflood 淹水感測類有站點、時間、座標與 `alarmState`。
- 缺水深測值。

下一步：

- public API 或官方 contract 若找到水深欄位，才能升級為 flood depth。
- 在此之前只能做 `flood_sensor_status` 或 `infrastructure_status`。
- 不能把 `alarmState` 當水深或風險分數主訊號。

## 需要補強的產品能力

### 1. 查詢點半徑內 coverage 評估

初版已建立「查詢點附近」評估，而不是只看 county coverage。

目前 public response 欄位為 `nearby_realtime_coverage`，已輸出：

- nearest sensor distance by signal type。
- sensor count within 500m / 1km / 3km / 5km。
- coverage confidence：high / medium / low / no-local-sensor。
- missing nearby signal types。
- stale nearby station count。

下一步應把這套評估擴展到 admin / ops dashboard、township / village heatmap，
並用實際事件回放校準各 signal type 的有效半徑。

### 2. UI / Public API 文案分級

需要避免二元文案：

- 不說「此縣市即時水情完整」。
- 不說「此縣市沒有資料」。
- 改說「附近有 / 沒有哪幾種即時觀測」。

建議等級：

- 高可信：查詢點附近有近期水深、水位、雨水下水道或雨量觀測。
- 中可信：只有警戒、設施狀態或較遠觀測站。
- 低覆蓋：只有 CWA / NCDR 或靜態資料，缺附近地方水文觀測。

### 3. Sensor density 和 source quality dashboard

需要 admin 或 ops dashboard 追蹤：

- 各縣市各 signal type 站數。
- 各 signal type stale rate。
- 最近成功 ingestion。
- adapter failure streak。
- county / township / village coverage heatmap。
- 需要人工授權、API contract、metadata release 的工作隊列。

### 4. 排程化 candidate discovery

目前已有 candidate smoke / request packet，但仍需排程化：

- Technical retry queue：臺北疏散門、雲林 status-only、臺東 timeout 線索。
- Contract discovery queue：苗栗、屏東、臺東、連江。
- Authorization queue：花蓮、金門、連江。

排程結果不應自動升 production；必須通過欄位、freshness、座標、授權檢查。

## 尚未補強的風險

### 1. 民間 / crowdsourced 即時水情尚未形成可信主幹

目前專案重心仍是官方與開放資料。民間來源、社群回報、群眾回報雖有架構線索，
但尚未成為全台可信即時主幹。

需要補：

- 民間資料 source approval。
- 反濫用與可信度評分。
- 地理位置隱私處理。
- 與官方觀測衝突時的解釋策略。

### 2. 「即時」仍受 station density 限制

即使 adapter 是 live，如果查詢點離 station 太遠，仍不能宣稱使用者所在地有即時水情。

需要補：

- 每筆 evidence 的 spatial applicability。
- 每種 sensor 的有效參考半徑。
- 查詢結果中揭露「最近觀測距離」。

### 3. Source overlap / double counting 仍需持續治理

Civil IoT、WRA IoW、FHY、地方平台可能有同源或重疊感測器。

需要補：

- station identity matching。
- duplicate suppression。
- source precedence。
- 同一設備在中央與地方來源重複出現時的 attribution policy。

## 本地端工作成果摘要

本地工作樹目前包含以下大類成果，已準備 commit：

1. 高雄 local rainfall adapter、env gates、registry/runtime wiring 與 migration。
2. Local source candidate smoke module、CLI 與測試。
3. Coverage-aware admin API 欄位與 OpenAPI schema。
4. Local source action plan 追蹤欄位與完整 blocker queue。
5. Official request packet generator 支援 public API contract requests。
6. 6 個縣市的 generated request packets。
7. 2026-06-29 local source blocker resolution design spec。
8. 本交接進度文件。

## 接手建議順序

1. 先 sync branch `codex/local-source-candidate-smoke`。
2. 跑本文件下方的驗證指令。
3. 檢查 `GET /admin/v1/local-source-coverage` 與 `GET /admin/v1/local-source-action-plan`。
4. 複驗並擴充 `nearby_realtime_coverage`，確認「縣市有資料但查詢點附近沒有資料」
   的 public API / UI 邊界在 Docker runtime 與正式環境都成立。
5. 再推臺北疏散門 fallback、雲林 status-only UI、苗栗/屏東/臺東 request packet 流程。
6. 最後處理花蓮、金門、連江這類需要人工授權或政策合作的項目。

## 驗證指令

本地已使用 Python 3.12 runtime 驗證：

```bash
PYTHONPATH=apps/api /Users/marcus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest apps/api/tests/test_admin_contract.py apps/api/tests/test_local_source_action_plan.py apps/api/tests/test_local_source_request_packets.py tests/test_local_source_request_packets_cli.py -q

PYTHONPATH=apps/workers /Users/marcus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest apps/workers/tests/test_local_source_candidate_smoke.py tests/test_local_source_candidate_smoke_cli.py -q

PYTHONPATH=apps/workers /Users/marcus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest apps/workers/tests/test_local_kaohsiung_yilan_water_adapters.py apps/workers/tests/test_adapter_registry_config.py -q

PYTHONPATH=apps/api /Users/marcus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 infra/scripts/validate_openapi.py

/Users/marcus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m ruff check apps/api/app/api/routes/admin.py apps/api/app/api/schemas.py apps/api/app/domain/realtime/local_source_action_plan.py apps/api/app/domain/realtime/local_source_coverage.py apps/api/app/domain/realtime/local_source_request_packets.py apps/api/tests/test_admin_contract.py apps/api/tests/test_local_source_action_plan.py apps/api/tests/test_local_source_request_packets.py apps/workers/app/ops/local_source_candidate_smoke.py apps/workers/tests/test_local_source_candidate_smoke.py tests/test_local_source_request_packets_cli.py
```

注意：系統預設 `/usr/bin/python3` 是 Python 3.9，不能跑本專案 API 測試；專案使用
Python 3.12 語法，例如 PEP 695 generic function syntax。

## Query-point nearby coverage implementation status

2026-06-29 query-point nearby coverage 初版已落地在 public API、Web UI、runtime
smoke assertion 與 handoff 文件中。Public risk response 欄位為
`nearby_realtime_coverage`。

已驗證：

```powershell
$py='C:\Users\y_mea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_nearby_realtime_coverage.py apps/api/tests/test_evidence_repository.py apps/api/tests/test_public_risk_service.py apps/api/tests/test_public_contract.py -q -p no:cacheprovider --basetemp '.codex-tmp\pytest\basetemp'
# 103 passed, 2 existing warnings

$env:PYTHONPATH='apps/api'
& $py infra/scripts/validate_openapi.py
# OpenAPI 3.1 spec valid. paths=16 schemas=61

npm test --prefix apps/web
# 49 passed

npm run lint --prefix apps/web
# passed

npm run typecheck --prefix apps/web
# passed
```

Full Docker runtime smoke status on this machine:

- `.\\scripts\\runtime-smoke.ps1 -StopOnExit` was blocked by local PowerShell
  execution policy before running.
- Retried with `powershell.exe -ExecutionPolicy Bypass -File .\\scripts\\runtime-smoke.ps1 -StopOnExit`.
- After Docker Desktop was started, full Docker runtime smoke passed on this
  machine. The smoke executed the live Compose API/Web stack and included the
  new nearby coverage assertion:

```text
Nearby realtime coverage smoke: overall=no_local_sensor, missing=rainfall,water_level,flood_depth,sewer_water_level
MVT smoke: layer=query-heat, HTTP 200, content-type=application/vnd.mapbox-vector-tile
MVT smoke: layer=flood-potential, HTTP 200, content-type=application/vnd.mapbox-vector-tile
reports_enabled_smoke=ok report_id=<runtime-smoke-report-id> status=pending
tile_lifecycle_smoke=ok pruned_cache=1 pruned_features=1 invalidated_features=2 deleted_cache=1
Web smoke: HTTP 200 from http://localhost:3000
Runtime smoke passed.
```

Runtime smoke follow-up fix applied:

- The smoke now temporarily enables the seeded `query-heat` and
  `flood-potential` MVT layers only for runtime validation, then restores their
  previous `map_layers.status`.
- The reports enabled-path smoke now handles both sync and async
  `create_user_report` implementations.
- Post-smoke DB verification confirmed `query-heat` and `flood-potential`
  returned to `disabled` with no `runtime_smoke_previous_status` marker.

Boundary statement: county coverage is not nearby coverage. A county can have
local or central realtime sources while the queried point still has no fresh
sensor within the relevant radius. Public API and UI must continue to describe
the nearby result as `high` / `medium` / `low` / `no_local_sensor` /
`unavailable` instead of saying the county is complete or empty.
