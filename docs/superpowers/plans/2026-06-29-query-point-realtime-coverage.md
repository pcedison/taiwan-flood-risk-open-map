# Query-Point Realtime Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add query-point nearby realtime coverage so public risk responses and UI can distinguish county-level source availability from sensors actually near the searched point.

**Architecture:** Keep scoring and coverage separate. Reuse existing persisted realtime/evidence tables, add a focused PostGIS coverage query plus a pure evaluator, then attach `nearby_realtime_coverage` to `/v1/risk/assess` responses, profile fast-path responses, OpenAPI, Web display helpers, and runtime smoke. Coverage affects confidence/limitations text only; it must not silently change realtime or historical risk scores.

**Tech Stack:** FastAPI, Pydantic, psycopg/PostGIS SQL, pytest, OpenAPI 3.1 validator, Next.js/React/TypeScript, Node test runner, Playwright, PowerShell Docker Compose smoke.

## Global Constraints

- Default public-facing language is Traditional Chinese.
- Do not output or commit secrets, tokens, cookies, passwords, or full authorization headers.
- Query heat must remain attention metadata and must not affect realtime or historical risk score.
- County-level local source coverage must not be presented as nearby sensor coverage.
- Local/API diagnostic realtime fallback remains local or staging diagnostic only; production risk responses use worker-persisted evidence.
- Do not scrape private dashboards, bypass login, bypass captcha, reverse private APIs, or convert HTML fetched time into observed time.
- Status-only sources such as Yunlin `alarmState` must not be treated as flood depth, water level, or rainfall measurement.
- Full Docker runtime smoke is a required baseline and final regression gate, but it is not sufficient unless the new `nearby_realtime_coverage` assertions are added.

---

## Priority Roadmap

| Priority | Phase | Outcome | Exit Gate |
| --- | --- | --- | --- |
| P0 | Runtime baseline | Confirm this Windows machine can run the existing project baseline before feature work. | Focused 2026-06-29 tests still pass; full Docker runtime smoke result is recorded. |
| P1 | API contract and domain model | `RiskAssessmentResponse` includes stable `nearby_realtime_coverage`. | Pydantic tests and OpenAPI validation pass. |
| P1 | PostGIS coverage query and evaluator | API can compute nearest sensor distance, bucket counts, freshness, and missing signals by signal type. | Repository/evaluator unit tests pass with DB-free cursor fakes. |
| P1 | Public risk integration | Standard and profile-backed `/v1/risk/assess` responses include coverage without changing scores. | Public contract and public risk service tests pass. |
| P2 | Web public UX | Users see "nearby realtime observations" separate from county/source diagnostics. | Web unit tests, typecheck, and Playwright smoke pass. |
| P2 | Runtime smoke extension | Full Docker runtime smoke asserts `nearby_realtime_coverage` exists and is structurally valid. | `.\scripts\runtime-smoke.ps1 -StopOnExit` passes after implementation. |
| P3 | Admin/Ops follow-up | Operators can monitor sensor density, stale rates, and unresolved source queues. | New admin/API dashboard work is separately accepted; not required for first public response slice. |
| Human | Source authorization and governance | Private permissions, contracts, and production launch evidence are collected. | User-provided evidence exists outside repo and passes private validators where applicable. |

## File Structure Map

- Modify `apps/api/app/api/schemas.py`: add coverage Pydantic models and response field.
- Modify `docs/api/openapi.yaml`: mirror the new public response contract.
- Modify `apps/api/app/domain/evidence/repository.py`: add a DB query for nearby realtime coverage rows.
- Create `apps/api/app/domain/realtime/nearby_coverage.py`: pure signal taxonomy, bucket aggregation, coverage confidence, and limitation text.
- Modify `apps/api/app/api/services/public_risk.py`: accept a coverage dependency and attach coverage to standard responses.
- Modify `apps/api/app/api/services/public_profiles.py`: attach coverage to profile-backed fast-path responses.
- Modify `apps/api/app/api/routes/public.py`: wire repository query/evaluator into the public risk dependency bag and cache key.
- Modify `apps/api/tests/test_evidence_repository.py`: SQL and mapping tests for the coverage query.
- Create `apps/api/tests/test_nearby_realtime_coverage.py`: pure evaluator tests.
- Modify `apps/api/tests/test_public_risk_service.py`: service tests for cached, standard, and profile fast-path coverage.
- Modify `apps/api/tests/test_public_contract.py`: response contract tests for `nearby_realtime_coverage`.
- Modify `apps/web/app/lib/page-types.ts`: add TypeScript response types.
- Modify `apps/web/app/lib/risk-display.ts`: add formatting helpers for coverage level, nearest distance, bucket counts, and missing signals.
- Modify `apps/web/app/lib/ui-text.ts`: add Traditional Chinese display copy.
- Create `apps/web/app/components/nearby-coverage-section.tsx`: public nearby coverage panel.
- Modify `apps/web/app/components/diagnostics-section.tsx`: add detailed signal/bucket diagnostics.
- Modify `apps/web/app/page.tsx`: render the nearby coverage panel and pass diagnostics props.
- Modify `apps/web/tests/unit/risk-display.test.ts`: coverage helper tests.
- Modify `apps/web/tests/e2e/map-risk.spec.ts`: public UI smoke for nearby coverage and missing nearby data.
- Modify `scripts/runtime-smoke.ps1`: assert coverage object in live `/v1/risk/assess`.
- Modify `docs/runbooks/runtime-smoke.md`: document the new smoke assertion.
- Modify `docs/reviews/coverage-aware-beta-progress-handoff-2026-06-29.md`: append implementation status after the slice lands.

