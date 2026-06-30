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

## Task 14: Tainan Static Water Metadata And Non-Measurement Leads

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: Tainan SOA datasets for regional-drainage water-station metadata,
  114 pump-station basic data, 114 water-gate basic data, regional-drainage
  CCTV image index, and the WRA/Tainan joint flood-sensor endpoint.
- Produces: structured metadata and non-qualifying source evidence on the
  Tainan signal-gap queue item, without reducing the unresolved
  `sewer_water_level` or `pump_or_gate_status` gaps.

- [x] Write failing tests proving Tainan signal-gap items expose static metadata
  source names/URLs and non-measurement leads.
- [x] Record water-station, pump-station, and water-gate datasets as static
  metadata only.
- [x] Mark regional-drainage realtime images as image-only CCTV, not
  sewer-water-level or pump/gate-status measurements.
- [x] Mark the WRA/Tainan joint flood-sensor endpoint as unavailable for
  production ingestion after the live smoke returned `data:null`.
- [x] Regenerate request packet artifacts and update OpenAPI/docs.

Completed 2026-06-30: 臺南市 still has `local.tainan.flood_sensor`, but the
remaining signal-gap request now carries official static metadata leads and
explicit non-qualifying evidence. The Tainan gap remains `sewer_water_level`
and `pump_or_gate_status`; CCTV image URLs and static facility metadata must
not be treated as realtime measurements.

## Task 15: Miaoli Sewer Monitoring Contract-Blocker Evidence

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/tests/test_local_source_action_plan.py`
- Modify: `apps/api/tests/test_local_source_request_packets.py`
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: Miaoli official results-review page for the 114年度雨水下水道即時水情監測系統建置計畫.
- Produces: structured `candidate_contract_*` fields for Miaoli public API contract review and request packets, without promoting HTML/JPG evidence into production ingestion.

- [x] Write failing tests proving Miaoli contract blockers expose missing read API fields.
- [x] Record that the official page confirms 58 water-level monitoring stations across 10 town/city urban-planning areas.
- [x] Record monthly maintenance/monthly-report evidence while preserving that no latest-observation read API or station metadata file is exposed.
- [x] Mark the public HTML article/JPGs as non-measurement evidence that cannot satisfy `sewer_water_level` or `pump_or_gate_status`.
- [x] Regenerate request packet artifacts and update local source docs.

Completed 2026-06-30: 苗栗縣 still has `local.miaoli.flood_sensor` for FHY
government-supplier flood sensors. The official sewer-monitoring results page
now strengthens the request packet with concrete station-count and maintenance
facts, but it remains a public API contract blocker until Miaoli publishes a
machine-readable read API with observed time, station/device id, value, unit,
and joinable WGS84 station metadata.

## Task 16: Taitung Warning-System Contract-Blocker Evidence

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/tests/test_local_source_action_plan.py`
- Modify: `apps/api/tests/test_local_source_request_packets.py`
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: Taitung County Government flood-control news page and Audit Office
  page for Taitung County Government water-warning system setup.
- Produces: structured `candidate_contract_*` fields for the Taitung public
  API contract review and request packets, without promoting news/audit summary
  evidence into production ingestion.

- [x] Write failing tests proving Taitung contract blockers expose missing read
  API fields.
- [x] Record that the county news page confirms water-monitoring system context:
  flood sensors, water-level stations, rain gauges, and realtime cameras.
- [x] Record that the Audit Office page confirms integration of 49 CWA rainfall
  stations and 9 WRA water-level stations.
- [x] Mark the news/audit summary and realtime camera references as
  non-measurement evidence that cannot satisfy a local-government
  latest-observation read API.
- [x] Regenerate request packet artifacts and update local source docs.

Completed 2026-06-30: 臺東縣 still has `local.taitung.flood_sensor` for FHY
government-supplier flood sensors. The Taitung warning-system evidence proves
system context and central CWA/WRA station integration, but it remains a public
API contract blocker until Taitung publishes a machine-readable local-government
read API with observed time, station/device id, value, unit, and joinable WGS84
station metadata.

