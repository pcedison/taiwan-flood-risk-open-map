# 台灣淹水風險開放地圖 Project Work Plan

版本：0.1.0  
狀態：正式工作進度規劃  
來源規格：`docs/PROJECT_SDD.md`  
最後更新：2026-04-28  
專案授權決策：Apache-2.0  
主要部署決策：GitHub repo -> Zeabur VPS auto deploy  
語系決策：繁體中文 only

---

## 0. 工作計畫定位

本文件將 `docs/PROJECT_SDD.md` 轉成可執行的工程進度規劃。SDD 是需求與架構契約；本文件是實作、派工、驗收、除錯、修復與整合契約。

若 SDD 與本文件衝突，以 SDD 為準；若工作計畫需要改變架構、資料契約、授權、隱私、風險模型或部署策略，必須先更新 SDD 或新增 ADR。

---

## 1. 專案總目標

建立一個公益、開源優先、可自架、可審計、可解釋的台灣淹水風險查詢平台。

MVP 必須完成：

- 全台灣地圖查詢。
- 地址搜尋與地圖點選。
- 半徑查詢。
- 官方資料 ingestion。
- 至少一個非官方公開佐證來源。
- 即時風險、歷史風險、信心程度。
- 風險等級：`低`、`中`、`高`、`極高`、`未知`。
- Evidence list 與 explanation。
- Query heat 與風險分離。
- Docker Compose local development。
- Zeabur 部署契約。
- 基礎 CI、測試、除錯、修復與整合流程。

---

## 2. 執行節奏

### 2.1 里程碑節奏

每個 phase 採用同一套節奏：

1. Contract freeze：確認該階段 API、schema、module boundary。
2. Parallel build：依 work package 並行實作。
3. Self verification：每個 work package 自測。
4. Integration branch：合入整合分支。
5. Integration verification：跑 contract、integration、E2E smoke。
6. Repair window：針對整合失敗切修復任務。
7. Milestone acceptance：依驗收條件確認完成。

### 2.2 Branch 規則

- Branch prefix：`codex/`
- Integration branch：`codex/integration-sdd-mvp`
- 每個 work package 優先使用獨立 branch。
- 任何 subagent 不得修改非 ownership 檔案，除非主控整合者明確指定。

### 2.3 進度狀態定義

- `Not Started`：尚未開始。
- `Ready`：需求與依賴已滿足，可以派工。
- `In Progress`：正在實作。
- `Blocked`：等待依賴、資料、決策或環境。
- `Ready for Integration`：自測通過，等待合入。
- `Integrating`：正在整合分支驗證。
- `Repairing`：整合或驗收失敗，正在修復。
- `Done`：通過該 work package Definition of Done。

---

## 3. Phase Roadmap

### Phase 0：Contracts and Skeleton

目標：

- 建立專案骨架、ADR、OpenAPI、Docker Compose、CI 基礎。

建議工期：

- 2-4 個工作日。

可並行 work packages：

- WP-001 SDD/ADR/Contracts
- WP-004 Backend API Core
- WP-006 Geospatial and Database
- WP-014 Testing and CI
- WP-012 Observability and Ops, docs-only subset

主要產物：

- ADR skeleton。
- OpenAPI draft。
- Monorepo skeleton。
- Docker Compose base。
- `.env.example`。
- Zeabur deployment notes。
- Mock risk API。
- CI lint/typecheck/unit skeleton。

Phase 0 驗收：

- `docker compose up` 可以啟動核心服務或 placeholder services。
- `GET /health` 可回應。
- OpenAPI draft 可被驗證。
- 基礎 CI 可執行。
- ADR-0001 到 ADR-0008 skeleton 存在。

### Phase 1：Map and Core Query MVP

目標：

- 使用者可以在地圖上搜尋或點選位置，後端可以回傳 mock risk assessment。

建議工期：

- 4-7 個工作日。

可並行 work packages：

- WP-002 Frontend Map Shell
- WP-003 Frontend Search and Risk UI
- WP-004 Backend API Core
- WP-006 Geospatial and Database
- WP-014 Testing and CI

