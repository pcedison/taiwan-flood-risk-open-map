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
- Consumes: `production_gate_evidence[].satisfied_requirements` and matching
  `production_gate_evidence[].requirement_evidence[]` entries in the private
  `local-source-completion-evidence/v1` JSON.
- Produces: completion-audit production gates that can only pass when every
  required production requirement for that gate is backed by requirement-level
  accepted evidence.

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

## Task 33: Completion Evidence Targets In Request Packets

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/tests/test_local_source_request_packets.py`
- Modify: `tests/test_local_source_request_packets_cli.py`
- Modify: `docs/data-sources/local/generated-official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.json`

**Interfaces:**
- Consumes: action-plan authorization requests, metadata-release monitors,
  public API contract reviews, and signal-gap requests.
- Produces: `completion_evidence_targets` on every official request packet so
  an accepted official reply can be translated into the private
  `local-source-completion-evidence/v1` manifest without guessing.

- [x] Write a failing test requiring authorization, metadata-release, public
  contract, and signal-gap packets to expose their target completion evidence
  section, gate or signal type, accepted statuses, and private evidence-ref
  hint.
- [x] Add source-contract evidence targets for `authorization_request`,
  `metadata_release_monitor`, and `public_api_contract_review` packets.
- [x] Add signal-family evidence targets for every missing signal type carried
  by a `signal_gap_request`.
- [x] Render completion evidence targets into Markdown outreach packets and
  regenerate JSON/Markdown artifacts.

Completed 2026-06-30: official outreach artifacts now include the exact
completion-evidence target needed after a formal reply lands. This does not
create official approvals; it removes ambiguity between sending a request and
recording accepted evidence for the completion audit.

## Task 34: Request Packet Completion Evidence Draft

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `scripts/local-source-request-packets.py`
- Modify: `apps/api/tests/test_local_source_request_packets.py`
- Modify: `tests/test_local_source_request_packets_cli.py`
- Modify: `docs/data-sources/local/generated-official-request-packets.md`
- Modify: `docs/data-sources/local/generated-official-request-packets.json`
- Add: `docs/data-sources/local/generated-completion-evidence-template.json`

**Interfaces:**
- Consumes: official request packets and their `completion_evidence_targets`.
- Produces: a `local-source-completion-evidence/v1` draft manifest with every
  current source-contract and signal-family blocker listed as `pending`, so
  operators can fill accepted private evidence after official replies, adapter
  smoke, or hosted evidence are actually available.

- [x] Write failing tests proving authorization/metadata/contract packets also
  expose signal-family evidence targets, not only source-contract targets.
- [x] Add `build_completion_evidence_template()` so request packets can produce
  a pending draft manifest without claiming any completion evidence.
- [x] Add `scripts/local-source-request-packets.py --format evidence-template`.
- [x] Regenerate request packet artifacts and the generated completion-evidence
  draft.

Completed 2026-06-30: official outreach now maps to both completion gates that
matter: source-contract evidence and signal-family evidence. The generated
draft is intentionally all `pending` and does not include hosted production
gate evidence; Zeabur worker persistence, monitoring, and public-risk smoke
still require real private ops evidence before the completion audit can pass.

## Task 35: Production Public Smoke Evidence Artifact

**Files:**
- Modify: `scripts/taiwan_wide_public_beta_smoke.py`
- Add: `tests/test_taiwan_wide_public_beta_smoke.py`
- Add: `docs/reviews/production-public-beta-smoke-2026-06-30-f08c6346.json`

**Interfaces:**
- Consumes: hosted public `/health`, `/v1/geocode`, and `/v1/risk/assess`.
- Produces: a repeatable JSON smoke artifact recording production
  `deployment_sha`, sample count, failures, and public risk-query sample
  coverage.

- [x] Write a failing test for `--evidence-output`.
- [x] Add JSON evidence output without changing the pass/fail semantics of the
  existing smoke command.
- [x] Run the smoke against `https://floodrisk.cc` after PR #13 was merged to
  `main` and Zeabur reported production deployment success.

Completed 2026-06-30: `main` advanced from `7e92cf6` to merge commit
`f08c6346`, Zeabur reported a successful production deployment for that SHA,
`/health` and `/ready` both returned `deployment_sha=f08c6346...`, and the
Taiwan-wide public smoke passed 44 county/town samples. This proves deployment
and public query smoke for the merge, but does not satisfy the remaining
worker-persisted source evidence, raw snapshot retention, scheduler cadence,
hosted egress, or admin freshness/alerting gates.

## Task 36: Rate-Aware Production Public Smoke

**Files:**
- Modify: `scripts/taiwan_wide_public_beta_smoke.py`
- Modify: `tests/test_taiwan_wide_public_beta_smoke.py`
- Modify: `docs/runbooks/deploy-zeabur.md`
- Modify: `docs/runbooks/open-data-geocoder-import.md`
- Modify: `docs/runbooks/public-beta-readiness-2026-05-04.md`
- Add: `docs/reviews/production-public-beta-smoke-2026-06-30-cebb3305.json`

**Interfaces:**
- Consumes: hosted public rate-limit headers from `/v1/geocode` and
  `/v1/risk/assess`.
- Produces: a production-safe public beta smoke command that respects 429
  `Retry-After`, supports sample delay, and still writes JSON evidence.

- [x] Reproduce the hosted smoke failure after PR #14 deployment:
  the fast 44-sample run returned HTTP 429 for later samples because hosted
  risk-assessment rate limiting is enabled.
- [x] Write failing tests for 429 retry and sample delay propagation.
- [x] Add `--request-delay-seconds`, `--rate-limit-retries`, and
  `--rate-limit-retry-delay-seconds` to the smoke script.
- [x] Update runbooks so production smoke examples use the rate-aware command.
- [x] Re-run the production smoke against `https://floodrisk.cc` with
  `deployment_sha=cebb3305...` and capture a 44-sample passing artifact.

Completed 2026-06-30: PR #14 merge commit `cebb3305` was deployed by Zeabur,
`/health` and `/ready` returned that SHA, and the rate-aware Taiwan-wide public
smoke passed 44 county/town samples. This resolves the smoke-tool rate-limit
false failure. It still does not satisfy source-family completion,
authorization/contract approvals, worker raw-snapshot retention, hosted
scheduler cadence, hosted egress review, or production monitoring/alerting.

## Task 37: Hosted Public-Risk Evidence Path Smoke