## Task 17: P0 Local Open-Data Release Monitor Summary

**Files:**
- Modify: `apps/workers/app/ops/local_source_discovery_monitor.py`
- Modify: `apps/workers/tests/test_local_source_discovery_monitor.py`
- Modify: `apps/workers/tests/test_realtime_source_gate.py`
- Modify: release-monitor docs and monitoring runbook.

**Interfaces:**
- Consumes: data.gov.tw dataset export candidates for unresolved local-source
  counties such as 金門縣 and 連江縣.
- Produces: machine-readable `summary.by_county` release-monitor state for each
  target county: `live_candidate_found`, `metadata_only`, or `no_candidate`.

- [x] Write failing tests proving the discovery monitor summarizes per-county
  release-monitor state.
- [x] Surface `candidate_live_read_api_count_by_county`,
  `metadata_only_count_by_county`, and `target_counties_without_candidates`.
- [x] Propagate the summary through the realtime source gate JSON.
- [x] Document how operators should use the summary for `monitor_open_data_release`.

Completed 2026-06-30: 連江縣 still has no verified local direct realtime API.
This task makes the P0 open-data-release monitor machine-readable so scheduled
checks or alerts can distinguish "new live candidate appeared" from "only
metadata remains visible" and "no candidate in the export".

## Task 18: Production Ops Gates In Official Request Packets

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/tests/test_local_source_request_packets.py`
- Modify: `tests/test_local_source_request_packets_cli.py`
- Modify: generated request packet artifacts and local source docs.

**Interfaces:**
- Consumes: local-source action plan request packets for authorization,
  metadata release, public API contract, live-smoke review, and signal-gap
  follow-up.
- Produces: `production_operational_requirements` on every request packet:
  `freshness_policy`, `raw_snapshot_retention_policy`,
  `monitored_scheduler_cadence`, `hosted_egress_review`, and
  `worker_persisted_evidence_path`.

- [x] Write failing tests proving request packets expose production operational
  gates in JSON and Markdown outputs.
- [x] Add raw snapshot retention, scheduler cadence, hosted egress review, and
  worker-persisted evidence path to request bodies/checklists.
- [x] Regenerate official request packet artifacts.
- [x] Document the operational gates in the manual request-packet guide.

Completed 2026-06-30: Official requests now ask for more than API columns.
They explicitly collect the production-readiness evidence needed before any
local source can become hosted worker ingestion. This does not mean credentials
or hosted egress approvals have been granted; it makes those gates visible and
trackable in the source-contract workflow.

## Task 19: Realtime Source Gate Production-Readiness Summary

**Files:**
- Modify: `apps/workers/app/ops/realtime_source_gate.py`
- Modify: `apps/workers/tests/test_realtime_source_gate.py`
- Modify: `scripts/realtime-source-gate.py`
- Add: `tests/test_realtime_source_gate_cli.py`
- Modify: `docs/runbooks/civil-iot-live-enablement.md`

**Interfaces:**
- Consumes: official live-smoke result, unresolved local-source discovery, and
  optional production-gate evidence booleans.
- Produces: `production_readiness` JSON with required, satisfied, and missing
  gates for hosted/production source readiness.

- [x] Write failing tests proving the source gate exposes production-readiness
  state and can fail when required evidence is missing.
- [x] Track credential review, source license review, raw snapshot retention
  policy, hosted scheduler cadence, hosted egress review, alert routing
  ownership, and worker-persisted evidence smoke.
- [x] Add CLI evidence JSON input and fail-closed mode for hosted readiness
  rehearsals.
- [x] Document that green live smoke is not production completeness.

Completed 2026-06-30: `realtime-source-gate` now reports production-readiness
gaps separately from live upstream health. It can identify whether a hosted
readiness run is still missing credential, license, retention, cadence, egress,
alert, or worker-persisted-evidence proof. This still does not create those
private approvals; it makes them machine-visible.

## Task 20: WRA/NCDR TLS Compatibility For Hosted Egress Smoke

**Files:**
- Add: `apps/workers/app/adapters/_taiwan_gov_tls.py`
- Add: `apps/workers/tests/test_taiwan_gov_tls.py`
- Modify: `apps/workers/app/adapters/wra/water_level.py`
- Modify: `apps/workers/app/adapters/wra_iow/flood_depth.py`
- Modify: `apps/workers/app/adapters/ncdr/cap_alerts.py`
- Modify: related worker adapter tests.
- Modify: `docs/runbooks/civil-iot-live-enablement.md`

**Interfaces:**
- Consumes: Python/OpenSSL verified HTTPS requests to WRA open-data and NCDR CAP
  endpoints.
- Produces: official-source live fetches that tolerate missing Subject Key
  Identifier in the government certificate chain while retaining CA and hostname
  verification.

- [x] Reproduce the local live-smoke failure and confirm it is tied to
  `VERIFY_X509_STRICT`, not disabled credentials.
- [x] Write failing tests requiring WRA, WRA IoW, and NCDR fetchers to pass a
  verified non-strict Taiwan government open-data TLS context.
- [x] Implement the shared TLS context helper and wire only the affected
  official fetchers.
- [x] Document the hosted egress interpretation so operators do not disable TLS
  verification.

Completed 2026-06-30: WRA water-level, WRA IoW flood-depth, and NCDR CAP fetchers
now use a shared TLS context that clears only `VERIFY_X509_STRICT`; certificate
chain and hostname verification remain enabled. This removes a local/hosted
egress false negative for government open-data endpoints whose certificate chain
omits SKI. It does not satisfy source-license review, credential review, raw
snapshot policy, scheduler cadence, alert routing, or worker-persisted evidence
smoke by itself.

## Task 21: Kinmen KWIS Token-Gated Pump Status Adapter

**Files:**
- Add: `apps/workers/app/adapters/local_kinmen/`
- Add: `apps/workers/tests/test_local_kinmen_kwis_adapter.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `.env.example`, `docker-compose.yml`
- Modify: `docs/runbooks/civil-iot-live-enablement.md`