## Proposed Response Contract

Add this field to `RiskAssessmentResponse`:

```json
{
  "nearby_realtime_coverage": {
    "overall_level": "medium",
    "evaluated_at": "2026-06-29T12:00:00Z",
    "query_radius_m": 500,
    "radius_buckets_m": [500, 1000, 3000, 5000],
    "summary": "查詢點 1 公里內有雨量與水位觀測，但缺淹水深度與雨水下水道水位。",
    "signal_breakdown": [
      {
        "signal_type": "rainfall",
        "label": "雨量",
        "coverage_level": "high",
        "nearest_distance_m": 230.4,
        "nearest_source_id": "local.kaohsiung.rainfall:ST-001",
        "nearest_observed_at": "2026-06-29T11:55:00Z",
        "counts_by_radius_m": {"500": 1, "1000": 4, "3000": 12, "5000": 18},
        "fresh_count": 4,
        "stale_count": 0,
        "status_only_count": 0,
        "missing_reason": null
      }
    ],
    "missing_signal_types": ["flood_depth", "sewer_water_level"],
    "limitations": [
      "縣市已有資料不代表查詢點附近有感測器；本摘要依查詢點距離重新計算。",
      "coverage 僅描述附近觀測密度與新鮮度，不直接改變風險分數。"
    ],
    "county_level_note": "縣市級 coverage catalog 只作背景；附近 coverage 以查詢點半徑重新判斷。"
  }
}
```

Allowed values:

- `overall_level` and `coverage_level`: `high`, `medium`, `low`, `no_local_sensor`, `unavailable`.
- `signal_type`: `rainfall`, `water_level`, `flood_depth`, `sewer_water_level`, `pump_or_gate_status`, `flood_warning`, `status_only`.
- Bucket keys are strings: `"500"`, `"1000"`, `"3000"`, `"5000"`, because JSON object keys are strings.

## Task 0: Baseline Verification And Runtime Smoke Decision

**Files:**
- Read: `docs/reviews/coverage-aware-beta-progress-handoff-2026-06-29.md`
- Read: `docs/runbooks/runtime-smoke.md`
- Run: `scripts/runtime-smoke.ps1`

**Interfaces:**
- Consumes: existing branch `codex/local-source-candidate-smoke`.
- Produces: baseline pass/fail note for the implementation handoff.