**Files:**
- Add: `scripts/hosted_public_risk_evidence_smoke.py`
- Add: `tests/test_hosted_public_risk_evidence_smoke.py`
- Modify: `docs/runbooks/official-realtime-source-of-truth.md`
- Add: `docs/reviews/hosted-public-risk-evidence-smoke-2026-06-30-32baafa.json`
- Add: `docs/reviews/hosted-public-risk-completion-evidence-2026-06-30-32baafa.json`

**Interfaces:**
- Consumes: hosted `/health` and `/v1/risk/assess`.
- Produces: a public-risk evidence artifact plus a partial
  `local-source-completion-evidence/v1` overlay for
  `public_risk_worker_evidence_path`.

- [x] Write failing tests for a hosted public-risk smoke artifact and partial
  completion evidence overlay.
- [x] Add a no-secret smoke that checks `data_freshness` for CWA/WRA realtime
  sources, official rainfall/water-level evidence with `observed_at` and
  `ingested_at`, and a populated `nearby_realtime_coverage` block.
- [x] Run the smoke against `https://floodrisk.cc` after `main` deployed
  `32baafa...`.
- [x] Validate the partial completion overlay with
  `scripts/local-source-completion-audit.py`.

Completed 2026-06-30: the hosted public-risk smoke passed for deployment
`32baafa...`, and the partial completion evidence overlay satisfies only the
`public_risk_worker_evidence_path` requirements:
`hosted_risk_response_worker_evidence_smoke` and
`query_point_nearby_coverage_smoke`. The overall completion audit remains
incomplete because required signal families, official authorization/contracts,
hosted worker persistence/raw snapshot/scheduler/egress evidence, and
production monitoring/alerting are still unresolved.

## Task 38: Hosted Source-Freshness Evidence Smoke

**Files:**
- Add: `scripts/hosted_source_freshness_smoke.py`
- Add: `tests/test_hosted_source_freshness_smoke.py`
- Modify: `docs/runbooks/official-realtime-source-of-truth.md`
- Modify: `docs/runbooks/monitoring-freshness-alerts.md`

**Interfaces:**
- Consumes: hosted `/health` and admin-only `/admin/v1/sources`.
- Produces: a source-freshness evidence artifact plus a partial
  `local-source-completion-evidence/v1` overlay for the
  `hosted_worker_persisted_evidence` requirements that `/admin/v1/sources` can
  actually prove.

- [x] Write failing tests for admin token usage, checked CWA/WRA source
  summaries, and the partial completion evidence overlay.
- [x] Add a token-safe hosted source freshness smoke that reads the admin token
  from an environment variable and never writes it to the artifact.
- [x] Limit completion targets to `freshness_policy` and
  `worker_persisted_evidence_path`; do not claim raw snapshot retention,
  scheduler cadence, hosted egress review, alert routing, or scheduler
  ownership.
- [ ] Run the smoke against production after a valid `ADMIN_BEARER_TOKEN` is
  available and capture an accepted artifact under `docs/reviews/`.
- [ ] Validate that production artifact with `scripts/local-source-completion-audit.py`.

Status 2026-06-30: implementation and unit tests are complete, but the actual
hosted admin smoke is pending because this local session does not have
`ADMIN_BEARER_TOKEN`. The full completion audit remains incomplete until the
production artifact and the still-missing raw snapshot, scheduler, egress, and
alerting evidence are recorded.

## Task 39: Mergeable Completion Evidence Audit

**Files:**
- Modify: `scripts/local-source-completion-audit.py`
- Modify: `tests/test_local_source_completion_audit_cli.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Add: `docs/reviews/hosted-public-risk-evidence-smoke-2026-06-30-b5f0fcf.json`
- Add: `docs/reviews/hosted-public-risk-completion-evidence-2026-06-30-b5f0fcf.json`

**Interfaces:**
- Consumes: one or more `local-source-completion-evidence/v1` JSON overlays.
- Produces: a merged completion audit where public smoke, hosted source,
  monitoring, source-contract, and signal-family evidence can accumulate
  without hand-editing a single private manifest.

- [x] Write a failing CLI test proving repeated `--completion-evidence-json`
  arguments merge production-gate requirement evidence from separate files.
- [x] Add multi-file merge support to `scripts/local-source-completion-audit.py`
  while preserving aggregate-only audit output.
- [x] Re-run hosted public-risk evidence smoke against deployed `b5f0fcf...`
  and capture current public-risk completion evidence under `docs/reviews/`.
- [x] Validate that the merged audit marks only
  `public_risk_worker_evidence_path` satisfied from the public-risk artifact
  and keeps signal gaps, source contracts, hosted worker persistence, and
  monitoring incomplete.

Completed 2026-06-30: completion evidence can now be accumulated from multiple
artifacts. The current `b5f0fcf...` hosted public-risk artifact satisfies only
`public_risk_worker_evidence_path`; it does not reduce
`pump_or_gate_status:14`, `flood_depth:5`, `sewer_water_level:5`,
authorization/contract blockers, hosted worker raw snapshot/scheduler/egress
requirements, or monitoring/alerting requirements.

## Task 40: Signal-Gap Discovery Evidence Artifacts

**Files:**
- Modify: `scripts/local-source-discovery-monitor.py`
- Add: `tests/test_local_source_discovery_monitor_cli.py`
- Add: `docs/reviews/signal-gap-discovery-refresh-2026-06-30-pump-or-gate.json`
- Add: `docs/reviews/signal-gap-discovery-refresh-2026-06-30-flood-depth.json`
- Add: `docs/reviews/signal-gap-discovery-refresh-2026-06-30-sewer-water-level.json`
- Modify: `docs/data-sources/local/2026-06-28-local-source-verification-log.md`
- Modify: `docs/data-sources/local/official-request-packets.md`

**Interfaces:**
- Consumes: current data.gov.tw dataset export through
  `scripts/local-source-discovery-monitor.py`.
- Produces: repeatable UTF-8 `local-source-discovery-refresh/v1` evidence
  artifacts for the current required signal-family gap batches.

- [x] Write failing CLI tests requiring `--captured-at` and `--evidence-output`
  to produce a UTF-8 evidence artifact with a clear discovery conclusion.
- [x] Add `--captured-at` and `--evidence-output` to the discovery monitor CLI
  without changing classifier behavior or `--fail-on-candidate` semantics.
- [x] Re-run the `pump_or_gate_status`, `flood_depth`, and
  `sewer_water_level` batches against the current data.gov.tw export with
  `--fail-on-candidate`.
- [x] Capture reviewed discovery artifacts under `docs/reviews/`.

Completed 2026-06-30: the refreshed evidence artifacts show 0
`candidate_live_read_api` rows for all three current signal-family gap batches:
`pump_or_gate_status` has 9 metadata-only candidates, `flood_depth` has 2
metadata-only candidates, and `sewer_water_level` has 11 metadata-only
candidates. This does not satisfy the signal-family completion gate; it
prevents starting adapters from stale or false-live discovery output and keeps
the next work focused on official read-API follow-up, authorization/contracts,
or future release-monitor hits.

## Task 41: Hosted Main Deployment Evidence Gate

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Add: `scripts/hosted_deployment_smoke.py`
- Add: `tests/test_hosted_deployment_smoke.py`
- Modify: `apps/api/tests/test_local_source_action_plan.py`
- Modify: `tests/test_local_source_completion_audit_cli.py`
- Modify: `docs/data-sources/local/local-source-completion-evidence.example.json`
- Modify: `docs/runbooks/official-realtime-source-of-truth.md`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Add: `docs/reviews/hosted-deployment-smoke-2026-06-30-19eb3ce.json`
- Add: `docs/reviews/hosted-deployment-completion-evidence-2026-06-30-19eb3ce.json`

**Interfaces:**
- Consumes: hosted public `/health` and `/ready`.
- Produces: a no-secret deployment evidence artifact plus a partial
  `local-source-completion-evidence/v1` overlay for the
  `production_deployment_evidence` gate.

- [x] Write failing tests requiring completion audit to expose
  `production_deployment_evidence` with `main_branch_deployed_sha` and
  `ready_dependency_smoke`.
- [x] Add a no-secret hosted deployment smoke that verifies `/health` and
  `/ready` both return the expected main merge SHA and healthy readiness
  dependencies.
- [x] Capture current production deployment evidence for `19eb3ce...`.
- [x] Validate that the deployment evidence can be merged with existing
  public-risk evidence while leaving the remaining signal, source-contract,
  hosted-worker, and monitoring gates incomplete.

Completed 2026-06-30: deployment of `main` is now a first-class completion
gate rather than chat-only evidence. The `19eb3ce...` hosted deployment smoke
satisfies only `production_deployment_evidence`; it does not reduce required
signal-family gaps, official authorization/contracts, hosted worker raw
snapshot/scheduler/egress requirements, or production monitoring/alerting.

## Task 42: Hosted Monitoring Evidence Overlay

**Files:**
- Add: `scripts/hosted_monitoring_evidence.py`
- Add: `tests/test_hosted_monitoring_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: a private hosted monitoring manifest with alert routing,
  scheduled freshness check, and worker/scheduler ownership evidence.
