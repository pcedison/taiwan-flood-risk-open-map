# Nationwide Sensor Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nationwide Taiwan realtime water-sensor integration complete, auditable, and production-safe across central backbone, local government sources, query-point nearby coverage, scheduler persistence, and operator monitoring.

**Architecture:** Keep the worker-persisted evidence path as the production source of truth. Use the local source coverage catalog as the authoritative backlog, expose a ranked integration queue for operators and agents, then complete each county/signal gap through adapters, authorization packets, public read API contracts, smoke tests, and hosted production gates. Query UI reads only the persisted evidence and nearby coverage output; county-level source availability never substitutes for sensors near the searched point.

**Tech Stack:** FastAPI, Pydantic, psycopg/PostGIS, Python worker adapters, pytest, OpenAPI 3.1 YAML, PowerShell runtime smoke, Zeabur single-service deployment with worker scheduler, Next.js/React for public display.

## Global Constraints

- Default public-facing language is Traditional Chinese.
- Hosted runtimes (`staging`, `production`, `production-beta`) must use worker-persisted evidence for official realtime data; direct API bridge calls are local diagnostic only.
- Do not scrape private dashboards, bypass login, bypass captcha, reverse private APIs, or use upload-only device APIs as read APIs.
- A production realtime source needs observed time, stable station/device id, measurement value, measurement unit/type, coordinate or joinable station metadata, source URL/license, freshness policy, raw snapshot retention, and monitored scheduler cadence.
- Status-only sources must not be mislabeled as water level, rainfall, or flood depth measurements.
- County-level coverage catalog entries are planning and operator metadata; public nearby coverage must be computed from persisted rows around the query point.
- Every code slice must start with a failing test, then a minimal implementation, then verification.
- GitHub PRs must state whether work is code, source contract, authorization packet, scheduler/ops gate, or production deployment evidence.

---

## Priority Roadmap

| Priority | Workstream | Counties / scope | Exit gate |
| --- | --- | --- | --- |
| P0 | Restore minimum nationwide hydrologic backbone | 連江縣 | Completed 2026-06-30 by `official.cwa.tide_level`; keep local-direct follow-up separate because CWA tide is coastal context, not a local flood/sewer/pump/gate feed. |
| P0 | Complete local direct source absence | 金門縣、連江縣 | Each county has either a production adapter or a documented authorization/open-data request with required read API fields. |
| P1 | Resolve authorization-gated richer sources | 花蓮縣、金門縣 | Request packet records official counterparty, API purpose, required fields, raw snapshot and license requirements. |
| P1 | Resolve technical live-smoke blockers | Current queue empty after 臺北市、雲林縣 status-only reviews | Candidate endpoints are smoked with observed time, id, value semantics, coordinates, and status-only separation. |
| P2 | Resolve public read API contract blockers | 苗栗縣、屏東縣、臺東縣 | Each candidate either becomes a production adapter or remains blocked with a precise missing field/contract reason. |
| P2 | Fill missing sensor signal families | Ready counties missing rainfall, water level, flood depth, sewer water level, or pump/gate status | `sensor_signal_gap_reviews` shows fewer missing required signal families per county, with no silent risk-score changes. |
| P3 | Hosted persistence and scheduler proof | All enabled central/local adapters | Worker scheduler writes raw snapshots, staging, adapter runs, and promoted evidence under Zeabur-compatible env gates. |
| P3 | Monitoring and alerting proof | `/admin/v1/sources`, freshness checks, monitoring dashboards | Fresh/stale/failed source state is visible and alertable; no deployed source is silently stale. |
| P4 | Public UX confidence alignment | Web risk sidebar and diagnostics | UI explains nearby sensor coverage, missing signal types, source confidence, and evidence age without claiming unavailable sensors. |

## File Structure Map

- Modify `apps/api/app/domain/realtime/local_source_action_plan.py`: build a ranked `integration_priority_queue` plus `sensor_signal_gap_reviews`.
- Modify `apps/api/app/api/schemas.py`: add Pydantic models for the new queues.
- Modify `apps/api/app/api/routes/admin.py`: continue returning the action plan through `LocalSourceActionPlan`.
- Modify `docs/api/openapi.yaml`: expose new queue fields in `AdminLocalSourceActionPlanResponse`.
- Modify `apps/api/tests/test_local_source_action_plan.py`: unit-test queue ordering and signal-gap inclusion.
- Modify `apps/api/tests/test_admin_contract.py`: contract-test the admin endpoint and OpenAPI schema.
- Modify `docs/reviews/coverage-aware-beta-progress-handoff-2026-06-29.md`: record that the next execution path starts from the ranked queue, not ad hoc source picking.
- Later adapter tasks modify `apps/workers/app/adapters/local_*`, `apps/workers/app/adapters/registry.py`, worker tests, env gates, and request packet docs per county.

