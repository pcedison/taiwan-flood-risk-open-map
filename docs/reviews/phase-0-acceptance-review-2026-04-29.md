# Phase 0 Acceptance Review — 2026-04-29

審查者：Claude (Opus 4.7) — 全棧視角，配合自動化工具驗證
審查目標：驗證 Codex GPT-5.5 交付的 Phase 0 是否符合 `docs/PROJECT_SDD.md` §18 與 `docs/PROJECT_WORK_PLAN.md` §3 的驗收條件，並修正不符合處。
審查範圍：Phase 0 — Contracts and Skeleton。Phase 1+ 之外的內容不在本次調整範圍內。

---

## 1. 設計觀察

Codex 採用**雙軌 runtime** 設計：

- `docker-compose.yml` 跑的是 stdlib-only placeholder：`apps/api/app/placeholder_server.py`、`apps/web/server-placeholder.mjs`。不需要 `pip install` / `npm install` 即可起動。
- 真實的 FastAPI app（`apps/api/app/main.py`）與 Next.js app（`apps/web/app/page.tsx`）作為 Phase 1+ scaffolding 同時存在。每個 app 的 `README.md` 都明確說明哪個是 placeholder、哪個是 future。

此設計符合 Phase 0 「placeholder services 可啟動」的工作計畫精神，且免除依賴安裝負擔。**代價**是 placeholder 與真實實作可能對同一份 OpenAPI 契約產生不同回應；本次審查確認了這點正是發生 P1 缺陷之處。

---

## 2. 驗收條件結果

引自 `docs/PROJECT_WORK_PLAN.md` §3 Phase 0 驗收。

| 條件 | 修正前 | 修正後 |
|---|---|---|
| `docker compose up` 可以啟動核心服務或 placeholder services | ✅ 7 個服務全 running | ✅ 維持 |
| `GET /health` 可回應 | ⚠️ 回應但不符合 `HealthResponse` 契約 | ✅ 完全符合契約 |
| OpenAPI draft 可被驗證 | ⚠️ CI 只是 echo 字串 | ✅ CI 透過 `openapi-spec-validator` 真正驗證 |
| 基礎 CI 可執行 | ✅ 但缺實際 schema gate | ✅ 增加 OpenAPI + fixture conformance gate |
| ADR-0001 到 ADR-0008 skeleton 存在 | ✅ 八份齊全且結構正確 | ✅ 維持 |

驗證使用工具：
- `openapi-spec-validator` (Python) — OpenAPI 3.1 meta-schema 驗證
- `jsonschema` (Python, Draft 2020-12) — 契約 fixtures + inline examples 驗證
- `docker compose config` — compose 檔語法
- `python -m compileall` — Python module byte-compile
- `curl` + 實機 PostGIS / Redis healthcheck — runtime smoke

---

## 3. 缺陷與修正

### P1-1：`/health` 違反 `HealthResponse` 契約

**症狀（修正前）**

兩個 `/health` 實作都與 `docs/api/openapi.yaml` 定義的 `HealthResponse` schema 不符：

- `apps/api/app/placeholder_server.py` 回傳 `{"status":"ok","service":"api","runtime":"placeholder"}`
  - 缺 `version`（required）、缺 `checked_at`（required）
  - 多了 `runtime`，違反 `additionalProperties: false`
- `apps/api/app/api/routes/health.py` 回傳 `{"status":"ok","service":"api"}`
  - 缺 `version`、缺 `checked_at`

**修正**

- placeholder 補上 `version`（從 `API_VERSION` env var，預設 `0.1.0-draft`）與 `checked_at`（每次請求 UTC ISO 8601 時間戳）；移除 `runtime` 欄位
- FastAPI route 同樣補齊；改用 `app.core.config.get_settings()` 拿配置以維持單一來源

**修正後 live 回應**

```json
{
  "status": "ok",
  "service": "flood-risk-api",
  "version": "0.1.0-draft",
  "checked_at": "2026-04-29T01:47:05.897880Z"
}
```

實機透過 jsonschema Draft 2020-12 對 `HealthResponse` schema 驗證 — 完全 conform。

### P1-2：CI 沒有真正驗證 OpenAPI

**症狀（修正前）**

`.github/workflows/ci.yml` 的 OpenAPI step：

```yaml
- name: OpenAPI validation placeholder
  run: |
    if [ -f docs/api/openapi.yaml ]; then
      echo "OpenAPI spec found; wire validator after contract package lands."
    else
      echo "OpenAPI spec not present in this runtime skeleton checkout; skipping."
    fi
```

只 echo 字串，未執行任何驗證。違反 Phase 0 驗收「OpenAPI draft 可被驗證」。

**修正**

- 新增 `infra/scripts/validate_openapi.py`：用 `openapi-spec-validator` 對 OpenAPI 3.1 meta-schema 驗證 `docs/api/openapi.yaml`，發現任何 schema 錯誤就 exit 1
- CI 安裝 `openapi-spec-validator`、`jsonschema`、`pyyaml` 後執行此 script

### P2-1：契約 fixtures / inline examples 無 schema regression 守門

**症狀**

`packages/contracts/fixtures/risk-assess-response.json` 與 `docs/api/openapi.yaml` 內 `paths.*.responses.*.content.application/json.examples` 都是契約測試材料，但沒有 CI gate 檢查它們仍符合對應 schema。未來改 spec 容易漂移而不被發現。

**修正**