- Produces: a fail-closed `local-source-completion-evidence/v1` overlay for
  `production_monitoring_and_alerting`.

- [x] Write failing tests requiring valid monitoring evidence to produce an
  accepted completion overlay.
- [x] Reject incomplete manifests that lack owner, cadence, verified status, or
  requirement-level evidence.
- [x] Support PowerShell UTF-8 BOM JSON manifests.
- [x] Document the private handoff command and required fields.

Completed 2026-06-30: operators now have a strict private evidence path for
`production_monitoring_and_alerting`. This does not itself prove hosted alert
routing or scheduler ownership; the audit is accepted only when real private
monitoring evidence is provided.

## Task 43: Hosted Worker Persistence Evidence Overlay

**Files:**
- Add: `scripts/hosted_worker_evidence.py`
- Add: `tests/test_hosted_worker_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: a private hosted worker manifest with freshness policy, raw
  snapshot retention, scheduler cadence, hosted egress, and worker-persisted
  evidence path proof.
- Produces: a fail-closed `local-source-completion-evidence/v1` overlay for
  `hosted_worker_persisted_evidence`.

- [x] Write failing tests requiring valid hosted worker evidence to produce an
  accepted completion overlay.
- [x] Reject incomplete manifests that lack verified status, retention days,
  scheduler cadence, hosted egress reviewer, or persisted adapter keys.
- [x] Support PowerShell UTF-8 BOM JSON manifests.
- [x] Document the private handoff command and required fields.

Completed 2026-06-30: operators now have a strict private evidence path for
all five `hosted_worker_persisted_evidence` requirements. This does not itself
prove hosted worker persistence; the audit is accepted only when real private
worker, scheduler, storage, and egress evidence is provided.

## Task 44: Source Contract Evidence Overlay

**Files:**
- Add: `scripts/source_contract_evidence.py`
- Add: `tests/test_source_contract_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: a private source-contract manifest covering every current
  `authorization_request`, `metadata_release_monitor`, and
  `public_api_contract_review` item.
- Produces: a fail-closed `local-source-completion-evidence/v1` overlay for
  `official_authorization_and_contracts`.

- [x] Write failing tests requiring valid source-contract evidence to produce
  an accepted completion overlay.
- [x] Reject incomplete manifests that lack an accepted status, evidence ref,
  review timestamp, or any current required county/gate.
- [x] Support PowerShell UTF-8 BOM JSON manifests.
- [x] Document the private handoff command and required fields.

Completed 2026-06-30: operators now have a strict private evidence path for
the six current official authorization/contract blockers. This does not itself
prove official authorization, metadata release, or public read API contracts;
the audit is accepted only when real private official replies or contract
reviews are supplied.

## Task 45: Signal Family Evidence Overlay

**Files:**
- Add: `scripts/signal_family_evidence.py`
- Add: `tests/test_signal_family_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: a private signal-family manifest covering every current
  county/signal item in `signal_gap_priority_groups`.
- Produces: a fail-closed `local-source-completion-evidence/v1` overlay for
  `required_signal_families`.

- [x] Write failing tests requiring valid signal-family evidence to produce an
  accepted completion overlay.
- [x] Reject incomplete manifests that contain `request_dispatched`, missing
  evidence refs, missing review timestamps, or omit any current county/signal
  requirement.
- [x] Support PowerShell UTF-8 BOM JSON manifests.
- [x] Document the private handoff command and required fields.

Completed 2026-06-30: operators now have a strict private evidence path for
the 24 current signal-family blockers. This does not itself prove pump/gate,
flood-depth, or sewer-level coverage; the audit is accepted only when real
private official replies, authorization-gated adapter evidence, production
adapter evidence, or official-unavailable decisions are supplied.

## Task 46: Hosted Worker Policy Evidence Overlay

**Files:**
- Add: `scripts/hosted_worker_policy_evidence.py`
- Add: `tests/test_hosted_worker_policy_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: a private hosted worker policy manifest for raw snapshot
  retention, scheduler cadence, and hosted egress review.