## Task 1: Ranked Integration Queue

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: `LocalSourceCoverageRecord`, `build_local_source_action_plan(records)`.
- Produces: `plan["integration_priority_queue"]` and `plan["sensor_signal_gap_reviews"]`.

- [x] **Step 1: Write the failing unit test**

Add assertions that:

```python
priority = plan["integration_priority_queue"]
assert [item["county"] for item in priority[:3]] == ["連江縣", "金門縣", "花蓮縣"]
assert priority[0]["priority_tier"] == "P0"
assert priority[0]["workstream"] == "monitor_open_data_release"
assert priority[0]["central_backbone_missing_signal_types"] == []
assert priority[0]["missing_signal_types"] == [
    "flood_depth",
    "sewer_water_level",
    "pump_or_gate_status",
]
assert priority[1]["workstream"] == "request_official_authorization"
assert "local_direct_source" in priority[1]["why_now"]

signal_gaps = {item["county"]: item for item in plan["sensor_signal_gap_reviews"]}
assert "嘉義市" in signal_gaps
assert {"flood_depth", "sewer_water_level", "pump_or_gate_status"}.issubset(
    set(signal_gaps["嘉義市"]["missing_signal_types"])
)
assert "高雄市" not in signal_gaps
```

Run:

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_local_source_action_plan.py -q
```

Expected: fail because the new queues do not exist.

- [x] **Step 2: Implement queue builders**

Add helper functions:

```python
def _integration_priority_queue(records: tuple[LocalSourceCoverageRecord, ...]) -> list[dict[str, Any]]:
    candidates = [record for record in records if _needs_integration_work(record)]
    ordered = sorted(candidates, key=_integration_sort_key)
    return [_integration_priority_item(rank=index + 1, record=record) for index, record in enumerate(ordered)]

def _sensor_signal_gap_reviews(records: tuple[LocalSourceCoverageRecord, ...]) -> list[dict[str, Any]]:
    return [
        _sensor_signal_gap_review(record)
        for record in records
        if record.local_direct_complete
        and record.next_action_code == "operate_adapter"
        and record.missing_signal_types
    ]
```

`_integration_sort_key()` must put central hydrologic gaps before local direct gaps, then authorization, live smoke, public API contract, and metadata release.

- [x] **Step 3: Verify unit tests pass**

Run:

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_local_source_action_plan.py -q
```

Expected: all tests pass.

- [x] **Step 4: Extend admin contract and OpenAPI**

Add Pydantic models:

```python
class LocalSourceIntegrationPriorityItem(ContractModel):
    rank: int = Field(ge=1)
    priority_tier: str
    county: str
    workstream: str
    next_action_code: str
    tracking_status: str
    requested_counterparty: str
    blocking_reason: str | None = None
    why_now: str
    completion_gate: str
    missing_signal_types: list[str] = Field(default_factory=list)
    central_backbone_missing_signal_types: list[str] = Field(default_factory=list)
    production_adapter_keys: list[str] = Field(default_factory=list)
    candidate_source_names: list[str] = Field(default_factory=list)
    candidate_source_urls: list[str] = Field(default_factory=list)
    application_urls: list[str] = Field(default_factory=list)
    required_read_api_fields: list[str] = Field(default_factory=list)
```

Add `integration_priority_queue` and `sensor_signal_gap_reviews` to `LocalSourceActionPlan`, then mirror those fields in `docs/api/openapi.yaml`.

- [x] **Step 5: Verify admin contract**