- [ ] **Step 1: Confirm branch and cleanliness**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse '@{u}'
```

Expected: current branch is `codex/local-source-candidate-smoke`, no modified files before feature work, and both SHAs match.

- [ ] **Step 2: Re-run the focused 2026-06-29 handoff tests**

Run:

```powershell
$py='C:\Users\y_mea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_admin_contract.py apps/api/tests/test_local_source_action_plan.py apps/api/tests/test_local_source_request_packets.py tests/test_local_source_request_packets_cli.py -q
$env:PYTHONPATH='apps/workers'
& $py -m pytest apps/workers/tests/test_local_source_candidate_smoke.py tests/test_local_source_candidate_smoke_cli.py -q
$env:PYTHONPATH='apps/workers'
& $py -m pytest apps/workers/tests/test_local_kaohsiung_yilan_water_adapters.py apps/workers/tests/test_adapter_registry_config.py -q
$env:PYTHONPATH='apps/api'
& $py infra/scripts/validate_openapi.py
& $py -m ruff check apps/api/app/api/routes/admin.py apps/api/app/api/schemas.py apps/api/app/domain/realtime/local_source_action_plan.py apps/api/app/domain/realtime/local_source_coverage.py apps/api/app/domain/realtime/local_source_request_packets.py apps/api/tests/test_admin_contract.py apps/api/tests/test_local_source_action_plan.py apps/api/tests/test_local_source_request_packets.py apps/workers/app/ops/local_source_candidate_smoke.py apps/workers/tests/test_local_source_candidate_smoke.py tests/test_local_source_request_packets_cli.py
```

Expected: all commands exit 0.

- [ ] **Step 3: Run full Docker runtime smoke if Docker is available**

Run:

```powershell
docker compose version
docker info
.\scripts\runtime-smoke.ps1 -StopOnExit
```

Expected: full smoke ends with `Runtime smoke passed.` If Docker is unavailable, record the exact Docker error and continue with unit/API work; do not claim full runtime acceptance.

- [ ] **Step 4: Commit no code**

Do not commit after Task 0 unless the plan document itself is being committed. This task records baseline state only.

## Task 1: Add API Coverage Contract

**Files:**
- Modify: `apps/api/app/api/schemas.py`
- Modify: `docs/api/openapi.yaml`
- Modify: `apps/api/tests/test_public_contract.py`

**Interfaces:**
- Consumes: `RiskAssessmentResponse`.
- Produces: `NearbyRealtimeCoverage`, `NearbyCoverageSignal`, and `RiskAssessmentResponse.nearby_realtime_coverage`.

- [ ] **Step 1: Write failing public contract test**

Add an assertion to an existing successful `/v1/risk/assess` test in `apps/api/tests/test_public_contract.py`:

```python
coverage = payload["nearby_realtime_coverage"]
assert coverage["query_radius_m"] == 500
assert coverage["radius_buckets_m"] == [500, 1000, 3000, 5000]
assert coverage["overall_level"] in {
    "high",
    "medium",
    "low",
    "no_local_sensor",
    "unavailable",
}
assert "縣市" in coverage["county_level_note"]
assert_openapi_schema(payload, "RiskAssessmentResponse")
```

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_public_contract.py -q
```

Expected: fails because `nearby_realtime_coverage` is absent.

- [ ] **Step 2: Add Pydantic models**

Add to `apps/api/app/api/schemas.py` near `QueryHeat`:

```python
NearbyCoverageLevel = Literal["high", "medium", "low", "no_local_sensor", "unavailable"]
NearbyCoverageSignalType = Literal[
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
    "pump_or_gate_status",
    "flood_warning",
    "status_only",
]


class NearbyCoverageSignal(ContractModel):
    signal_type: NearbyCoverageSignalType
    label: str
    coverage_level: NearbyCoverageLevel
    nearest_distance_m: float | None = Field(default=None, ge=0)
    nearest_source_id: str | None = None
    nearest_observed_at: datetime | None = None
    counts_by_radius_m: dict[str, int] = Field(default_factory=dict)
    fresh_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    status_only_count: int = Field(default=0, ge=0)
    missing_reason: str | None = None


class NearbyRealtimeCoverage(ContractModel):
    overall_level: NearbyCoverageLevel
    evaluated_at: datetime
    query_radius_m: int = Field(ge=50, le=2000)
    radius_buckets_m: list[int] = Field(default_factory=lambda: [500, 1000, 3000, 5000])
    summary: str
    signal_breakdown: list[NearbyCoverageSignal]
    missing_signal_types: list[NearbyCoverageSignalType] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    county_level_note: str
```

Add to `RiskAssessmentResponse`:

```python
nearby_realtime_coverage: NearbyRealtimeCoverage
```

- [ ] **Step 3: Mirror schema in OpenAPI**

Add `NearbyCoverageSignal` and `NearbyRealtimeCoverage` under `components.schemas` in `docs/api/openapi.yaml`, then add `nearby_realtime_coverage` to `RiskAssessmentResponse.required` and `RiskAssessmentResponse.properties`.

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py infra/scripts/validate_openapi.py
```

Expected: OpenAPI validator passes after schema wiring is complete.

- [ ] **Step 4: Commit Task 1**

```powershell
git add apps/api/app/api/schemas.py docs/api/openapi.yaml apps/api/tests/test_public_contract.py
git commit -m "feat(api): add nearby realtime coverage contract"
```

## Task 2: Add Nearby Coverage Repository Query

**Files:**
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/tests/test_evidence_repository.py`

**Interfaces:**
- Consumes: `official_realtime_latest` rows.
- Produces: `NearbyCoverageRow` and `query_nearby_realtime_coverage_rows(...)`.

- [ ] **Step 1: Write failing repository SQL test**

Add a test to `apps/api/tests/test_evidence_repository.py`:

```python
def test_query_nearby_realtime_coverage_rows_counts_radius_buckets() -> None:
    captured = {}

    class Cursor:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        def fetchall(self):
            return [
                {
                    "adapter_key": "local.kaohsiung.rainfall",
                    "source_id": "local.kaohsiung.rainfall:ST-001",
                    "event_type": "rainfall",
                    "station_id": "ST-001",
                    "observed_at": datetime(2026, 6, 29, 11, 55, tzinfo=UTC),
                    "ingested_at": datetime(2026, 6, 29, 11, 56, tzinfo=UTC),
                    "distance_to_query_m": 230.4,
                    "freshness_state": "fresh",
                }
            ]

    rows = query_nearby_realtime_coverage_rows(
        database_url="postgresql://example",
        lat=22.6273,
        lng=120.3014,
        observed_since=datetime(2026, 6, 29, 9, 0, tzinfo=UTC),
        connection_factory=lambda: FakeConnection(Cursor()),
    )

    assert rows[0].adapter_key == "local.kaohsiung.rainfall"
    assert rows[0].distance_to_query_m == 230.4
    assert "official_realtime_latest" in captured["sql"]
    assert "ST_DWithin" in captured["sql"]
    assert 5000 in captured["params"]
```

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_evidence_repository.py -q
```

Expected: fails because the function does not exist.

- [ ] **Step 2: Add dataclass and function**

Add to `apps/api/app/domain/evidence/repository.py`:

```python
@dataclass(frozen=True)
class NearbyCoverageRow:
    adapter_key: str
    source_id: str
    event_type: str
    station_id: str | None
    observed_at: datetime | None
    ingested_at: datetime
    distance_to_query_m: float
    freshness_state: str


def query_nearby_realtime_coverage_rows(
    *,
    database_url: str,
    lat: float,
    lng: float,
    radius_buckets_m: tuple[int, ...] = (500, 1000, 3000, 5000),
    observed_since: datetime | None = None,
    statement_timeout_ms: int = 1500,
    connection_factory: ConnectionFactory | None = None,
) -> tuple[NearbyCoverageRow, ...]:
    max_radius_m = max(radius_buckets_m)
    observed_filter = "AND latest.observed_at >= %s::timestamptz" if observed_since else ""
    observed_params: tuple[datetime, ...] = (observed_since,) if observed_since else ()
    sql = f"""
        WITH query_point AS (
            SELECT
                ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS geog,
                (%s::double precision / 90000.0) AS degree_radius
        )
        SELECT
            latest.adapter_key,
            latest.source_id,
            latest.event_type,
            latest.station_id,
            latest.observed_at,
            latest.ingested_at,
            ST_Distance(latest.geom::geography, qp.geog) AS distance_to_query_m,
            CASE
                WHEN latest.observed_at IS NULL THEN 'stale'
                WHEN latest.observed_at >= now() - interval '10 minutes' THEN 'fresh'
                WHEN latest.observed_at >= now() - interval '60 minutes' THEN 'stale'
                ELSE 'stale'
            END AS freshness_state
        FROM official_realtime_latest latest
        CROSS JOIN query_point qp
        WHERE latest.geom IS NOT NULL
            {observed_filter}
            AND latest.geom && ST_Expand(qp.geom, qp.degree_radius)
            AND ST_DWithin(latest.geom::geography, qp.geog, %s)
        ORDER BY distance_to_query_m ASC, latest.observed_at DESC NULLS LAST
    """
    params = (lng, lat, lng, lat, max_radius_m, *observed_params, max_radius_m)
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                _apply_statement_timeout(cursor, statement_timeout_ms)
                cursor.execute(sql, params)
                return tuple(_nearby_coverage_row(row) for row in cursor.fetchall())
    except psycopg.errors.UndefinedTable as exc:
        if _is_missing_relation(exc, _LATEST_OFFICIAL_RELATION):
            return ()
        raise EvidenceRepositoryUnavailable(str(exc)) from exc
    except (OSError, psycopg.Error) as exc:
        raise EvidenceRepositoryUnavailable(str(exc)) from exc
```

Add `_nearby_coverage_row(row)` to map dict rows into `NearbyCoverageRow`.

- [ ] **Step 3: Run repository tests**

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_evidence_repository.py -q
```

Expected: repository tests pass.

- [ ] **Step 4: Commit Task 2**

```powershell
git add apps/api/app/domain/evidence/repository.py apps/api/tests/test_evidence_repository.py
git commit -m "feat(api): query nearby realtime coverage rows"
```

## Task 3: Add Pure Coverage Evaluator

**Files:**
- Create: `apps/api/app/domain/realtime/nearby_coverage.py`
- Create: `apps/api/tests/test_nearby_realtime_coverage.py`

**Interfaces:**
- Consumes: `NearbyCoverageRow`.
- Produces: `build_nearby_realtime_coverage(...) -> NearbyRealtimeCoverage`.

- [ ] **Step 1: Write failing evaluator tests**

Create `apps/api/tests/test_nearby_realtime_coverage.py` with tests for:

```python
def test_nearby_coverage_distinguishes_nearby_from_county_available() -> None: ...
def test_nearby_coverage_counts_500_1000_3000_5000_buckets() -> None: ...
def test_nearby_coverage_reports_missing_flood_depth_and_sewer() -> None: ...
def test_nearby_coverage_status_only_does_not_count_as_flood_depth() -> None: ...
def test_nearby_coverage_unavailable_when_repository_unavailable() -> None: ...
```

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_nearby_realtime_coverage.py -q
```

Expected: fails because module is absent.

- [ ] **Step 2: Implement evaluator**

Create `apps/api/app/domain/realtime/nearby_coverage.py` with:

```python
RADIUS_BUCKETS_M = (500, 1000, 3000, 5000)
REQUIRED_SIGNAL_TYPES = (
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
)
SIGNAL_LABELS = {
    "rainfall": "雨量",
    "water_level": "水位",
    "flood_depth": "淹水深度",
    "sewer_water_level": "雨水下水道水位",
    "pump_or_gate_status": "抽水站或水門狀態",
    "flood_warning": "官方警戒",
    "status_only": "狀態訊號",
}
```

Implement:

```python
def coverage_signal_type(event_type: str, adapter_key: str) -> str:
    ...

def build_nearby_realtime_coverage(
    *,
    rows: tuple[NearbyCoverageRow, ...],
    query_radius_m: int,
    evaluated_at: datetime,
    repository_unavailable: bool = False,
) -> NearbyRealtimeCoverage:
    ...
```

Rules:

- `rainfall` is high at least one fresh station within 1000m, medium within 3000m, low within 5000m.
- `water_level`, `flood_depth`, and `sewer_water_level` are high within 500m, medium within 1000m, low within 3000m, and no local sensor beyond that.
- `flood_warning` can support context but does not satisfy hydrologic observation.
- `status_only` is displayed as status-only and never satisfies `flood_depth`, `water_level`, or `rainfall`.
- `overall_level` is the best level among required hydrologic signals, downgraded to `low` when only rainfall or warning exists.
- Repository failure returns `overall_level="unavailable"` with a clear limitation.

- [ ] **Step 3: Run evaluator tests**

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_nearby_realtime_coverage.py -q
```

Expected: evaluator tests pass.

- [ ] **Step 4: Commit Task 3**

```powershell
git add apps/api/app/domain/realtime/nearby_coverage.py apps/api/tests/test_nearby_realtime_coverage.py
git commit -m "feat(api): evaluate query-point realtime coverage"
```

## Task 4: Integrate Coverage Into Public Risk Responses

**Files:**
- Modify: `apps/api/app/api/services/public_risk.py`
- Modify: `apps/api/app/api/services/public_profiles.py`
- Modify: `apps/api/app/api/routes/public.py`
- Modify: `apps/api/tests/test_public_risk_service.py`
- Modify: `apps/api/tests/test_public_contract.py`

**Interfaces:**
- Consumes: `build_nearby_realtime_coverage`.
- Produces: standard and profile-backed risk responses with coverage.

- [ ] **Step 1: Write failing service test**

In `apps/api/tests/test_public_risk_service.py`, update `_dependencies()` to require a `nearby_realtime_coverage` dependency and add a test:

```python
def test_assess_risk_includes_nearby_realtime_coverage() -> None:
    response = public_risk.assess_risk(
        RiskAssessRequest(...),
        settings=_settings(),
        created_at=NOW,
        dependencies=_dependencies(
            nearby_realtime_coverage=lambda request, now: NearbyRealtimeCoverage(...),
        ),
    )
    assert response.nearby_realtime_coverage.query_radius_m == 500
```

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_public_risk_service.py -q
```

Expected: fails because the dependency and response field are not wired.

- [ ] **Step 2: Extend dependency bag**

In `public_risk.py`, add:

```python
class NearbyRealtimeCoverageLookup(Protocol):
    def __call__(
        self, request: RiskAssessRequest, /, *, now: datetime
    ) -> NearbyRealtimeCoverage: ...
```

Add `nearby_realtime_coverage: NearbyRealtimeCoverageLookup` to `RiskAssessmentDependencies`.

- [ ] **Step 3: Compute coverage before profile fast path**

In `assess_risk`, compute:

```python
nearby_coverage = dependencies.nearby_realtime_coverage(risk_request, now=created_at)
```

Pass it into:

- profile-backed response path.
- standard `RiskAssessmentResponse(...)`.
- `assessment_result_snapshot(...)` as `nearby_realtime_coverage`.

- [ ] **Step 4: Wire route dependency**

In `routes/public.py`, add `_nearby_realtime_coverage(request, now)` that:

1. returns unavailable coverage when `settings.evidence_repository_enabled` is false;
2. calls `query_nearby_realtime_coverage_rows(...)` with `observed_since = now - REALTIME_OFFICIAL_LOOKBACK`;
3. catches `EvidenceRepositoryUnavailable` and returns unavailable coverage;
4. calls `build_nearby_realtime_coverage(...)`.

Add this function to `_risk_assessment_dependencies()`.

Update `_risk_assessment_response_cache_key`:

```python
"cache_version": "realtime-evidence-v3-nearby-coverage",
```

- [ ] **Step 5: Update profile fast path**

Modify `public_profiles.profile_backed_response(...)` to accept `nearby_realtime_coverage: NearbyRealtimeCoverage` and attach it to the returned response. The profile fast path must not skip coverage.

- [ ] **Step 6: Run API tests**

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_public_risk_service.py apps/api/tests/test_public_contract.py apps/api/tests/test_nearby_realtime_coverage.py -q
$env:PYTHONPATH='apps/api'
& $py infra/scripts/validate_openapi.py
```