- Produces: a mergeable fail-closed `local-source-completion-evidence/v1`
  overlay for the remaining `hosted_worker_persisted_evidence` requirements
  not proven by hosted source freshness smoke.

- [x] Write failing tests requiring valid policy evidence to produce accepted
  requirement-level completion overlay.
- [x] Reject incomplete manifests that lack verified status, retention days,
  scheduler cadence, egress reviewer, or requirement evidence.
- [x] Support PowerShell UTF-8 BOM JSON manifests.
- [x] Document how to merge the policy overlay with the hosted source-freshness
  overlay.

Completed 2026-06-30: operators can now split hosted-worker proof into
public-safe admin freshness evidence plus private policy/ops evidence. This
does not itself prove hosted worker persistence or policy acceptance; the audit
is accepted only when real hosted source-freshness and private policy evidence
are supplied.

## Task 47: Civil IoT Signal Gap Coverage Reconciliation

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_coverage.py`
- Modify: `apps/api/tests/test_local_source_action_plan.py`
- Modify: `apps/api/tests/test_admin_contract.py`
- Modify: `tests/test_local_source_completion_audit_cli.py`
- Modify: `docs/api/openapi.yaml`

**Interfaces:**
- Consumes: Civil IoT live adapter distribution smoke for flood sensors, sewer
  water level, pump water level, and gate water level.
- Produces: updated local source coverage and completion audit signal-family
  blockers reflecting verified Civil IoT county coverage.

- [x] Write a failing coverage test requiring Civil IoT-backed sewer, flood,
  and pump coverage for verified counties.
- [x] Reconcile Taoyuan, Taichung, Chiayi City, Tainan, and Yunlin coverage
  against live adapter county distribution.
- [x] Reduce current signal-family blockers from `pump_or_gate_status:14`,
  `flood_depth:5`, `sewer_water_level:5` to `pump_or_gate_status:13`,
  `flood_depth:3`, `sewer_water_level:1`.
- [x] Keep metadata-only and non-measurement sources from being promoted to
  realtime coverage.

Completed 2026-06-30: Civil IoT live distribution evidence now reduces the
signal-family blocker count from 24 to 17. This does not satisfy remaining
signal-family completion; Lienchiang still lacks all three listed signal types,
Taipei and Penghu still lack flood depth, and 13 counties still lack
pump_or_gate_status.

## Task 48: Current Signal Gap Discovery Evidence Refresh

**Files:**
- Modify: `docs/reviews/signal-gap-discovery-refresh-2026-06-30-pump-or-gate.json`
- Modify: `docs/reviews/signal-gap-discovery-refresh-2026-06-30-flood-depth.json`
- Modify: `docs/reviews/signal-gap-discovery-refresh-2026-06-30-sewer-water-level.json`
- Modify: `docs/data-sources/local/2026-06-28-local-source-verification-log.md`

**Interfaces:**
- Consumes: current `signal_gap_priority_groups` discovery monitor commands.
- Produces: refreshed UTF-8 discovery evidence for the 17 remaining
  county/signal blockers.

- [x] Re-run current `pump_or_gate_status` discovery for the 13-county batch.
- [x] Re-run current `flood_depth` discovery for Lienchiang, Penghu, and Taipei.
- [x] Re-run current `sewer_water_level` discovery for Lienchiang only.
- [x] Record that all three current discovery runs found 0
  `candidate_live_read_api` datasets.

Completed 2026-06-30: discovery evidence now matches the post-Civil-IoT
17-item signal gap list. This does not reduce the completion audit blockers;
it proves that the current public data.gov.tw export does not expose a
promotion-ready live read API for the remaining signal gaps.

## Task 49: Public API Contract Probe For Current Review Queue

**Files:**
- Add: `apps/api/app/domain/realtime/local_source_contract_probe.py`
- Add: `apps/api/tests/test_local_source_contract_probe.py`
- Add: `scripts/public-api-contract-probe.py`
- Add: `tests/test_public_api_contract_probe_cli.py`
- Add: `docs/reviews/public-api-contract-probe-2026-06-30.json`
- Modify: `docs/data-sources/local/2026-06-28-local-source-verification-log.md`

**Interfaces:**
- Consumes: current `public_api_contract_reviews` from
  `build_local_source_action_plan`.
- Produces: a fail-closed live probe artifact for Miaoli, Pingtung, and
  Taitung public contract blockers.

- [x] Write failing tests for machine-readable read API detection, HTML blocker
  detection, and non-measurement CCTV/warning context.
- [x] Add a CLI with fixture mode, live URL probing, `--fail-on-live-candidate`,
  and explicit `--allow-insecure-tls` recording for public government pages
  that fail Python's strict certificate verifier.
- [x] Run the live probe for the 3 current public API contract review counties
  and 8 candidate URLs.
- [x] Record that 0 `candidate_live_read_api` sources were found.

Completed 2026-06-30: the public contract queue now has a reproducible probe
artifact instead of only static notes. This does not satisfy the
`official_authorization_and_contracts` gate; Miaoli, Pingtung, and Taitung still
need official read API contracts, accepted unavailability records, or promoted
production adapters before the blockers can clear.

## Task 50: Public Completion Audit Markdown Report

**Files:**
- Modify: `scripts/local-source-completion-audit.py`
- Modify: `tests/test_local_source_completion_audit_cli.py`
- Add: `docs/reviews/hosted-deployment-smoke-2026-06-30-5dc502f.json`
- Add: `docs/reviews/hosted-deployment-completion-evidence-2026-06-30-5dc502f.json`
- Add: `docs/reviews/hosted-public-risk-evidence-smoke-2026-06-30-5dc502f.json`
- Add: `docs/reviews/hosted-public-risk-completion-evidence-2026-06-30-5dc502f.json`
- Add: `docs/reviews/completion-audit-2026-06-30-5dc502f.json`
- Add: `docs/reviews/completion-audit-2026-06-30-5dc502f.md`

**Interfaces:**
- Consumes: hosted deployment smoke and hosted public-risk evidence smoke for
  main merge SHA `5dc502f360c5a8d813bc9b3787438f8d4a232cc0`.
- Produces: a public-safe Markdown report for unresolved completion gates,
  next workstreams, and committed evidence overlay counts.

- [x] Write a failing CLI test requiring `--markdown-output` to emit a
  human-readable completion audit report.
- [x] Add Markdown rendering while keeping JSON stdout and `--output` behavior
  unchanged.
- [x] Re-run hosted deployment and hosted public-risk smokes against
  `https://floodrisk.cc` for the deployed `5dc502f...` main SHA.