**Interfaces:**
- Consumes: Kinmen KWIS ASMX `KWIS_Get_Pump_Basic_Unit_Data`, which is a
  token-gated read method. Official blank-token smoke on 2026-06-30 returned
  HTTP 200 with `ErrMsg: (7) invalid Token` and `Data: []`.
- Produces: a disabled-by-default runtime adapter key
  `local.kinmen.kwis_pump_station` that only wires when
  `SOURCE_KINMEN_KWIS_PUMP_STATION_ENABLED=true`,
  `SOURCE_KINMEN_KWIS_PUMP_STATION_API_ENABLED=true`, the adapter key is
  selected, and `KINMEN_KWIS_API_TOKEN` is configured.

- [x] Write failing tests proving KWIS string envelopes parse into explicit
  status-only pump records.
- [x] Reject invalid/blank token responses as authorization errors.
- [x] Keep runtime wiring fail-closed when the token is missing, without making
  blank-token upstream calls.
- [x] Reuse the Taiwan government TLS compatibility context while retaining CA
  and hostname verification.
- [x] Document that this is adapter readiness, not Kinmen production completion.

Completed 2026-06-30: Kinmen now has a token-gated KWIS pump/status adapter
ready for formal read-side authorization. This does not mark Kinmen local direct
coverage complete. Production completion still requires the county-issued Token,
response schema confirmation, license/rate-limit review, raw snapshot retention,
hosted scheduler cadence, hosted egress review, alert routing, and a
worker-persisted evidence smoke with real authorized rows.