Expected: all commands pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add apps/api/app/api/services/public_risk.py apps/api/app/api/services/public_profiles.py apps/api/app/api/routes/public.py apps/api/tests/test_public_risk_service.py apps/api/tests/test_public_contract.py
git commit -m "feat(api): attach nearby realtime coverage to risk responses"
```

## Task 5: Add Public Web Coverage UI

**Files:**
- Modify: `apps/web/app/lib/page-types.ts`
- Modify: `apps/web/app/lib/risk-display.ts`
- Modify: `apps/web/app/lib/ui-text.ts`
- Create: `apps/web/app/components/nearby-coverage-section.tsx`
- Modify: `apps/web/app/components/diagnostics-section.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/tests/unit/risk-display.test.ts`
- Modify: `apps/web/tests/e2e/map-risk.spec.ts`

**Interfaces:**
- Consumes: `RiskAssessmentResponse.nearby_realtime_coverage`.
- Produces: public nearby coverage panel and diagnostics detail.

- [ ] **Step 1: Write failing TypeScript unit tests**

In `apps/web/tests/unit/risk-display.test.ts`, add tests for:

```ts
test("nearbyCoverageSummary labels nearby sensor availability", () => {
  const state = nearbyCoverageSummary({
    overall_level: "medium",
    summary: "查詢點 1 公里內有雨量與水位觀測。",
    missing_signal_types: ["flood_depth"],
    signal_breakdown: [],
    query_radius_m: 500,
    radius_buckets_m: [500, 1000, 3000, 5000],
    evaluated_at: "2026-06-29T12:00:00Z",
    limitations: [],
    county_level_note: "縣市級 coverage catalog 只作背景。",
  });
  assert.equal(state.badge, "附近觀測：中");
});
```

Run:

```powershell
npm test --prefix apps/web
```

Expected: fails because helper/types do not exist.

- [ ] **Step 2: Add TypeScript types**

Add to `apps/web/app/lib/page-types.ts`:

```ts
export type NearbyCoverageLevel = "high" | "medium" | "low" | "no_local_sensor" | "unavailable";
export type NearbyCoverageSignalType =
  | "rainfall"
  | "water_level"
  | "flood_depth"
  | "sewer_water_level"
  | "pump_or_gate_status"
  | "flood_warning"
  | "status_only";

export type NearbyRealtimeCoverage = {
  overall_level: NearbyCoverageLevel;
  evaluated_at: string;
  query_radius_m: number;
  radius_buckets_m: number[];
  summary: string;
  signal_breakdown: Array<{
    signal_type: NearbyCoverageSignalType;
    label: string;
    coverage_level: NearbyCoverageLevel;
    nearest_distance_m: number | null;
    nearest_source_id: string | null;
    nearest_observed_at: string | null;
    counts_by_radius_m: Record<string, number>;
    fresh_count: number;
    stale_count: number;
    status_only_count: number;
    missing_reason: string | null;
  }>;
  missing_signal_types: NearbyCoverageSignalType[];
  limitations: string[];
  county_level_note: string;
};
```

Add `nearby_realtime_coverage: NearbyRealtimeCoverage` to `RiskAssessmentResponse`.

- [ ] **Step 3: Add display helpers**

In `apps/web/app/lib/risk-display.ts`, add:

```ts
export function nearbyCoverageLevelLabel(level: NearbyCoverageLevel): string { ... }
export function formatDistanceMeters(value: number | null): string { ... }
export function nearbyCoverageSummary(coverage: NearbyRealtimeCoverage | null): {
  badge: string;
  tone: "good" | "warn" | "poor" | "muted";
  summary: string;
} { ... }
```

Rules:

- `high` -> `附近觀測：高`
- `medium` -> `附近觀測：中`
- `low` -> `附近觀測：低`
- `no_local_sensor` -> `附近無近距觀測`
- `unavailable` -> `附近觀測暫不可判斷`

- [ ] **Step 4: Add public component**

Create `apps/web/app/components/nearby-coverage-section.tsx`:

```tsx
"use client";