- [x] Commit the latest completion-audit JSON and Markdown evidence artifacts.

Completed 2026-06-30: the repository now records a public-safe completion audit
report for deployed main SHA `5dc502f...`. The satisfied gates are
`local_direct_or_tracked_request`, `central_backbone_minimum_coverage`,
`production_deployment_evidence`, and `public_risk_worker_evidence_path`. The
overall objective remains incomplete because signal-family blockers,
official authorization/contracts, hosted worker persistence evidence, and
production monitoring/alerting still require accepted evidence.

## Task 51: Official Live Smoke County Distribution Evidence

**Files:**
- Modify: `apps/workers/app/ops/official_realtime_live_smoke.py`
- Modify: `apps/workers/tests/test_official_realtime_live_smoke.py`
- Modify: `scripts/official-realtime-live-smoke.py`
- Add: `tests/test_official_realtime_live_smoke_cli.py`
- Add: `docs/reviews/official-realtime-live-smoke-2026-06-30.json`

**Interfaces:**
- Consumes: live CWA/WRA/WRA IoW/NCDR/Civil IoT official backbone adapter
  smoke results.
- Produces: public-safe evidence with per-adapter county distribution counts,
  so remaining signal-family blockers can be checked against actual current
  upstream coverage.

- [x] Write failing tests requiring smoke result dictionaries to expose
  `county_counts_by_county`.
- [x] Add `--evidence-output` to `scripts/official-realtime-live-smoke.py`.
- [x] Run the live smoke and commit the current county distribution artifact.
- [x] Confirm current central live coverage does not reduce the 17 remaining
  signal-family blockers.

Completed 2026-06-30: live smoke evidence now records exact county
distribution for each official realtime adapter. The run confirms that
`flood_depth` remains missing for Taipei, Penghu, and Lienchiang;
`sewer_water_level` remains missing for Lienchiang; and Civil IoT pump/gate
water-level coverage currently appears only in 嘉義縣、新竹市、臺南市、雲林縣,
so the 13 `pump_or_gate_status` blocker counties remain
unresolved.

## Task 52: Deployed Main 70677db Completion Evidence

**Files:**
- Add: `docs/reviews/hosted-deployment-smoke-2026-06-30-70677db.json`
- Add: `docs/reviews/hosted-deployment-completion-evidence-2026-06-30-70677db.json`
- Add: `docs/reviews/hosted-public-risk-evidence-smoke-2026-06-30-70677db.json`
- Add: `docs/reviews/hosted-public-risk-completion-evidence-2026-06-30-70677db.json`
- Add: `docs/reviews/completion-audit-2026-06-30-70677db.json`
- Add: `docs/reviews/completion-audit-2026-06-30-70677db.md`

**Interfaces:**
- Consumes: hosted `/health`, `/ready`, and public risk query smoke output for
  deployed main merge SHA `70677dba26d2b5b703088c59d3b3599b3c41beda`.
- Produces: public-safe completion evidence proving the current production
  deployment and public-risk worker-evidence path while preserving the remaining
  sensor/source/ops blockers.

- [x] Re-run hosted deployment smoke against `https://floodrisk.cc` for
  `70677db...`.
- [x] Re-run hosted public-risk evidence smoke against the Tainan query sample.
- [x] Merge the public completion overlays into the completion audit JSON and
  Markdown report.
- [x] Confirm the overall objective remains incomplete, with signal-family,
  official authorization/contracts, hosted worker persistence, and monitoring
  gates still open.

Completed 2026-06-30: production deployment evidence and public-risk evidence
are now committed for deployed `main` SHA `70677db...`. The current public audit
marks `production_deployment_evidence` and `public_risk_worker_evidence_path`
satisfied from public-safe evidence, while `required_signal_families`,
`official_authorization_and_contracts`, `hosted_worker_persisted_evidence`, and
`production_monitoring_and_alerting` remain incomplete.

## Task 53: Hosted Source Freshness Full Backbone Gate

**Files:**
- Modify: `scripts/hosted_source_freshness_smoke.py`
- Modify: `tests/test_hosted_source_freshness_smoke.py`
- Modify: `docs/runbooks/official-realtime-source-of-truth.md`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: hosted `/admin/v1/sources` source diagnostics.
- Produces: a stricter public-safe hosted source-freshness smoke that defaults
  to the full official realtime backbone instead of a two-source CWA/WRA sample.

- [x] Write a failing CLI/unit test proving omitted `--required-adapter-key`
  arguments require the full hosted realtime backbone.
- [x] Expand default required adapter keys to CWA rainfall/tide, WRA water
  level, NCDR CAP, WRA IoW flood depth, and Civil IoT flood/sewer/pump/gate.
- [x] Preserve repeated `--required-adapter-key` overrides for documented
  incident or staged rollout checks.
- [x] Update operator docs so narrowed checks are not used as completion
  evidence for the full hosted worker path.

Completed 2026-06-30: future hosted source-freshness completion evidence can no
longer satisfy `freshness_policy` and `worker_persisted_evidence_path` by
checking only `official.cwa.rainfall` and `official.wra.water_level`. This does
not itself satisfy `hosted_worker_persisted_evidence`; an admin token, real
hosted source diagnostics, raw snapshot retention, scheduler cadence, hosted
egress review, and monitoring evidence are still required.

## Task 54: Reject Narrow Hosted Source Completion Evidence

**Files:**
- Modify: `scripts/local-source-completion-audit.py`
- Modify: `tests/test_local_source_completion_audit_cli.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`

**Interfaces:**
- Consumes: local `hosted-source-freshness-smoke/v1` artifacts referenced by
  `local-source-completion-evidence/v1` overlays.
- Produces: completion-audit validation that rejects narrowed hosted source
  freshness artifacts when they are used as hosted worker completion evidence.

- [x] Write a failing audit test proving a two-adapter hosted source artifact
  cannot satisfy hosted worker freshness/worker-path evidence.