## Task 22: Authorization-Gated Adapter Readiness In Action Plan

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: local coverage records with adapters that are implemented or
  implementable but blocked on formal read-side authorization.
- Produces: `authorization_gated_adapter_keys` on authorization requests and
  integration-priority items, without counting those adapters as production
  coverage.

- [x] Write failing tests proving Kinmen exposes
  `local.kinmen.kwis_pump_station` as authorization-gated readiness.
- [x] Keep `production_adapter_keys` empty for Kinmen so completion counts and
  signal coverage are not inflated.
- [x] Add schema and OpenAPI fields so the admin contract can distinguish
  production adapters from adapters waiting on official credentials.
- [x] Verify action-plan/admin contract, OpenAPI validation, API lint, and the
  Kinmen worker adapter regression test.

Completed 2026-06-30: `/admin/v1/local-source-action-plan` now separates
production adapters from authorization-gated adapter readiness. Kinmen remains
`needs_authorization_request`, but operators and UI can show that a KWIS pump
status adapter is ready to activate after official Token approval and hosted
worker-persisted evidence smoke.

## Task 23: Lienchiang Open-Data Release Monitor Contract

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: the P0 `monitor_open_data_release` action-plan item for Lienchiang
  and the existing worker-side `scripts/local-source-discovery-monitor.py`.
- Produces: `open_data_release_monitor` on metadata-release and
  integration-priority items so scheduled operators know which catalog to scan,
  what current state is expected, and what state should trigger adapter TDD.

- [x] Write failing tests requiring Lienchiang to expose a data.gov.tw release
  monitor command and escalation rule.
- [x] Keep Lienchiang incomplete: expected state is `metadata_only`, and the
  escalation state is `live_candidate_found`.
- [x] Update Pydantic and OpenAPI contracts so `/admin/v1/local-source-action-plan`
  can drive release-monitor scheduling without scraping prose.
- [x] Verify action-plan/admin contract tests, OpenAPI validation, and API lint.

Completed 2026-06-30: the P0 Lienchiang item now includes a machine-readable
release-monitor contract:
`PYTHONPATH=apps/workers python scripts/local-source-discovery-monitor.py --county 連江縣 --fail-on-candidate`.
Finding a `candidate_live_read_api` remains an escalation into source review
and adapter TDD, not automatic production completion.

## Task 24: Signal-Family Gap Priority Groups

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: the ranked `integration_priority_queue` and every county's
  `missing_signal_types`.
- Produces: `signal_gap_priority_groups`, grouped by required water signal
  family so source discovery, official requests, and future adapter work can be
  batched across counties.

- [x] Write failing tests proving `pump_or_gate_status` is the top grouped gap.
- [x] Count grouped counties and tracking states without changing county
  completion counts.
- [x] Add API and OpenAPI schema so operators can see that pump/gate status is
  the largest remaining signal-family gap.
- [x] Verify action-plan/admin contract tests, OpenAPI validation, and API lint.

Completed 2026-06-30: action plan now reports
`signal_gap_priority_groups`. The current largest batch is
`pump_or_gate_status` across 14 counties/items, with P0 blockers preserved for
Lienchiang and Kinmen and P2 signal-gap reviews preserved for ready counties.
This is prioritization infrastructure; each listed county still needs a
production adapter, authorization-gated adapter, or official unavailable-source
record before the nationwide objective can be called complete.

## Task 25: Pump/Gate Signal Discovery Filter And Batch Command

**Files:**
- Modify: `apps/workers/app/ops/local_source_discovery_monitor.py`
- Modify: `scripts/local-source-discovery-monitor.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/workers/tests/test_local_source_discovery_monitor.py`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: the data.gov.tw dataset export and
  `signal_gap_priority_groups[].signal_type`.
- Produces: signal-targeted discovery results and a machine-readable
  `discovery_monitor` command for each grouped signal gap.