import type { NearbyRealtimeCoverage } from "../lib/page-types";
import { formatDistanceMeters, nearbyCoverageSummary } from "../lib/risk-display";

export function NearbyCoverageSection({
  coverage,
}: {
  coverage: NearbyRealtimeCoverage | null;
}) {
  const summary = nearbyCoverageSummary(coverage);
  return (
    <section className="panel-section nearby-coverage" data-testid="nearby-coverage">
      <div className="section-heading">
        <span className="section-kicker">附近即時觀測</span>
        <strong>{summary.badge}</strong>
      </div>
      <p>{summary.summary}</p>
      {coverage ? (
        <ul className="nearby-coverage-list">
          {coverage.signal_breakdown.slice(0, 4).map((signal) => (
            <li key={signal.signal_type}>
              <strong>{signal.label}</strong>
              <span>{formatDistanceMeters(signal.nearest_distance_m)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 5: Place UI without overwhelming first view**

In `apps/web/app/page.tsx`, render `NearbyCoverageSection` after `RiskSummarySection` and before `EvidenceSection`. In `DiagnosticsSection`, add a detailed list showing bucket counts and stale counts.

- [ ] **Step 6: Run Web tests**

Run:

```powershell
npm test --prefix apps/web
npm run lint --prefix apps/web
npm run typecheck --prefix apps/web
```

Expected: all pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add apps/web/app/lib/page-types.ts apps/web/app/lib/risk-display.ts apps/web/app/lib/ui-text.ts apps/web/app/components/nearby-coverage-section.tsx apps/web/app/components/diagnostics-section.tsx apps/web/app/page.tsx apps/web/tests/unit/risk-display.test.ts apps/web/tests/e2e/map-risk.spec.ts
git commit -m "feat(web): show nearby realtime coverage"
```

## Task 6: Extend Runtime Smoke And Run Full Regression

**Files:**
- Modify: `scripts/runtime-smoke.ps1`
- Modify: `docs/runbooks/runtime-smoke.md`

**Interfaces:**
- Consumes: live `/v1/risk/assess` response.
- Produces: runtime smoke assertion for `nearby_realtime_coverage`.

- [ ] **Step 1: Add failing smoke assertion**

In `scripts/runtime-smoke.ps1`, immediately after the existing query heat assertions, add:

```powershell
if (-not $risk.nearby_realtime_coverage) {
    Fail-Smoke "Risk assessment response did not include nearby_realtime_coverage." "api"
}
if (-not $risk.nearby_realtime_coverage.radius_buckets_m) {
    Fail-Smoke "Nearby realtime coverage did not include radius_buckets_m." "api"
}
if (-not $risk.nearby_realtime_coverage.summary) {
    Fail-Smoke "Nearby realtime coverage did not include a summary." "api"
}
Write-Host "Nearby realtime coverage smoke: overall=$($risk.nearby_realtime_coverage.overall_level), missing=$($risk.nearby_realtime_coverage.missing_signal_types -join ',')"
```

- [ ] **Step 2: Update runbook**

In `docs/runbooks/runtime-smoke.md`, add the coverage assertion to the numbered check list and successful output block.

- [ ] **Step 3: Run full verification**

Run:

```powershell
$env:PYTHONPATH='apps/api'
& $py -m pytest apps/api/tests/test_nearby_realtime_coverage.py apps/api/tests/test_evidence_repository.py apps/api/tests/test_public_risk_service.py apps/api/tests/test_public_contract.py -q
$env:PYTHONPATH='apps/api'
& $py infra/scripts/validate_openapi.py
npm test --prefix apps/web
npm run lint --prefix apps/web
npm run typecheck --prefix apps/web
.\scripts\runtime-smoke.ps1 -StopOnExit
```

Expected: all pass. If full Docker smoke fails for Docker availability or port conflicts, record the exact error and rerun after fixing the local environment.

- [ ] **Step 4: Commit Task 6**

```powershell
git add scripts/runtime-smoke.ps1 docs/runbooks/runtime-smoke.md
git commit -m "test(runtime): smoke nearby realtime coverage"
```

## Task 7: Documentation And Handoff

**Files:**
- Modify: `docs/reviews/coverage-aware-beta-progress-handoff-2026-06-29.md`
- Modify: `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`
- Optional modify: `README.md`

**Interfaces:**
- Consumes: verified implementation results.
- Produces: updated operator/user-facing status that does not overclaim coverage.

- [ ] **Step 1: Add status note to handoff**

Append a section titled `Query-point nearby coverage implementation status` to `docs/reviews/coverage-aware-beta-progress-handoff-2026-06-29.md`.

Include:

- response field name: `nearby_realtime_coverage`;
- verified command list and pass/fail results;
- exact limitation that county coverage is not nearby coverage;
- whether full Docker runtime smoke passed on this machine.

- [ ] **Step 2: Update source matrix wording**

In `docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md`, add a note under implementation constraints:

```markdown
查詢結果中的 nearby coverage 以查詢點距離與資料新鮮度計算；本矩陣的縣市級 ready 狀態只代表來源已接上或可作背景，不能單獨宣稱使用者附近有即時感測器。
```

- [ ] **Step 3: Run docs-neutral checks**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files modified.

- [ ] **Step 4: Commit Task 7**

```powershell
git add docs/reviews/coverage-aware-beta-progress-handoff-2026-06-29.md docs/data-sources/local/taiwan-local-realtime-water-source-matrix.md README.md
git commit -m "docs: record nearby realtime coverage boundary"
```

## Task 8: Optional Admin/Ops Sensor Density Follow-Up

**Files:**
- Modify: `apps/api/app/api/schemas.py`
- Modify: `apps/api/app/api/routes/admin.py`
- Create: `apps/api/app/domain/realtime/sensor_density.py`
- Create: `apps/api/tests/test_sensor_density_admin.py`
- Modify: `docs/runbooks/monitoring-dashboard.md`

**Interfaces:**
- Consumes: same coverage query/evaluator from Tasks 2-3.
- Produces: admin-only county/township signal density summary.

- [ ] **Step 1: Keep this out of the first public slice**

Do not start this task until Tasks 1-7 are merged or accepted. The public risk response is the release-critical path.

- [ ] **Step 2: Define admin endpoint only after operator questions are known**

Candidate endpoint:

```text
GET /admin/v1/sensor-density
```

Candidate summary fields:

- county
- signal_type
- fresh_station_count
- stale_station_count
- latest_success_at
- adapter_failure_streak
- counties_or_townships_missing_signal

- [ ] **Step 3: Create a separate plan before implementation**

Write a new plan `docs/superpowers/plans/YYYY-MM-DD-sensor-density-admin-dashboard.md` before coding this task.

## Human Intervention Queue

These cannot be completed safely by automation alone. They should start after the core nearby coverage implementation is verified, because the new coverage UI will make the remaining gaps visible and easier to explain.

| Priority | Item | Why Human Action Is Required | Deliverable From User |
| --- | --- | --- | --- |
| H1 | 花蓮 Senslink / 行動水情 read API 授權 | Dashboard/login access and data reuse terms require official permission. | Approved read API contract, allowed use statement, rate limit, sample response, credential storage owner. |
| H1 | 金門 KWIS read API confirmation | Public docs describe upload/API credentials, not an approved public read API. | Written confirmation whether a latest read API exists; credentials or decision that no production adapter is allowed. |
| H1 | 連江即時水文觀測資料釋出或納入 Civil IoT/WRA | Current public data is static and central hydrologic backbone is weak. | Government contact response, release plan, or explicit no-data/no-sensor statement. |
| H2 | 苗栗雨水下水道 read API contract | Existing source is HTML/result page, not stable machine-readable read API. | API endpoint, observed time field, station ID, coordinate metadata, license. |
| H2 | 屏東 PTEOC RainStation/River/Flood/Crawler contract | HTML is readable but lacks production-required timestamp/station/coordinate contract. | Official read API or station metadata join contract. |
| H2 | 臺東預警系統 read API contract | System clue exists but public endpoint is not confirmed. | Official endpoint, field descriptions, license, update cadence. |
| H2 | Production secrets and Zeabur env | Secrets cannot be inspected or invented by Codex. | CWA/WRA tokens, admin bearer token, DB/Redis URLs, Zeabur project access, production domain. |
| H3 | Public safety scoring calibration decisions | Thresholds involve public-risk tolerance, not just engineering. | Accepted calibration manifest, event replay evidence, threshold/risk tolerance sign-off. |
| H3 | Legal/privacy approval for forum, social, and user reports | Terms, moderation, retention, and abuse governance require owner approval. | Written acceptance of source approval manifests and launch gates. |
| H3 | Alert routing and on-call owner | Production incident response cannot be automated without accountable humans. | Alert route, escalation owner, response hours, rollback decision owner. |

## Acceptance Definition

This plan is accepted when:

- `/v1/risk/assess` always includes `nearby_realtime_coverage`.
- Coverage reports nearest distance and 500m/1km/3km/5km counts by signal type.
- Response text and Web UI clearly distinguish county-level source availability from nearby sensor availability.
- Status-only evidence is visible as status-only and does not satisfy flood depth, water level, or rainfall.
- Risk scores do not change solely because coverage metadata was added.
- Focused API tests, Web tests, OpenAPI validation, and full Docker runtime smoke pass, or the full Docker limitation is explicitly recorded with the exact blocker.
- Manual intervention queue remains visible and is not silently represented as completed engineering work.