- [x] Keep full hosted realtime backbone artifacts accepted for the
  `freshness_policy` and `worker_persisted_evidence_path` requirements while
  leaving raw snapshots, scheduler cadence, and hosted egress still incomplete.
- [x] Update private evidence handoff docs so operators know the audit now
  enforces the full-backbone requirement for public-safe local artifacts.

Completed 2026-06-30: the completion audit now blocks a local
`hosted-source-freshness-smoke/v1` artifact from being counted as hosted worker
evidence unless both `required_adapter_keys` and `checked_sources` include CWA
rainfall/tide, WRA water level, NCDR CAP, WRA IoW flood depth, and Civil IoT
flood/sewer/pump/gate adapters.

## Task 55: Source Contract Dispatch Tracking

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `scripts/local-source-request-packets.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Modify: action-plan, admin-contract, request-packet, and runbook tests.

**Interfaces:**
- Consumes: current `authorization_requests`, `metadata_release_monitors`, and
  `public_api_contract_reviews`.
- Produces: a `source-contract-dispatch-evidence` overlay path and audit
  counter for official request dispatch progress without satisfying
  `official_authorization_and_contracts`.

- [x] Write failing tests proving `request_dispatched` source-contract evidence
  is counted separately from accepted source-contract evidence.
- [x] Add a request-packet CLI format that generates private dispatch overlays
  for the six current authorization/release/contract blockers.
- [x] Expose `source_contract_dispatch_count` in the admin action-plan contract
  and OpenAPI schema.
- [x] Document that dispatch overlays are private progress evidence and must not
  be committed or treated as completion evidence.

Completed 2026-06-30: source-contract request dispatch can now be tracked in
the completion audit as progress toward official authorization and public read
API contracts. It does not reduce the current blocker counts; accepted official
reply, authorization, contract verification, metadata release, or
official-unavailable evidence is still required.

## Task 56: Signal Gap Dispatch Follow-Up Tracking

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `apps/api/app/domain/realtime/local_source_request_packets.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `scripts/local-source-request-packets.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Modify: action-plan, admin-contract, request-packet, and completion-audit tests.

**Interfaces:**
- Consumes: `signal-gap-dispatch-evidence` and
  `source-contract-dispatch-evidence` overlays with optional
  `follow_up_due_at`.
- Produces: completion-audit overlay counts for dispatch follow-up scheduling
  without satisfying `required_signal_families` or
  `official_authorization_and_contracts`.

- [x] Write failing tests proving signal-gap `request_dispatched` evidence can
  carry `follow_up_due_at`, is counted as dispatch progress, and keeps
  `required_signal_families` incomplete.
- [x] Add `--follow-up-due-at` to dispatch overlay generation for signal-gap
  and source-contract request packets.
- [x] Expose follow-up counts and the next follow-up timestamp in the admin
  action-plan contract and OpenAPI schema.
- [x] Document that follow-up scheduling is private progress evidence and must
  not be treated as accepted official coverage.

Completed 2026-06-30: official request dispatch overlays can now record a
follow-up due timestamp. The audit reports the number of dispatch items with
scheduled follow-up and the next due timestamp while still requiring accepted
official replies, production adapter evidence, authorization-gated adapter
evidence, or official-unavailable decisions before any completion gate is
satisfied.

## Task 57: Official Request Follow-Up Monitor

**Files:**
- Add: `scripts/local-source-request-followups.py`
- Add: `tests/test_local_source_request_followups_cli.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Modify: `docs/superpowers/plans/2026-06-30-nationwide-sensor-integration.md`

**Interfaces:**
- Consumes: private `local-source-completion-evidence/v1` dispatch overlays
  containing `signal_family_gap_evidence` and `source_contract_evidence`
  entries with `status: request_dispatched`.
- Produces: a public-safe follow-up report with pending/overdue counts,
  `overdue_items`, and `next_follow_up_due_at`, without echoing
  `evidence_ref`.

- [x] Write failing CLI tests proving overdue dispatches make
  `--fail-on-overdue` exit 1 and private evidence refs are not printed.
- [x] Add the follow-up monitor CLI with repeatable
  `--completion-evidence-json`, `--as-of`, `--output`, and
  `--fail-on-overdue`.
- [x] Document how operators can run the monitor against private dispatch
  overlays after sending official signal-gap and source-contract requests.

Completed 2026-06-30: dispatched official requests can now be monitored for
pending or overdue follow-up without exposing private correspondence refs. This
still does not satisfy `required_signal_families` or
`official_authorization_and_contracts`; it keeps the official request workflow
from becoming invisible while waiting for accepted replies or production
adapter evidence.

## Task 58: Completion Audit Follow-Up Overdue Visibility

**Files:**
- Modify: `apps/api/app/domain/realtime/local_source_action_plan.py`
- Modify: `scripts/local-source-completion-audit.py`
- Modify: `tests/test_local_source_completion_audit_cli.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Modify: `docs/superpowers/plans/2026-06-30-nationwide-sensor-integration.md`

**Interfaces:**
- Consumes: private dispatch overlays with `follow_up_due_at` and an audit
  review timestamp passed as `--as-of`.
- Produces: public-safe completion audit overlay fields for signal-family and
  source-contract overdue follow-up counts, without exposing `evidence_ref` or
  accepting dispatched requests as completion evidence.

- [x] Write a failing completion-audit CLI test requiring `--as-of` to report
  overdue signal-family and source-contract dispatch follow-ups.
- [x] Add optional `follow_up_as_of` plumbing to the local-source action-plan
  completion audit.
- [x] Add `--as-of` to `local-source-completion-audit.py` and include overdue
  counts in JSON/Markdown output.
- [x] Document that overdue visibility is an operator review aid, not a
  completion substitute for official replies, production adapters, or
  official-unavailable evidence.

Completed 2026-06-30: the aggregate completion audit can now show dated
overdue follow-up counts for dispatched official requests. This keeps the main
completion report aligned with the separate follow-up monitor while preserving
the current blockers until accepted signal-family, source-contract, hosted
worker, monitoring, and production evidence is supplied.

## Task 59: Current Main Hosted Deployment Evidence Refresh

**Files:**
- Add: `docs/reviews/hosted-deployment-smoke-2026-06-30-0634cdc.json`
- Add: `docs/reviews/hosted-deployment-completion-evidence-2026-06-30-0634cdc.json`
- Add: `docs/reviews/hosted-public-risk-evidence-smoke-2026-06-30-0634cdc.json`
- Add: `docs/reviews/hosted-public-risk-completion-evidence-2026-06-30-0634cdc.json`
- Add: `docs/reviews/completion-audit-2026-06-30-0634cdc.json`
- Add: `docs/reviews/completion-audit-2026-06-30-0634cdc.md`
- Modify: `docs/superpowers/plans/2026-06-30-nationwide-sensor-integration.md`

**Interfaces:**
- Consumes: hosted `/health`, `/ready`, and `/v1/risk/assess` smoke output for
  deployed main merge SHA `0634cdc1ecf1d300ba18fb30008adef90da85e4a`.
- Produces: public-safe completion evidence that satisfies the current
  production deployment and public-risk worker evidence gates while preserving
  the remaining source, hosted worker, and monitoring blockers.

- [x] Re-run hosted deployment smoke against `https://floodrisk.cc` for the
  deployed `0634cdc...` main SHA.