主要產物：

- MapLibre/Leaflet 地圖 shell。
- 地址搜尋 UI。
- 地圖點選 marker。
- Radius circle。
- Risk panel。
- Evidence drawer placeholder。
- PostGIS radius query helper。
- `POST /v1/risk/assess` mock implementation。

Phase 1 驗收：

- 使用者可以開啟首頁看到台灣地圖。
- 點選地圖可產生 marker 與半徑。
- 輸入地址可呼叫 geocode API mock 或 adapter skeleton。
- 風險面板顯示 `低/中/高/極高/未知` 之一。
- 桌面與手機版 UI 不溢位。
- Playwright smoke test 通過。

### Phase 2：Official and Public Evidence Ingestion

目標：

- 接入官方氣象、水利、淹水潛勢資料，並加入至少一個非官方公開佐證來源。

建議工期：

- 7-14 個工作日。

可並行 work packages：

- WP-007 Worker Framework
- WP-008 Official Data Adapters
- WP-009 News/Public Web Adapters
- WP-006 Geospatial and Database
- WP-012 Observability and Ops
- WP-013 Security and Privacy, data retention subset

主要產物：

- Worker runtime。
- Adapter contract implementation。
- CWA rainfall/warning adapter。
- WRA water/flood adapter。
- Flood potential import pipeline。
- News/RSS/public web adapter or legally reviewed forum adapter。
- Raw snapshot + staging + promote pipeline。
- Data source health tracking。

Phase 2 驗收：

- 至少兩個官方資料家族可 ingestion。
- 至少一個非官方公開佐證來源可 ingestion。
- Evidence normalization tests 通過。
- Adapter failure 不會讓 API 整體失效。
- Source freshness 可查詢。
- Raw snapshots 有 retention policy。

### Phase 3：Risk Scoring v0

目標：

- 根據 evidence 產生可解釋的即時風險、歷史風險與信心程度。

建議工期：

- 5-9 個工作日。

可並行 work packages：

- WP-005 Domain Risk Engine
- WP-003 Frontend Search and Risk UI
- WP-004 Backend API Core
- WP-014 Testing and CI

主要產物：

- Score version `risk-v0`。
- Realtime scoring。
- Historical scoring。
- Confidence scoring。
- Explanation builder。
- Golden fixtures。
- API integration。
- UI evidence explanation。

Phase 3 驗收：

- Golden fixtures 通過。
- 每個風險結果都有 explanation。
- AI/NLP 輸出不得成為唯一事實來源。
- Query heat 不影響 risk score。
- API 回應含 data freshness 與 missing sources。

### Phase 4：Expanded News and Public Discussion

目標：

- 擴充新聞與公開討論訊號，提高覆蓋率、去重與文字分類品質。

建議工期：

- 7-14 個工作日。

可並行 work packages：

- WP-009 News/Public Web Adapters
- WP-010 Forum Adapters
- WP-005 Domain Risk Engine, source weighting subset
- WP-013 Security and Privacy
- WP-014 Testing and CI

主要產物：

- PTT adapter, optional and default disabled until legal review。
- Dcard adapter, optional and default disabled until legal review。
- Rules + small open-source NLP classifier。
- Location mention extraction。
- Deduplication pipeline。
- False positive review fixtures。

Phase 4 驗收：

- Forum adapters 可用 config 開關。
- 不預設儲存 username。
- 不公開全文。
- NLP fixture tests 包含 false positive/false negative。
- 非官方 evidence 在 UI 上清楚標示來源與信心程度。

### Phase 5：Public Reports and Governance

目標：

- 使用者可匿名回報淹水，並具備審核、濫用控制與隱私保護。

建議工期：

- 7-14 個工作日。

可並行 work packages：

- WP-003 Frontend Search and Risk UI, report UI subset
- WP-004 Backend API Core, report API subset
- WP-013 Security and Privacy
- WP-012 Observability and Ops
- WP-014 Testing and CI

主要產物：