- [x] Write failing worker tests proving discovery can filter candidates by
  required `pump_or_gate_status` signal type.
- [x] Add `--signal-type` to the local-source discovery CLI so operators can
  run grouped gap scans without manually reviewing unrelated rainfall, water
  level, or flood-depth datasets.
- [x] Attach a `discovery_monitor` command to signal-gap priority groups in
  `/admin/v1/local-source-action-plan`.
- [x] Update Pydantic and OpenAPI contracts for the new monitor object.
- [x] Run a live data.gov.tw smoke against the current top pump/gate batch.

Completed 2026-06-30: discovery can now scan the current top
`pump_or_gate_status` gap directly:
`PYTHONPATH=apps/workers python scripts/local-source-discovery-monitor.py --signal-type pump_or_gate_status --fail-on-candidate ...`.
The first live smoke found 11 pump/gate candidates across the 14-county batch
and temporarily flagged one New Taipei item as `candidate_live_read_api`.
Task 26 corrected that interpretation after source review showed the item is an
annual pump-station inventory, not a latest-observation read API.

## Task 26: Pump/Gate Discovery Precision And False-Live Reclassification

**Files:**
- Modify: `apps/workers/app/ops/local_source_discovery_monitor.py`
- Test: `apps/workers/tests/test_local_source_discovery_monitor.py`
- Modify: `docs/superpowers/plans/2026-06-30-nationwide-sensor-integration.md`

**Interfaces:**
- Consumes: data.gov.tw export metadata fields such as `資料下載網址`,
  `主要欄位說明`, `更新頻率`, and `資料提供屬性`.
- Produces: cleaner pump/gate discovery output that separates annual static
  inventories from real latest-observation read API candidates and avoids
  same-name city/county cross-matches.

- [x] Write failing tests proving New Taipei dataset `125249` is metadata-only:
  it updates yearly and exposes station name, completion year, address, river,
  and pump type, not observed time or pump/gate status rows.
- [x] Parse the official data.gov.tw export field aliases so discovery output
  preserves download URLs, update frequency, and field descriptions.
- [x] Exclude non-sensor infrastructure/statistics lists such as drought wells,
  visit/contact lists, and sewer facility-count datasets from pump/gate
  discovery.
- [x] Prevent `嘉義市` from matching `嘉義縣` sources and `新竹縣` from matching
  `新竹市` sources through the short-name fallback.
- [x] Re-run the live pump/gate data.gov.tw smoke.

Completed 2026-06-30: the corrected live smoke returns 9 pump/gate metadata-only
candidates across Taoyuan, Taichung, and New Taipei, with zero
`candidate_live_read_api` matches in the current 14-county batch. This means no
new pump/gate adapter should be started from that discovery result yet; the next
production movement is official read-API request follow-up, authorization, or a
new live candidate appearing in the release monitor.

## Task 27: Signal Gap Official Request Batch Contract

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: `signal_gap_priority_groups` derived from the nationwide local
  source coverage catalog.
- Produces: `signal_gap_priority_groups[].official_request_batch`, including
  target signal type, grouped counties, requested counterparties, required read
  API fields, production operational requirements, and the request-packet
  generator command.

- [x] Write failing domain and admin-contract tests proving each grouped signal
  gap exposes a formal official request batch.
- [x] Attach required realtime read fields and production operational gates to
  the grouped batch so missing sensor families cannot be presented as complete
  integration.
- [x] Update Pydantic and OpenAPI contracts for the new batch object.

Completed 2026-06-30: the action plan now makes the next step explicit for the
largest current gap, `pump_or_gate_status` across 14 counties. Because Task 26
found zero live read API candidates, this batch is not an adapter
implementation; it is the official read-API request and completion-gate contract
needed before the nationwide sensor objective can be closed.