Run:

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_admin_contract.py::test_admin_local_source_action_plan_contract -q
python infra/scripts/validate_openapi.py
```

Expected: both commands pass.

## Task 2: Lienchiang Hydrologic Backbone Packet

**Files:**
- Modify: `docs/data-sources/local/official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.json`
- Test: `apps/api/tests/test_local_source_request_packets.py`

**Interfaces:**
- Consumes: `integration_priority_queue[0]` for `連江縣`.
- Produces: a request packet asking for live hydrologic read API fields and a tracking status for official follow-up.

- [x] Historical blocker packet created before CWA tide-level integration. Superseded 2026-06-30 by Task 12: `official.cwa.tide_level` closes the central `hydrologic_observation` gap, so the current packet targets local-direct `flood_depth`, `sewer_water_level`, and `pump_or_gate_status`.
- [x] Generate or update the packet content from existing `build_local_source_action_plan()` data.
- [x] Run `python -m pytest apps/api/tests/test_local_source_request_packets.py tests/test_local_source_request_packets_cli.py -q`.

## Task 3: Kinmen KWIS Authorization Packet

**Files:**
- Modify: `docs/data-sources/local/official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.json`
- Test: `apps/api/tests/test_local_source_request_packets.py`

**Interfaces:**
- Consumes: `integration_priority_queue` item for `金門縣`.
- Produces: a packet that distinguishes KWIS upload API documents from the needed read API contract and lists the token-gated read methods discovered in the ASMX/WSDL.

- [x] Write a failing test requiring the Kinmen packet to state that upload-only APIs are insufficient.
- [x] Add required read API fields and counterparty `金門縣政府 / KWIS 維運窗口`.
- [x] Confirm KWIS ASMX/WSDL exposes token-gated read methods for rain gauges, water-level gauges, flood-sensing devices, pumps, and station sensor lists.
- [x] Record blank-token smoke result: KWIS read methods return `ErrMsg (7)` with `Data: []`, so production adapter remains blocked on official Token authorization.
- [x] Run request packet tests.

## Task 4: Taipei Evacuation Gate Live Smoke

**Files:**
- Modify: `apps/workers/app/ops/local_source_candidate_smoke.py`
- Modify: `apps/workers/tests/test_local_source_candidate_smoke.py`
- Modify: `docs/data-sources/local/2026-06-28-local-source-verification-log.md`

**Interfaces:**
- Consumes: candidate URL `臺北市疏散門即時監測`.
- Produces: existing smoke status `promotion_ready` / `start_adapter_tdd` only when observed time, station id, status semantics, and coordinates are validated.

- [x] Write a failing smoke test for mirror host fallback from `wic.heo.taipei` to `wic.gov.taipei`.
- [x] Implement fallback without bypassing auth or private endpoints.
- [x] Keep evacuation gate status out of flood depth and water level event types.

## Task 5: Yunlin Status-Only Evidence Type

**Files:**
- Modify: `apps/api/app/domain/realtime/nearby_coverage.py`
- Modify: `apps/workers/app/adapters/local_yunlin/water.py`
- Modify: worker and API tests for status-only handling.

**Interfaces:**
- Consumes: Yunlin `alarmState` rows with station id, latest update time, and coordinates.
- Produces: status-only evidence that can appear in coverage diagnostics but does not satisfy flood depth, water level, or rainfall measurements.

- [x] Write a failing test proving `alarmState` cannot reduce `missing_signal_types["flood_depth"]`.
- [x] Add a low-weight status-only event type with explicit UI/diagnostic wording.
- [x] Run API nearby coverage tests and Yunlin adapter tests.

Completed 2026-06-30: `status_only` now remains a low-weight diagnostics-only
event type. It can populate nearby coverage as a status clue, but it does not
satisfy rainfall, water level, flood depth, or sewer water-level measurement
coverage and has no realtime risk factor.

## Task 6: Hosted Worker Persistence Gate

**Files:**
- Modify: `scripts/runtime-smoke.ps1`
- Modify: `docs/runbooks/runtime-smoke.md`
- Modify: `docs/runbooks/worker-scheduler-deployment.md`

**Interfaces:**
- Consumes: enabled adapter list from Zeabur-compatible env vars.
- Produces: smoke evidence that hosted-like mode uses worker-persisted rows and does not call the API realtime bridge.

- [x] Add runtime smoke assertions for `official_realtime_latest` row freshness by adapter.
- [x] Add a hosted-mode guard assertion that `REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED` is not used during normal smoke.
- [x] Document required evidence before claiming production readiness.

Completed 2026-06-30: runtime smoke now rejects enabled diagnostic fallback
during normal runs, explicitly sets
`REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED=false`, verifies the managed WRA
fixture wrote fresh worker-persisted rows into `official_realtime_latest`, and
documents that hosted readiness requires worker/scheduler persistence evidence
rather than the API realtime bridge.

## Task 7: Signal Gap Request Packets

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `docs/data-sources/local/generated-official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.json`
- Modify: `docs/data-sources/local/official-request-packets.md`
- Test: `apps/api/tests/test_local_source_request_packets.py`
- Test: `tests/test_local_source_request_packets_cli.py`

**Interfaces:**
- Consumes: `sensor_signal_gap_reviews`, `live_smoke_reviews`, and
  `integration_priority_queue`.
- Produces: priority-ordered official request packets for authorization,
  metadata release, live-smoke/status-only review, public API contracts, and
  missing signal-family follow-up.

- [x] Add failing tests requiring generated request packets to follow
  `integration_priority_queue` order.
- [x] Add live-smoke review packets for臺北市與雲林縣 so status-only or gate
  state cannot be treated as water measurements.
- [x] Add signal-gap request packets for ready counties whose adapters do not
  cover every required water signal family.
- [x] Regenerate Markdown/JSON request packet artifacts.

Completed 2026-06-30: generated request packets now include 18 priority-ordered
items. The output starts with 連江縣、金門縣、花蓮縣、臺東縣 and
continues through public API contract and signal-gap follow-up packets. Signal
gap packets explicitly require official read APIs or documented unavailability
for missing families such as `flood_depth`, `sewer_water_level`, and
`pump_or_gate_status`, while warning that `status-only` data must not be
misrepresented as a measurement.

## Task 8: Yunlin Status-Only Queue Reclassification

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: generated request packet artifacts.
- Test: action-plan, admin-contract, and request-packet tests.

**Interfaces:**
- Consumes: Yunlin local source coverage status-only metadata and
  `sensor_signal_gap_reviews`.
- Produces: action-plan and request-packet output that treats Yunlin
  `alarmState` as an accepted status-only diagnostic clue, while keeping
  `flood_depth` as an unresolved signal gap.

- [x] Write failing tests proving Yunlin leaves `live_smoke_reviews`.
- [x] Add status-only source metadata to integration priority and signal-gap
  items.
- [x] Regenerate request packets so Yunlin becomes a `signal_gap_request` with
  status-only source names, URLs, and signal type.
- [x] Update OpenAPI/admin contract to expose the new status-only metadata on
  priority items.

Completed 2026-06-30: 雲林縣 now leaves the P1 live-smoke queue and appears as
a P2 `signal_gap_request` for missing `flood_depth`. The packet keeps
`雲林 iflood 淹水感測狀態` as a status-only source and explicitly preserves the
rule that `alarmState` cannot satisfy flood-depth measurement coverage.

## Task 9: Official Backbone Fixture Persistence Expansion

**Files:**
- Modify: `apps/workers/app/jobs/official_demo.py`
- Modify: `apps/workers/tests/test_worker_entrypoints.py`
- Modify: `scripts/runtime-smoke.ps1`
- Modify: `docs/runbooks/runtime-smoke.md`
- Modify: `docs/runbooks/worker-scheduler-deployment.md`

**Interfaces:**
- Consumes: fixture-backed CWA, WRA, Civil IoT, and L2 public-web sample adapter rows.
- Produces: hosted-like smoke evidence that official central backbone adapters write raw snapshots, staging rows, adapter runs, promoted evidence, and `official_realtime_latest` rows by adapter.

- [x] Add failing tests proving fixture mode includes CWA, WRA, and Civil IoT official backbone adapters.
- [x] Expand the managed runtime persist smoke to verify latest-row freshness and metric columns for CWA rainfall, WRA water level, Civil IoT flood depth, and Civil IoT water-level families.
- [x] Document that this smoke validates fixture-backed worker persistence, not real upstream credentials, source egress, or every county's local direct integration.

## Task 10: Taipei Evacuation Gate Status-Only Reclassification

**Files:**
- Modify: `apps/workers/app/ops/local_source_candidate_smoke.py`
- Modify: `apps/workers/tests/test_local_source_candidate_smoke.py`
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: action-plan, request-packet, CLI, admin contract tests.
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: Taipei evacuation/water-gate candidate fields `stationNo`, `recTime`, `lng`, `lat`, and `fo`/`fc`/`flt`.
- Produces: status-only source metadata for `臺北市水門啟閉狀態`, while keeping `flood_depth` unresolved and tracked through signal-gap request packets.

- [x] Write failing tests proving Taipei evacuation gates are not `promotion_ready` measurements.
- [x] Reclassify gate open/close fields as `status_only_ready` and remove Taipei from `live_smoke_reviews`.
- [x] Regenerate request packets so Taipei becomes a `signal_gap_request` with `gate_status` status-only metadata.
- [x] Update matrix and verification log to explain that gate status cannot satisfy water level, rainfall, or flood-depth coverage.

## Task 11: Lienchiang Non-Qualifying Official Leads

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `docs/api/openapi.yaml`
- Modify: request-packet, action-plan, admin contract, and CLI tests.
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: 連江自來水廠水庫水位月報 and `erbwater` public realtime monitoring page.
- Produces: `non_qualifying_source_*` metadata in local source coverage,
  action-plan, admin, and request-packet outputs, without reducing the
  local-direct signal gaps.

- [x] Write failing tests proving Lienchiang excluded official leads are exposed.
- [x] Record water-reservoir monthly PDFs and environmental CEMS as
  non-qualifying sources.
- [x] Regenerate official request packets so the P0 request includes exclusion
  reasons.
- [x] Update matrix and verification log to preserve that Lienchiang still needs
  local-direct realtime water feeds; CWA tide-level integration now satisfies
  the minimum central `hydrologic_observation` gate separately.

## Task 12: CWA Tide-Level Backbone for Lienchiang

**Files:**
- Add: `apps/workers/app/adapters/cwa/tide.py`
- Add: `apps/workers/tests/test_cwa_tide_level_adapter.py`
- Add: `infra/migrations/0031_cwa_tide_level_source.sql`
- Modify: worker registry/runtime/demo/staging/freshness tests and API coverage/action-plan contracts.
- Modify: official/local data-source docs, OpenAPI examples, Zeabur and scheduler runbooks.

**Interfaces:**
- Consumes: CWA `O-B0075-001` tide-level observations and CWA `O-B0076-001`
  sea-surface station metadata.
- Produces: `official.cwa.tide_level` water-level evidence with station
  metadata, source URLs, coastal-context limitations, and CWA source gates.

- [x] Write failing adapter tests for joining tide observations with station metadata.
- [x] Implement CWA tide-level live adapter, runtime builder, registry metadata, official demo fixture, staging passthrough, and source migration.
- [x] Classify `official.cwa.tide_level` as `tide_level` / `water_level` for central and nearby coverage while preserving coastal-only limitations.
- [x] Update local coverage/action-plan contracts so 22/22 counties meet the minimum central backbone, while 連江縣 remains P0 for local-direct `flood_depth`, `sewer_water_level`, and `pump_or_gate_status`.
- [x] Regenerate request packet artifacts and update OpenAPI/docs/runbooks.

Completed 2026-06-30: 連江縣 no longer appears in
`counties_missing_hydrologic_backbone`; `central_backbone_minimum_complete_count`
is 22. This is not full nationwide completion: 金門縣 and 連江縣 still lack
complete local-direct production sources, and multiple ready counties still
have documented signal-family gaps.

## Task 13: Pingtung PTEOC Contract-Blocker Evidence

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `docs/api/openapi.yaml`
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: PTEOC `/RainStation/Details/*`, `/Flood/Details/*`, and
  `/Crawler/Details/*` public HTML.
- Produces: structured `candidate_contract_*` fields in coverage/action-plan/admin
  outputs and official request packets, while keeping PTEOC out of production
  ingestion until an official read API or station metadata join is available.

- [x] Write failing tests proving PTEOC candidate pages expose missing fields and
  non-measurement pages as structured contract blockers.
- [x] Record RainStation missing `observed_at` and joinable WGS84 metadata.
- [x] Mark Flood detail pages as warning-threshold/status pages, not flood-depth
  measurements.
- [x] Mark Crawler detail pages as CCTV image pages, not water-level measurements.
- [x] Regenerate request packet artifacts and update OpenAPI/docs.

Completed 2026-06-30: 屏東縣 still has `local.pingtung.flood_sensor` for FHY
government-supplier flood sensors. PTEOC remains a public API contract blocker;
it must not be promoted by scraping HTML or by using `fetched_at` as
`observed_at`.

## Completion Gates

The full objective is complete only when:

- All 22 counties have either local direct adapters or official request packets with tracked status.
- Central backbone minimum coverage has no missing county.
- Required signal families are either present, status-only with explicit labeling, or documented as unavailable with official follow-up.
- Worker scheduler writes raw snapshots, staging rows, adapter runs, and promoted evidence in hosted-like mode.
- `/admin/v1/sources`, `/admin/v1/local-source-coverage`, and `/admin/v1/local-source-action-plan` expose freshness, missing signal, and queue state.
- Public risk responses use worker-persisted evidence and query-point nearby coverage.
- CI, OpenAPI validation, focused API/worker tests, and runtime smoke pass.