- User report API。
- Upload pipeline。
- EXIF cleanup。
- Moderation dashboard。
- Abuse prevention。
- Audit logs。

Phase 5 驗收：

- 匿名回報可建立。
- 上傳媒體會清理不必要 metadata。
- 管理者可審核回報。
- 可疑回報不會直接成為高權重 evidence。

### Phase 6：Production Hardening

目標：

- 完成 Zeabur production beta、監控、備份、壓測、部署文件與公開限制說明。

建議工期：

- 5-10 個工作日。

可並行 work packages：

- WP-011 Tile and Layer Pipeline
- WP-012 Observability and Ops
- WP-013 Security and Privacy
- WP-014 Testing and CI
- WP-001 SDD/ADR/Contracts, release docs subset

主要產物：

- Zeabur deployment runbook。
- Production `.env.example`。
- Backup/restore runbook。
- Metrics dashboard。
- Source freshness alert。
- Load test report。
- Public limitation statement。

Phase 6 驗收：

- GitHub push 可觸發 Zeabur redeploy。
- Production beta health check 通過。
- 備份與還原流程演練通過。
- P95 查詢延遲符合 SDD 目標或有清楚風險紀錄。
- 公開頁面有資料來源、限制與免責說明。

---

## 4. Subagent Parallel Work Design

### 4.1 Subagent 角色

`Coordinator`

- 主控整合。
- 維護 SDD、work plan、ADR、branch strategy。
- 分配 work package。
- 審查 subagent final report。
- 合併與解衝突。

`Builder`

- 負責指定檔案範圍的實作。
- 需附上自測結果。
- 不修改非 ownership 檔案。

`Verifier`

- 負責測試、E2E、contract verification、效能 smoke。
- 不直接修改 production code，除非被指定為 repair agent。

`Repair Agent`

- 只處理明確失敗項目。
- 修改範圍必須最小。
- 修復後回報 root cause 與測試結果。

### 4.2 可並行規則

可以並行：

- Frontend map shell 與 backend API skeleton。
- Worker framework 與 official adapters。
- Risk engine 與 UI risk panel，只要 API contract frozen。
- Observability 與 deployment runbook。
- Security/privacy policy 與 user report UI。

不可並行或需先 freeze：

- Database migration 與 dependent API query。
- OpenAPI response schema 與 frontend API client。
- Risk score thresholds 與 golden fixtures。
- Adapter normalized schema 與 ingestion pipeline。
- Deployment process 與 runtime service definitions。

### 4.3 Ownership Matrix

| Work Package | Ownership | Can Run In Parallel With | Must Wait For |
|---|---|---|---|
| WP-001 SDD/ADR/Contracts | `docs/`, `packages/contracts/` | all docs-only tasks | user decisions |
| WP-002 Frontend Map Shell | `apps/web/src/features/map/` | WP-004, WP-006 | frontend skeleton |
| WP-003 Search/Risk UI | `apps/web/src/features/search/`, `risk/`, `evidence/` | WP-005 after API mock | OpenAPI risk response |
| WP-004 Backend API Core | `apps/api/app/api/`, `schemas/` | WP-002, WP-006 | OpenAPI draft |
| WP-005 Risk Engine | `apps/api/app/domain/risk/`, `scoring/` | WP-003 after fixture contract | evidence schema |
| WP-006 Geospatial/DB | `infra/migrations/`, db infra | WP-004 | schema draft |
| WP-007 Worker Framework | `apps/workers/app/jobs/`, `pipelines/` | WP-008, WP-009 | adapter contract |
| WP-008 Official Adapters | `apps/workers/app/adapters/cwa/`, `wra/` | WP-007 | adapter fixtures |
| WP-009 News/Public Web | `apps/workers/app/adapters/news/` | WP-007, WP-005 | legal/source review |
| WP-010 Forum Adapters | `ptt/`, `dcard/` | WP-009 | legal/source review |
| WP-011 Tile/Layer | `packages/geo/`, tile infra | WP-002 | map layer contract |
| WP-012 Observability/Ops | `infra/monitoring/`, `docs/runbooks/` | almost all | service names |
| WP-013 Security/Privacy | `apps/api/app/security/`, `docs/privacy/` | WP-004, WP-007 | data retention rules |
| WP-014 Testing/CI | `.github/workflows/`, tests | all | skeleton structure |