## Task 28: Signal-Scoped Official Request Packet Generation

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `scripts/local-source-request-packets.py`
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: generated request packet artifacts and OpenAPI example.
- Test: `apps/api/tests/test_local_source_request_packets.py`
- Test: `tests/test_local_source_request_packets_cli.py`
- Test: action-plan/admin contract tests.

**Interfaces:**
- Consumes: `signal_gap_priority_groups[].official_request_batch` and the
  existing official request packet builder.
- Produces: signal-scoped official request packets through
  `scripts/local-source-request-packets.py --signal-type <signal>`, so the top
  pump/gate batch can be generated directly from the admin action plan command.

- [x] Write failing domain and CLI tests proving `pump_or_gate_status` filters
  to the 14-county signal-gap batch.
- [x] Carry `target_signal_types` onto authorization and contract packets via
  their priority items so non-`signal_gap_request` blockers remain in the
  signal-scoped batch.
- [x] Add `--signal-type` to the packet CLI and action-plan batch command.
- [x] Regenerate request packet artifacts so official follow-up documents show
  target signal families consistently.

Completed 2026-06-30: operators can now run the command exposed by
`/admin/v1/local-source-action-plan` to generate only the official request
packets relevant to the current `pump_or_gate_status` batch. This still does
not complete the sensors; it removes a manual filtering step before official
read-API outreach and keeps authorization, metadata-release, and public
contract blockers in the same signal-scoped batch.

## Task 29: Completion Gate Audit In Action Plan

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`

**Interfaces:**
- Consumes: local-source action plan counts, signal-gap priority groups,
  authorization requests, metadata-release monitors, public API contract
  reviews, and live-smoke reviews.
- Produces: `plan["completion_audit"]`, a machine-readable audit of which
  nationwide completion gates are satisfied and which remain incomplete.

- [x] Write failing domain and admin-contract tests proving the action plan
  reports incomplete completion gates.
- [x] Add gate summaries for local direct/tracked-request coverage, central
  backbone coverage, required signal families, official authorization and
  contracts, hosted worker-persisted evidence, production monitoring, and the
  hosted public-risk evidence path.
- [x] Update Pydantic and OpenAPI contracts so the admin endpoint can be used as
  the canonical unfinished-work checklist.

Completed 2026-06-30: `/admin/v1/local-source-action-plan` now returns
`completion_audit.overall_status=incomplete` with exact blockers. The current
audit records central backbone coverage as satisfied, but keeps required signal
families, official authorization/contracts, hosted worker-persisted evidence,
monitoring/alerting, and hosted risk-response evidence as incomplete. This is a
completion gate, not completion of the nationwide sensor objective.

## Task 30: Completion Evidence Overlay

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Add: `scripts/local-source-completion-audit.py`
- Add: `docs/data-sources/local/local-source-completion-evidence.example.json`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`
- Test: `tests/test_local_source_completion_audit_cli.py`

**Interfaces:**
- Consumes: optional `local-source-completion-evidence/v1` JSON containing
  signal-family evidence, source-contract evidence, and hosted production-gate
  evidence. Private `evidence_ref` values remain in ops-controlled storage and
  are never echoed by the public/admin audit.
- Produces: an updated `completion_audit` where gates can become `satisfied`
  only when accepted evidence covers the current blockers.

- [x] Write failing tests proving a complete evidence overlay can satisfy
  required signal-family, official authorization/contract, hosted persistence,
  monitoring, and public-risk evidence gates.
- [x] Add a CLI so operators can run:
  `python scripts/local-source-completion-audit.py --completion-evidence-json <private.json> --fail-on-incomplete`.
- [x] Add an example evidence manifest and OpenAPI schema for the aggregate
  `evidence_overlay` summary.

Completed 2026-06-30: completion gates now have a concrete evidence ingestion
path. This does not create official approvals or hosted Zeabur evidence by
itself; it lets those future private artifacts drive the same audit without
rewriting code or manually editing completion status.