- 新增 `infra/scripts/validate_contract_fixtures.py`：
  - 把 `packages/contracts/fixtures/*.json` 對應到 schema 名稱（目前 `risk-assess-response.json` → `RiskAssessmentResponse`）
  - 走訪 OpenAPI 所有 path operation 的 inline examples，對 response schema 驗證每一份 example
  - 任何不符即 exit 1 並印出 schema path 與錯誤訊息
- CI 加入此 step

### Housekeeping：`Settings.app_name` 雙重職責

**問題**

`Settings.app_name` 同時充當 FastAPI `title=`（人類可讀，例如 "Flood Risk API"）與 `/health` 的 `service` 欄位（OpenAPI example 是 kebab-case `flood-risk-api`）。把任一個改成另一個都會讓對方變難看或不對齊範例。

**修正**

`Settings` 拆成兩個欄位：

- `app_title`：給 FastAPI `title=` 用，預設 `"Flood Risk API"`
- `service_id`：給 `/health` 用，預設 `"flood-risk-api"`

兩處實作（FastAPI `main.py`、`/health` route）相應更新。

### Housekeeping：`.claude/` 入 `.gitignore`

`.claude/settings.local.json` 是 Claude Code 工作時的本地設定，不該入版本控制。`.gitignore` 加入 `.claude/`。

---

## 4. 動到的檔案清單

### Modified

- `.github/workflows/ci.yml` — 換掉 OpenAPI echo placeholder 為真實驗證 step；增加 fixture 驗證 step；compose config 加 `--quiet`
- `.gitignore` — 加 `.claude/`
- `apps/api/app/api/routes/health.py` — `/health` 補齊 `version` 與 `checked_at`
- `apps/api/app/core/config.py` — `Settings` 拆 `app_title` / `service_id`，新增 `API_VERSION` env var 讀取
- `apps/api/app/main.py` — `FastAPI(title=...)` 改用 `app_title`
- `apps/api/app/placeholder_server.py` — `/health` 補齊欄位、移除 `runtime`、用 `API_VERSION` env var

### Added

- `infra/scripts/validate_openapi.py` — OpenAPI 3.1 meta-schema 驗證器（CI gate）
- `infra/scripts/validate_contract_fixtures.py` — fixtures + inline examples 對 schema 的 conformance 驗證器（CI gate）
- `docs/reviews/phase-0-acceptance-review-2026-04-29.md` — 本檔

---

## 5. Verification Evidence

修正後在本機完整跑過下列驗證，全綠：

```text
$ python -m compileall -q apps/api apps/workers
compileall OK

$ python infra/scripts/validate_openapi.py
OpenAPI 3.1 spec valid. paths=8 schemas=33

$ python infra/scripts/validate_contract_fixtures.py
All contract examples and fixtures conform to their OpenAPI schemas.

$ docker compose config --quiet
(no output, exit 0)

$ docker compose up -d
(7 services started: web, api, worker, scheduler, postgres healthy, redis healthy, minio)

$ curl -s http://localhost:8000/health
{"status": "ok", "service": "flood-risk-api", "version": "0.1.0-draft", "checked_at": "2026-04-29T...Z"}

$ docker compose exec -T postgres psql -U flood_risk -d flood_risk -c "SELECT PostGIS_Version();"
3.4 USE_GEOS=1 USE_PROJ=1 USE_STATS=1
```

並透過 jsonschema Draft 2020-12 將 live `/health` 回應對 `HealthResponse` schema 驗證 — conform。

---

## 6. 不在本次修正範圍

下列項目觀察到但屬 Phase 1+ 工作或無 Phase 0 驗收影響，**未動**：

- `apps/web/app/page.tsx` 與 `apps/web/server-placeholder.mjs` 是兩條不相干路徑。Phase 1 切換到 Next.js 時要一起替換 compose `command` 與 web Dockerfile / npm install
- `apps/api/app/main.py` 在 compose 跑不到，要等 Phase 1 加上 Dockerfile + pip install + uvicorn 才會啟用
- `infra/migrations/` 只有 `0001_enable_postgis.sql`。SDD §11.1 列的 13 個 table 屬 Phase 1+ Work Package WP-006 範圍
- 沒有實質單元測試（各 `tests/` 只有 README placeholder）。Work Plan 把這歸到「lint/typecheck/unit skeleton」，Phase 0 容許
- `apps/api/app/api/errors.py` 的 `error_payload` 把 `details=None` 寫成 `{}`，OpenAPI schema 容許 null/object/array/string；不影響 conformance
- `Frontend lint and test placeholder` 與 `Backend lint placeholder` 等仍是 echo，等實際 dependency 安裝步驟與 lint config 進來再啟用

---

## 7. 給 Phase 1 接手者的提醒

- 替換 placeholder → FastAPI 時，`/health` 已契約合規，只需把 compose `command` 換成 `uvicorn app.main:app` 並加上 image build / dependency install
- 任何新 endpoint 都要先在 `docs/api/openapi.yaml` 加 schema 與 example，再實作（SDD §0.2）。CI 的 fixture validator 會擋住 example / fixture 漂移
- 新 fixture 要登錄到 `infra/scripts/validate_contract_fixtures.py` 的 `FIXTURE_SCHEMA_MAP`
- 所有有對應 OpenAPI schema 的 JSON 回應，**多餘欄位都是契約違反**（多數 schema 都 `additionalProperties: false`）。debug 欄位請走 header 或另開 endpoint