---

## 5. Work Package Backlog

### Epic A：Project Foundation

#### A1. Create repository foundation

Owner：WP-001, WP-014  
Status：Ready  
Dependencies：none

Tasks:

- Create monorepo folders.
- Add Apache-2.0 `LICENSE`.
- Add root `README.md`.
- Add `.gitignore`.
- Add `.env.example`.
- Add initial `docker-compose.yml`.
- Add Zeabur deployment placeholder config if needed.

Definition of Done:

- Repo can be pushed to GitHub.
- File layout matches SDD.
- No generated secrets committed.

#### A2. ADR skeleton

Owner：WP-001  
Status：Ready  
Dependencies：none

Tasks:

- Create `docs/adr/0001-sdd-as-source-of-truth.md`.
- Create ADR files 0002-0008.
- Add ADR template.

Definition of Done:

- All initial ADRs exist.
- Each ADR has status, context, decision, consequences.

#### A3. Contract skeleton

Owner：WP-001, WP-004  
Status：Ready  
Dependencies：none

Tasks:

- Create `docs/api/openapi.yaml`.
- Define health, geocode, risk assessment, evidence, layers.
- Add schema examples.

Definition of Done:

- OpenAPI validates.
- Examples match SDD risk level labels.

### Epic B：Runtime Skeleton

#### B1. Backend API skeleton

Owner：WP-004  
Status：Ready  
Dependencies：A3

Tasks:

- Initialize FastAPI app.
- Add `/health`.
- Add structured error format.
- Add API router skeleton.
- Add config loader.

Definition of Done:

- API runs locally.
- `/health` returns ok.
- Basic tests pass.

#### B2. Database skeleton

Owner：WP-006  
Status：Ready  
Dependencies：A1

Tasks:

- Add PostGIS service.
- Add migration tooling.
- Add initial tables.
- Add spatial indexes.

Definition of Done:

- Migrations apply from empty DB.
- DB has PostGIS extension enabled.

#### B3. Worker skeleton

Owner：WP-007  
Status：Ready  
Dependencies：A1

Tasks:

- Add worker app skeleton.
- Add scheduler placeholder.
- Add sample job.
- Add job status table integration or stub.

Definition of Done:

- Sample job runs.
- Failed job logs structured error.

### Epic C：Map MVP

#### C1. Frontend skeleton

Owner：WP-002, WP-003  
Status：Ready after A1
Dependencies：A1

Tasks:

- Initialize Next.js TypeScript app.
- Add map-first route.
- Add layout and basic design system.

Definition of Done:

- App runs locally.
- First screen is map-focused.

#### C2. Map interaction

Owner：WP-002  
Status：Ready after C1
Dependencies：C1

Tasks:

- Add MapLibre/Leaflet map.
- Add Taiwan default viewport.
- Add click marker.
- Add radius circle.
- Add layer control placeholder.

Definition of Done:

- Desktop and mobile screenshot nonblank.
- Click emits coordinates.
- Radius stays visually stable.

#### C3. Search and risk panel

Owner：WP-003  
Status：Ready after C1, A3
Dependencies：C1, A3

Tasks:

- Add address search UI.
- Add radius selector.
- Add risk summary panel.
- Add evidence drawer.
- Add loading/error/partial states.

Definition of Done:

- No text overflow on mobile.
- Risk levels use `低/中/高/極高/未知`.

### Epic D：Geocode and Risk API

#### D1. Geocode adapter interface

Owner：WP-004, WP-006  
Status：Ready after A3
Dependencies：A3

Tasks:

- Add geocode endpoint.
- Add provider interface.
- Add mock provider.
- Add TGOS fallback placeholder.

Definition of Done:

- API returns candidates with confidence.
- Provider can be switched by config.

#### D2. Mock risk API

Owner：WP-004, WP-005  
Status：Ready after A3
Dependencies：A3

Tasks:

- Add risk assess endpoint.
- Add mock evidence response.
- Add data freshness placeholder.
- Add query heat placeholder.

Definition of Done:

- Frontend can consume response.
- Contract tests pass.

### Epic E：Official Evidence

#### E1. Adapter contract implementation

Owner：WP-007  
Status：Ready after B3
Dependencies：B3

Tasks:

- Define `DataSourceAdapter`.
- Add raw snapshot pipeline.
- Add staging and promote hooks.

Definition of Done:

- Sample adapter can fetch, normalize, validate, promote.

#### E2. CWA adapter

Owner：WP-008  
Status：Ready after E1
Dependencies：E1

Tasks:

- Add rainfall fixture.
- Add warning fixture.
- Add parser.
- Add normalized evidence mapping.

Definition of Done:

- Fixture parser tests pass.
- Source metadata documented.

#### E3. WRA adapter

Owner：WP-008  
Status：Ready after E1
Dependencies：E1

Tasks:

- Add water/flood warning fixtures.
- Add parser.
- Add normalized evidence mapping.

Definition of Done:

- Fixture parser tests pass.
- Source metadata documented.

#### E4. Flood potential import

Owner：WP-008, WP-006  
Status：Ready after B2
Dependencies：B2

Tasks:

- Add import script skeleton.
- Add CRS conversion rules.
- Add layer metadata.

Definition of Done:

- Sample geometry imports into PostGIS.
- Spatial intersection query works.

### Epic F：Non-official Public Evidence

#### F1. News/public web adapter

Owner：WP-009  
Status：Ready after E1
Dependencies：E1

Tasks:

- Define source allowlist.
- Add RSS/public web fixture.
- Add parser.
- Add URL/title/time/location extraction.

Definition of Done:

- Adapter default enabled only for reviewed sources.
- No full text redistribution by default.

#### F2. Rules + small NLP classifier

Owner：WP-009, WP-005  
Status：Ready after F1
Dependencies：F1

Tasks:

- Add flood keyword rules.
- Add negative keyword rules.
- Add location mention extraction.
- Add small open-source NLP model wrapper or placeholder.
- Add false positive/false negative fixtures.

Definition of Done:

- Classifier output has version.
- Every classification keeps evidence ID.
- Tests cover ambiguous phrases.

### Epic G：Risk Scoring

#### G1. Scoring engine v0

Owner：WP-005  
Status：Ready after E2, E3, F1
Dependencies：E2, E3, F1

Tasks:

- Add realtime score factors.
- Add historical score factors.
- Add confidence score.
- Add threshold mapping to risk levels.

Definition of Done:

- Pure unit tests pass.
- Score version recorded.

#### G2. Explanation builder

Owner：WP-005, WP-003  
Status：Ready after G1
Dependencies：G1

Tasks:

- Generate summary.
- Generate main reasons.
- Generate missing source warnings.
- Render explanation in UI.

Definition of Done:

- User can see why a level was assigned.
- Missing sources are visible.

### Epic H：Ops, Security, and Deployment

#### H1. Zeabur deployment runbook

Owner：WP-012  
Status：Ready after A1
Dependencies：A1

Tasks:

- Create `docs/runbooks/deploy-zeabur.md`.
- Document env vars.
- Document services.
- Document migration step.
- Document rollback strategy.

Definition of Done:

- A new maintainer can deploy from GitHub to Zeabur using the runbook.

#### H2. Privacy and retention baseline

Owner：WP-013  
Status：Ready after B2, E1
Dependencies：B2, E1

Tasks:

- Add query aggregation rules.
- Add raw snapshot retention notes.
- Add no-username storage rule for forum evidence.

Definition of Done:

- Sensitive fields identified.
- Retention policy documented.

#### H3. Observability baseline

Owner：WP-012  
Status：Ready after B1, B3
Dependencies：B1, B3