## Task 31: Requirement-Level Production Gate Evidence

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `scripts/local-source-completion-audit.py`
- Modify: `docs/data-sources/local/local-source-completion-evidence.example.json`
- Test: `apps/api/tests/test_local_source_action_plan.py`
- Test: `apps/api/tests/test_admin_contract.py`
- Test: `tests/test_local_source_completion_audit_cli.py`

**Interfaces:**
- Consumes: `production_gate_evidence[].satisfied_requirements` in the private
  `local-source-completion-evidence/v1` JSON.
- Produces: completion-audit production gates that can only pass when every
  required production requirement for that gate is backed by accepted evidence.

- [x] Write a failing test proving a coarse production gate evidence item does
  not satisfy hosted/production completion.
- [x] Require `hosted_worker_persisted_evidence` to cover freshness policy, raw
  snapshot retention, monitored scheduler cadence, hosted egress review, and
  worker-persisted evidence path individually.
- [x] Require `production_monitoring_and_alerting` to cover hosted alert
  routing, scheduled freshness checks, and worker/scheduler alert ownership.
- [x] Require `public_risk_worker_evidence_path` to cover hosted public-risk
  worker-evidence smoke and query-point nearby coverage smoke.
- [x] Expose only aggregate requirement evidence counts and remaining blocking
  items; never echo private `evidence_ref` values.

Completed 2026-06-30: production completion evidence is now requirement-level.
Partial hosted evidence reduces the relevant blocking list but cannot mark a
production gate satisfied until all required requirements for that gate are
accepted. This still does not create Zeabur production evidence; it prevents a
single coarse evidence record from masking unfinished hosted requirements.

## Task 32: Sewer Discovery False-Live Reclassification

**Files:**
- Modify: `apps/workers/app/ops/local_source_discovery_monitor.py`
- Modify: `apps/workers/tests/test_local_source_discovery_monitor.py`
- Modify: `docs/data-sources/local/2026-06-28-local-source-verification-log.md`

**Interfaces:**
- Consumes: live `data.gov.tw` discovery output for the current
  `sewer_water_level` gap group.
- Produces: discovery output that keeps data-catalog/GIS download listings as
  `metadata_only` instead of `candidate_live_read_api`.

- [x] Run current signal-gap discovery for `pump_or_gate_status`,
  `flood_depth`, and `sewer_water_level`.
- [x] Reproduce the false-live classification for Taichung datasets `120801`
  and `120833`, whose fields describe data catalog downloads rather than
  latest observations.
- [x] Add a failing test proving Taichung rainwater-sewer GIS catalog rows are
  not live sewer-water-level read APIs.
- [x] Reclassify catalog download listings with fields such as `資料集名稱`,
  `資料格式`, `下載網址`, `上架日期`, and `資料資源欄位` as static metadata.
- [x] Re-run the live sewer discovery smoke with `--fail-on-candidate` and
  confirm no `candidate_live_read_api` remains for the current sewer batch.

Completed 2026-06-30: no new public read API adapter should be started from the
current sewer-water-level discovery batch. Taichung, Taoyuan, Chiayi City, and
Tainan results remain metadata/GIS candidates; Lienchiang still has no
candidate. The next movement for `sewer_water_level` remains official read-API
request follow-up or a future release-monitor hit.

## Completion Gates

The full objective is complete only when:

- All 22 counties have either local direct adapters or official request packets with tracked status.
- Central backbone minimum coverage has no missing county.
- Required signal families are either present, status-only with explicit labeling, or documented as unavailable with official follow-up.
- Worker scheduler writes raw snapshots, staging rows, adapter runs, and promoted evidence in hosted-like mode.
- `/admin/v1/sources`, `/admin/v1/local-source-coverage`, and `/admin/v1/local-source-action-plan` expose freshness, missing signal, and queue state.
- Public risk responses use worker-persisted evidence and query-point nearby coverage.
- CI, OpenAPI validation, focused API/worker tests, and runtime smoke pass.