- [x] Re-run hosted public risk evidence smoke against the Tainan query sample.
- [x] Merge both completion overlays into the completion audit JSON and
  Markdown report.
- [x] Confirm the overall objective remains incomplete after the refresh.

Completed 2026-06-30: production deployment evidence and public-risk evidence
are now committed for deployed `main` SHA `0634cdc...`. The current public
audit marks `production_deployment_evidence` and
`public_risk_worker_evidence_path` satisfied, while
`required_signal_families`, `official_authorization_and_contracts`,
`hosted_worker_persisted_evidence`, and `production_monitoring_and_alerting`
remain incomplete.

## Task 60: Hosted Monitoring Scheduled Smoke Workflow

**Files:**
- Add: `.github/workflows/hosted-monitoring.yml`
- Add: `tests/test_hosted_monitoring_workflow.py`
- Modify: `docs/runbooks/monitoring-freshness-alerts.md`
- Modify: `docs/superpowers/plans/2026-06-30-nationwide-sensor-integration.md`

**Interfaces:**
- Consumes: hosted deployment, public-risk, and hosted source-freshness smoke
  scripts.
- Produces: a scheduled GitHub Actions workflow that runs public hosted smokes
  every 30 minutes and runs the admin `/admin/v1/sources` full-backbone
  freshness smoke when `ADMIN_BEARER_TOKEN` is configured.

- [x] Write a failing workflow contract test requiring schedule,
  workflow-dispatch, public smoke commands, optional admin freshness smoke, and
  artifact upload.
- [x] Add `.github/workflows/hosted-monitoring.yml` with a 30-minute cron and
  manual `expected_deployment_sha` override.
- [x] Upload hosted monitoring JSON artifacts for later completion-evidence
  review.
- [x] Document that this creates scheduled smoke infrastructure but does not by
  itself satisfy alert routing ownership or hosted worker policy evidence.

Completed 2026-06-30: hosted monitoring smokes can now run on a GitHub Actions
schedule and preserve JSON artifacts. This moves the
`scheduled_freshness_checks` path from manual-only toward auditable automation,
but `production_monitoring_and_alerting` remains incomplete until accepted
alert routing ownership, scheduled source-freshness evidence, and
worker/scheduler alert ownership are recorded through the monitoring evidence
manifest.

## Task 61: Official Smoke Signal-Gap Evidence Crosswalk

**Files:**
- Add: `apps/api/app/domain/realtime/local_source_signal_gap_evidence.py`
- Add: `scripts/local-source-signal-gap-evidence.py`
- Add: `apps/api/tests/test_local_source_signal_gap_evidence.py`
- Add: `tests/test_local_source_signal_gap_evidence_cli.py`
- Add: `docs/reviews/official-realtime-live-smoke-2026-06-30-signal-gap-refresh.json`
- Add: `docs/reviews/local-source-signal-gap-evidence-2026-06-30.json`
- Modify: `docs/runbooks/civil-iot-live-enablement.md`
- Modify: `docs/superpowers/plans/2026-06-30-nationwide-sensor-integration.md`

**Interfaces:**
- Consumes: `official-realtime-live-smoke/v1` artifacts and
  `signal_gap_priority_groups` from the local-source action plan.
- Produces: `local-source-signal-gap-evidence/v1` artifacts that show which
  unresolved county/signal items are newly observed by official live smoke and
  which remain unresolved.

- [x] Write failing API and CLI tests proving official live-smoke observations
  are compared to signal-gap groups without satisfying completion gates.
- [x] Add a public-safe evidence builder and CLI with `--official-live-smoke-json`,
  `--output`, and `--fail-on-unresolved`.
- [x] Re-run official live smoke and emit a signal-gap crosswalk artifact.
- [x] Document the repeatable smoke + crosswalk command sequence in the Civil
  IoT live-enablement runbook.

Completed 2026-06-30: the latest official live smoke was healthy for WRA and
Civil IoT sources, with CWA rainfall skipped because no local
`CWA_API_AUTHORIZATION` was available. The crosswalk found 0 newly observed
official coverage items for the 17 unresolved signal-gap items, leaving
`pump_or_gate_status:13`, `flood_depth:3`, and `sewer_water_level:1`
unresolved. This confirms the next source-completion step remains official
local read API requests, authorization, public API contract follow-up, or
official-unavailable evidence rather than promoting a newly discovered central
IoT source.

## Task 62: Pending Evidence Manifest Templates