Tasks:

- Add structured log fields.
- Add metrics placeholders.
- Add source freshness metric.
- Add basic dashboard plan.

Definition of Done:

- API and worker emit structured logs.
- Source freshness can be inspected.

### Epic I：Verification and Integration

#### I1. CI baseline

Owner：WP-014  
Status：Ready after A1
Dependencies：A1

Tasks:

- Add lint/typecheck/unit workflow placeholders.
- Add OpenAPI validation.
- Add backend tests.
- Add frontend tests.

Definition of Done:

- CI runs on PR.
- Required checks documented.

#### I2. E2E smoke

Owner：WP-014, WP-002, WP-003  
Status：Ready after C2, D2
Dependencies：C2, D2

Tasks:

- Open app.
- Verify map nonblank.
- Click map.
- Run risk query.
- Verify risk panel.

Definition of Done:

- E2E smoke passes locally.
- Screenshot artifacts are usable for review.

---

## 6. Debug, Repair, and Verification Workflow

### 6.1 Bug intake format

Each bug must include:

- `bug_id`
- Affected phase/work package
- Severity：P0/P1/P2/P3
- Reproduction steps
- Expected behavior
- Actual behavior
- Logs/screenshots if available
- Suspected owner
- Blocking status

### 6.2 Severity rules

P0:

- App cannot start.
- Data loss.
- Security/privacy breach.
- Risk API returns structurally invalid response.

P1:

- Core query broken.
- Evidence ingestion broken for required sources.
- Risk scoring contradicts contract.
- Deployment broken.

P2:

- Single optional adapter broken.
- UI state broken but workaround exists.
- Performance below target but usable.

P3:

- Copy issue.
- Minor visual issue.
- Non-blocking docs gap.

### 6.3 Repair workflow

1. Reproduce。
2. Identify owner。
3. Assign repair agent。
4. Patch minimal scope。
5. Add regression test if feasible。
6. Run affected test suite。
7. Re-run integration smoke if core path touched。
8. Update runbook or SDD/ADR if root cause was contract ambiguity。

### 6.4 Verification gates

Per work package:

- Unit tests for touched domain/adapter code.
- Typecheck/lint for touched app.
- Fixture tests for parser/classifier changes.
- Contract tests for API/schema changes.

Per phase:

- Docker Compose smoke.
- API health.
- Risk query smoke.
- Frontend map smoke.
- Data source health if ingestion phase.

Pre-Zeabur deploy:

- Main branch clean.
- Required env vars documented.
- Migration plan known.
- Worker/scheduler service definitions present.
- Rollback steps documented.

---

## 7. Integration Checklist

Before merging a work package into integration branch:

- Ownership respected.
- No unrelated file churn.
- Tests listed in final report.
- Docs updated if behavior changed.
- API/schema changes reflected in OpenAPI.
- DB changes include migration.
- New env vars added to `.env.example`.

Before merging integration branch into main:

- All required work packages for phase are `Done`.
- Contract tests pass.
- E2E smoke passes.
- SDD/ADR changes reviewed.
- Zeabur deploy impact reviewed.
- Known limitations documented.

---

## 8. Subagent Final Report Template

Every subagent must return:

```text
Work package:
Branch:
Changed files:
What changed:
Tests run:
Results:
Known risks:
Follow-up tasks:
```

For repair agents:

```text
Bug ID:
Root cause:
Fix summary:
Regression test:
Verification:
Residual risk:
```

---

## 9. Initial Parallelization Plan

### Wave 1：Foundation

Can start together:

- Agent A：WP-001 ADR + contracts docs。
- Agent B：WP-004 FastAPI skeleton。
- Agent C：WP-006 PostGIS migration skeleton。
- Agent D：WP-014 CI baseline。
- Agent E：WP-012 Zeabur runbook and ops docs。

Integration target:

- Phase 0 acceptance.

### Wave 2：Map and API

Can start after Wave 1 skeleton:

- Agent A：WP-002 map shell。
- Agent B：WP-003 search/risk UI。
- Agent C：WP-004 geocode/risk endpoints。
- Agent D：WP-006 radius query helper。
- Agent E：WP-014 E2E smoke。

Integration target:

- Phase 1 acceptance.

### Wave 3：Evidence Pipeline

Can start after adapter contract:

- Agent A：WP-007 worker framework。
- Agent B：WP-008 CWA adapter。
- Agent C：WP-008 WRA adapter。
- Agent D：WP-008 flood potential import。
- Agent E：WP-009 news/public web adapter。
- Agent F：WP-012 source freshness observability。

Integration target:

- Phase 2 acceptance.

### Wave 4：Scoring and Explanation

Can start after normalized evidence fixtures:

- Agent A：WP-005 scoring engine。
- Agent B：WP-005 explanation builder。
- Agent C：WP-003 UI explanation rendering。
- Agent D：WP-014 golden fixture regression tests。

Integration target:

- Phase 3 acceptance.

### Wave 5：Expansion and Production

Can start after MVP core stable:

- Agent A：WP-010 forum adapters。
- Agent B：WP-009 NLP classifier。
- Agent C：WP-011 tile/layer pipeline。
- Agent D：WP-013 privacy/security hardening。
- Agent E：WP-012 production monitoring and runbooks。

Integration target:

- Phase 4-6 acceptance.

---

## 10. Current Project Status

As of 2026-04-28:

- SDD：Done draft, accepted for planning.
- Work plan：Created.
- Repo foundation：Done.
- GitHub repository：Done, `https://github.com/pcedison/taiwan-flood-risk-open-map`.
- Git remote `origin`：Done.
- Apache-2.0 license：Done.
- ADR skeleton：Done.
- OpenAPI draft：Done and linted.
- Monorepo folders：Done.
- Docker Compose base：Done and validated.
- Zeabur runbook：Done.
- API/web/worker placeholder runtime：Done and smoke-tested.
- First commit/push：Pending.
- Implementation：Phase 0 foundation files complete; Phase 1 map and core query implementation starts after first commit/push.

Completed execution order:

1. Create repo foundation.
2. Create GitHub repository and set `origin`.
3. Add Apache-2.0 license.
4. Add ADR skeleton.
5. Add OpenAPI draft.
6. Add monorepo folders.
7. Add Docker Compose base.
8. Add Zeabur deployment runbook.
9. Add API/web/worker placeholder runtimes.
10. Run first integration smoke.

Finalization before Phase 1:

1. Stage Phase 0 files.
2. Commit Phase 0 foundation.
3. Push `main` to GitHub.

Next execution order:

1. Replace placeholder API with contract-backed FastAPI routes.
2. Add first real `/v1/risk/assess` mock response using contract fixture.
3. Replace web placeholder with real Next.js map-first shell.
4. Add geocode provider interface and mock provider.
5. Add PostGIS table migration skeleton for core domain entities.
6. Add first frontend-to-backend smoke path.
7. Add Playwright E2E smoke for map-first workflow.

---

## 11. Completion Definition

The project is considered MVP-complete when:

- Phase 0 through Phase 3 are accepted.
- Phase 2 includes at least one non-official public evidence adapter.
- Zeabur deployment path is documented and tested.
- Risk result is explainable and evidence-backed.
- Test and repair workflow has been exercised at least once.
- Known limitations are visible to users.

The project is considered public-beta-ready when:

- Phase 4 is accepted or explicitly deferred by ADR.
- Phase 6 production hardening essentials are accepted.
- Backup/restore and deploy rollback are documented.
- Monitoring can detect source freshness failure.

---

## 12. Planning Principle

This work plan is intentionally designed so that implementation can be split across independent agents without breaking architectural coherence:

- SDD controls the shape.
- OpenAPI controls service boundaries.
- Database migrations control persistence.
- Adapter contract controls data ingestion.
- Golden fixtures control scoring behavior.
- E2E smoke controls user workflow.
- Integration branch controls convergence.

No individual work package is allowed to redefine the product by accident.