**Files:**
- Modify: `scripts/signal_family_evidence.py`
- Modify: `scripts/source_contract_evidence.py`
- Modify: `tests/test_signal_family_evidence.py`
- Modify: `tests/test_source_contract_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Add: `docs/data-sources/local/generated-signal-family-evidence-template.json`
- Add: `docs/data-sources/local/generated-source-contract-evidence-template.json`

**Interfaces:**
- Consumes: current `signal_gap_priority_groups`, `authorization_requests`,
  `metadata_release_monitors`, and `public_api_contract_reviews`.
- Produces: public-safe pending manifest templates that operators can copy
  into private ops storage, fill with accepted evidence refs, and validate
  before emitting completion overlays.

- [x] Write failing CLI tests proving both evidence tools can generate a
  complete pending manifest template and that the pending template is rejected
  as completion evidence.
- [x] Add `--template-output` and optional `--captured-at` to
  `signal_family_evidence.py` and `source_contract_evidence.py`.
- [x] Generate public-safe templates for the current 17 signal-family gaps and
  6 source authorization/contract items.
- [x] Document the template generation step in the private production evidence
  handoff runbook.

Completed 2026-07-01: operators now have reproducible pending manifest
templates for every current unresolved local-source completion item. The
templates intentionally fail validation until each entry is replaced with
accepted official reply, production adapter, authorization-gated adapter,
contract verification, metadata release, or official-unavailable evidence.

## Task 63: Hosted Worker And Monitoring Evidence Templates

**Files:**
- Modify: `scripts/hosted_worker_evidence.py`
- Modify: `scripts/hosted_worker_policy_evidence.py`
- Modify: `scripts/hosted_monitoring_evidence.py`
- Modify: `tests/test_hosted_worker_evidence.py`
- Modify: `tests/test_hosted_worker_policy_evidence.py`
- Modify: `tests/test_hosted_monitoring_evidence.py`
- Modify: `docs/runbooks/private-production-evidence-handoff.md`
- Add: `docs/data-sources/local/generated-hosted-worker-evidence-template.json`
- Add: `docs/data-sources/local/generated-hosted-worker-policy-evidence-template.json`
- Add: `docs/data-sources/local/generated-hosted-monitoring-evidence-template.json`

**Interfaces:**
- Consumes: hosted worker persisted evidence requirements, hosted worker policy
  requirements, and production monitoring/alerting requirements from the
  completion audit gates.
- Produces: public-safe pending manifest templates that operators can copy
  into private ops storage, fill with verified evidence refs, and validate
  before emitting completion overlays.

- [x] Write failing CLI tests proving each hosted evidence tool can generate a
  complete pending manifest template and that the pending template is rejected
  as completion evidence.
- [x] Add `--template-output` and optional `--captured-at` to hosted worker,
  hosted worker policy, and hosted monitoring evidence CLIs.
- [x] Generate public-safe templates for the current hosted worker persisted,
  hosted worker policy, and hosted monitoring/alerting gates.
- [x] Document the template generation step in the private production evidence
  handoff runbook.

Completed 2026-07-01: hosted worker and monitoring blockers now have the same
operator handoff pattern as local source gaps. The templates intentionally fail
validation until each requirement is replaced with verified private evidence,
so they move the project closer to acceptance without overstating production
readiness.

## Task 64: Hosted Monitoring Schedule Readiness Watchdog

**Files:**
- Add: `scripts/hosted-monitoring-schedule-readiness.py`
- Add: `tests/test_hosted_monitoring_schedule_readiness_cli.py`
- Add: `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01.json`
- Add: `docs/reviews/hosted-monitoring-schedule-readiness-2026-07-01.md`
- Modify: `docs/runbooks/monitoring-freshness-alerts.md`
- Modify: `docs/reviews/source-gap-progress-2026-07-01.md`

**Interfaces:**
- Consumes: public-safe GitHub Actions schedule-run metadata from
  `gh run list --event schedule`.
- Produces: a schedule readiness artifact that checks the latest Hosted
  Monitoring scheduled run conclusion, head SHA, and freshness window, and
  emits partial completion evidence only when the latest schedule run is
  successful, recent, and on the expected main SHA.

- [x] Write failing CLI tests proving recent successful schedule runs can emit
  `scheduled_freshness_checks` completion evidence while failed/wrong-SHA/stale
  runs cannot.
- [x] Add the watchdog CLI with `--runs-json` fixture support,
  `--expected-head-sha`, `--max-age-minutes`, Markdown output, optional
  completion-evidence output, and `--fail-on-not-ready`.
- [x] Run the watchdog against the live GitHub repository for current main
  `2d86ca32718ae4ef65a8e30c59c84028b0000a1b`.
- [x] Record that the latest real Hosted Monitoring schedule run is still the
  failed pre-fix run `28493475510`, on SHA
  `9d671d2a4a63ec30ff8a79204b7346304404f15f`, so no
  `scheduled_freshness_checks` completion overlay was produced.

Completed 2026-07-01: the project can now detect and document when GitHub
scheduled Hosted Monitoring has not yet produced acceptable post-fix schedule
evidence. This does not satisfy `production_monitoring_and_alerting`; it keeps
the `scheduled_freshness_checks` requirement honest until a real successful,
fresh schedule run appears on the expected main SHA. Alert routing and
worker/scheduler alert ownership still require private monitoring evidence.

## Task 65: Hosted Monitoring Failure Issue Route

**Files:**
- Modify: `.github/workflows/hosted-monitoring.yml`
- Modify: `tests/test_hosted_monitoring_workflow.py`
- Modify: `docs/runbooks/monitoring-freshness-alerts.md`
- Modify: `docs/reviews/source-gap-progress-2026-07-01.md`

**Interfaces:**
- Consumes: Hosted Monitoring job failure state and GitHub Actions context.
- Produces: a public-safe GitHub Issue alert route under
  `[hosted-monitoring-alert] Hosted Monitoring failure`, creating the issue once
  and adding comments on later failures.

- [x] Write a failing workflow contract test requiring `issues: write` and a
  failure-only GitHub issue routing step.
- [x] Add `actions/github-script` routing after artifact upload, using only run
  URL, workflow, event, and SHA.
- [x] Document that this provides an alert channel but still does not satisfy
  `hosted_alert_routing` without accepted private monitoring evidence naming an
  owner, review timestamp, and evidence ref.

Completed 2026-07-01: Hosted Monitoring failures now have a no-secret GitHub
Issue route. This moves `production_monitoring_and_alerting` closer to
operation, but the completion gate remains incomplete until the route is
reviewed, owned, and recorded in a valid hosted monitoring evidence manifest.

## Completion Gates

The full objective is complete only when:

- All 22 counties have either local direct adapters or official request packets with tracked status.
- Central backbone minimum coverage has no missing county.
- Required signal families are either present, status-only with explicit labeling, or documented as unavailable with official follow-up.
- Worker scheduler writes raw snapshots, staging rows, adapter runs, and promoted evidence in hosted-like mode.
- Hosted `/health` and `/ready` return the accepted `main` merge SHA, with readiness dependencies healthy.
- `/admin/v1/sources`, `/admin/v1/local-source-coverage`, and `/admin/v1/local-source-action-plan` expose freshness, missing signal, and queue state.
- Public risk responses use worker-persisted evidence and query-point nearby coverage.
- CI, OpenAPI validation, focused API/worker tests, and runtime smoke pass.
