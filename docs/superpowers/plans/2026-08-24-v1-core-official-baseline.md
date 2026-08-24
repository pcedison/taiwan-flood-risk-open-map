# Flood Risk v1 Core and Official Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one nationwide address/point-and-radius assessment path that reads persisted official current evidence and persisted official historical context, fails closed when query-local realtime coverage is insufficient, and exposes a rolling-compatible public response and Web UI.

**Architecture:** Keep the existing dual scorer, `evidence`, `official_realtime_latest`, ingestion job/run records, geocoder tables, and nearby coverage builders. Add a focused persisted `AssessmentRepository`, a pure safety/base composer, and an API-layer `AssessmentService`; the public route constructs only `AssessmentService(repository, scorer)` and performs no upstream risk I/O. Official adapters run only in the worker, and every source remains independently gated and failure-isolated.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PostgreSQL/PostGIS, psycopg 3, pytest, Ruff, mypy, Next.js 16, React 19, TypeScript 6, Node test runner, Playwright.

## Global Constraints

- Start every task from green. A task may run a RED test locally, but its commit is made only after that test and all named regressions are GREEN.
- Public `/v1/risk/assess` must never wait for CWA, WRA, NCDR, news, forum, social, profile, query-heat, tile, or other upstream/product paths.
- Preserve `score_risk(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult` and all approved scoring fixtures unchanged.
- Score official current evidence and historical/context evidence in separate scorer calls. Never pass news, forum, social, or recent community evidence into the core current scorer.
- Core v1 calls `compose_base_overall(...)` only. It returns `community.state="none"`; community corroboration/uplift is a later plan and must not be partially implemented here.
- Missing, failed, stale, disabled, or query-locally uncovered required realtime sources cannot support public `低`. A fresh station elsewhere in Taiwan is not query-local coverage.
- Current station evidence is bounded by the user-selected radius. CAP/admin-area evidence qualifies by containment or intersection with that radius, using the persisted reviewed area geometry rather than centroid distance.
- Resolve jurisdiction from the query point on the server with `query_realtime_jurisdiction_context(...)`. Do not add or trust `admin_code` on `RiskAssessRequest`.
- Latest, historical, nearby-coverage, source-health, and jurisdiction reads fail independently. One failed read cannot erase successful reads from another category.
- Historical flood and flood-potential geometry may affect historical background only. It cannot assert current flooding.
- Evidence previews are bounded to 10 and add `location_precision` and `limitations`; `/v1/evidence/{assessment_id}` remains the bounded detail route.
- Persistence is fail-soft and ADR-0006-safe: coarsen coordinates, persist no raw query text, never dump the exact public response into `result_snapshot`, and never convert a successful assessment into HTTP 500 because its audit write failed.
- Live adapters default off. Credentials are environment/secrets only and are redacted from URLs, exceptions, logs, snapshots, and responses.
- Retain but freeze v2 batch/replay, query heat, precomputed profiles, profile refresh, embeddings, tiles, and the 22-county proof refresh/publication machinery. Stop their production entry-point writes and do not drop tables or delete modules. The only scoped compatibility exception is read-only reuse of one already-active, immutable, checksum-reviewed jurisdiction boundary snapshot plus migration 0038's exact v1 source-mapping/contract replacement; no snapshot builder, inventory refresher, proof publisher, or generic proof API becomes reachable.
- WRA dataset 25770 is a metadata index whose `sourceurl` points to KML. CWA `W-C0033-003` is CAP XML with `areaDesc`/Taiwan geocodes. NCDR current access is `datastore -> capid -> dump`; the legacy Atom endpoint is parser regression coverage only.

---

## File and Responsibility Map

### API files

- Create `apps/api/app/domain/assessment/models.py` — immutable assessment inputs and base decision types.
- Create `apps/api/app/domain/assessment/safety.py` — query-local low-risk gate and base-only overall composition.
- Create `apps/api/app/domain/assessment/repository.py` — focused repository protocol and Postgres adapter over existing read functions.
- Create `apps/api/app/domain/assessment/__init__.py` — stable exports.
- Create `apps/api/app/api/services/assessment.py` — persisted-only orchestration, compatibility presentation, bounded evidence-detail authorization, and privacy-safe audit persistence; v1 never treats the legacy evidence cache as an authorization source.
- Create `apps/api/tests/test_assessment_safety.py`, `test_assessment_repository.py`, and `test_assessment_service.py`.
- Modify `apps/api/app/api/schemas.py`, `apps/api/app/api/routes/public.py`, `apps/api/app/api/services/public_evidence.py`, `apps/api/app/domain/evidence/repository.py`, `apps/api/app/domain/evidence/__init__.py`, `apps/api/tests/test_public_contract.py`, `apps/api/tests/test_evidence_repository.py`, `packages/contracts/fixtures/risk-assess-response.json`, and `docs/api/openapi.yaml`.

### Worker/source files

- Create `apps/workers/app/jobs/v1_baseline.py`, `apps/workers/app/cli/v1_baseline_cli.py`, and `apps/workers/tests/test_v1_baseline.py`.
- Create WRA history, CWA warning, and revised NCDR fixtures/tests under the exact adapter directories named in Tasks 10–12.
- Create `apps/workers/app/adapters/cap_identity.py` and share it across CWA,
  NCDR, staging/promotion tests, and canonical CAP lifecycle locking.
- Create `docs/runbooks/flood-potential-import.production.yaml` only from an actually downloaded, checksummed official artifact; extend the existing validator/importer rather than adding a parallel materializer.
- Modify `apps/workers/app/adapters/contracts.py`, `apps/workers/app/jobs/ingestion.py`, `apps/workers/app/jobs/freshness.py`, `apps/workers/app/jobs/runtime.py`, `apps/workers/app/jobs/runtime_managed.py` only where a public type/export is explicitly required, `apps/workers/app/pipelines/promotion.py`, `apps/workers/app/config.py`, `apps/workers/app/adapters/registry.py`, `apps/workers/app/main.py`, `apps/workers/app/cli/parser.py`, `apps/workers/app/scheduler.py`, `apps/workers/app/cli/maintenance_cli.py`, and `apps/workers/app/cli/profiles_cli.py`.
- Create `infra/migrations/0038_v1_official_baseline_sources.sql` and
  `tests/test_v1_official_migration_postgres.py`; do not create a second
  evidence/latest/run schema.

### Web files

- Modify `apps/web/app/lib/page-types.ts`, `apps/web/app/lib/risk-display/risk.ts`, `apps/web/app/lib/risk-display/evidence.ts`, `apps/web/app/lib/risk-display.ts`, `apps/web/app/lib/ui-text.ts`, `apps/web/app/components/risk-summary-section.tsx`, `apps/web/app/components/evidence-section.tsx`, and `apps/web/app/page.tsx`.
- Modify `apps/web/tests/unit/risk-display.test.ts` and `apps/web/tests/e2e/map-risk.spec.ts`.

### Retained but frozen

- `apps/api/app/api/services/public_risk.py` and `apps/api/tests/test_public_risk_service.py` remain legacy characterization only; no production route imports the service.
- `apps/api/app/domain/profiles/*`, `apps/workers/app/jobs/profiles.py`, `apps/workers/app/jobs/query_heat.py`, `apps/workers/app/jobs/tile_cache.py`, migrations `0005` and `0015`, and their unit tests remain in the tree.
- `apps/api/app/domain/realtime/official.py` remains diagnostic/legacy code and is not reachable from assessment.

---

### Task 1: Lock Existing Scoring, Geocoding, and Constructor Behavior

**Files:**

- Modify: `apps/api/tests/test_scoring.py`
- Modify: `apps/api/tests/test_public_response_cache.py`
- Reference: `apps/api/tests/fixtures/scoring/partial_source_outage.json`
- Reference: `apps/api/tests/fixtures/scoring/stale_official_realtime.json`
- Reference: `apps/api/tests/test_geocoding_normalization.py`
- Reference: `apps/api/tests/test_geocoding_provider_chain.py`
- Reference: `apps/web/tests/e2e/map-risk.spec.ts`

**Interfaces:**

- Consumes the existing scorer and existing `RiskAssessmentResponse` constructor.
- Produces passing characterization that explains why fail-closed behavior belongs after the base scorer and proves old response constructors remain supported during Task 4.

- [ ] **Step 1: Add passing scorer characterization**

Use the existing `_signal_from_fixture` helper in `test_scoring.py`:

```python
def _score_fixture(name: str) -> RiskScoringResult:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return score_risk(
        tuple(_signal_from_fixture(item) for item in payload["signals"]),
        now=datetime.fromisoformat(payload["now"]),
    )


def test_partial_source_outage_can_be_low_before_public_safety_gate() -> None:
    result = _score_fixture("partial_source_outage.json")
    assert result.realtime_level == "低"
    assert result.missing_sources


def test_stale_official_realtime_is_unknown_in_base_scorer() -> None:
    assert _score_fixture("stale_official_realtime.json").realtime_level == "未知"
```

Import `RiskScoringResult` from `app.domain.risk` in the same file.

- [ ] **Step 2: Run characterization before any production change**

Run:

```bash
(cd apps/api && python -m pytest tests/test_scoring.py tests/test_public_response_cache.py tests/test_geocoding_normalization.py tests/test_geocoding_provider_chain.py -q)
```

Expected: PASS.

- [ ] **Step 3: Run the existing Web input-flow characterization**

Run:

```bash
(cd apps/web && npm test)
(cd apps/web && npm run e2e -- --grep "address|landmark|map click|radius")
```

Expected: PASS. Do not change address, landmark, map-click, or radius request semantics in later tasks.

- [ ] **Step 4: Commit only the passing characterization**

```bash
git add apps/api/tests/test_scoring.py
git commit -m "test: characterize v1 scorer safety boundary"
```

---

### Task 2: Add Pure Assessment Types, Query-Local Safety, and Base Composition

**Files:**

- Create: `apps/api/app/domain/assessment/models.py`
- Create: `apps/api/app/domain/assessment/safety.py`
- Create: `apps/api/app/domain/assessment/__init__.py`
- Create: `apps/api/tests/test_assessment_safety.py`

**Interfaces:**

- Consumes `EvidenceRecord`, `NearbyRealtimeCoverage`, and `RiskScoringResult`.
- Produces:

```text
apply_realtime_safety(scoring: RiskScoringResult, data: AssessmentData) -> RiskScoringResult
compose_base_overall(
    realtime_scoring: RiskScoringResult,
    historical_scoring: RiskScoringResult,
) -> OverallDecision
```

- [ ] **Step 1: Write the RED truth-table tests**

Define all fixtures in `test_assessment_safety.py`. Cover these exact cases:

```python
def test_fresh_station_outside_query_local_radius_cannot_support_low() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("regional_reference", 8_000.0),
            water_level=("regional_reference", 7_000.0),
        ),
        source_states=all_required_sources_fresh(),
    )
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "未知"


def test_query_local_rainfall_and_hydrology_can_support_low() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("fresh_nearby", 900.0),
            water_level=("fresh_nearby", 1_200.0),
        ),
        source_states=all_required_sources_fresh(),
    )
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "低"


def test_informational_local_gap_does_not_override_reviewed_required_mapping() -> None:
    data = assessment_data(
        coverage=coverage_with(
            rainfall=("fresh_nearby", 900.0),
            flood_depth=("fresh_nearby", 700.0),
        ),
        source_states=all_required_national_sources_fresh(),
        required_realtime_source_keys=NATIONAL_REQUIRED_KEYS,
        local_machine_feed_missing=("高雄市地方政府機器介面尚未核准",),
    )
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "低"


def test_failed_required_source_changes_only_low_to_unknown() -> None:
    data = assessment_data(source_states=one_required_source_failed())
    assert apply_realtime_safety(low_scoring(), data).realtime_level == "未知"
    assert apply_realtime_safety(high_scoring(), data).realtime_level == "高"


def test_core_composer_uses_realtime_before_history() -> None:
    decision = compose_base_overall(high_scoring(), medium_history_scoring())
    assert (decision.level, decision.dominant_mode) == ("高", "realtime")


def test_core_composer_labels_history_only_as_context() -> None:
    decision = compose_base_overall(unknown_scoring(), medium_history_scoring())
    assert (decision.level, decision.dominant_mode) == ("中", "historical_context")


def test_core_composer_has_no_community_uplift() -> None:
    signature = inspect.signature(compose_base_overall)
    assert tuple(signature.parameters) == ("realtime_scoring", "historical_scoring")
```

Run:

```bash
(cd apps/api && python -m pytest tests/test_assessment_safety.py -q)
```

Expected: FAIL during import because `app.domain.assessment` does not exist.

- [ ] **Step 2: Implement the immutable types**

```python
# apps/api/app/domain/assessment/models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.api.schemas import NearbyRealtimeCoverage
from app.domain.evidence import EvidenceRecord

RiskLevel = Literal["低", "中", "高", "極高", "未知"]
ConfidenceLevel = Literal["低", "中", "高", "未知"]
DominantMode = Literal["realtime", "historical_context", "community_warning", "unknown"]
SourceState = Literal["fresh", "degraded", "stale", "failed", "disabled", "not_applicable"]


@dataclass(frozen=True)
class AssessmentSourceState:
    source_key: str
    signal_type: str
    state: SourceState
    observed_at: datetime | None
    checked_at: datetime | None
    message: str | None


@dataclass(frozen=True)
class AssessmentData:
    current_official: tuple[EvidenceRecord, ...]
    historical: tuple[EvidenceRecord, ...]
    nearby_coverage: NearbyRealtimeCoverage
    source_states: tuple[AssessmentSourceState, ...]
    required_realtime_source_keys: frozenset[str]
    current_available: bool
    historical_available: bool
    coverage_available: bool
    health_available: bool
    jurisdiction_available: bool
    resolved_admin_code: str | None
    resolved_admin_name: str | None
    local_machine_feed_missing: tuple[str, ...]


@dataclass(frozen=True)
class OverallDecision:
    level: RiskLevel
    confidence: ConfidenceLevel
    dominant_mode: DominantMode
    reasons: tuple[str, ...]
```

Keep the `community_warning` literal as an API seam, but do not return it from this task.

- [ ] **Step 3: Implement the query-local low gate and base-only composer**

```python
# apps/api/app/domain/assessment/safety.py
from dataclasses import replace

from app.domain.assessment.models import AssessmentData, OverallDecision
from app.domain.risk import RiskScoringResult

_USABLE_LOCAL_STATES = frozenset({"fresh_nearby", "degraded_nearby"})
_HYDROLOGY = frozenset({"water_level", "flood_depth", "sewer_water_level"})


def _query_local_signal_types(data: AssessmentData) -> frozenset[str]:
    return frozenset(
        item.signal_type
        for item in data.nearby_coverage.signal_breakdown
        if item.availability_state in _USABLE_LOCAL_STATES
        and item.nearest_distance_m is not None
        and item.nearest_distance_m <= data.nearby_coverage.query_radius_m
    )


def can_support_low_realtime(data: AssessmentData) -> bool:
    if not all((
        data.current_available,
        data.coverage_available,
        data.health_available,
        data.jurisdiction_available,
        data.nearby_coverage.source_health_checked,
        data.nearby_coverage.jurisdiction_checked,
        data.nearby_coverage.jurisdiction_catalog_complete,
    )):
        return False
    state_by_key = {state.source_key: state.state for state in data.source_states}
    if any(
        state_by_key.get(key) not in {"fresh", "degraded", "not_applicable"}
        for key in data.required_realtime_source_keys
    ):
        return False
    local = _query_local_signal_types(data)
    return "rainfall" in local and bool(local & _HYDROLOGY)


def apply_realtime_safety(
    scoring: RiskScoringResult,
    data: AssessmentData,
) -> RiskScoringResult:
    if scoring.realtime_level != "低" or can_support_low_realtime(data):
        return scoring
    message = "必要的官方即時來源或查詢點附近涵蓋不足，不能把結果判為低風險。"
    return replace(
        scoring,
        realtime_level="未知",
        explanation_summary="即時資料不足，無法判定目前風險；請另見歷史背景區塊。",
        missing_sources=tuple(dict.fromkeys((*scoring.missing_sources, message))),
    )


def compose_base_overall(
    realtime_scoring: RiskScoringResult,
    historical_scoring: RiskScoringResult,
) -> OverallDecision:
    if realtime_scoring.realtime_level != "未知":
        return OverallDecision(
            realtime_scoring.realtime_level,
            realtime_scoring.confidence_level,
            "realtime",
            realtime_scoring.main_reasons,
        )
    if historical_scoring.historical_level != "未知":
        return OverallDecision(
            historical_scoring.historical_level,
            historical_scoring.confidence_level,
            "historical_context",
            ("目前缺少可採用的即時證據；此等級只代表歷史背景風險。",),
        )
    return OverallDecision(
        "未知",
        "未知",
        "unknown",
        ("目前即時與歷史資料都不足，不能解讀為低風險。",),
    )
```

`local_machine_feed_missing` is public informational context, not an additional
hidden readiness gate. A reviewed local adapter blocks low only when the
jurisdiction policy includes it in `required_realtime_source_keys`; its
unhealthy state is then rejected by the exact loop above. This permits the
approved central-only v1 baseline in Kaohsiung and Pingtung while still requiring
the mapped Tainan local sensor when assessing Tainan.

Export only the exact public names from `app/domain/assessment/__init__.py`.

- [ ] **Step 4: Make the task GREEN and commit**

Run:

```bash
(cd apps/api && python -m pytest tests/test_assessment_safety.py tests/test_scoring.py -q)
(cd apps/api && python -m ruff check app/domain/assessment tests/test_assessment_safety.py)
```

Expected: PASS.

```bash
git add apps/api/app/domain/assessment apps/api/tests/test_assessment_safety.py
git commit -m "feat: add query-local assessment safety"
```

---

### Task 3: Build the Focused Persisted Read Model with Independent Failure States

**Files:**

- Create: `apps/api/app/domain/assessment/repository.py`
- Create: `apps/api/tests/test_assessment_repository.py`
- Modify: `apps/api/app/domain/assessment/__init__.py`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/domain/evidence/__init__.py`
- Modify: `apps/api/app/domain/realtime/nearby_coverage.py`
- Modify: `apps/api/app/domain/realtime/__init__.py`
- Modify: `apps/api/app/api/routes/public.py` (temporary legacy caller only)
- Modify: `apps/api/tests/test_evidence_repository.py`
- Create: `apps/api/tests/test_evidence_repository_postgres.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Create: `tests/fixtures/cap_identity_vectors.json`

**Interfaces:**

- Reuses these existing functions without duplicating their SQL:

```text
query_nearby_latest_official(
    *, database_url: str, lat: float, lng: float, radius_m: int,
    as_of: datetime, limit: int = 50,
    observed_since: datetime | None = None, ...
) -> tuple[EvidenceRecord, ...]
query_nearby_evidence(...) -> tuple[EvidenceRecord, ...]
query_nearby_realtime_coverage_rows(...) -> tuple[NearbyCoverageRow, ...]
query_realtime_source_health_rows(...) -> tuple[RealtimeSourceHealthRow, ...]
query_realtime_jurisdiction_context(...) -> RealtimeJurisdictionContext
build_nearby_source_health(...) -> tuple[NearbySourceHealth, ...]
build_nearby_realtime_coverage(...) -> NearbyRealtimeCoverage
```

- Produces:

```python
class AssessmentRepository(Protocol):
    def load(self, *, lat: float, lng: float, radius_m: int, as_of: datetime) -> AssessmentData: ...
    def persist(self, assessment: RiskAssessmentPersistence) -> None: ...
```

There is deliberately no `admin_code` parameter.

- [ ] **Step 1: Write RED repository tests for all five read boundaries**

Use injected module-level functions and explicit records. Required cases:

```python
def test_repository_resolves_jurisdiction_from_point_not_client_input() -> None:
    signature = inspect.signature(PostgresAssessmentRepository.load)
    assert "admin_code" not in signature.parameters
    repository.load(lat=22.9997, lng=120.2270, radius_m=750, as_of=NOW)
    assert captured_jurisdiction_query == {
        "lat": 22.9997,
        "lng": 120.2270,
        "search_radius_m": 750,
    }


def test_current_reader_receives_the_selected_radius() -> None:
    repository.load(lat=22.9997, lng=120.2270, radius_m=750, as_of=NOW)
    assert captured_latest_query["radius_m"] == 750


def test_admin_warning_uses_area_geometry_near_boundary() -> None:
    records = latest_query_with(
        query_point=POINT_NEAR_ADMIN_EDGE,
        radius_m=500,
        latest_point=ADMIN_CENTROID_OVER_500M_AWAY,
        evidence_geometry=ADMIN_POLYGON_INTERSECTING_RADIUS,
    )
    assert [item.id for item in records] == [WARNING_ID]


def test_expired_or_non_active_cap_never_enters_current_read() -> None:
    records = latest_query_with(
        ACTIVE_CAP,
        expired_cap(active_until=NOW),
        cancelled_cap(),
        as_of=NOW,
    )
    assert [item.id for item in records] == [ACTIVE_CAP.id]


def test_active_cap_is_not_dropped_by_station_observed_lookback() -> None:
    records = latest_query_with(
        active_cap(
            observed_at=NOW - timedelta(days=2),
            active_from=NOW - timedelta(days=2),
            active_until=NOW + timedelta(hours=1),
        ),
        as_of=NOW,
        observed_since=NOW - timedelta(hours=6),
    )
    assert [item.id for item in records] == [ACTIVE_CAP.id]


def test_same_cap_republished_by_ncdr_is_scored_once() -> None:
    records = official_current_with(CWA_CAP, NCDR_REPUBLICATION_OF_CWA_CAP)
    assert [item.id for item in records] == [CWA_CAP.id]


def test_cap_origin_requires_exact_sender_identifier_sent_and_admin() -> None:
    records = official_current_with(
        CWA_CAP,
        cap_with(sender="different@example.tw", identifier=CWA_CAP_IDENTIFIER, sent=CWA_CAP_SENT),
        cap_with(sender=CWA_CAP_SENDER, identifier=CWA_CAP_IDENTIFIER, sent=LATER_SENT),
        cap_with(sender=CWA_CAP_SENDER, identifier=CWA_CAP_IDENTIFIER, sent=CWA_CAP_SENT, admin_code="64000000"),
    )
    assert len(records) == 4


def test_cap_origin_encoding_has_no_delimiter_collision() -> None:
    left = _official_event_origin_key(
        sender="a|b", identifier="c", sent=CAP_SENT, admin_code="67000000"
    )
    right = _official_event_origin_key(
        sender="a", identifier="b|c", sent=CAP_SENT, admin_code="67000000"
    )
    assert left != right


@pytest.mark.parametrize("warning", [MISSING_CAP_SENDER, NAIVE_CAP_SENT, INVALID_CAP_ADMIN])
def test_incomplete_cap_identity_fails_closed_from_current_read(warning) -> None:
    records = latest_query_with(warning, as_of=NOW)
    assert records == ()


def test_generic_history_uses_exact_geography_radius_and_polygon_distance() -> None:
    # Real PostGIS fixture: the point is just beyond 1,000 metres; the polygon
    # intersects the 1,000-metre search circle even though its centroid does not.
    records = query_nearby_evidence(
        database_url=POSTGIS_URL,
        lat=QUERY_LAT,
        lng=QUERY_LNG,
        radius_m=1000,
        connection_factory=postgres_fixture,
    )
    assert OUTSIDE_POINT_ID not in {item.id for item in records}
    polygon = next(item for item in records if item.id == INTERSECTING_POLYGON_ID)
    assert polygon.distance_to_query_m <= 1000
    assert polygon.geometry["type"] in {"Polygon", "MultiPolygon"}


def test_legacy_route_passes_selected_radius_until_service_cutover() -> None:
    client.post("/v1/risk/assess", json=risk_request(radius_m=650))
    assert captured_latest_query["radius_m"] == 650


def test_latest_failure_keeps_historical_result() -> None:
    data = repository_with(latest=unavailable, history=(HISTORY,)).load(**POINT)
    assert data.current_available is False
    assert data.historical_available is True
    assert data.historical == (HISTORY,)


def test_history_failure_keeps_current_result() -> None:
    data = repository_with(latest=(LATEST,), history=unavailable).load(**POINT)
    assert data.current_available is True
    assert data.historical_available is False
    assert data.current_official == (LATEST,)


@pytest.mark.parametrize("failed_read", ["coverage", "health", "jurisdiction"])
def test_coverage_health_and_jurisdiction_fail_independently(failed_read: str) -> None:
    data = repository_with(**{failed_read: unavailable}).load(**POINT)
    assert data.current_official == (LATEST,)
    assert data.historical == (HISTORY,)
    assert getattr(data, f"{failed_read}_available") is False


def test_recent_news_forum_and_social_never_enter_core_scoring_partitions() -> None:
    data = repository_with(history=(NEWS, FORUM, SOCIAL, POTENTIAL, WRA_HISTORY)).load(**POINT)
    assert data.historical == (POTENTIAL, WRA_HISTORY)
    assert all(item.source_type == "official" for item in data.current_official)


def test_historical_or_context_scope_never_enters_current_even_if_latest_is_dirty() -> None:
    data = repository_with(
        latest=(WRA_HISTORY_MISWRITTEN_LATEST, FLOOD_POTENTIAL_MISWRITTEN_LATEST, CWA_RAIN),
    ).load(**POINT)
    assert {item.id for item in data.current_official} == {CWA_RAIN.id}


def test_disabled_catalog_source_is_immediately_excluded_without_deleting_audit() -> None:
    disable_source("official.wra_iow.flood_depth")
    data = repository.load(**POINT)
    assert WRA_IOW_ID not in {item.id for item in data.current_official}
    assert CWA_RAIN_ID in {item.id for item in data.current_official}
    assert evidence_audit_row_exists(WRA_IOW_ID)


def test_disabled_source_is_excluded_from_nearby_coverage_but_health_remains_visible() -> None:
    disable_source("official.wra_iow.flood_depth")
    rows = query_nearby_realtime_coverage_rows(**POINT)
    assert all(item.adapter_key != "official.wra_iow.flood_depth" for item in rows)
    assert source_health_row_exists("official.wra_iow.flood_depth")


def test_catalog_kill_switch_wins_over_prior_healthy_runtime_state() -> None:
    health = build_nearby_source_health((health_row(
        adapter_key="official.wra_iow.flood_depth",
        is_enabled=False,
        configured_health_status="healthy",
        runtime_enabled=True,
        runtime_pipeline_status="succeeded",
        latest_run_status="succeeded",
        latest_run_at=NOW - timedelta(minutes=1),
        latest_observed_at=NOW - timedelta(minutes=1),
    ),), evaluated_at=NOW)
    assert health[0].health_status == "disabled"
    assert health[0].reason_code == "disabled"
    data = repository_with(
        health=health,
        coverage=(OTHER_FRESH_DEPTH_COVERAGE,),
        required_keys=frozenset({"official.wra_iow.flood_depth"}),
    ).load(**POINT)
    response = assess(data)
    assert source_state(response, "official.wra_iow.flood_depth").state == "disabled"
    assert response.realtime.level == "未知"
    assert response.overall.level != "低"


def test_enabled_but_unmapped_legacy_source_cannot_score_or_satisfy_coverage() -> None:
    data = repository_with(
        jurisdiction=verified_context("67000000", "臺南市"),
        latest=(LEGACY_TIDE_ROW, TAINAN_SENSOR),
        coverage=(LEGACY_TIDE_COVERAGE, TAINAN_SENSOR_COVERAGE),
    ).load(**POINT)
    assert {item.adapter_key for item in data.current_official} == {
        "local.tainan.flood_sensor"
    }
    by_signal = {item.signal_type: item for item in data.nearby_coverage.signal_breakdown}
    assert by_signal["water_level"].nearest_source_id is None
    assert by_signal["flood_depth"].nearest_source_id == TAINAN_SENSOR_SOURCE_ID


def test_wrong_revision_or_unproved_mapping_never_becomes_applicable() -> None:
    context = query_context_with(
        reviewed_mapping("official.cwa.rainfall", revision="2026-08-24-v1-baseline"),
        unreviewed_mapping("local.legacy.flood", revision="draft-legacy"),
    )
    assert context.adapter_keys == ("official.cwa.rainfall",)
    data = repository_with(
        jurisdiction=context,
        latest=(CWA_RAIN, LEGACY_LOCAL_ROW),
        coverage=(CWA_RAIN_COVERAGE, LEGACY_LOCAL_COVERAGE),
    ).load(**POINT)
    assert {item.adapter_key for item in data.current_official} == {
        "official.cwa.rainfall"
    }


def test_local_source_from_another_county_cannot_score_or_satisfy_coverage() -> None:
    data = repository_with(
        jurisdiction=verified_context("67000000", "臺南市"),
        latest=(KAOHSIUNG_LOCAL_ROW, TAINAN_SENSOR),
        coverage=(KAOHSIUNG_LOCAL_COVERAGE, TAINAN_SENSOR_COVERAGE),
    ).load(**POINT)
    assert KAOHSIUNG_LOCAL_ID not in {item.id for item in data.current_official}
    depth = next(
        item for item in data.nearby_coverage.signal_breakdown
        if item.signal_type == "flood_depth"
    )
    assert depth.nearest_source_id == TAINAN_SENSOR_SOURCE_ID
    assert depth.counts_by_radius_m["1000"] == 1


def test_jurisdiction_read_failure_keeps_only_reviewed_national_current_rows() -> None:
    data = repository_with(
        jurisdiction=unavailable,
        latest=(CWA_RAIN, WRA_WATER, TAINAN_SENSOR, LEGACY_TIDE_ROW),
    ).load(**POINT)
    assert {item.adapter_key for item in data.current_official} == {
        "official.cwa.rainfall", "official.wra.water_level"
    }
    assert data.jurisdiction_available is False


def test_disabled_historical_source_is_excluded_while_enabled_history_remains() -> None:
    disable_source("official.wra.historical_flood")
    data = repository.load(**POINT)
    assert WRA_HISTORY_ID not in {item.id for item in data.historical}
    assert ENABLED_CONTEXT_ID in {item.id for item in data.historical}


def test_kaohsiung_gap_comes_from_server_resolved_home_jurisdiction() -> None:
    data = repository_with(jurisdiction=verified_context("64000000", "高雄市")).load(**POINT)
    assert data.resolved_admin_code == "64000000"
    assert data.local_machine_feed_missing == ("高雄市地方政府機器介面尚未核准",)
```

Run:

```bash
(cd apps/api && python -m pytest tests/test_assessment_repository.py -q)
```

Expected: FAIL importing `PostgresAssessmentRepository`.

- [ ] **Step 2: Add an explicit persisted evidence scope without breaking constructors**

Append constructor-compatible internal/defaulted fields to `EvidenceRecord`:

```python
evidence_scope: Literal["current", "historical", "context", "unspecified"] = "unspecified"
adapter_key: str | None = None
official_event_origin_key: str | None = None
active_from: datetime | None = None
active_until: datetime | None = None
```

In `query_nearby_evidence`, select:

```sql
CASE
    WHEN c.properties->>'evidence_scope' IN ('current', 'historical', 'context')
        THEN c.properties->>'evidence_scope'
    WHEN c.event_type = 'flood_potential' THEN 'context'
    ELSE 'unspecified'
END AS evidence_scope
```

Update `_record_from_row` for both mapping and positional rows. Existing
hand-built `EvidenceRecord(...)` calls continue to work because the new fields
are last and defaulted. The fields are domain-internal and are not added to the
public evidence schema.

Export the five existing focused read functions and row/context types through `app.domain.evidence.__init__` without removing current exports.

Correct every branch of `query_nearby_evidence`, including generic/historical
point and polygon evidence, to use `ST_DWithin(e.geom::geography, qp.geog,
radius_m)` and `ST_Distance(e.geom::geography, qp.geog)`. A degree-based bbox may
remain only as a conservative index prefilter; it is never the inclusion test or
reported distance. Return `ST_AsGeoJSON(e.geom)` for the evidence geometry and
use `ST_PointOnSurface` only for preview lat/lng. The core repository passes no
extended rainfall/water radius to this history reader. Keep any legacy optional
relevance arguments for compatibility, but their geography distance must also
be exact. Add the real-PostGIS boundary regression above, skipped only when
`EVIDENCE_TEST_DATABASE_URL` is absent during focused development. When
`OFFICIAL_DB_ACCEPTANCE_REQUIRED=1`, missing/unreachable PostGIS is an assertion
failure and the database-marked tests may not skip.

Change `query_nearby_latest_official` to require `radius_m`, bounded to the public
50–2000 metre contract, and a timezone-aware `as_of`; remove its four fixed
per-event radius arguments.
Update every call site and repository test in the same task, including the
temporary legacy public-route caller, which must pass `request.radius_m` until
Task 6 removes that path. For point/station rows,
filter `latest.geom` with that radius. When linked `evidence.geom` is an
admin-area or polygon geometry, filter and calculate distance with
`COALESCE(e.geom, latest.geom)` so containment has distance zero and an area
intersecting the selected-radius buffer is included even when its stored latest
centroid is farther away. Return `ST_AsGeoJSON(COALESCE(e.geom, latest.geom))`
while retaining `ST_PointOnSurface(...)` only for the preview lat/lng. Reject
invalid/empty geometry; never expand the assessment read to the 15 km diagnostic
coverage buckets.

For `flood_warning`, join its linked `evidence` and read only the exact reviewed
CAP properties introduced in Task 8. Require `cap_status='Actual'`,
`cap_message_type IN ('Alert','Update')`, `active_from <= as_of`, and
`as_of < active_until`; a missing/malformed bound fails closed. For each warning
row, require that no persisted successful ingestion job for the same adapter has
`error_code='no_active_event'` and `started_at >=` the row's validated
`ingestion_generation_started_at`. Use `NOT EXISTS`/`MAX(started_at)`, not merely
the latest job by completion time: an older slow Alert may finish after a newer
empty poll. Missing/malformed row generation fails closed from current. Select
`adapter_key`, parsed active bounds, and an
internal `official_event_origin_key` only when bounded `cap_sender`,
`cap_identifier`, timezone-aware `cap_sent`, and canonical eight-digit
`admin_code` are all valid. Compute it as SHA-256 over UTF-8 canonical JSON
`[sender, identifier, sent_utc_rfc3339, admin_code]` with
`ensure_ascii=False` and separators `(',', ':')`; never concatenate with a
delimiter. The API service never exposes the canonical input or digest.
If any identity component is missing, malformed, over its bound, or noncanonical,
exclude the entire warning row from the current reader; do not return it with a
null origin key because `_official_current` would otherwise count it. Implement
private `_official_event_origin_key(...)` in the API evidence repository using
the same canonical algorithm as Task 8. Both API and worker tests load
`tests/fixtures/cap_identity_vectors.json`, whose fixed vectors include the
delimiter-collision pair and exact expected SHA-256 digests, so the two package
implementations cannot drift.

```json
{
  "version": 1,
  "cases": [
    {
      "sender": "sender@example.tw",
      "identifier": "alert-1",
      "sent": "2026-08-24T03:04:05.000000Z",
      "admin_code": "67000000",
      "message_digest": "8fff28c9e7630535ac7df92504b443f1c8c4818a6d4223d72be7e33b6955e849",
      "origin_digest": "1425d38d7b9591c97400a7beeea5f8aab16dd20d2db3b3c25a2cdb2fcff240e0"
    },
    {
      "sender": "a|b",
      "identifier": "c",
      "sent": "2026-08-24T03:04:05.000000Z",
      "admin_code": "67000000",
      "message_digest": "0cddd41ff889825cccc30940a919dd52ea38b1590c3bed6ef49c826cfc8eb216",
      "origin_digest": "e74025e8ea3e281f71a6bb664e9b260c7467c80d3ab4d4c08f294c4d00850294"
    },
    {
      "sender": "a",
      "identifier": "b|c",
      "sent": "2026-08-24T03:04:05.000000Z",
      "admin_code": "67000000",
      "message_digest": "0b003b2031a7e713eb2e84b2d350f31cc51d0036a781e506d9f0846e9ed5c79d",
      "origin_digest": "460a3ac34b78fb98e9d02e373b80db1e1c68f538c7ce8e4263ebd3cd2b824ba4"
    }
  ]
}
```

Apply `observed_since` only to station/point event types `rainfall`,
`water_level`, `flood_depth`, and `flood_report`. Never apply that generic
lookback to `flood_warning`: an older CAP remains current for its validated
`active_from <= as_of < active_until` window until an Update, Cancel, expiry, or
successful `no_active_event` retirement removes it.

Make the catalog row the immediate public kill switch at every evidence read:
`query_nearby_latest_official` inner-joins `data_sources` by
`latest.adapter_key` with `is_enabled=true`; every branch of
`query_nearby_evidence` and `fetch_assessment_evidence` inner-joins by
`evidence.data_source_id` with `is_enabled=true`. Apply the predicate inside
each UNION branch before limit/order. Disabling one source therefore removes its
current, historical/context, preview, and expanded-detail rows immediately but
does not delete `evidence`, latest, staging, or run audit rows and does not hide
another enabled source. Add fake-row and real-Postgres regressions for both
disable and re-enable transitions.

Apply the same catalog predicate in *both* the latest-row and generic-evidence
fallback branches of `query_nearby_realtime_coverage_rows`. Source-health reads
remain visible for diagnostics even when a source is disabled, but a disabled
row cannot become current evidence or satisfy the nearby-coverage proof.

`RealtimeSourceHealthRow.is_enabled` is the authoritative catalog kill switch,
not merely a configuration hint. In `_source_health_decision`, return
`health_status="disabled"` and `reason_code="disabled"` immediately when it is
false, before considering a recent successful run, fresh observation,
`runtime_enabled`, or pipeline status. Retain those timestamps only as internal
diagnostics. Required-source readiness and `_source_states` consume that
disabled decision, so a different fresh source of the same signal type cannot
turn the assessment back to `low` while a required catalog row is disabled.

Harden `query_realtime_jurisdiction_context` itself: its public
`source_mappings` JSON may include only rows that participate in a
`mapping_proof_valid=true` signal contract for the resolved/considered
jurisdiction, whose mapping revision is exactly
`2026-08-24-v1-baseline`, whose manifest version/hash/count match the reviewed
contract, and whose review timestamp/ref are present. Do not emit a mapping
merely because it exists in `realtime_source_jurisdictions`. An unreviewed,
wrong-revision, hash-mismatched, or unrelated-county row therefore cannot enter
`jurisdiction.adapter_keys`, current scoring, source health, or coverage. Add a
real-SQL context regression plus the repository regression above.

In `nearby_coverage.py`, set the v1 absence-proof
`REQUIRED_SIGNAL_TYPES` to exactly `("rainfall", "water_level", "flood_depth")`.
Keep sewer, pump/gate, warning, and status rows in `_ALL_SIGNAL_TYPES` for optional
diagnostics. Add a regression proving an unreviewed optional sewer contract does
not make the three-type v1 jurisdiction catalog incomplete.

- [ ] **Step 3: Implement the repository with one `try` per read**

Use this control flow; do not wrap these calls in one shared exception block:

```python
class PostgresAssessmentRepository:
    def __init__(self, database_url: str, *, enabled: bool = True) -> None:
        self._database_url = database_url
        self._enabled = enabled

    def load(
        self,
        *,
        lat: float,
        lng: float,
        radius_m: int,
        as_of: datetime,
    ) -> AssessmentData:
        jurisdiction, jurisdiction_available = self._load_jurisdiction(
            lat=lat, lng=lng, search_radius_m=radius_m
        )
        national_fallback_keys = frozenset({
            "official.cwa.rainfall",
            "official.cwa.heavy_rain_warning",
            "official.wra.water_level",
            "official.wra_iow.flood_depth",
            "official.ncdr.cap",
        })
        applicable_keys = (
            frozenset(jurisdiction.adapter_keys)
            if jurisdiction_available and jurisdiction.resolution_status == "verified"
            else national_fallback_keys
        )
        required_keys = frozenset(
            mapping.adapter_key
            for mapping in jurisdiction.source_mappings
            if mapping.requirement_role == "required"
        ) if applicable_keys else frozenset()
        latest, current_available = self._load_latest(
            lat=lat, lng=lng, radius_m=radius_m, as_of=as_of
        )
        history, historical_available = self._load_history(
            lat=lat, lng=lng, radius_m=radius_m, as_of=as_of
        )
        coverage_rows, coverage_available = self._load_coverage(
            lat=lat, lng=lng, as_of=as_of
        )
        latest = tuple(item for item in latest if item.adapter_key in applicable_keys)
        coverage_rows = tuple(
            item for item in coverage_rows if item.adapter_key in applicable_keys
        )
        health_rows, health_available = self._load_health(tuple(sorted(applicable_keys)))

        source_health = build_nearby_source_health(
            health_rows,
            evaluated_at=as_of,
            jurisdictions_by_adapter=_jurisdictions_by_adapter(jurisdiction),
            required_adapter_keys=required_keys,
        )
        coverage = build_nearby_realtime_coverage(
            rows=coverage_rows,
            query_radius_m=radius_m,
            evaluated_at=as_of,
            repository_unavailable=not coverage_available,
            source_health=source_health,
            source_health_unavailable=not health_available,
            source_health_checked=health_available,
            jurisdiction_status=jurisdiction.resolution_status,
            jurisdiction_checked=jurisdiction_available,
            jurisdiction_complete_signal_types=_complete_signal_types(jurisdiction),
            home_jurisdiction=jurisdiction.home_jurisdiction_name,
            considered_jurisdictions=tuple(name for _, name in jurisdiction.considered_jurisdictions),
            jurisdiction_mapping_revisions=jurisdiction.mapping_revisions,
        )
        return AssessmentData(
            current_official=_official_current(latest),
            historical=_historical_only(history),
            nearby_coverage=coverage,
            source_states=_source_states(
                source_health=source_health,
                applicable_keys=applicable_keys,
                required_keys=required_keys,
            ),
            required_realtime_source_keys=required_keys,
            current_available=current_available,
            historical_available=historical_available,
            coverage_available=coverage_available,
            health_available=health_available,
            jurisdiction_available=jurisdiction_available,
            resolved_admin_code=jurisdiction.home_jurisdiction_code,
            resolved_admin_name=jurisdiction.home_jurisdiction_name,
            local_machine_feed_missing=_local_machine_gaps(jurisdiction, source_health),
        )
```

Each `_load_*` catches only `EvidenceRepositoryUnavailable` and returns `(empty_value, False)`. When repository support is disabled, return all availability flags false and build the existing unavailable coverage model; `persist` becomes a no-op.

The applicability filter is an authority boundary, not just a health display
filter. With a verified jurisdiction, only the exact adapter keys in its active
reviewed mappings may enter `_official_current` or the coverage builder. With a
failed/unverified jurisdiction read, retain only the five immutable reviewed
national fallback keys above so an independent boundary-read outage does not
erase valid national evidence; local and legacy/unmapped adapters remain
excluded, and `jurisdiction_available=false` still prevents a public `低`.

```python
class PostgresAssessmentRepository:
    def persist(self, assessment: RiskAssessmentPersistence) -> None:
        if not self._enabled:
            return
        persist_risk_assessment(
            database_url=self._database_url,
            assessment=assessment,
        )
```

Do not open a second repository abstraction or duplicate the persistence SQL.

Filtering is exact:

```python
def _official_current(records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    filtered = tuple(
        item for item in records
        if item.source_type == "official"
        and item.evidence_scope == "current"
        and item.event_type in {"rainfall", "water_level", "flood_warning", "flood_report"}
    )
    output: list[EvidenceRecord] = []
    warning_index: dict[str, int] = {}
    for item in filtered:
        key = item.official_event_origin_key if item.event_type == "flood_warning" else None
        if key is None:
            output.append(item)
            continue
        index = warning_index.get(key)
        if index is None:
            warning_index[key] = len(output)
            output.append(item)
            continue
        if _warning_origin_rank(item) < _warning_origin_rank(output[index]):
            output[index] = item
    return tuple(output)


def _warning_origin_rank(item: EvidenceRecord) -> tuple[int, float]:
    authority_rank = {
        "official.cwa.heavy_rain_warning": 0,
        "official.ncdr.cap": 1,
    }.get(item.adapter_key, 2)
    observed_rank = -(item.observed_at.timestamp() if item.observed_at else 0.0)
    return authority_rank, observed_rank


def _historical_only(records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    return tuple(
        item for item in records
        if item.source_type in {"official", "derived"}
        and (
            item.evidence_scope in {"historical", "context"}
            or item.event_type == "flood_potential"
        )
    )
```

The warning dedupe is a scoring/read projection only: both CWA and NCDR audit
evidence/latest rows remain. It collapses only the exact canonical CAP message
identity `(sender, identifier, sent)` plus administrative area, preferring the
direct CWA publication over NCDR's republication of that same message. A
different sender, identifier, sent instant, or area remains independent;
effective-window or title similarity never collapses government warnings.

The exact `evidence_scope == "current"` predicate is a second fail-closed
partition boundary. Historical/context/unspecified evidence is never current
even if an old migration or operator error left a row in
`official_realtime_latest`; Task 8 also prevents new non-current rows from being
written there.

Rename the existing private `_public_source_id(adapter_key)` helper to the
exported `public_realtime_source_id(adapter_key)`, update its internal callers,
and export it from `app.domain.realtime`. Build source states by adapter key, not
by comparing the public slug to the jurisdiction mapping:

```python
def _source_states(
    *,
    source_health: tuple[NearbySourceHealth, ...],
    applicable_keys: frozenset[str],
    required_keys: frozenset[str],
) -> tuple[AssessmentSourceState, ...]:
    by_public_id = {item.source_id: item for item in source_health}
    output: list[AssessmentSourceState] = []
    for key in sorted(applicable_keys):
        item = by_public_id.get(public_realtime_source_id(key))
        if item is None:
            output.append(AssessmentSourceState(
                source_key=key,
                signal_type=coverage_signal_type("status_only", key),
                state="disabled" if key in required_keys else "not_applicable",
                observed_at=None,
                checked_at=None,
                message="必要來源尚未登錄或沒有健康紀錄。" if key in required_keys else None,
            ))
            continue
        output.append(AssessmentSourceState(
            source_key=key,
            signal_type=item.signal_types[0],
            state={
                "healthy": "fresh",
                "degraded": "degraded",
                "failed": "failed",
                "disabled": "disabled",
                "unknown": "stale",
            }[item.health_status],
            observed_at=item.observed_at,
            checked_at=item.checked_at,
            message=item.message,
        ))
    return tuple(output)
```

This also synthesizes a fail-closed state when a required mapping has no health
row; a missing row can never disappear from the low-risk gate.

Deduplicate only when combining for display, by stable `item.id`, with current first. Do not deduplicate historical events by `(event_type, source_id)` because that collapses distinct events.

- [ ] **Step 4: Derive South Taiwan gaps only from resolved jurisdiction**

Use this immutable policy table in `repository.py`:

```python
_LOCAL_POLICY = {
    "67000000": ("local.tainan.flood_sensor", "臺南市地方淹水感測器尚未可用"),
    "64000000": (None, "高雄市地方政府機器介面尚未核准"),
    "10013000": (None, "屏東縣地方政府機器介面尚未核准"),
}
```

Tainan has no gap only when its mapped source state is `fresh` or `degraded`. Kaohsiung and Pingtung always expose the approved message until a later reviewed-source change updates both policy and tests.

- [ ] **Step 5: Make repository and evidence regressions GREEN**

Run:

```bash
(cd apps/api && python -m pytest tests/test_assessment_repository.py tests/test_evidence_repository.py tests/test_evidence_repository_postgres.py tests/test_nearby_realtime_coverage.py tests/test_public_contract.py -q)
(cd apps/api && python -m ruff check app/domain/assessment app/domain/evidence app/domain/realtime app/api/routes/public.py tests/test_assessment_repository.py)
```

Expected: PASS.

- [ ] **Step 6: Commit the read model**

```bash
git add apps/api/app/domain/assessment/repository.py apps/api/app/domain/assessment/__init__.py apps/api/app/domain/evidence/repository.py apps/api/app/domain/evidence/__init__.py apps/api/app/domain/realtime/nearby_coverage.py apps/api/app/domain/realtime/__init__.py apps/api/app/api/routes/public.py apps/api/tests/test_assessment_repository.py apps/api/tests/test_evidence_repository.py apps/api/tests/test_evidence_repository_postgres.py apps/api/tests/test_public_contract.py tests/fixtures/cap_identity_vectors.json
git commit -m "feat: add persisted assessment read model"
```

---

### Task 4: Add the Response Contract Without Breaking Existing Constructors

**Files:**

- Modify: `apps/api/app/api/schemas.py` at `RiskLevelBlock`, `EvidencePreview`, and `RiskAssessmentResponse`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/domain/evidence/__init__.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `apps/api/tests/test_public_response_cache.py`
- Modify: `packages/contracts/fixtures/risk-assess-response.json`
- Modify: `docs/api/openapi.yaml`

**Interfaces:**

- Adds `as_of`, dimension confidence/reasons, `community`, `overall`, `dominant_mode`, `data_status`, and `community_refresh`.
- Keeps every current constructor valid until Task 5 populates authoritative values.

- [ ] **Step 1: Write RED schema and old-constructor tests in the same task**

```python
def test_risk_response_schema_exposes_additive_v1_fields() -> None:
    properties = RiskAssessmentResponse.model_json_schema()["properties"]
    assert {
        "as_of", "community", "overall", "dominant_mode",
        "data_status", "community_refresh",
    } <= properties.keys()


def test_legacy_constructor_gets_safe_additive_defaults() -> None:
    response = _response()
    payload = response.model_dump(mode="json")
    assert payload["as_of"] == payload["created_at"]
    assert payload["community"]["state"] == "none"
    assert payload["overall"]["level"] in {"低", "中", "高", "極高", "未知"}
    assert payload["data_status"] == {"sources": [], "missing": []}
```

Run:

```bash
(cd apps/api && python -m pytest tests/test_public_contract.py::test_risk_response_schema_exposes_additive_v1_fields tests/test_public_response_cache.py -q)
```

Expected: FAIL only because new fields do not exist; existing constructor tests still pass.

- [ ] **Step 2: Add defaulted models and a safe compatibility validator**

```python
from typing import Self


DominantMode = Literal["realtime", "historical_context", "community_warning", "unknown"]
CommunityState = Literal[
    "none", "unverified", "community_corroborated", "officially_corroborated"
]
PublicSourceState = Literal[
    "fresh", "degraded", "stale", "failed", "disabled", "not_applicable"
]


class RiskLevelBlock(ContractModel):
    level: RiskLevel
    confidence: ConfidenceLevel = "未知"
    reasons: list[str] = Field(default_factory=list)


class CommunityRiskBlock(ContractModel):
    state: CommunityState = "none"
    level: RiskLevel = "未知"
    reasons: list[str] = Field(default_factory=list)


class PublicSourceStatus(ContractModel):
    source_key: str
    signal_type: str
    state: PublicSourceState
    observed_at: datetime | None = None
    checked_at: datetime | None = None
    message: str | None = None


class DataStatus(ContractModel):
    sources: list[PublicSourceStatus] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class CommunityRefresh(ContractModel):
    state: Literal["not_available", "idle", "prioritized"] = "not_available"
    last_completed_at: datetime | None = None
```

Define and export the shared domain type from
`apps/api/app/domain/evidence/repository.py`, then import it in `schemas.py` and
append the defaulted preview fields:

```python
EvidenceLocationPrecision = Literal[
    "point", "road_or_lane", "poi", "admin_area", "polygon",
    "inferred", "map_click", "unknown",
]

# EvidencePreview
location_precision: EvidenceLocationPrecision = "unknown"
limitations: list[str] = Field(default_factory=list)
```

This evidence-specific public union is shared by official and community previews.
Do not reuse geocoder `GeocodePrecision`, because it also permits
`exact_address`, which must never be disclosed on evidence.

Extend `RiskAssessmentResponse` after all existing required fields:

```python
as_of: datetime | None = None
dominant_mode: DominantMode = "unknown"
community: CommunityRiskBlock = Field(default_factory=CommunityRiskBlock)
overall: RiskLevelBlock | None = None
data_status: DataStatus = Field(default_factory=DataStatus)
community_refresh: CommunityRefresh = Field(default_factory=CommunityRefresh)

@model_validator(mode="after")
def fill_additive_compatibility_defaults(self) -> Self:
    if self.as_of is None:
        self.as_of = self.created_at
    if self.overall is None:
        if self.realtime.level != "未知":
            self.overall = RiskLevelBlock(
                level=self.realtime.level,
                confidence=self.confidence.level,
                reasons=list(self.explanation.main_reasons),
            )
            self.dominant_mode = "realtime"
        elif self.historical.level != "未知":
            self.overall = RiskLevelBlock(
                level=self.historical.level,
                confidence=self.confidence.level,
                reasons=["此相容結果只代表歷史背景風險。"],
            )
            self.dominant_mode = "historical_context"
        else:
            self.overall = RiskLevelBlock(level="未知")
            self.dominant_mode = "unknown"
    return self
```

This validator is transitional compatibility, not the authoritative composer. Task 5 always supplies `overall` and `dominant_mode` explicitly.

- [ ] **Step 3: Update OpenAPI and the checked-in response fixture**

Make the new properties present in the response schema and example. Use the exact community enum above. Add `location_precision` and `limitations` to evidence preview. Preserve legacy fields `confidence`, `explanation`, `data_freshness`, `query_heat`, and `nearby_realtime_coverage`.

- [ ] **Step 4: Run contract, cache, and validators**

Run:

```bash
(cd apps/api && python -m pytest tests/test_public_contract.py tests/test_public_response_cache.py -q)
python infra/scripts/validate_openapi.py
```

Expected: PASS. The validator takes no path argument.

- [ ] **Step 5: Commit the additive constructor-compatible contract**

```bash
git add apps/api/app/api/schemas.py apps/api/app/domain/evidence/repository.py apps/api/app/domain/evidence/__init__.py apps/api/tests/test_public_contract.py apps/api/tests/test_public_response_cache.py packages/contracts/fixtures/risk-assess-response.json docs/api/openapi.yaml
git commit -m "feat: add rolling-compatible assessment contract"
```

---

### Task 5: Implement `AssessmentService` with Separate Scoring and Privacy-Safe Persistence

**Files:**

- Create: `apps/api/app/api/services/assessment.py`
- Create: `apps/api/tests/test_assessment_service.py`
- Modify: `apps/api/app/api/services/public_evidence.py`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/tests/test_evidence_repository.py`
- Modify: `apps/api/tests/test_public_evidence_cache.py`

**Interfaces:**

- Consumes `AssessmentRepository`, `score_risk`, `apply_realtime_safety`, and `compose_base_overall`.
- Produces:

```python
class RiskScorer(Protocol):
    def __call__(
        self,
        signals: tuple[RiskEvidenceSignal, ...],
        *,
        now: datetime,
    ) -> RiskScoringResult: ...


class AssessmentService:
    def __init__(self, repository: AssessmentRepository, scorer: RiskScorer) -> None: ...
    def assess(
        self,
        request: RiskAssessRequest,
        *,
        now: datetime,
    ) -> RiskAssessmentResponse: ...
```

- [ ] **Step 1: Write RED service tests before implementation**

Use a two-method fake repository and a recording scorer:

```python
@dataclass
class FakeRepository:
    data: AssessmentData
    persisted: list[RiskAssessmentPersistence] = field(default_factory=list)
    fail_persist: bool = False

    def load(self, **_kwargs: object) -> AssessmentData:
        return self.data

    def persist(self, assessment: RiskAssessmentPersistence) -> None:
        if self.fail_persist:
            raise EvidenceRepositoryUnavailable("audit write unavailable")
        self.persisted.append(assessment)


def test_service_scores_current_and_history_in_separate_calls(now, request, data) -> None:
    calls: list[tuple[RiskEvidenceSignal, ...]] = []

    def scorer(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult:
        calls.append(signals)
        return score_risk(signals, now=now)

    response = AssessmentService(FakeRepository(data), scorer).assess(request, now=now)

    assert len(calls) == 2
    assert {signal.source_type for signal in calls[0]} == {"official"}
    assert {signal.event_type for signal in calls[1]} <= {
        "flood_potential", "flood_report", "road_closure"
    }
    assert response.community.state == "none"


def test_core_service_never_calls_a_community_composer() -> None:
    source = inspect.getsource(AssessmentService.assess)
    assert "compose_base_overall" in source
    assert "compose_with_community" not in source
    assert "CommunityDecision" not in source


def test_persist_failure_does_not_change_successful_response(now, request, data) -> None:
    response = AssessmentService(
        FakeRepository(data, fail_persist=True), score_risk
    ).assess(request, now=now)
    assert response.assessment_id
    assert response.overall is not None


def test_persisted_snapshot_is_coarsened_and_has_no_raw_query(now, request, data) -> None:
    repository = FakeRepository(data)
    AssessmentService(repository, score_risk).assess(request, now=now)
    snapshot = repository.persisted[0].result_snapshot
    assert snapshot["location"] == {
        "lat": round(request.point.lat, 2),
        "lng": round(request.point.lng, 2),
    }
    assert snapshot["location_text"] is None
    assert request.location_text not in json.dumps(snapshot, ensure_ascii=False)


def test_required_current_read_failure_is_unknown_not_low(now, request, data) -> None:
    response = AssessmentService(
        FakeRepository(replace(data, current_available=False)), score_risk
    ).assess(request, now=now)
    assert response.realtime.level == "未知"
    assert response.overall.level != "低"


def test_v1_detail_read_ignores_stale_evidence_cache_after_source_disable() -> None:
    cache_assessment_evidence(ASSESSMENT_ID, [WRA_ITEM])  # legacy seeded value
    disable_source("official.wra_iow.flood_depth")
    response = client.get(f"/v1/evidence/{ASSESSMENT_ID}")
    assert response.status_code == 200
    assert WRA_IOW_ID not in {item["id"] for item in response.json()["items"]}
    assert database_fetch_spy.calls == [ASSESSMENT_ID]
```

Run:

```bash
(cd apps/api && python -m pytest tests/test_assessment_service.py -q)
```

Expected: FAIL because `AssessmentService` is not defined.

- [ ] **Step 2: Make evidence conversion preserve precision and limitations**

Append defaulted fields to `EvidenceRecord` so existing constructors stay valid:

```python
location_precision: EvidenceLocationPrecision = "unknown"
limitations: tuple[str, ...] = ()
```

Select them from `evidence.properties` in repository queries:

```sql
CASE
    WHEN c.properties->>'location_precision' IN (
        'point', 'road_or_lane', 'poi', 'admin_area', 'polygon',
        'inferred', 'map_click'
    ) THEN c.properties->>'location_precision'
    ELSE 'unknown'
END AS location_precision,
COALESCE(
    ARRAY(SELECT jsonb_array_elements_text(COALESCE(c.properties->'limitations', '[]'::jsonb))),
    ARRAY[]::text[]
) AS limitations
```

For `official_realtime_latest`, use `point` unless
`quality_flags.location_precision` is one of the evidence allowlist values above.
Map `exact_address` and every unknown value to `unknown`. Update
`evidence_from_record` and `evidence_preview` to copy both fields.

- [ ] **Step 3: Implement the service and call the scorer exactly twice**

The orchestration order is fixed:

```python
data = self._repository.load(
    lat=request.point.lat,
    lng=request.point.lng,
    radius_m=request.radius_m,
    as_of=now,
)
current_items = tuple(evidence_from_record(item) for item in data.current_official)
historical_items = tuple(evidence_from_record(item) for item in data.historical)
current_scoring = self._scorer(
    tuple(signal_from_evidence(item) for item in current_items),
    now=now,
)
historical_scoring = self._scorer(
    tuple(signal_from_evidence(item) for item in historical_items),
    now=now,
)
current_scoring = apply_realtime_safety(current_scoring, data)
overall = compose_base_overall(current_scoring, historical_scoring)
```

Never use `current_scoring.historical_level` or `historical_scoring.realtime_level` in the response. Build:

```python
realtime=RiskLevelBlock(
    level=current_scoring.realtime_level,
    confidence=current_scoring.confidence_level,
    reasons=list(current_scoring.main_reasons),
),
historical=RiskLevelBlock(
    level=historical_scoring.historical_level,
    confidence=historical_scoring.confidence_level,
    reasons=list(historical_scoring.main_reasons),
),
community=CommunityRiskBlock(),
overall=RiskLevelBlock(
    level=overall.level,
    confidence=overall.confidence,
    reasons=list(overall.reasons),
),
dominant_mode=overall.dominant_mode,
as_of=now,
```

Derive `data_freshness`, `data_status`, and legacy `nearby_realtime_coverage` from the same `AssessmentData`; do not create an empty freshness list or placeholder coverage. Return a compatibility `QueryHeat(period="frozen", attention_level="未知", query_count_bucket="frozen", unique_approx_count_bucket="frozen", updated_at=now)` without reading query-heat storage.

Combine display evidence current-first, deduplicate by `id`, apply
`display_evidence_items`, and expose at most 10 previews. Pass only syntactically
valid UUID evidence IDs into persistence. Do **not** call
`cache_assessment_evidence` from the v1 service: source enablement, suppression,
and retention are mutable read-time authorization predicates, so a cached
evidence object can outlive its permission to be public.

Change the production `/v1/evidence/{assessment_id}` path to always call
`assessment_db_evidence`/`fetch_assessment_evidence`, whose SQL applies the
current `data_sources.is_enabled=true` predicate. It must ignore memory/Redis
entries even if a legacy caller seeded one before a source was disabled. Retain
the cache module and its isolated serialization tests for rollback
compatibility, but it is not an authority-bearing v1 read path. If audit
persistence failed, the assessment response remains successful and its later
detail lookup may be empty; serving stale unauthorized detail is not the
fallback.

- [ ] **Step 4: Make persistence additive and authoritative without breaking old callers**

Append defaulted compatibility fields to `RiskAssessmentPersistence`:

```python
overall_level: str | None = None
dominant_mode: str | None = None
```

Update `persist_risk_assessment` so `risk_level` uses `overall_level` when present; the temporary fallback is only for legacy constructors:

```python
storage_overall = (
    _storage_risk_level(assessment.overall_level)
    if assessment.overall_level is not None
    else _max_storage_risk_level(
        assessment.realtime_level,
        assessment.historical_level,
    )
)
```

Fix the current mojibake mapping in the same commit:

```python
def _storage_risk_level(level: str) -> str:
    return {
        "低": "low",
        "中": "medium",
        "高": "high",
        "極高": "severe",
        "未知": "unknown",
    }.get(level, "unknown")
```

Update every `RiskAssessmentPersistence(...)` constructor in `apps/api/app` and `apps/api/tests`, even though defaults preserve compatibility. Assert the SQL parameter for `risk_level` comes from `overall_level`.

- [ ] **Step 5: Build a coarsened audit snapshot, not `response.model_dump()`**

Implement this private service helper:

```python
def _privacy_safe_result_snapshot(
    *,
    request: RiskAssessRequest,
    response: RiskAssessmentResponse,
    current_scoring: RiskScoringResult,
    historical_scoring: RiskScoringResult,
    evidence_ids: tuple[str, ...],
) -> dict[str, object]:
    assert response.overall is not None
    return {
        "assessment_id": response.assessment_id,
        "location": {
            "lat": round(request.point.lat, 2),
            "lng": round(request.point.lng, 2),
        },
        "location_text": None,
        "radius_m": request.radius_m,
        "score_version": response.score_version,
        "scores": {
            "realtime": current_scoring.realtime_score,
            "historical": historical_scoring.historical_score,
            "confidence": max(
                current_scoring.confidence_score,
                historical_scoring.confidence_score,
            ),
        },
        "levels": {
            "realtime": response.realtime.level,
            "historical": response.historical.level,
            "overall": response.overall.level,
            "confidence": response.overall.confidence,
        },
        "dominant_mode": response.dominant_mode,
        "evidence_ids": list(evidence_ids),
        "data_status": response.data_status.model_dump(mode="json"),
        "created_at": response.created_at.isoformat(),
        "expires_at": response.expires_at.isoformat(),
    }
```

Catch `EvidenceRepositoryUnavailable` around `repository.persist(...)` and return the already-built response. Do not catch programming errors.

- [ ] **Step 6: Run service, evidence, persistence, and static checks**

Run:

```bash
(cd apps/api && python -m pytest tests/test_assessment_service.py tests/test_evidence_repository.py tests/test_realtime_intensity.py tests/test_public_evidence_cache.py tests/test_public_response_cache.py -q)
(cd apps/api && python -m ruff check app/api/services/assessment.py app/api/services/public_evidence.py app/domain/evidence tests/test_assessment_service.py)
(cd apps/api && python -m mypy app)
```

Expected: PASS.

- [ ] **Step 7: Commit the persisted-only service**

```bash
git add apps/api/app/api/services/assessment.py apps/api/app/api/services/public_evidence.py apps/api/app/domain/evidence/repository.py apps/api/tests/test_assessment_service.py apps/api/tests/test_evidence_repository.py apps/api/tests/test_public_evidence_cache.py
git commit -m "feat: add persisted-only assessment service"
```

---

### Task 6: Collapse the Public Route to `AssessmentService`

**Files:**

- Modify: `apps/api/app/api/routes/public.py` at `assess_risk` and its risk-only helpers/imports
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `apps/api/tests/test_public_risk_service.py`
- Reference without modifying: `apps/api/app/api/services/public_risk.py`

**Interfaces:**

- Produces `_assessment_service(settings: Settings) -> AssessmentService`.
- Keeps rate limiting and `POST /v1/risk/assess` request shape unchanged.

- [ ] **Step 1: Add a RED route-level no-upstream regression**

```python
def test_risk_assess_does_not_call_legacy_or_request_time_upstreams(monkeypatch) -> None:
    from app.api.services import public_risk as legacy_public_risk
    from app.domain.history import news_enrichment
    from app.domain.realtime import official as official_realtime

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy/request-time risk path was called")

    monkeypatch.setattr(legacy_public_risk, "assess_risk", forbidden)
    monkeypatch.setattr(official_realtime, "fetch_official_realtime_bundle", forbidden)
    monkeypatch.setattr(news_enrichment, "search_public_flood_news", forbidden)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.2270},
            "radius_m": 1000,
            "time_context": "now",
            "location_text": "臺南市東區",
        },
    )
    assert response.status_code == 200
```

Run:

```bash
(cd apps/api && python -m pytest tests/test_public_contract.py::test_risk_assess_does_not_call_legacy_or_request_time_upstreams -q)
```

Expected: FAIL because the current route still calls `public_risk.assess_risk`.

- [ ] **Step 2: Replace the route wiring**

```python
def _assessment_service(settings: Settings) -> AssessmentService:
    return AssessmentService(
        PostgresAssessmentRepository(
            settings.database_url,
            enabled=settings.evidence_repository_enabled,
        ),
        score_risk,
    )


@router.post("/risk/assess", response_model=RiskAssessmentResponse)
def assess_risk(
    request: RiskAssessRequest,
    http_request: FastAPIRequest,
) -> RiskAssessmentResponse:
    settings = get_settings()
    _enforce_public_rate_limit(
        http_request,
        settings=settings,
        namespace="public-risk-assess-rate",
        max_requests=settings.risk_assessment_rate_limit_max_requests,
        endpoint_name="Risk assessment",
    )
    return _assessment_service(settings).assess(request, now=_now())
```

Delete only route-local risk helpers that become unreachable: `_risk_assessment_dependencies`, request-time official bridge wiring, on-demand news wiring, profile fast-path wiring, profile refresh enqueue wiring, and query-heat response lookup wiring. Keep geocoding, evidence detail, reports, layers, and rate-limit helpers.

Do not delete `public_risk.py`; `test_public_response_cache.py` imports its placeholder coverage builder and the legacy service tests remain characterization for one release.

- [ ] **Step 3: Port public contract fixtures to the repository/service seam**

Replace the autouse risk monkeypatches on `public_routes.query_nearby_evidence`, profile, and query-heat functions with one monkeypatch of `public_routes._assessment_service` or the focused repository functions. Keep non-risk layer/geocode fixtures unchanged.

Move route-specific assertions about profile fast paths, on-demand news, query-heat popularity, and dependency-bag call order into legacy `test_public_risk_service.py` only when they still characterize retained code. Remove them from the public-route contract because those behaviors are deliberately frozen. Add route cases for:

- fresh query-local low;
- partial current source -> unknown;
- current high;
- history-only -> `historical_context`;
- independent latest/history/coverage/health/jurisdiction failure;
- server-resolved Tainan, Kaohsiung, and Pingtung gaps;
- address, landmark, and map-click clients sending no `admin_code`.

- [ ] **Step 4: Make the entire API route suite GREEN**

Run each pytest invocation as a separate process so module-level app/cache state cannot leak:

```bash
(cd apps/api && python -m pytest tests/test_assessment_service.py -q)
(cd apps/api && python -m pytest tests/test_public_contract.py -q)
(cd apps/api && python -m pytest tests/test_public_risk_service.py tests/test_public_response_cache.py -q)
(cd apps/api && python -m pytest tests/test_geocoding_normalization.py tests/test_geocoding_provider_chain.py -q)
```

Expected: PASS.

- [ ] **Step 5: Prove the production route has no frozen path**

Run:

```bash
! rg -n "public_risk\.assess_risk|RiskAssessmentDependencies|fetch_official_realtime_bundle|search_public_flood_news|fetch_best_profile_for_point|fetch_query_heat_snapshot|enqueue_profile_refresh_job" apps/api/app/api/routes/public.py
(cd apps/api && python -m ruff check app/api/routes/public.py tests/test_public_contract.py)
(cd apps/api && python -m mypy app)
```

Expected: all commands exit 0; the search prints no matches.

- [ ] **Step 6: Commit the cutover**

```bash
git add apps/api/app/api/routes/public.py apps/api/tests/test_public_contract.py apps/api/tests/test_public_risk_service.py
git commit -m "refactor: collapse public risk route to assessment service"
```

---

### Task 7: Freeze Legacy Product Readers, Writers, and Generic Runtime Dispatch

**Files:**

- Create: `apps/workers/app/jobs/frozen_legacy.py`
- Modify: `apps/workers/app/main.py`
- Modify: `apps/workers/app/cli/parser.py`
- Modify: `apps/workers/app/scheduler.py`
- Modify: `apps/workers/app/cli/maintenance_cli.py`
- Modify: `apps/workers/app/cli/profiles_cli.py`
- Modify: `apps/workers/app/cli/queue_cli.py`
- Modify: `apps/workers/app/cli/runtime_cli.py`
- Modify: `apps/workers/tests/test_worker_entrypoints.py`
- Create: `apps/workers/tests/test_scheduler.py`
- Modify: `apps/api/app/api/services/public_layers.py`
- Modify: `apps/api/app/api/routes/tiles.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `apps/api/tests/test_tiles_contract.py`
- Modify: `docs/api/openapi.yaml`

**Interfaces:**

- Keeps legacy flags parseable for deployment compatibility.
- Produces a metadata-only frozen result and guarantees production entry points
  do not construct or call query-heat/profile/embedding/tile/generic-runtime
  writers, while public routes cannot read query heat, tile cache, or PMTiles.

- [ ] **Step 1: Write RED no-write entry-point tests**

```python
@pytest.mark.parametrize(
    "argv",
    [
        ["--aggregate-query-heat"],
        ["--seed-risk-profiles"],
        ["--rebuild-risk-profile", "--profile-kind", "risk_grid", "--profile-key", "x"],
        ["--work-profile-refresh-jobs"],
        ["--refresh-tile-features"],
        ["--run-enabled-adapters"],
        ["--work-runtime-queue", "--once"],
        ["--enqueue-runtime-jobs"],
        ["--scheduler", "--max-ticks", "1"],
        ["--run-official-demo", "--persist"],
        [
            "--requeue-runtime-job", "job-1",
            "--requeue-requested-by", "fixture-operator",
            "--requeue-reason", "fixture-reason",
        ],
    ],
)
def test_frozen_legacy_commands_never_construct_writers(monkeypatch, argv, capsys) -> None:
    monkeypatch.setattr(
        "app.cli.maintenance_cli.PostgresQueryHeatAggregationJob",
        lambda *_args, **_kwargs: pytest.fail("query heat writer constructed"),
    )
    monkeypatch.setattr(
        "app.cli.profiles_cli.rebuild_risk_profile",
        lambda *_args, **_kwargs: pytest.fail("profile writer called"),
    )
    assert main(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "frozen"


def test_direct_generic_cli_helpers_are_frozen_before_writer_construction(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.cli.queue_cli.PostgresRuntimeQueue",
        lambda *_args, **_kwargs: pytest.fail("runtime queue constructed"),
    )
    assert queue_cli.work_runtime_queue(
        settings=SETTINGS, once=True, max_ticks=None,
        persist=True, database_url=None,
    ) == 2
    assert queue_cli.enqueue_runtime_jobs(
        settings=SETTINGS, scheduler=False, once=True, max_ticks=None,
    ) == 2
    assert queue_cli.requeue_runtime_job(
        settings=SETTINGS, database_url=None, job_id="job-1",
        reset_attempts=True, requested_by="fixture", reason="fixture",
    ) == 2
    assert runtime_cli.run_managed_enabled_adapters(
        settings=SETTINGS, database_url=None
    ) == 2
    assert runtime_cli.run_managed_enabled_adapters_loop(
        settings=SETTINGS, database_url=None, once=True, max_ticks=1
    ) == 2
    assert runtime_cli.run_official_demo(
        settings=SETTINGS, persist=True, database_url=None
    ) == 2


def test_scheduler_maintenance_keeps_privacy_retention_only(monkeypatch) -> None:
    monkeypatch.setattr(
        scheduler,
        "PostgresQueryHeatAggregationJob",
        lambda *_args, **_kwargs: pytest.fail("query heat writer constructed"),
    )
    monkeypatch.setattr(
        scheduler,
        "PostgresTileCacheWriter",
        lambda *_args, **_kwargs: pytest.fail("tile writer constructed"),
    )
    retention = RecordingEvidenceRetentionJob()
    monkeypatch.setattr(
        scheduler, "PostgresEvidenceRetentionJob", lambda **_kwargs: retention
    )
    result = run_maintenance_once(settings=SETTINGS)
    assert result.status == "succeeded"
    assert retention.calls == [
        ("prune_realtime", SETTINGS.evidence_realtime_retention_hours),
        ("prune_location_queries", SETTINGS.location_queries_retention_hours),
    ]


def test_scheduler_never_dispatches_generic_runtime_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        scheduler,
        "run_enabled_adapters_once",
        lambda **_kwargs: pytest.fail("generic runtime dispatched"),
    )
    monkeypatch.setattr(
        scheduler,
        "enqueue_enabled_adapters_once",
        lambda **_kwargs: pytest.fail("generic queue enqueued"),
    )
    assert scheduler.main(("--run-enabled-adapters", "--once")) == 2
    assert scheduler.main(("--enqueue-runtime-jobs", "--once")) == 2
    assert scheduler.main(("--official-demo", "--once")) == 2


def test_public_layers_hide_query_heat_and_local_tile_products() -> None:
    response = client.get("/v1/layers")
    assert response.status_code == 200
    assert all(item["category"] != "query_heat" for item in response.json()["items"])
    serialized = response.text.lower()
    assert "/v1/tiles/" not in serialized
    assert "pmtiles" not in serialized


def test_local_tile_route_is_frozen_before_repository_construction(monkeypatch) -> None:
    monkeypatch.setattr(
        tile_routes,
        "fetch_vector_tile",
        lambda *_args, **_kwargs: pytest.fail("tile read executed"),
    )
    response = client.get("/v1/tiles/query-heat/8/215/107.mvt")
    assert response.status_code == 404
```

Run:

```bash
(cd apps/workers && python -m pytest tests/test_worker_entrypoints.py tests/test_scheduler.py -q)
```

Expected: FAIL because current entry points still execute legacy writers.

- [ ] **Step 2: Add one explicit freeze result and intercept every production entry point**

```python
# apps/workers/app/jobs/frozen_legacy.py
from typing import Final

FROZEN_LEGACY_REASON: Final = "v1_legacy_product_writers_frozen"
FROZEN_LEGACY_COMMANDS: Final = (
    "aggregate_query_heat",
    "seed_risk_profiles",
    "rebuild_risk_profile",
    "work_profile_refresh_jobs",
    "refresh_tile_features",
    "run_enabled_adapters",
    "work_runtime_queue",
    "enqueue_runtime_jobs",
    "requeue_runtime_job",
    "generic_scheduler",
    "official_demo",
)
```

In `main.py`, check these parsed flags before dispatch and print:

```python
print(json.dumps({
    "status": "frozen",
    "reason": FROZEN_LEGACY_REASON,
    "tables_retained": True,
}, ensure_ascii=False, sort_keys=True))
return 2
```

`--maintenance` is not a frozen command because it owns required evidence and
location-query privacy retention. Refactor `run_maintenance_once` so it does not
construct `PostgresQueryHeatAggregationJob` or `PostgresTileCacheWriter`, leaves
their result fields empty, but still constructs `PostgresEvidenceRetentionJob`
and executes both `prune_realtime` and `prune_location_queries`. A failure in
either retained path returns the existing failed result; successful retention
returns `succeeded`. In `maintenance_cli.py`, freeze only the explicit
query-heat/tile subpaths while preserving the scheduler maintenance entrypoint;
in `profiles_cli.py`, guard every profile/embedding writer. Retain legacy
implementation functions and isolated tests—only production calls to the
frozen product writers are removed.

Guard the generic runtime paths at both dispatch layers. `main.py` and the
scheduler reject `--run-enabled-adapters`, `--work-runtime-queue`,
`--enqueue-runtime-jobs`, the mutating `--requeue-runtime-job`, bare
`--scheduler`, and mutating `--run-official-demo --persist`/scheduler
`--official-demo` before any
queue/repository/adapter construction. The concrete mutating helpers in
`queue_cli.py` and `runtime_cli.py` repeat the same guard and return exit code 2
with the frozen metadata payload, so an import-and-call cannot bypass the
top-level parser. Read-only dead-letter listing, summary, and metrics commands
may remain available; no requeue/replay mutation does. The dedicated Task 14
`--v1-baseline` wrapper is the only reviewed official ingestion entry point and
the later community plan has its own isolated scheduler. When Task 14 lands, it
adds an explicit scheduler branch *before* the generic freeze and no other
scheduler mode becomes reachable.

Freeze legacy product reads as well as writes. Remove `query_heat` from dynamic
and static public layer listings, reject any layer URL backed by
`tile_cache_entries`, local `/v1/tiles/...`, or PMTiles, and make the local tile
route return the existing non-enumerating 404 without constructing its
repository. Official flood-potential context remains available through the
persisted evidence/assessment path; only a separately reviewed external
official tile URL may appear as layer metadata. Do not expose a stale local tile
or query-heat product merely because its table still exists. Update the static
OpenAPI contract and tests to match this frozen read boundary.

- [ ] **Step 3: Update CLI help and run focused regressions**

Keep frozen writer flags accepted but change their help text to state they exit
2 in v1. Describe `--maintenance` as retention-only. Run:

```bash
(cd apps/workers && python -m pytest tests/test_worker_entrypoints.py tests/test_scheduler.py tests/test_runtime_queue.py tests/test_query_heat_aggregation.py tests/test_profile_refresh_jobs.py tests/test_tile_cache.py -q)
(cd apps/workers && python -m ruff check app/jobs/frozen_legacy.py app/main.py app/cli app/scheduler.py tests/test_worker_entrypoints.py)
(cd apps/api && python -m pytest tests/test_public_contract.py tests/test_tiles_contract.py -q)
python infra/scripts/validate_openapi.py
```

Expected: PASS. Unit tests prove retained modules still parse/operate in isolation; entry-point tests prove production cannot call them.

- [ ] **Step 4: Commit the freeze**

```bash
git add apps/workers/app/jobs/frozen_legacy.py apps/workers/app/main.py apps/workers/app/cli/parser.py apps/workers/app/cli/maintenance_cli.py apps/workers/app/cli/profiles_cli.py apps/workers/app/cli/queue_cli.py apps/workers/app/cli/runtime_cli.py apps/workers/app/scheduler.py apps/workers/tests/test_worker_entrypoints.py apps/workers/tests/test_scheduler.py apps/api/app/api/services/public_layers.py apps/api/app/api/routes/tiles.py apps/api/tests/test_public_contract.py apps/api/tests/test_tiles_contract.py docs/api/openapi.yaml
git commit -m "refactor: freeze legacy product paths for v1"
```

---

### Task 8: Enforce Advisory-Locked Latest Monotonicity and Bidirectional Central/Local Deduplication

**Files:**

- Modify: `apps/workers/app/pipelines/staging.py`
- Modify: `apps/workers/app/pipelines/promotion.py`
- Modify: `apps/workers/app/jobs/ingestion.py`
- Create: `apps/workers/app/adapters/cap_identity.py`
- Modify: `apps/workers/app/adapters/cwa/rainfall.py`
- Modify: `apps/workers/app/adapters/wra/water_level.py`
- Modify: `apps/workers/app/adapters/wra_iow/flood_depth.py`
- Modify: `apps/workers/app/adapters/local_tainan/flood_sensor.py`
- Modify: `apps/workers/tests/test_staging_pipeline.py`
- Modify: `apps/workers/tests/test_promotion_pipeline.py`
- Create: `apps/workers/tests/test_promotion_monotonicity_postgres.py`
- Modify: `apps/workers/tests/test_ingestion_job_runner.py`
- Modify: `apps/workers/tests/test_official_adapters.py`
- Modify: `apps/workers/tests/test_wra_iow_flood_depth_adapter.py`
- Modify: `apps/workers/tests/test_tainan_flood_sensor_adapter.py`

**Interfaces:**

- Changes `EvidencePromotionWriter.write_evidence(payload) -> str | None`.
- `None` means an idempotent/conflicting/duplicate candidate was terminally consumed and did not create accepted evidence.
- Uses transaction-scoped advisory locks before any read whose natural-key row may not yet exist.
- Changes `build_staging_batch(result, *, raw_ref=None,
  ingestion_generation_started_at: datetime | None = None)` for backward
  compatibility with non-CAP/direct callers. Managed `run_adapter_batch` always
  passes its captured timezone-aware `started_at`, which is then stored
  unchanged as `AdapterBatchRunSummary.started_at`; CAP staging/promotion
  requires a non-null timezone-aware generation and fails closed otherwise. No
  adapter can provide or override that generation.

- [ ] **Step 1: Write RED unit and Postgres concurrency tests**

Cover all decisions and both arrival orders:

```python
def test_advisory_lock_precedes_latest_select_or_insert() -> None:
    writer.write_evidence(realtime_payload(observed_at=NOW, value=20.0))
    sql = [statement for statement, _ in cursor.executions]
    lock_index = next(i for i, item in enumerate(sql) if "pg_advisory_xact_lock" in item)
    insert_index = next(i for i, item in enumerate(sql) if "INSERT INTO evidence" in item)
    assert lock_index < insert_index


def test_equal_time_equal_value_is_terminal_idempotent() -> None:
    first = writer.write_evidence(realtime_payload(observed_at=NOW, value=20.0))
    second = writer.write_evidence(realtime_payload(observed_at=NOW, value=20.0, staging_id="s2"))
    assert first is not None
    assert second is None
    assert cursor.staging_terminal_reason("s2") == "idempotent_existing_observation"


def test_equal_time_conflicting_value_rejects_before_evidence_insert() -> None:
    writer.write_evidence(realtime_payload(observed_at=NOW, value=20.0))
    result = writer.write_evidence(realtime_payload(observed_at=NOW, value=99.0, staging_id="s2"))
    assert result is None
    assert cursor.staging_terminal_reason("s2") == "conflicting_latest"
    assert cursor.accepted_evidence_count_for("s2") == 0


def test_central_first_rejects_exact_local_duplicate() -> None:
    writer.write_evidence(central_depth(NOW, 12.0))
    assert writer.write_evidence(local_depth(NOW, 12.0, staging_id="local")) is None
    assert cursor.latest_adapter_keys() == ["official.wra_iow.flood_depth"]


def test_local_first_is_replaced_when_exact_central_duplicate_arrives() -> None:
    writer.write_evidence(local_depth(NOW, 12.0))
    central_id = writer.write_evidence(central_depth(NOW, 12.0))
    assert central_id is not None
    assert cursor.latest_adapter_keys() == ["official.wra_iow.flood_depth"]


@pytest.mark.parametrize("adapter_key", [
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
])
def test_cap_area_uses_canonical_message_and_admin_latest_key(adapter_key: str) -> None:
    payload = cap_area_payload(adapter_key=adapter_key, admin_code="67000000")
    evidence_id = writer.write_evidence(payload)
    assert evidence_id is not None
    assert cursor.latest_station_id() == (
        "cap:67000000:" + cap_message_digest(
            sender=payload.properties["cap_sender"],
            identifier=payload.properties["cap_identifier"],
            sent=payload.properties["cap_sent"],
        )
    )
    assert cursor.persisted_evidence_geometry() == REVIEWED_TAINAN_GEOMETRY


def test_two_active_alerts_in_one_admin_area_remain_independent() -> None:
    first = cap_area_payload(identifier="alert-1", sent=NOW - timedelta(minutes=2))
    second = cap_area_payload(identifier="alert-2", sent=NOW - timedelta(minutes=1))
    writer.write_evidence(first)
    writer.write_evidence(second)
    assert set(cursor.active_cap_identifiers()) == {"alert-1", "alert-2"}


def test_update_atomically_retires_only_reference_triples_then_upserts_itself() -> None:
    writer.write_evidence(CAP_ALERT_V1)
    writer.write_evidence(UNRELATED_PARALLEL_ALERT)
    writer.write_evidence(CAP_UPDATE_V2_REFERENCING_V1)
    assert set(cursor.active_cap_identifiers()) == {
        CAP_UPDATE_V2_REFERENCING_V1.properties["cap_identifier"],
        UNRELATED_PARALLEL_ALERT.properties["cap_identifier"],
    }


def test_cancel_retires_exact_reference_triple_and_cannot_resurrect_by_replay() -> None:
    writer.write_evidence(CAP_ALERT_V1)
    writer.write_evidence(UNRELATED_PARALLEL_ALERT)
    writer.write_evidence(CAP_CANCEL_REFERENCING_V1)
    assert cursor.latest_exists_for_cap(CAP_ALERT_V1) is False
    assert cursor.latest_exists_for_cap(UNRELATED_PARALLEL_ALERT) is True
    assert writer.write_evidence(replay(CAP_ALERT_V1)) is None
    assert cursor.latest_exists_for_cap(CAP_ALERT_V1) is False


@pytest.mark.parametrize("commit_order", ["cancel_first", "update_first"])
def test_cross_adapter_cancel_and_update_share_origin_lock(commit_order: str) -> None:
    race_cap_mutations(
        update=CWA_UPDATE_V2,
        cancel=NCDR_CANCEL_REFERENCING_V2,
        commit_order=commit_order,
    )
    assert cursor.latest_exists_for_cap(CWA_UPDATE_V2) is False


def test_cap_key_encoding_distinguishes_sender_and_delimiter_boundaries() -> None:
    assert cap_message_digest(sender="sender|a", identifier="b", sent=CAP_SENT) != (
        cap_message_digest(sender="sender", identifier="a|b", sent=CAP_SENT)
    )


@pytest.mark.parametrize("scope", ["historical", "context", "unspecified", None])
def test_non_current_scope_is_never_upserted_to_official_latest(scope) -> None:
    evidence_id = writer.write_evidence(
        official_flood_report_payload(evidence_scope=scope)
    )
    assert evidence_id is not None  # retained as audit/history/context evidence
    assert cursor.official_latest_inserts == 0
```

Build `central_depth` from the actual v1 normalized WRA IoW shape
(`adapter_key="official.wra_iow.flood_depth"`, stable station/source ID,
`flood_depth_cm` derived from upstream `latestvalue`, point geometry) and
`local_depth` from the Tainan shape
(`adapter_key="local.tainan.flood_sensor"`, `flood_depth_cm` derived from
`WaterDepth`, its stable station/source ID, point geometry within 150 metres).
Use the same observation instant/value but distinct station IDs so the tests
exercise the spatial duplicate rule used by the two sources Task 14 can enable;
do not use the frozen Civil-IoT candidate as the only central fixture.

The Postgres test opens two connections, races the same absent latest key, and asserts one deterministic latest row with no equal-time overwrite. It also races a cross-adapter Update and Cancel in both commit orders. Skip only when `PROMOTION_TEST_DATABASE_URL` is absent during focused developer runs and `OFFICIAL_DB_ACCEPTANCE_REQUIRED` is not `1`; Task 16 supplies both variables, makes missing/unreachable PostGIS fail, and treats every database regression as mandatory.

Run:

```bash
(cd apps/workers && python -m pytest tests/test_promotion_pipeline.py tests/test_promotion_monotonicity_postgres.py -q)
```

Expected: FAIL because current code uses `>=`, has no advisory lock, and marks local duplicates only by weight.

- [ ] **Step 2: Acquire locks in one documented order before duplicate/insert decisions**

Inside the existing transaction, before admin enrichment or accepted evidence insert:

```python
def _lock_realtime_decision(cursor: Any, payload: EvidencePromotionPayload) -> None:
    station_id = _official_realtime_station_id(payload)
    # Warning order is adapter lifecycle, then sorted canonical origin locks,
    # then observation dedupe and latest. Station order starts at dedupe.
    keys: list[str] = []
    if payload.event_type == "flood_warning":
        keys.append(f"official-warning-lifecycle|{payload.adapter_key}")
        keys.extend(sorted(_cap_origin_lock_keys(payload)))
        # A message-level Cancel may validly have no area/station key. It still
        # acquires lifecycle/reference locks and retires exact references.
        if station_id is not None and payload.properties.get("cap_message_type") != "Cancel":
            keys.append(
                "official-realtime-latest|"
                f"{payload.adapter_key}|{payload.event_type}|{station_id}"
            )
    elif station_id is not None and payload.observed_at is not None:
        keys.extend((
        "official-realtime-dedupe|"
        f"{payload.event_type}|{payload.observed_at.astimezone(UTC).isoformat()}",
        "official-realtime-latest|"
        f"{payload.adapter_key}|{payload.event_type}|{station_id}",
        ))
    else:
        return
    for key in keys:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (key,),
        )
```

Every Alert, Update, Cancel, and `no_active_event` retirement for a warning adapter
must take the same adapter lifecycle lock. Update/Cancel then take globally stable
origin locks in sorted digest order. `_cap_origin_lock_keys` returns own origin
for Alert, own origin union every reference for Update, and references only for
Cancel. This makes a cross-adapter Cancel that references an Update serialize on
that Update's own global origin even though their adapter lifecycle locks differ.
This order is identical across all paths. An absent row
cannot be protected by `SELECT ... FOR UPDATE`; advisory locks are mandatory.
After locking, check lifecycle tombstones and exact central/local duplicates,
then read/classify latest, then insert accepted evidence only for `insert`,
`update`, or `historical_only`.

- [ ] **Step 3: Compute fingerprints from real columns and terminally consume non-promotions**

Do not reference a nonexistent `existing.value_fingerprint`. Compute both fingerprints from event type, normalized metric/warning state, station ID, rounded geometry, and UTC `observed_at`.

For `idempotent`, `conflict`, and `duplicate_central`, use only the candidate's
validated `properties["staging_evidence_id"]` to target its staging row:

```sql
UPDATE staging_evidence
SET validation_status = 'rejected', rejection_reason = %s
WHERE id = %s::uuid AND validation_status = 'accepted'
```

Return `None`. This terminal update prevents the accepted candidate from being selected forever.

For central arriving after an exact local duplicate, keep the old local `evidence` audit row but delete its matching `official_realtime_latest` row in the same transaction before inserting/updating central latest. Exact means same event, same timestamp, same normalized value, and identical station ID or a point within 150 metres. Central wins; a non-exact or local-only observation remains.

- [ ] **Step 4: Make promotion count only actual writes**

```python
def promote_accepted_staging(
    writer: EvidencePromotionWriter,
    *,
    limit: int | None = None,
    adapter_keys: tuple[str, ...] | None = None,
) -> PromotionResult:
    evidence_ids: list[str] = []
    # retain existing candidate dedupe
    for candidate in writer.fetch_accepted_staging(limit=limit, adapter_keys=adapter_keys):
        evidence_id = writer.write_evidence(build_evidence_promotion_payload(candidate))
        if evidence_id is not None:
            evidence_ids.append(evidence_id)
    return PromotionResult(promoted=len(evidence_ids), evidence_ids=tuple(evidence_ids))
```

Update all memory writers/fakes to return `str | None`.

- [ ] **Step 5: Make the SQL defense strict**

```sql
WHERE EXCLUDED.observed_at > official_realtime_latest.observed_at
```

Malformed, future-time, illegal-coordinate, unknown-unit, equal-time conflict, failed, or partial input never deletes or overwrites a previous latest row.

Make `_should_upsert_official_realtime_latest` require the validated promoted
property `evidence_scope == "current"` before any latest-key calculation or
write. `historical`, `context`, missing, and malformed scope values may remain
in generic `evidence` when otherwise valid but can never create/update
`official_realtime_latest`. This double-enforces the Task 3 read projection and
prevents the WRA historical flood adapter or flood-potential context from
becoming a present-tense signal.

In the same task, make the four already-existing v1 realtime adapters emit the
scope explicitly in their normalized raw payloads:

```text
official.cwa.rainfall           rainfall       evidence_scope=current
official.wra.water_level        water_level    evidence_scope=current
official.wra_iow.flood_depth    flood_report   evidence_scope=current
local.tainan.flood_sensor       flood_report   evidence_scope=current
```

Add adapter→staging→promotion regressions for all four: the field survives the
strict passthrough and exactly one current row is upserted. Keep the bridge
closed to every adapter/event pair not on this reviewed list. Tasks 11 and 12
must likewise set `current` on their new CAP adapters; Tasks 10 and 13 set only
`historical`/`context`. Do not infer current from `source_type="official"` or
from a missing scope.

- [ ] **Step 6: Preserve only reviewed classification metadata through staging**

Extend `_STAGING_PAYLOAD_PASSTHROUGH_KEYS` with the exact reviewed keys
`evidence_scope`, `location_precision`, `limitations`, `admin_code`, and
`dataset_revision`, plus CAP-only `cap_sender`, `cap_identifier`, `cap_sent`,
`cap_references`, `cap_status`, `cap_message_type`, `active_from`, and
`active_until`. `ingestion_generation_started_at` is injected by the managed
ingestion boundary from its timezone-aware cycle start; it is never accepted
from an adapter payload. Do not copy an arbitrary nested `properties` object. Validate
`evidence_scope` against `current|historical|context`, validate
`location_precision` against the Task 4 public precision enum, retain only a
canonical administrative code, and bound `limitations` to a short list of
non-empty public strings. Existing `source_url`/`resource_url` keys carry the
metadata URL and resolved artifact URL.

The CAP fields are accepted only for `event_type='flood_warning'`: sender and
identifier are non-empty bounded strings, `cap_sent` is timezone-aware RFC3339,
and references are a bounded list of structured objects containing exactly
`sender`, `identifier`, and timezone-aware `sent`. Parse CAP references into
triples before staging and never recover field boundaries with string splitting.
Status is exactly `Actual`, message type is `Alert|Update|Cancel`, and both active
bounds are timezone-aware RFC3339 with `active_from < active_until` for
Alert/Update. Update and Cancel require at least one earlier reference triple;
duplicate triples collapse in canonical order. Invalid lifecycle metadata is
rejected at staging, never silently converted to current.

Create `apps/workers/app/adapters/cap_identity.py` as the single shared owner of
the following collision-safe representation. CWA, NCDR, promotion, and tests
import these helpers rather than duplicating or splitting identity strings:

```python
def canonical_cap_message_json(*, sender: str, identifier: str, sent: datetime) -> str:
    sent_utc = sent.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return json.dumps(
        [sender, identifier, sent_utc],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def cap_message_digest(*, sender: str, identifier: str, sent: datetime) -> str:
    canonical = canonical_cap_message_json(
        sender=sender, identifier=identifier, sent=sent
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def official_event_origin_key(
    *, sender: str, identifier: str, sent: datetime, admin_code: str
) -> str:
    canonical = json.dumps(
        [
            sender,
            identifier,
            sent.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            admin_code,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Before staging deduplication, both CAP adapters must also derive the raw and
normalized `source_id` from this identity so rows do not collide prematurely:

```python
def cap_source_id(
    *, sender: str, identifier: str, sent: datetime, admin_code: str | None,
    message_level: bool = False,
) -> str:
    digest = cap_message_digest(sender=sender, identifier=identifier, sent=sent)
    discriminator = "message" if message_level else f"area:{admin_code}"
    if not message_level and not re.fullmatch(r"\d{8}", admin_code or ""):
        raise ValueError("CAP area source id requires canonical admin code")
    return f"cap:{digest}:{discriminator}"
```

Alert/Update emits one ID per canonical area; a valid area-less Cancel emits
exactly `cap:{digest}:message`. The normalized evidence ID is exactly
`stable_evidence_id(adapter_key, cap_source_id)` using the existing two-argument
helper. `raw_ref` participates only in staging/promotion deduplication and never
in evidence-ID derivation. Neither path may fall back to bare `identifier`.
Tests cover one CAP with multiple areas,
same identifier with different sender or sent, and an area-less Cancel before
promotion, proving none is lost by the staging dictionary or promotion DISTINCT.

Add a staging regression built from a `RawSourceItem` and `NormalizedEvidence`
that proves the five general reviewed fields reach
`StagingEvidenceUpsert.payload`, the
source geometry remains under `location_payload.geometry`, and an unrelated
`private_note` key does not pass through. This is the only generic bridge from
adapter raw payloads to promoted `evidence.properties`; Tasks 10, 11, and 13
must test their adapter-specific payloads against it. CAP regressions separately
prove the eight lifecycle fields and worker-injected generation survive without
any arbitrary XML/body content.

Implement the generation bridge as
`build_staging_batch(result, ingestion_generation_started_at=started_at)` inside
`_summary_from_result`; add the timezone-aware instant to each accepted staged
payload only after adapter normalization, then require it in CAP promotion.
`run_adapter_batch.started_at`, the staging value, evidence property, and latest
quality flag must be the same instant. Add a regression that supplies a forged
adapter payload generation and proves the worker-owned value replaces/rejects
it. Never substitute `fetched_at`, source `cap_sent`, promotion time, or
`finished_at` because those do not order overlapping poll generations.

- [ ] **Step 7: Resolve warning admin geometry without fabricated polygons**

Do not use `admin_area_profiles` or `geocoder_open_data_entries`: the current
geocoder bootstrap stores points and neither relation proves a reviewed polygon.
For a CAP payload with a canonical 8-digit county/city `admin_code` and no source
geometry, reuse the exact active-snapshot integrity CTE from Task 3 and select
exactly one matching `realtime_jurisdiction_boundaries` row only when its parent
snapshot is active, complete for 22 jurisdictions, reviewed, manifest-approved,
and every stored geometry checksum remains valid. Require a non-empty valid
Polygon/MultiPolygon and exact code equality; never fuzzy-match `areaDesc`.
Persist that boundary's actual MultiPolygon and put `ST_PointOnSurface` into
`latest_point_geometry`. Set `location_precision='admin_area'` and retain the
original geocode/area description. A finer code without a separately reviewed
polygon, a missing/ambiguous active snapshot, or a checksum mismatch leaves the
audit evidence unlocated and cannot write latest; never substitute a geocoder
point or hard-coded city centroid. Add unit and real-PostGIS regressions for
Polygon/MultiPolygon resolution, exact-code mismatch, inactive/unreviewed
snapshot, and checksum failure.

For polygon/admin-area evidence, preserve the reviewed area in `evidence.geom` and use only explicit `latest_point_geometry` for `official_realtime_latest.geom`. The Task 3 current reader must join by `evidence_id` and use that area geometry for containment/radius intersection; the centroid exists only to satisfy the point-only latest table and must never be the warning's public applicability test.

Copy the validated evidence precision into
`official_realtime_latest.quality_flags.location_precision` on insert/update,
but make the Task 3 reader prefer the linked
`evidence.properties.location_precision` and fall back to the latest flag only
for legacy rows. Add a conversion regression proving CAP boundary evidence is
publicly `admin_area`, never downgraded to `point` merely because the latest
table stores `ST_PointOnSurface`.

Define the latest natural key for a `flood_warning` area as
`station_id="cap:" + canonical_admin_code + ":" + cap_message_digest(...)`.
Extend `_official_realtime_station_id` to return it only for a validated
eight-digit `admin_code` and complete canonical `(sender, identifier, sent)`
triple; do not hash `areaDesc`, use a centroid, or key by area alone. This permits
independent simultaneous alerts in one administrative area. The adapter key
remains part of the physical latest primary key, so CWA and NCDR retain
independent audit rows; Task 3 dedupes exact cross-feed republications by the
four-field origin key. An unresolved code or incomplete CAP triple may remain
audit evidence but cannot enter `official_realtime_latest`. Task 11 and Task 12 each add an
adapter→staging→promotion regression, while Task 3 proves the linked
checksum-reviewed boundary—not this latest key's point-on-surface—controls
radius applicability.

For an active Alert/Update, persist the eight validated CAP lifecycle properties
on `evidence` and mirror only bounded digests/active bounds plus
`ingestion_generation_started_at` into latest `quality_flags`. Under the shared
lifecycle/origin locks, an Update first retires every physical latest row whose
linked evidence has an exact referenced `(sender, identifier, sent)` triple,
then upserts its own message key atomically; unrelated alerts in the same area
remain. A Cancel is audit evidence but never a latest upsert and retires only
exact reference triples. The lookup may remove CWA and NCDR physical copies of
the same canonical message, but never a different triple. Before any Alert or
Update upsert, query retained lifecycle evidence under its origin lock; a prior
Update/Cancel tombstone referencing that exact triple makes an out-of-order
replay historical-only, so it cannot resurrect a retired warning. A stale
Cancel cannot delete a later or unrelated message. Expired/future Alert/Update
input is terminally rejected before latest. Task 3's `as_of` filter remains the
final defense if cleanup is delayed.

- [ ] **Step 8: Run staging and promotion tests in isolated processes and commit**

Run:

```bash
(cd apps/workers && python -m pytest tests/test_ingestion_job_runner.py tests/test_staging_pipeline.py tests/test_promotion_pipeline.py tests/test_official_adapters.py tests/test_wra_iow_flood_depth_adapter.py tests/test_tainan_flood_sensor_adapter.py -q)
(cd apps/workers && python -m pytest tests/test_promotion_monotonicity_postgres.py -q)
(cd apps/workers && python -m ruff check app/pipelines/staging.py app/pipelines/promotion.py tests/test_staging_pipeline.py tests/test_promotion_pipeline.py tests/test_promotion_monotonicity_postgres.py)
```

Expected: unit tests PASS; Postgres tests PASS when configured or report only the explicit environment skip.

```bash
git add apps/workers/app/jobs/ingestion.py apps/workers/app/pipelines/staging.py apps/workers/app/pipelines/promotion.py apps/workers/app/adapters/cap_identity.py apps/workers/app/adapters/cwa/rainfall.py apps/workers/app/adapters/wra/water_level.py apps/workers/app/adapters/wra_iow/flood_depth.py apps/workers/app/adapters/local_tainan/flood_sensor.py apps/workers/tests/test_ingestion_job_runner.py apps/workers/tests/test_staging_pipeline.py apps/workers/tests/test_promotion_pipeline.py apps/workers/tests/test_promotion_monotonicity_postgres.py apps/workers/tests/test_official_adapters.py apps/workers/tests/test_wra_iow_flood_depth_adapter.py apps/workers/tests/test_tainan_flood_sensor_adapter.py
git commit -m "fix: serialize official latest promotion decisions"
```

---

### Task 9: Add Successful `no_active_event` Semantics and Source-Specific Health

**Files:**

- Modify: `apps/workers/app/adapters/contracts.py`
- Modify: `apps/workers/app/jobs/ingestion.py`
- Modify: `apps/workers/app/jobs/freshness.py`
- Modify: `apps/workers/app/jobs/runtime_managed.py`
- Modify: `apps/workers/app/pipelines/promotion.py`
- Modify: `apps/workers/tests/test_ingestion_job_runner.py`
- Modify: `apps/workers/tests/test_freshness_monitoring.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`
- Modify: `apps/workers/tests/test_promotion_pipeline.py`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/domain/realtime/nearby_coverage.py`
- Modify: `apps/api/tests/test_evidence_repository.py`
- Modify: `apps/api/tests/test_nearby_realtime_coverage.py`

**Interfaces:**

- Appends `no_active_event: bool = False` to `AdapterRunResult`.
- Appends defaulted `event_active_from_min: datetime | None = None` and
  `event_active_until_max: datetime | None = None` to
  `AdapterBatchRunSummary`; they are freshness-only validated warning-window
  fields and do not replace authentic evidence/source timestamps.
- Appends `latest_run_error_code: str | None = None` and `freshness_threshold_seconds: int | None = None` to `RealtimeSourceHealthRow`.
- Treats a recent successful empty warning poll as healthy without pretending it produced a nearby station.
- Retires only that adapter's warning latest rows after a persisted successful `no_active_event` poll while retaining audit evidence.

- [ ] **Step 1: Write RED empty-warning and source-threshold tests**

Because Tasks 10–12 perform production adapter registration later, these Task 9
managed-cycle tests use a test-local `monkeypatch` fixture that adds only the
synthetic CWA warning, NCDR warning, and historical-flood builders/metadata to
`ADAPTER_REGISTRY` and restores it after each test. Do not register unfinished
production adapters in Task 9 or make `enabled_adapter_keys()` accept unknown
keys globally.

```python
def test_valid_empty_warning_poll_is_success_not_skipped() -> None:
    summary = run_adapter_batch(EmptyWarningAdapter(no_active_event=True))
    assert summary.status == "succeeded"
    assert summary.items_fetched == 0
    assert summary.error_code == "no_active_event"


def test_empty_transport_or_parse_failure_is_not_no_active_event() -> None:
    summary = run_adapter_batch(FailingWarningAdapter())
    assert summary.status == "failed"
    assert summary.error_code != "no_active_event"


def test_recent_no_active_warning_poll_is_healthy_context() -> None:
    source = build_nearby_source_health(
        (health_row(
            adapter_key="official.cwa.heavy_rain_warning",
            latest_run_status="succeeded",
            latest_run_error_code="no_active_event",
            latest_run_at=NOW - timedelta(minutes=2),
            freshness_threshold_seconds=600,
        ),),
        evaluated_at=NOW,
    )[0]
    assert source.health_status == "healthy"
    assert source.reason_code == "operational"


@pytest.mark.parametrize("adapter_key", [
    "official.cwa.heavy_rain_warning", "official.ncdr.cap",
])
def test_managed_valid_empty_warning_is_success_without_source_timestamp(
    adapter_key: str,
) -> None:
    result = run_managed_empty_warning(adapter_key, no_active_event=True)
    assert result.status == "succeeded"
    assert len(result.summaries) == 1
    assert result.summaries[0].error_code == "no_active_event"
    assert result.summaries[0].source_timestamp_max is None


def test_plain_empty_or_failed_warning_never_uses_no_active_freshness_branch() -> None:
    assert run_managed_empty_warning(
        "official.cwa.heavy_rain_warning", no_active_event=False
    ).status != "succeeded"
    assert run_managed_failed_warning().error_code != "no_active_event"


@pytest.mark.parametrize("adapter_key", [
    "official.cwa.heavy_rain_warning", "official.ncdr.cap",
])
def test_active_long_lived_warning_uses_validated_event_window_not_sent_age(
    adapter_key: str,
) -> None:
    result = run_managed_warning(
        adapter_key,
        sent_at=NOW - timedelta(hours=12),
        active_from=NOW - timedelta(hours=12),
        active_until=NOW + timedelta(hours=3),
    )
    assert result.status == "succeeded"
    assert len(result.summaries) == 1
    assert result.summaries[0].event_active_from_min == NOW - timedelta(hours=12)
    assert result.summaries[0].event_active_until_max == NOW + timedelta(hours=3)


def test_historical_flood_uses_background_fetch_freshness_not_event_age() -> None:
    result = run_managed_historical_flood(
        event_observed_at=NOW - timedelta(days=3650), fetched_at=NOW
    )
    assert result.status == "succeeded"
    assert result.summaries[0].source_timestamp_max == NOW - timedelta(days=3650)


def test_managed_no_active_poll_retires_only_its_warning_latest_rows() -> None:
    result = run_managed_runtime_ingestion_cycle(
        {"official.cwa.heavy_rain_warning": EMPTY_CWA_ADAPTER},
        settings=CWA_ONLY_SETTINGS,
        promotion_writer=writer,
        staging_writer=staging_writer,
        run_writer=run_writer,
        promote=True,
    )
    assert result.status == "succeeded"
    assert writer.retired_no_active == ["official.cwa.heavy_rain_warning"]
    assert cursor.latest_exists(CWA_WARNING_ID) is False
    assert cursor.latest_exists(NCDR_WARNING_ID) is True
    assert cursor.evidence_exists(CWA_WARNING_ID) is True


@pytest.mark.parametrize("commit_order", ["old_empty_first", "new_alert_first"])
def test_older_empty_generation_never_retires_newer_alert(commit_order: str) -> None:
    race_warning_mutations(
        empty_generation=NOW,
        alert_generation=NOW + timedelta(seconds=1),
        commit_order=commit_order,
    )
    assert cursor.latest_exists(NEW_CWA_WARNING_ID) is True


def test_newer_empty_generation_retires_older_alert_only() -> None:
    writer.write_evidence(cap_payload_with_generation(CWA_ALERT, NOW))
    writer.retire_warning_latest_for_no_active_event(
        adapter_key="official.cwa.heavy_rain_warning",
        generation_started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
    )
    assert cursor.latest_exists(CWA_WARNING_ID) is False
    assert cursor.latest_exists(NCDR_WARNING_ID) is True


@pytest.mark.parametrize("commit_order", ["new_empty_first", "old_alert_first"])
def test_newer_empty_generation_blocks_older_alert_resurrection(commit_order: str) -> None:
    race_warning_mutations(
        empty_generation=NOW + timedelta(seconds=1),
        alert_generation=NOW,
        commit_order=commit_order,
    )
    assert cursor.latest_exists(OLD_CWA_WARNING_ID) is False
```

- [ ] **Step 2: Add defaulted result/row fields and persist the run marker**

When `result.fetched` is empty and `result.no_active_event` is true,
`_summary_from_result` returns succeeded with `error_code="no_active_event"`.
It does not build an empty staging snapshot. All other empty results retain
current skipped/failure semantics.

Update `freshness.py` and its caller explicitly: only the reviewed CWA/NCDR
warning adapter keys with `result.no_active_event is True`, zero fetched rows,
and no adapter errors bypass timestamp freshness and remain succeeded with
`source_timestamp_max=None`. This is an event-cadence operational marker, not a
fabricated observation time. A plain empty result, parser/transport failure,
station adapter, or any result containing errors follows the existing
freshness path and cannot enter this branch. Test both reviewed warning keys
through the real managed cycle, not only `_summary_from_result`.

For non-empty CWA/NCDR warnings, compute the two new summary fields only from
validated Alert/Update `active_from`/`active_until` windows; preserve the real
`source_timestamp_min/max` derived from CAP `sent`/observed times. Pass the
explicit window to freshness evaluation. A warning whose sent time is old
remains operational while `event_active_from_min <= checked_at <
event_active_until_max`; an expired/future/malformed window is never rescued.
Generalize the current NCDR-only helper/branch to the exact reviewed warning-key
set and do not overload or fabricate `source_timestamp_max`.

Add both `official.wra.historical_flood` and
`official.flood_potential.geojson` to `_cadence_for_adapter`'s exact
static/background set. For a successful validated fetch their operational
freshness uses `summary.finished_at`/artifact revision, not old event/scenario
time; preserve authentic `source_timestamp_min/max` for history scoring and
audit. Plain realtime station adapters retain timestamp freshness.

Append
`EvidencePromotionWriter.retire_warning_latest_for_no_active_event(*,
adapter_key: str, generation_started_at: datetime, completed_at: datetime) -> int`.
Its Postgres implementation accepts only the reviewed CWA/NCDR event adapter
keys and takes exactly the same
`official-warning-lifecycle|{adapter_key}` transaction advisory lock as Task 8
Alert/Update/Cancel promotion. Under that lock, delete only that adapter's
`event_type='flood_warning'` latest rows whose validated
`quality_flags.ingestion_generation_started_at <= generation_started_at`; a
missing/malformed row generation fails closed and is not bulk-deleted. Commit
once and never delete linked `evidence`. In
`run_managed_runtime_ingestion_cycle`, call it only after the successful run
summary with `error_code='no_active_event'` has been persisted and only when
`promote=True`; a retirement exception returns a failed managed result without
affecting later Task 14 sources. Never invoke it for an empty failure/skipped
run or a station adapter. The generation is the cycle's captured `started_at`,
not completion time, so an older slow poll cannot erase a newer Alert that
committed first. Every warning latest upsert mirrors that same cycle generation.
Under the same lifecycle lock, Alert/Update promotion must query the persisted
maximum successful `no_active_event` `ingestion_jobs.started_at` for its adapter.
When `candidate.ingestion_generation_started_at <= max_empty_generation`, retain
audit evidence but terminalize it as historical-only and never upsert latest.
This prevents a slow older Alert from resurrecting after a newer empty poll has
already committed. The two-connection Postgres tests cover both commit orders in
both directions: older empty/newer Alert always leaves the Alert; newer
empty/older Alert never leaves the Alert.

Select `ingestion_jobs.error_code AS latest_run_error_code` and:

```sql
NULLIF(data_sources.metadata->>'freshness_threshold_seconds', '')::integer
    AS freshness_threshold_seconds
```

in `_query_realtime_source_health_rows`; update mapping and positional row conversion.

- [ ] **Step 3: Use source-specific health thresholds**

For station sources, use `freshness_threshold_seconds` from catalog, with the existing 600-second fallback and a degraded window of three times the fresh threshold. For event sources (`flood_warning`, `status_only`), a recent successful `no_active_event` run is operational even when no latest observation exists. It does not create query-local coverage; the low gate still requires local rainfall plus hydrology.

- [ ] **Step 4: Run API and worker tests in separate processes**

```bash
(cd apps/workers && python -m pytest tests/test_ingestion_job_runner.py tests/test_freshness_monitoring.py tests/test_runtime_managed_ingestion.py tests/test_promotion_pipeline.py tests/test_promotion_monotonicity_postgres.py -q)
(cd apps/api && python -m pytest tests/test_evidence_repository.py tests/test_nearby_realtime_coverage.py tests/test_assessment_repository.py -q)
```

Expected: PASS.

- [ ] **Step 5: Commit health semantics**

```bash
git add apps/workers/app/adapters/contracts.py apps/workers/app/jobs/ingestion.py apps/workers/app/jobs/freshness.py apps/workers/app/jobs/runtime_managed.py apps/workers/app/pipelines/promotion.py apps/workers/tests/test_ingestion_job_runner.py apps/workers/tests/test_freshness_monitoring.py apps/workers/tests/test_runtime_managed_ingestion.py apps/workers/tests/test_promotion_pipeline.py apps/workers/tests/test_promotion_monotonicity_postgres.py apps/api/app/domain/evidence/repository.py apps/api/app/domain/realtime/nearby_coverage.py apps/api/tests/test_evidence_repository.py apps/api/tests/test_nearby_realtime_coverage.py
git commit -m "feat: distinguish healthy empty warning polls"
```

### Task 10: Implement the WRA historical-flood adapter as metadata -> KML

**Files:**

- Create: `apps/workers/app/adapters/wra/historical_flood.py`
- Create: `apps/workers/tests/fixtures/wra_historical_flood_index.json`
- Create: `apps/workers/tests/fixtures/wra_historical_flood_sample.kml`
- Create: `apps/workers/tests/test_wra_historical_flood_adapter.py`
- Modify: `apps/workers/app/adapters/wra/__init__.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/config.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Reference: `apps/workers/app/pipelines/staging.py`
- Reference: `apps/workers/tests/test_staging_pipeline.py`

**Pinned source contract:**

```python
WRA_HISTORICAL_INDEX_URL = (
    "https://opendata.wra.gov.tw/api/v2/"
    "72d7aee9-e29b-49a2-bd0b-54acc8e3b75c?format=JSON&sort=_importdate+asc"
)

FetchJson = Callable[[str, int], object]
FetchText = Callable[[str, int], str]

class WraHistoricalFloodAdapter:
    metadata: AdapterMetadata
    def fetch(self) -> tuple[RawSourceItem, ...]: ...
    def normalize(self, raw: RawSourceItem) -> NormalizedEvidence | None: ...
    def run(self) -> AdapterRunResult: ...
```

The metadata JSON is an index, not evidence. `fetch()` must select the current KML
record from `sourceurl`, require `https` and the `opendata.wra.gov.tw` host, fetch
the KML, and return one `RawSourceItem` per valid `Placemark`. Never treat a
metadata row, filename, or download URL as a flood point.

- [ ] **Step 1: Write RED metadata/KML contract tests**

Cover the two requests in order, Polygon and Point placemarks, Taiwan bounds,
stable source IDs, malformed XML, empty KML, duplicate placemarks, a non-HTTPS or
off-domain `sourceurl`, and a metadata response with no KML record. Both fetchers
are injected; tests never contact the network.

```python
def test_fetch_resolves_metadata_then_reads_kml() -> None:
    adapter = WraHistoricalFloodAdapter(fetch_json=fake_index, fetch_text=fake_kml)
    rows = adapter.fetch()
    assert requested_urls == [WRA_HISTORICAL_INDEX_URL, APPROVED_KML_URL]
    assert rows[0].payload["evidence_scope"] == "historical"


def test_normalize_marks_history_and_preserves_source_geometry() -> None:
    raw = adapter.fetch()[0]
    item = adapter.normalize(raw)
    assert item is not None
    assert item.event_type == EventType.FLOOD_REPORT
    assert raw.payload["evidence_scope"] == "historical"
    assert raw.payload["location_precision"] in {"point", "polygon"}
    assert raw.payload["geometry"]["type"] in {"Point", "Polygon", "MultiPolygon"}

    staged = build_staging_batch(
        adapter.run(), ingestion_generation_started_at=RUN_STARTED_AT
    ).accepted[0]
    assert staged.payload["evidence_scope"] == "historical"
    assert staged.payload["location_precision"] in {"point", "polygon"}
    assert staged.payload["location_payload"]["geometry"] == raw.payload["geometry"]
```

- [ ] **Step 2: Implement the complete adapter and exports**

Use `defusedxml` for parsing. Preserve source geometry; reject invalid or
out-of-Taiwan coordinates instead of substituting a centroid. Put the dataset
revision, metadata URL, resolved KML URL, historical observation limitations,
and location precision in each `RawSourceItem.payload`; Task 8's reviewed staging
allowlist then carries them into promoted `evidence.properties`. A normalized
row must have a parseable source-provided historical event timestamp. Reject a
placemark whose event timestamp is absent or invalid; never substitute
`fetched_at`. Retrieval time remains `ingested_at`, never event time.

- [ ] **Step 3: Wire disabled-by-default configuration**

Add the independent settings/gates
`SOURCE_WRA_HISTORICAL_FLOOD_ENABLED`,
`SOURCE_WRA_HISTORICAL_FLOOD_API_ENABLED`,
`WRA_HISTORICAL_FLOOD_INDEX_URL`, and
`WRA_HISTORICAL_FLOOD_TIMEOUT_SECONDS`. Register
`official.wra.historical_flood`; do not reuse the water-level gate. Update the
checked-in source catalog with the metadata URL and the Government Open Data
License attribution. Every new gate is false in `.env.example` and by default.

- [ ] **Step 4: Run focused worker tests**

```bash
(cd apps/workers && python -m pytest tests/test_wra_historical_flood_adapter.py tests/test_adapter_registry_config.py tests/test_official_source_catalog.py -q)
(cd apps/workers && python -m ruff check app/adapters/wra tests/test_wra_historical_flood_adapter.py)
```

Expected: PASS.

- [ ] **Step 5: Commit the WRA adapter**

```bash
git add apps/workers/app/adapters/wra/historical_flood.py apps/workers/app/adapters/wra/__init__.py apps/workers/app/adapters/registry.py apps/workers/app/jobs/runtime.py apps/workers/app/config.py apps/workers/tests/fixtures/wra_historical_flood_index.json apps/workers/tests/fixtures/wra_historical_flood_sample.kml apps/workers/tests/test_wra_historical_flood_adapter.py apps/workers/tests/test_adapter_registry_config.py apps/workers/tests/test_official_source_catalog.py .env.example docs/data-sources/official/official-source-catalog.yaml
git commit -m "feat: ingest WRA historical flood KML"
```

### Task 11: Implement CWA heavy-rain warnings from CAP

**Files:**

- Create: `apps/workers/app/adapters/cwa/heavy_rain_warning.py`
- Create: `apps/workers/tests/fixtures/cwa_heavy_rain_warning_cap.xml`
- Create: `apps/workers/tests/test_cwa_heavy_rain_warning_adapter.py`
- Modify: `apps/workers/app/adapters/cwa/__init__.py`
- Modify: `apps/workers/app/adapters/registry.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/config.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Reference: `apps/workers/app/pipelines/staging.py`
- Reference: `apps/workers/tests/test_staging_pipeline.py`
- Reference: `apps/workers/app/pipelines/promotion.py`
- Reference: `apps/workers/tests/test_promotion_pipeline.py`

**Pinned source contract:**

```python
CWA_HEAVY_RAIN_CAP_URL = (
    "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/W-C0033-003?format=CAP"
)
CwaFetchCap = Callable[[str, str, int], str]

class CwaHeavyRainWarningAdapter:
    metadata: AdapterMetadata
    def fetch(self) -> tuple[RawSourceItem, ...]: ...
    def normalize(self, raw: RawSourceItem) -> NormalizedEvidence | None: ...
    def run(self) -> AdapterRunResult: ...
```

- [ ] **Step 1: Write RED CAP lifecycle and jurisdiction tests**

Pin `status=Actual`, `msgType in {Alert, Update}`, `scope=Public`, effective/onset
and expires handling, `areaDesc`, Taiwan CAP geocodes, multiple `area` elements,
Cancel/expired/future alerts, malformed CAP, and authorization redaction. A valid
CAP response with no active warning returns `AdapterRunResult(no_active_event=True)`;
transport, authentication, and schema errors do not.

Every active area carries bounded `cap_sender`, `cap_identifier`, `cap_sent`,
structured `cap_references`, `cap_status`, `cap_message_type`, `active_from`, and
`active_until` through raw, staging, evidence, and latest flags. Parse each CAP
reference as the exact `(sender, identifier, sent)` triple. Add
Alert→Update→Cancel promotion regressions proving Update atomically retires its
referenced triple and inserts itself, Cancel retires only the exact referenced
triple, parallel same-area alerts survive, and all audit rows remain. Include a
valid message-level Cancel with no `area`; it still produces one lifecycle
tombstone and retires references under origin locks. Add expired/as-of and
Cancel-before-replayed-Alert coverage.

Assert `RawSourceItem.source_id` and `NormalizedEvidence.source_id` use Task 8's
`cap_source_id`: message digest plus `area:{admin_code}` for each active area and
the fixed `message` discriminator for an area-less Cancel. A multi-area CAP
produces distinct staged rows, while identical bare identifiers with different
sender or sent instants never collide before lifecycle handling.

```python
def test_active_cap_area_normalizes_without_a_fake_polygon() -> None:
    raw = adapter.fetch()[0]
    item = adapter.normalize(raw)
    assert item is not None
    assert item.event_type == EventType.FLOOD_WARNING
    assert raw.payload["location_precision"] == "admin_area"
    assert raw.payload["admin_code"] == "67000000"
    assert raw.payload.get("geometry") is None

    staged = build_staging_batch(
        adapter.run(), ingestion_generation_started_at=RUN_STARTED_AT
    ).accepted[0]
    assert staged.payload["location_precision"] == "admin_area"
    assert staged.payload["admin_code"] == "67000000"
    assert "location_payload" not in staged.payload

    promoted = promote_fixture(staged, reviewed_boundary=TAINAN_POLYGON)
    assert promoted.latest_station_id == (
        "cap:67000000:" + cap_message_digest(
            sender=staged.payload["cap_sender"],
            identifier=staged.payload["cap_identifier"],
            sent=parse_rfc3339(staged.payload["cap_sent"]),
        )
    )
    assert promoted.evidence_geometry == TAINAN_POLYGON
```

- [ ] **Step 2: Implement authenticated CAP parsing**

Pass authorization as a separate argument to `CwaFetchCap`; never concatenate or
log it. Parse XML with `defusedxml`. Emit one normalized warning per CAP area.
Keep an area without usable geometry as `geometry=None` plus canonical
`admin_code`; Task 8 promotion resolves that code against the reviewed server-side
boundary snapshot. Never invent a city centroid or polygon.

Parse Update and Cancel messages into lifecycle evidence with validated
reference triples instead of treating Cancel as active or silently dropping it.
A message-level Cancel without an area emits one `geometry=None`,
`admin_code=None` tombstone rather than disappearing. Alert and Update require
valid effective/onset and expires bounds. The adapter never decides scoring
dedupe; it preserves the canonical sender, identifier, and sent instant needed
by Task 3 to recognize a later NCDR republication of the exact same message.

- [ ] **Step 3: Register independent, disabled gates and the correct license**

Add `official.cwa.heavy_rain_warning`,
`SOURCE_CWA_HEAVY_RAIN_WARNING_ENABLED`,
`SOURCE_CWA_HEAVY_RAIN_WARNING_API_ENABLED`,
`CWA_HEAVY_RAIN_WARNING_CAP_URL`, and
`CWA_HEAVY_RAIN_WARNING_TIMEOUT_SECONDS`. Reuse `CWA_API_AUTHORIZATION` only as
the credential. The catalog license must be `中央氣象署開放資料平臺使用規範`
with `https://opendata.cwa.gov.tw/about/rules`; do not label this source with the
generic Government Open Data License. Keep both gates false by default.

- [ ] **Step 4: Run focused worker tests**

```bash
(cd apps/workers && python -m pytest tests/test_cwa_heavy_rain_warning_adapter.py tests/test_adapter_registry_config.py tests/test_official_source_catalog.py tests/test_ingestion_job_runner.py -q)
(cd apps/workers && python -m ruff check app/adapters/cwa tests/test_cwa_heavy_rain_warning_adapter.py)
```

Expected: PASS.

- [ ] **Step 5: Commit CWA CAP support**

```bash
git add apps/workers/app/adapters/cwa/heavy_rain_warning.py apps/workers/app/adapters/cwa/__init__.py apps/workers/app/adapters/registry.py apps/workers/app/jobs/runtime.py apps/workers/app/config.py apps/workers/tests/fixtures/cwa_heavy_rain_warning_cap.xml apps/workers/tests/test_cwa_heavy_rain_warning_adapter.py apps/workers/tests/test_adapter_registry_config.py apps/workers/tests/test_official_source_catalog.py .env.example docs/data-sources/official/official-source-catalog.yaml
git commit -m "feat: ingest CWA CAP heavy rain warnings"
```

### Task 12: Replace the NCDR Atom runtime path with datastore -> dump CAP

**Files:**

- Modify: `apps/workers/app/adapters/ncdr/cap_alerts.py`
- Modify: `apps/workers/app/adapters/ncdr/__init__.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `apps/workers/app/config.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_ncdr_cap_adapter.py`
- Create: `apps/workers/tests/fixtures/ncdr_datastore_active.json`
- Create: `apps/workers/tests/fixtures/ncdr_dump_flood_cap.xml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Reference: `apps/workers/app/pipelines/staging.py`
- Reference: `apps/workers/app/pipelines/promotion.py`
- Reference: `apps/workers/tests/test_promotion_pipeline.py`

**Pinned runtime contract:**

```python
NCDR_DATASTORE_API_URL = "https://alerts.ncdr.nat.gov.tw/api/datastore"
NCDR_DUMP_API_URL = "https://alerts.ncdr.nat.gov.tw/api/dump"

NcdrFetchJson = Callable[[str, Mapping[str, str], int], object]
NcdrFetchText = Callable[[str, Mapping[str, str], int], str]

class NcdrCapAlertAdapter:
    metadata: AdapterMetadata
    def fetch(self) -> tuple[RawSourceItem, ...]: ...
    def normalize(self, raw: RawSourceItem) -> NormalizedEvidence | None: ...
    def run(self) -> AdapterRunResult: ...
```

- [ ] **Step 1: Rewrite tests RED around the documented two-stage API**

Assert that `fetch()` calls `/api/datastore` with the API key supplied separately,
extracts a bounded and de-duplicated list of CAP IDs, then calls `/api/dump` once
per selected ID. Cover flood/high-water classification after CAP parsing,
multiple areas, inactive/cancelled alerts, malformed datastore JSON, malformed
CAP, a dump failure, and secret-free errors. A valid empty datastore is
`no_active_event=True`; a failed request is not.

The dump CAP fixtures assert the same eight bounded lifecycle fields and
structured reference triples as Task 11. Add two order-independent read
regressions: CWA then NCDR and NCDR then CWA for the exact same
sender/identifier/sent/admin identity both yield one current scoring item with
direct CWA preferred, while a different sender, identifier, sent instant, or
admin remains an independent warning. Both physical evidence/latest audit rows
remain. Add a cross-feed Update/Cancel race in both commit orders.

Pin the injected calls as datastore params `{"key": api_key}` and dump params
`{"key": api_key, "capid": cap_id}`. Tests inspect the params object but any
failure rendering must replace the `key` value with `[REDACTED]`.

- [ ] **Step 2: Implement datastore -> dump while retaining parser regression coverage**

Keep `parse_ncdr_cap_payload()` and the existing Atom fixture test as a parser
regression only. The default runtime builder must never call the Atom endpoint.
Normalize CAP area geocodes exactly as in Task 11: canonical `admin_code`,
`location_precision="admin_area"`, and no hard-coded centroid. Add a finite
`NCDR_MAX_CAP_IDS_PER_RUN` setting and deterministic CAP-ID ordering.

Preserve CAP sender/identifier/sent/reference triples/status/message type/active
bounds exactly as Task 11 and emit message-level Cancel tombstones through
staging/promotion. Do not invent an identity from NCDR `capid`; only the CAP
document's canonical `(sender, identifier, sent)` triple is the cross-feed
origin, and `capid` remains transport metadata only.

Use the same Task 8 `cap_source_id` algorithm before staging. The NCDR adapter
must not retain its current bare-identifier source ID: multi-area messages,
same-identifier/different-sender messages, same-identifier/different-sent
messages, and message-level Cancel tombstones each receive distinct deterministic
source IDs and evidence derivations.

Extend the fixture test through `build_staging_batch(
adapter.run(), ingestion_generation_started_at=RUN_STARTED_AT)` and Task 8
promotion. It
must produce `station_id="cap:67000000:" + cap_message_digest(...)`, persist the reviewed area geometry
on `evidence`, and use only its point-on-surface in the point-only latest row.
The Task 3 query regression then proves a radius intersecting the area includes
the warning even when that point is outside the selected radius.

- [ ] **Step 3: Replace configuration without compatibility ambiguity**

Add `NCDR_ALERTS_API_KEY`, `NCDR_DATASTORE_API_URL`, `NCDR_DUMP_API_URL`, and
`NCDR_MAX_CAP_IDS_PER_RUN`. Remove `NCDR_CAP_API_URL` from the default runtime
path and `.env.example`; if parsing it remains temporarily necessary for a
deprecation window, it must be explicitly named legacy and may not select Atom.
Keep `SOURCE_NCDR_CAP_ENABLED=false` and
`SOURCE_NCDR_CAP_API_ENABLED=false` by default.

- [ ] **Step 4: Run focused worker tests**

```bash
(cd apps/workers && python -m pytest tests/test_ncdr_cap_adapter.py tests/test_adapter_registry_config.py tests/test_official_source_catalog.py tests/test_ingestion_job_runner.py -q)
(cd apps/workers && python -m ruff check app/adapters/ncdr tests/test_ncdr_cap_adapter.py)
```

Expected: PASS.

- [ ] **Step 5: Commit the NCDR transport correction**

```bash
git add apps/workers/app/adapters/ncdr/cap_alerts.py apps/workers/app/adapters/ncdr/__init__.py apps/workers/app/jobs/runtime.py apps/workers/app/config.py apps/workers/tests/test_ncdr_cap_adapter.py apps/workers/tests/fixtures/ncdr_datastore_active.json apps/workers/tests/fixtures/ncdr_dump_flood_cap.xml apps/workers/tests/test_adapter_registry_config.py apps/workers/tests/test_official_source_catalog.py .env.example docs/data-sources/official/official-source-catalog.yaml
git commit -m "fix: ingest NCDR alerts through datastore and dump"
```

### Task 13: Produce and enforce the flood-potential production manifest

**Files:**

- Create: `docs/runbooks/flood-potential-import.production.yaml`
- Modify: `docs/runbooks/flood-potential-import.example.yaml`
- Modify: `infra/scripts/validate_flood_potential_import.py`
- Modify: `infra/scripts/import_flood_potential_layer.py`
- Modify: `tests/test_flood_potential_import_validator.py`
- Modify: `apps/workers/app/adapters/flood_potential/importer.py`
- Modify: `apps/workers/app/config.py`
- Modify: `apps/workers/app/jobs/runtime.py`
- Modify: `.env.example`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`
- Modify: `apps/workers/tests/test_adapter_registry_config.py`
- Create: `apps/workers/tests/test_flood_potential_production_manifest.py`
- Modify: `apps/api/app/domain/evidence/repository.py`
- Modify: `apps/api/app/domain/assessment/models.py`
- Modify: `apps/api/app/domain/assessment/repository.py`
- Modify: `apps/api/app/api/services/assessment.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `apps/api/tests/test_assessment_repository.py`
- Modify: `apps/api/tests/test_assessment_service.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `packages/contracts/fixtures/risk-assess-response.json`
- Modify: `docs/api/openapi.yaml`
- Reference: `apps/workers/app/pipelines/staging.py`
- Reference: `apps/workers/tests/test_staging_pipeline.py`

**Pinned discovery contract:**

Use WRA dataset `25766` metadata, not a guessed GeoJSON endpoint:

```text
https://opendata.wra.gov.tw/api/v2/de9578fe-b014-4f00-b8ca-e6280324f08d?format=JSON&sort=_importdate+asc
```

The metadata index publishes a set of separate SHP/7z resources by covered
county/city, not one nationwide archive. The production manifest must therefore
pin the complete resource set advertised for one selected scenario. V1 uses the
same scenario in every resource, merged layer, API copy, and catalog metadata;
one archive can never satisfy nationwide acceptance.

- [ ] **Step 1: Write RED production-evidence tests**

Extend `tests/test_flood_potential_import_validator.py` so production validation
rejects an example/template manifest, a metadata-page URL masquerading as the
package, a missing/duplicate metadata-advertised resource, mixed scenarios, a
zero or missing per-resource feature count, a checksum not computed from each
downloaded archive, an unknown per-resource source/output CRS, a scenario
missing duration or rainfall depth, overlapping or unmapped coverage, and a
merged output whose checksum/count is absent. A manifest with only one valid
county archive must fail. The existing synthetic
`_production_complete_manifest()` remains unit data only and must not be
accepted as the repository's production artifact.

Pin this production shape: metadata index URL/retrieval time/SHA-256; selected
scenario; sorted `expected_resource_ids`; one sorted resource record per ID with
official URL, archive filename/SHA-256, archive members, source CRS, covered
jurisdiction codes, and measured input/output feature counts; sorted covered and
known-gap jurisdiction codes; and one merged output path/CRS/SHA-256/feature
count. The covered plus known-gap jurisdiction sets must equal the 22 canonical
`realtime_jurisdictions`, without overlap. Every known gap requires a public
reason tied to the official index; it cannot be silently treated as low risk or
no flood potential.

Add a repository-level test that loads
`docs/runbooks/flood-potential-import.production.yaml` and calls
`validate_manifest_file(path, require_production_complete=True)`.

Add an adapter-to-staging regression proving each feature exposes top-level
`evidence_scope="context"`, `location_precision="polygon"`, and bounded public
`limitations` derived from the validated manifest. The GeoJSON's arbitrary
nested `properties` object must not be copied wholesale. After
`build_staging_batch(adapter.run())`, those reviewed fields and
`location_payload.geometry` must be present so promotion persists them and
`_historical_only` can classify the row.

Add repository/service tests for one covered and one known-gap jurisdiction.
The active reviewed boundary determines the jurisdiction. The covered case may
load context features; the known-gap case appends a public data-status message
such as `官方淹水潛勢圖資未涵蓋此縣市` while leaving realtime and other historical
evidence unchanged. Read coverage from the reviewed flood-potential source
metadata returned within the existing jurisdiction read boundary; do not trust
client administrative input or infer coverage from an empty spatial result.

Pin the typed flow before implementing those tests:

```python
FloodPotentialCoverageState = Literal["covered", "known_gap", "unavailable"]

@dataclass(frozen=True)
class RealtimeJurisdictionContext:
    # existing fields first
    flood_potential_coverage_state: FloodPotentialCoverageState = "unavailable"
    flood_potential_coverage_reason: str | None = None

@dataclass(frozen=True)
class AssessmentData:
    # existing fields first
    flood_potential_coverage_state: FloodPotentialCoverageState = "unavailable"
    flood_potential_coverage_reason: str | None = None

class FloodPotentialCoverageStatus(ContractModel):
    state: FloodPotentialCoverageState = "unavailable"
    reason: str | None = None

class DataStatus(ContractModel):
    sources: list[PublicSourceStatus] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    flood_potential: FloodPotentialCoverageStatus = Field(
        default_factory=FloodPotentialCoverageStatus
    )
```

`query_realtime_jurisdiction_context` is the sole SQL projection. It returns
`covered` or `known_gap` only when the exact
`official.flood_potential.geojson` catalog row is enabled and its metadata says
`production_complete=true`, carries the validated production manifest SHA-256
and review revision, and partitions the exact resolved jurisdiction code into
one of the disjoint reviewed `covered_jurisdictions` or
`known_gap_jurisdictions` arrays. A gap must have that code's bounded public
reason. Disabled/missing source, invalid manifest metadata, overlap, absent code,
or jurisdiction-read failure returns `unavailable` with no guessed reason.
`PostgresAssessmentRepository.load` copies those two fields verbatim to
`AssessmentData`; `AssessmentService` maps them to `data_status.flood_potential`
and appends the reviewed gap reason to `data_status.missing` only for
`known_gap`. Client admin input and empty spatial results never select state.

Exact assertions are:

```python
assert covered.flood_potential_coverage_state == "covered"
assert covered_response.data_status.flood_potential.state == "covered"
assert gap.flood_potential_coverage_state == "known_gap"
assert gap_response.data_status.flood_potential == FloodPotentialCoverageStatus(
    state="known_gap", reason="官方淹水潛勢圖資未涵蓋此縣市"
)
assert "官方淹水潛勢圖資未涵蓋此縣市" in gap_response.data_status.missing
assert disabled_response.data_status.flood_potential.state == "unavailable"
```

Update the response fixture, OpenAPI, and constructor-compatibility tests in this
task; all new fields are defaulted so earlier Task 4 remains independently green.

- [ ] **Step 2: Materialize facts from the official artifact**

Extend the importer with `--source-archive-dir DIR` and `--write-evidence PATH`.
It must snapshot and hash the metadata response, derive the complete resource
ID/URL set for the selected scenario, require exactly one local archive per
resource ID, compute every SHA-256 from those bytes, inspect every archive's
members, use `ogrinfo`/`ogr2ogr` to discover/transform each CRS, map features to
reviewed jurisdiction codes, merge the transformed outputs deterministically,
and measure per-resource plus merged feature counts/checksums. It must not accept
operator-provided checksum, CRS, resource-list, or feature-count overrides.

Run the real import in a clean operator-controlled artifact directory (never
commit the large SHP/7z or generated layer):

```bash
python infra/scripts/import_flood_potential_layer.py docs/runbooks/flood-potential-import.production.yaml --source-archive-dir "$FLOOD_POTENTIAL_SOURCE_ARCHIVE_DIR" --write-evidence docs/runbooks/flood-potential-import.production.yaml --require-tools
python infra/scripts/validate_flood_potential_import.py docs/runbooks/flood-potential-import.production.yaml --production-complete
```

The first command may initially consume a skeleton with metadata/scenario fields,
but it may set `production_complete: true` only after the metadata resource set,
all archive checksums, retrieval time, exact shared scenario, every source/output
CRS, per-resource coverage/counts, explicit official gaps, and merged output
reference/checksum/non-zero count are measured. Never copy the fake checksum,
internal owner, `private-ops://`, or CDN values from a test fixture.

- [ ] **Step 3: Gate runtime use on the validated production manifest**

Add `FLOOD_POTENTIAL_PRODUCTION_MANIFEST_PATH` and require it when
`SOURCE_FLOOD_POTENTIAL_ENABLED=true` or
`SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED=true`. The builder verifies
`production_complete`, complete resource coverage, one shared scenario, and the
local merged GeoJSON path/checksum before constructing
`FloodPotentialGeoJsonAdapter`. The offline validator must also recheck every
archive when the archive directory is supplied. A URL or single county archive
is insufficient. Keep both gates false in defaults and `.env.example`.
Preserve the exact supported `evidence_scope="context"` value and a public
planning/reference limitation so this layer can never enter the current-official
scorer. Do not invent a separate `planning` scope that the API reader does not
recognize.

- [ ] **Step 4: Run validator and worker tests**

```bash
python -m pytest tests/test_flood_potential_import_validator.py -q
python infra/scripts/validate_flood_potential_import.py docs/runbooks/flood-potential-import.production.yaml --production-complete
(cd apps/workers && python -m pytest tests/test_flood_potential_production_manifest.py tests/test_adapter_registry_config.py -q)
(cd apps/api && python -m pytest tests/test_assessment_repository.py tests/test_assessment_service.py tests/test_public_contract.py -q)
```

Expected: PASS using measured production evidence. If the official artifact or
conversion toolchain is unavailable, stop here with both gates off; do not mark
the baseline complete or fabricate the manifest.

- [ ] **Step 5: Commit manifest enforcement and measured evidence**

```bash
git add docs/runbooks/flood-potential-import.production.yaml docs/runbooks/flood-potential-import.example.yaml infra/scripts/validate_flood_potential_import.py infra/scripts/import_flood_potential_layer.py tests/test_flood_potential_import_validator.py apps/workers/app/adapters/flood_potential/importer.py apps/workers/app/config.py apps/workers/app/jobs/runtime.py apps/workers/tests/test_adapter_registry_config.py apps/workers/tests/test_flood_potential_production_manifest.py apps/api/app/domain/evidence/repository.py apps/api/app/domain/assessment/models.py apps/api/app/domain/assessment/repository.py apps/api/app/api/services/assessment.py apps/api/app/api/schemas.py apps/api/tests/test_assessment_repository.py apps/api/tests/test_assessment_service.py apps/api/tests/test_public_contract.py packages/contracts/fixtures/risk-assess-response.json docs/api/openapi.yaml .env.example docs/data-sources/official/official-source-catalog.yaml
git commit -m "feat: pin flood potential production evidence"
```

### Task 14: Add the per-source managed v1 baseline and migration 0038

**Files:**

- Create: `apps/workers/app/jobs/v1_baseline.py`
- Create: `apps/workers/app/cli/v1_baseline_cli.py`
- Create: `apps/workers/tests/test_v1_baseline.py`
- Modify: `apps/workers/pyproject.toml`
- Modify: `apps/workers/app/main.py`
- Modify: `apps/workers/app/cli/parser.py`
- Modify: `apps/workers/app/scheduler.py`
- Modify: `apps/workers/app/jobs/runtime_managed.py`
- Modify: `apps/workers/app/jobs/ingestion.py`
- Modify: `apps/workers/tests/test_worker_entrypoints.py`
- Modify: `apps/workers/tests/test_scheduler.py`
- Modify: `apps/workers/tests/test_runtime_managed_ingestion.py`
- Modify: `apps/workers/tests/test_ingestion_job_runner.py`
- Create: `infra/migrations/0038_v1_official_baseline_sources.sql`
- Modify: `infra/migrations/README.md`
- Modify: `apps/api/app/api/routes/health.py`
- Modify: `apps/api/app/domain/realtime/nearby_coverage.py`
- Modify: `apps/api/tests/test_public_contract.py`
- Modify: `apps/api/tests/test_evidence_repository.py`
- Modify: `apps/api/tests/test_nearby_realtime_coverage.py`
- Modify: `apps/workers/tests/test_official_source_catalog.py`
- Modify: `tests/test_apply_migrations_script.py`
- Create: `tests/test_v1_official_migration_postgres.py`
- Modify: `.env.example`
- Modify: `docs/runbooks/worker-scheduler-deployment.md`

**Exact managed wrapper:**

```python
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

from app.adapters.contracts import DataSourceAdapter
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import WorkerSettings
from app.jobs.ingestion import (
    IngestionRunSummaryWriter,
    record_pipeline_status,
    record_runtime_selection,
)
from app.jobs.runtime_managed import (
    ManagedRuntimeIngestionResult,
    RuntimeAdapterBuilder,
    run_managed_runtime_ingestion_cycle,
)
from app.logging import log_event
from app.pipelines.ingestion_runs import PostgresIngestionRunWriter
from app.pipelines.promotion import EvidencePromotionWriter
from app.pipelines.staging import StagingBatchWriter

V1_BASELINE_ADAPTER_KEYS: tuple[str, ...] = (
    "official.cwa.rainfall",
    "official.cwa.heavy_rain_warning",
    "official.wra.water_level",
    "official.wra_iow.flood_depth",
    "official.wra.historical_flood",
    "official.ncdr.cap",
    "official.flood_potential.geojson",
    "local.tainan.flood_sensor",
)

V1_API_GATE_ATTR_BY_KEY = {
    "official.cwa.rainfall": "source_cwa_api_enabled",
    "official.cwa.heavy_rain_warning": "source_cwa_heavy_rain_warning_api_enabled",
    "official.wra.water_level": "source_wra_api_enabled",
    "official.wra_iow.flood_depth": "source_wra_iow_flood_depth_api_enabled",
    "official.wra.historical_flood": "source_wra_historical_flood_api_enabled",
    "official.ncdr.cap": "source_ncdr_cap_api_enabled",
    "official.flood_potential.geojson": "source_flood_potential_geojson_enabled",
    "local.tainan.flood_sensor": "source_tainan_flood_sensor_api_enabled",
}


def v1_runtime_gate_is_open(settings: WorkerSettings, key: str) -> bool:
    return bool(getattr(settings, V1_API_GATE_ATTR_BY_KEY[key]))


def _resolve_v1_run_writer(
    *, settings: WorkerSettings, database_url: str | None,
    run_writer: IngestionRunSummaryWriter | None,
) -> IngestionRunSummaryWriter | None:
    if run_writer is not None:
        return run_writer
    resolved_database_url = database_url or settings.database_url
    return (
        PostgresIngestionRunWriter(database_url=resolved_database_url)
        if resolved_database_url else None
    )


def run_v1_baseline_cycle(
    *,
    settings: WorkerSettings,
    adapter_builder: RuntimeAdapterBuilder,
    database_url: str | None = None,
    staging_writer: StagingBatchWriter | None = None,
    run_writer: IngestionRunSummaryWriter | None = None,
    promotion_writer: EvidencePromotionWriter | None = None,
) -> tuple[ManagedRuntimeIngestionResult, ...]:
    results: list[ManagedRuntimeIngestionResult] = []
    selected_keys = tuple(
        key for key in V1_BASELINE_ADAPTER_KEYS
        if key in enabled_adapter_keys(settings)
        and v1_runtime_gate_is_open(settings, key)
    )
    cycle_started_at = datetime.now(UTC)
    selection_writer = _resolve_v1_run_writer(
        settings=settings, database_url=database_url, run_writer=run_writer
    )
    record_runtime_selection(
        selection_writer,
        enabled_adapter_keys=selected_keys,
        known_adapter_keys=tuple(ADAPTER_REGISTRY),
    )
    resolved_database_url = database_url or settings.database_url
    if selected_keys and not resolved_database_url and (
        staging_writer is None or selection_writer is None or promotion_writer is None
    ):
        # Never fetch upstream when an attempted production cycle cannot persist
        # staging, run health, and promotion.
        if selection_writer is not None:
            for key in selected_keys:
                record_pipeline_status(
                    selection_writer,
                    adapter_keys=(key,), status="failed", complete=False,
                    run_at=cycle_started_at,
                )
        return tuple(persistence_unavailable_result(key) for key in selected_keys)
    for key in selected_keys:
        source_started_at = datetime.now(UTC)
        scoped_settings = replace(settings, enabled_adapter_keys=(key,))
        try:
            # Construction is inside the isolation boundary. A broken manifest or
            # constructor for one source cannot prevent the next source.
            adapter_map: Mapping[str, DataSourceAdapter] = adapter_builder(scoped_settings)
            adapter = adapter_map.get(key)
            if adapter is None:
                record_pipeline_status(
                    selection_writer,
                    adapter_keys=(key,), status="failed", complete=False,
                    run_at=source_started_at,
                )
                results.append(missing_adapter_result(key))
                continue
            result = run_managed_runtime_ingestion_cycle(
                {key: adapter},
                settings=scoped_settings,
                database_url=database_url,
                staging_writer=staging_writer,
                run_writer=selection_writer,
                promotion_writer=promotion_writer,
                promote=True,
                promotion_adapter_keys=(key,),
                job_key=f"worker.v1_baseline.{key}",
                record_runtime_selection_state=False,
            )
        except Exception as exc:
            record_pipeline_status(
                selection_writer,
                adapter_keys=(key,), status="failed", complete=False,
                run_at=source_started_at,
            )
            log_event(
                "runtime.v1_baseline.source.failed",
                adapter_key=key,
                error_code=exc.__class__.__name__,
            )
            result = failed_adapter_exception_result(key, exc)
        if result.status == "skipped" and result.reason == "no_database_url":
            record_pipeline_status(
                selection_writer,
                adapter_keys=(key,), status="failed", complete=False,
                run_at=source_started_at,
            )
            result = persistence_unavailable_result(key)
        results.append(result)
    return tuple(results)
```

`missing_adapter_result(key)` is a small public-safe factory returning a failed
`ManagedRuntimeIngestionResult` with `error_code="missing_adapter"` and the key
in `reason`; it must not expose credentials. There is no public
`ManagedPersistenceWriters` type and no `now` argument. Do not add either merely
for this wrapper.

```python
def missing_adapter_result(key: str) -> ManagedRuntimeIngestionResult:
    return ManagedRuntimeIngestionResult(
        status="failed",
        reason=f"missing_adapter:{key}",
        error_code="missing_adapter",
    )


def failed_adapter_exception_result(
    key: str, exc: Exception
) -> ManagedRuntimeIngestionResult:
    return ManagedRuntimeIngestionResult(
        status="failed",
        reason=f"source_cycle_exception:{key}",
        error_code=exc.__class__.__name__,
    )


def persistence_unavailable_result(key: str) -> ManagedRuntimeIngestionResult:
    return ManagedRuntimeIngestionResult(
        status="failed",
        reason=f"persistence_unavailable:{key}",
        error_code="persistence_unavailable",
    )
```

This is the per-source isolation boundary. It catches `Exception`, not
`BaseException`, intentionally discards `str(exc)` because upstream exceptions
may contain credentials or payloads, records only adapter key/class, and always
continues to the next selected key.

`_resolve_v1_run_writer` above is the only wrapper-local writer resolver; do not
refer to a nonexistent public `build_ingestion_run_writer`. It returns the
injected writer, otherwise the normal `PostgresIngestionRunWriter` for the
resolved database URL, otherwise `None`.
Add the defaulted keyword-only
`record_runtime_selection_state: bool = True` to
`run_managed_runtime_ingestion_cycle` and propagate it through
`run_scheduled_ingestion_cycle` to a same-named defaulted keyword on
`run_enabled_adapter_batches`. Guard every `record_runtime_selection(...)` in
all three layers with that value; guarding only the outer managed call is
insufficient because the current scheduler→ingestion chain writes another
singleton selection. Generic legacy callers retain `True`. The v1 wrapper
records the **complete** selected set exactly once before per-source work, then
passes `False` through every scoped managed call and its nested scheduler/batch
call. Do not change pipeline-status, staging, run-summary, freshness, or
promotion behavior. A one-key scoped settings object must never rewrite every
other selected source to `runtime_enabled=false`.

- [ ] **Step 1: Write RED isolation and continuation tests**

Assert disabled baseline keys and keys whose API gate is false are not attempted.
Add a default-settings case proving that an allowlisted backbone key does not
become selected while its API gate is false. For every enabled baseline key,
assert each managed call receives exactly one adapter and
`enabled_adapter_keys=(key,)`; otherwise the existing managed runtime declares
all other selected keys missing. Assert the positional adapter mapping and every
keyword shown above. A returned failure, raised source exception, or missing
adapter produces a failed result but does not prevent later sources from
running. Inject a raised exception for the first selected adapter and assert the
second adapter is still called and both ordered results are returned. Promotion
is per source, not one all-or-nothing batch.

Add a regression with two selected sources and a recording run writer. Assert
`write_runtime_selection` is called once with both ordered keys and the full
known registry, both managed calls receive
`record_runtime_selection_state=False`, and the writer's final
`runtime_enabled` projection still contains both keys after the second source.
Exercise the real wrapper→managed→scheduler→`run_enabled_adapter_batches` call
chain, not only a mocked managed function: it must emit one full-set selection
write and zero singleton nested selection writes.

Seed the recording writer with prior healthy pipeline state, then cover both a
missing adapter and a constructor/source exception. Each must call
`write_pipeline_status(adapter_keys=(key,), status="failed", complete=False, ...)`,
the public health projection must become failed rather than retain old healthy,
and the following selected source must still run. Make the first per-key
`adapter_builder(scoped_settings)` raise while the second returns its adapter;
this proves construction itself is isolated. Also assert an attempted cycle
with no database URL and incomplete injected persistence writers makes zero
adapter-builder/upstream calls, returns `persistence_unavailable` failures, and
the CLI exits non-zero. Seed prior healthy state for this preflight too: when a
selection writer is available, every selected key must be recorded failed at
the one captured `cycle_started_at`, so public health cannot retain the old
healthy state. When no run writer can be resolved, the wrapper still returns
failures/non-zero and makes zero upstream calls but cannot claim a persisted
transition. A valid `no_active_event` result remains succeeded.

- [ ] **Step 2: Implement the wrapper, CLI, and scheduler entrypoint**

The CLI loads settings and passes the existing `build_runtime_adapters` function
as `adapter_builder`; it must not build the complete mapping before entering
`run_v1_baseline_cycle`. The wrapper invokes that factory once per scoped key
inside its `try`. It runs only the intersection of
`enabled_adapter_keys(settings)` and `V1_BASELINE_ADAPTER_KEYS`; a selected key
missing from the built mapping is a failure, while a disabled key is not an
attempt. Exit non-zero when any attempted result failed, emit only
counts/status/error codes, and never emit raw payloads or secrets. Treat
`skipped/no_database_url` for any attempted source as failed/non-zero; a command
that fetched nothing and persisted no staging/promotion is not successful. Do not
reimplement staging, run recording, or promotion.

Add one `--v1-baseline` dispatch in `app/cli/parser.py` and `app/main.py`, and the
same bounded-cycle selection in `app/scheduler.py`; both delegate to
`v1_baseline_cli`/`run_v1_baseline_cycle`. They must not bypass the Task 7 frozen
writer guards or call `run_managed_runtime_ingestion_cycle` directly.

- [ ] **Step 3: Write migration 0038 tests before SQL**

Tests must require:

- catalog rows for `official.cwa.heavy_rain_warning` and
  `official.wra.historical_flood`, a reviewed upserted row for
  `official.wra_iow.flood_depth`, and corrected datastore/dump metadata for
  `official.ncdr.cap`; the `official.flood_potential.geojson` metadata must copy
  the production manifest hash, sorted covered jurisdictions, sorted official
  known gaps/reasons, scenario, and merged output checksum exactly. Migration
  tests load the YAML and compare values rather than duplicating an unchecked
  county list;
- all eight exact `V1_BASELINE_ADAPTER_KEYS` appear once in the catalog upsert,
  with `is_enabled = false` on INSERT **and** a literal
  `is_enabled = false` in every `ON CONFLICT ... DO UPDATE`; tests load the
  post-migration table, assert the exact eight-key set/count and every row false,
  including CWA/WRA rows that migration 0003 may previously have enabled, so an
  earlier manual enable cannot survive deploy;
- every other inserted catalog column updated on conflict (`name`, `source_type`,
  `license`, `update_frequency`, `health_status`, `legal_basis`, and `metadata`),
  with authoritative `metadata = EXCLUDED.metadata` rather than a stale JSON
  merge;
- `freshness_threshold_seconds` and event-vs-station metadata for health logic;
- one exact v1 realtime mapping manifest. Delete only the old policy rows from
  `realtime_source_jurisdictions` and replace them with these six rows; do not
  delete any source, evidence, run, adapter, or module:

  ```text
  official.cwa.rainfall             rainfall       national TW       required
  official.cwa.heavy_rain_warning   flood_warning  national TW       required
  official.wra.water_level          water_level    national TW       required
  official.wra_iow.flood_depth      flood_depth    national TW       required
  official.ncdr.cap                 flood_warning  national TW       required
  local.tainan.flood_sensor         flood_depth    local    67000000 required
  ```

  All six rows use mapping revision `2026-08-24-v1-baseline`, null redundancy
  parent, reviewed timestamp, and `review_ref='0038_v1_official_baseline_sources'`.
  There are no other v1 mapping rows or `required` adapters; this prevents frozen
  tide/Civil-IoT/other-local candidates from making nationwide low-risk readiness
  impossible. Kaohsiung and Pingtung remain central-only and are surfaced by the
  explicit local-gap policy.
- recompute the deterministic JSON manifest count/SHA-256 in the migration for
  every jurisdiction's `rainfall`, `water_level`, `flood_depth`, and
  `flood_warning` contract
  using the exact ordering/encoding in
  `query_realtime_jurisdiction_context`, then store
  `catalog_status='reviewed_complete'`, the same mapping revision, reviewed
  timestamp, and migration review ref. The `flood_warning` contract has exactly
  the two reviewed keys `official.cwa.heavy_rain_warning` and
  `official.ncdr.cap` for all 22 jurisdictions, with count `2` and its canonical
  digest; otherwise Task 3 must fail closed rather than silently omit CAP.
  `flood_warning` remains optional to the three-signal low/absence proof even
  though its source mappings are required operational sources. Set
  `sewer_water_level` to `known_gap` with null approved count/hash. Tests load
  the post-migration rows, recompute hashes, and assert both warning keys enter
  every verified jurisdiction's applicable/required set rather than checking
  filename strings only;
- before inserting `flood_warning` contract rows, migration 0038 explicitly
  drops the 0035 constraint
  `realtime_jurisdiction_signal_contracts_signal_type_check` and recreates that
  same named CHECK with exactly `rainfall`, `water_level`, `flood_depth`,
  `sewer_water_level`, and `flood_warning`. A migrated-Postgres test queries
  `pg_get_constraintdef`, proves the new value is accepted, and proves an
  unknown signal type is rejected; editing migration 0035 is forbidden;
- Tainan resolves five national required adapters plus its local flood sensor;
  Kaohsiung, Pingtung, and a non-south control county resolve exactly the five
  national adapters. No legacy mapping key may appear in `required_keys`;
- Tainan as the only v1 local source, with Kaohsiung and Pingtung candidates
  still disabled; no migration or config implicitly enables any source;
- API coverage classification maps
  `official.cwa.heavy_rain_warning -> flood_warning`, adds its reviewed public
  label, and keeps it distinct from `official.ncdr.cap`; a health row for the
  new key must not be silently dropped by `build_nearby_source_health`;
- the expected filename/version/checksum contract moving from 0037 to 0038.

- [ ] **Step 4: Implement 0038 and update every schema sentinel**

Create `0038_v1_official_baseline_sources.sql`, document it in
`infra/migrations/README.md`, set
`REQUIRED_SCHEMA_VERSION = 38` and
`REQUIRED_SCHEMA_FILENAME = "0038_v1_official_baseline_sources.sql"`, recompute
the SHA-256 with the same bytes/algorithm used by `infra/scripts/apply_migrations.py`,
and update `apps/api/tests/test_public_contract.py` assertions and migration test
fixtures. The mapping replacement and contract digest refresh occur in the same
migration transaction, so no partial policy can be observed. Never edit an
already-applied migration or its recorded checksum.

- [ ] **Step 5: Add worker type checking only with its dependency**

Add `mypy>=1.11` and `types-PyYAML>=6.0` to the worker `dev` extra before making
type checking a gate. Type-check the touched modules explicitly; do not claim a
mypy gate that a fresh `pip install -e '.[dev]'` cannot run.

- [ ] **Step 6: Run migration, worker, and API tests in separate processes**

```bash
python infra/scripts/validate_migrations.py
python -m pytest tests/test_apply_migrations_script.py tests/test_v1_official_migration_postgres.py -q
(cd apps/workers && python -m pytest tests/test_v1_baseline.py tests/test_runtime_managed_ingestion.py tests/test_ingestion_job_runner.py tests/test_official_source_catalog.py tests/test_worker_entrypoints.py tests/test_scheduler.py -q)
(cd apps/workers && python -m mypy app/jobs/v1_baseline.py app/cli/v1_baseline_cli.py)
(cd apps/api && python -m pytest tests/test_public_contract.py tests/test_evidence_repository.py tests/test_nearby_realtime_coverage.py -q)
```

Expected: PASS. Do not combine API and worker pytest paths in one invocation;
both projects import a top-level package named `app`.

`test_v1_official_migration_postgres.py` is the non-mocked migration-path suite.
With `OFFICIAL_DB_ACCEPTANCE_REQUIRED=1` it requires two reachable, dedicated
empty database URLs. It applies all migrations to the first; on the second it
applies exactly 0001–0037 from a temporary manifest directory, seeds the
pre-0038 enabled/conflict state, then applies 0038. It queries real constraints,
all eight disabled catalog rows, six mapping rows, all 22 warning contracts and
digests. Missing URLs, a skip, or an already-dirty target is a hard failure.

- [ ] **Step 7: Commit the baseline runner and schema gate**

```bash
git add apps/workers/app/jobs/v1_baseline.py apps/workers/app/jobs/runtime_managed.py apps/workers/app/jobs/ingestion.py apps/workers/app/cli/v1_baseline_cli.py apps/workers/app/main.py apps/workers/app/cli/parser.py apps/workers/app/scheduler.py apps/workers/tests/test_v1_baseline.py apps/workers/tests/test_runtime_managed_ingestion.py apps/workers/tests/test_ingestion_job_runner.py apps/workers/tests/test_official_source_catalog.py apps/workers/tests/test_worker_entrypoints.py apps/workers/tests/test_scheduler.py apps/workers/pyproject.toml infra/migrations/0038_v1_official_baseline_sources.sql infra/migrations/README.md apps/api/app/api/routes/health.py apps/api/app/domain/realtime/nearby_coverage.py apps/api/tests/test_public_contract.py apps/api/tests/test_evidence_repository.py apps/api/tests/test_nearby_realtime_coverage.py tests/test_apply_migrations_script.py tests/test_v1_official_migration_postgres.py .env.example docs/runbooks/worker-scheduler-deployment.md
git commit -m "feat: add isolated v1 official baseline cycle"
```

### Task 15: Roll the Web UI forward with a legacy-response fallback

**Files:**

- Modify: `apps/web/app/lib/page-types.ts`
- Modify: `apps/web/app/lib/api-client.ts`
- Modify: `apps/web/app/lib/risk-display/types.ts`
- Modify: `apps/web/app/lib/risk-display/risk.ts`
- Modify: `apps/web/app/lib/risk-display/evidence.ts`
- Modify: `apps/web/app/lib/risk-display.ts`
- Modify: `apps/web/app/lib/ui-text.ts`
- Modify: `apps/web/app/components/risk-summary-section.tsx`
- Modify: `apps/web/app/components/evidence-section.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/tests/unit/api-client.test.ts`
- Modify: `apps/web/tests/unit/risk-display.test.ts`
- Modify: `apps/web/tests/e2e/map-risk.spec.ts`

**Compatibility rule:**

All Task 4 fields are optional in TypeScript during the rolling deploy. The UI
uses the new model only when both `response.overall` and
`response.dominant_mode` are present and valid. Otherwise it uses the existing
legacy `combinedRiskLevel`/legacy evidence presentation unchanged. It must never
translate `unknown` into `low`.

```typescript
export type AssessmentRiskPresentation = {
  riskLevel: string;
  realtimeLevel: string;
  historicalLevel: string;
  confidenceLevel: string;
  dominantMode: "realtime" | "historical_context" | "community_warning" | "unknown";
  contextLabel: string;
  reasons: string[];
  usesAdditiveModel: boolean;
};

export function legacyAssessmentRiskPresentation(
  response: RiskAssessmentResponse,
): AssessmentRiskPresentation;

export function assessmentRiskPresentation(
  response: RiskAssessmentResponse,
): AssessmentRiskPresentation;
```

- [ ] **Step 1: Write RED new, unknown, and legacy-only presentation tests**

```typescript
test("prefers the additive overall model when complete", () => {
  const view = assessmentRiskPresentation(newResponseFixture);
  assert.equal(view.riskLevel, "高");
  assert.match(view.contextLabel, /歷史|historical/);
});

test("unknown remains unknown", () => {
  assert.equal(assessmentRiskPresentation(unknownFixture).riskLevel, "未知");
});

test("English aliases normalize to the existing Chinese display values", () => {
  assert.equal(assessmentRiskPresentation(englishHighFixture).riskLevel, "高");
});

test("invalid additive level fails closed to unknown", () => {
  assert.equal(assessmentRiskPresentation(invalidOverallFixture).riskLevel, "未知");
});

test("legacy-only response renders exactly through the old fallback", () => {
  assert.deepEqual(
    assessmentRiskPresentation(legacyOnlyFixture),
    legacyAssessmentRiskPresentation(legacyOnlyFixture),
  );
});
```

Also cover a partially deployed response containing `overall` but no
`dominant_mode`; it must take the legacy path rather than mixing models.

- [ ] **Step 2: Add optional response types and the single fallback seam**

Define additive fields once in `page-types.ts`, validate them at the API-client
boundary, and feed `assessment.overall.level` through the existing
`normalizeRiskLevel` mapping. The presentation contract remains the existing
Chinese display vocabulary `低|中|高|極高|未知`; English transport aliases may
normalize into it, but an unrecognized additive level must become `未知` rather
than being passed through as arbitrary text. Implement
`assessmentRiskPresentation()` in
`risk-display/risk.ts`. Components consume that presentation object; they do not
repeat fallback logic. Show `as_of`, current-vs-historical context, coverage/data
status, evidence precision, and limitations without rendering exact persisted
coordinates.

Use the same public evidence union as the API, never the geocoder union:

```typescript
export type EvidenceLocationPrecision =
  | "point"
  | "road_or_lane"
  | "poi"
  | "admin_area"
  | "polygon"
  | "inferred"
  | "map_click"
  | "unknown";

// additive EvidencePreview fields
location_precision?: EvidenceLocationPrecision;
limitations?: string[];
```

`exact_address` is intentionally absent and fails API-client validation.

- [ ] **Step 3: Remove diagnostics/profile UI dependencies without deleting modules**

Remove `DiagnosticsSection` and profile/query-heat derived props/copy from
`page.tsx`, `risk-summary-section.tsx`, `evidence-section.tsx`, and the public
barrel. Do not delete `diagnostics-section.tsx` or
`risk-display/profile.ts` in this slice; Task 7 freezes their producers and they
remain rollback/characterization code. Add an e2e assertion that the assessment
page renders without a profile or diagnostics panel.

- [ ] **Step 4: Run the complete Web gate**

```bash
(cd apps/web && npm test)
(cd apps/web && npm run typecheck)
(cd apps/web && npm run lint)
(cd apps/web && npm run build)
(cd apps/web && npm run e2e -- --project=chromium tests/e2e/map-risk.spec.ts)
```

Expected: PASS.

- [ ] **Step 5: Commit rolling-compatible UI changes**

```bash
git add apps/web/app/lib/page-types.ts apps/web/app/lib/api-client.ts apps/web/app/lib/risk-display/types.ts apps/web/app/lib/risk-display/risk.ts apps/web/app/lib/risk-display/evidence.ts apps/web/app/lib/risk-display.ts apps/web/app/lib/ui-text.ts apps/web/app/components/risk-summary-section.tsx apps/web/app/components/evidence-section.tsx apps/web/app/page.tsx apps/web/tests/unit/api-client.test.ts apps/web/tests/unit/risk-display.test.ts apps/web/tests/e2e/map-risk.spec.ts
git commit -m "feat: render additive assessment model with fallback"
```

### Task 16: Run the end-to-end acceptance matrix and update operator docs

**Files:**

- Modify: `apps/api/README.md`
- Modify: `apps/workers/README.md`
- Modify: `apps/web/README.md`
- Modify: `docs/runbooks/worker-scheduler-deployment.md`
- Modify: `docs/data-sources/official/official-source-catalog.yaml`

- [ ] **Step 1: Document the one public read path and rollout order**

Document: migrate through 0038; deploy API with additive fields; deploy the Web
fallback; deploy workers with all new source gates off; validate each source in
staging; then enable one gate at a time. State that the public risk route has one
read-model load and one `AssessmentService` call, the base composer never applies
community uplift, historical/planning evidence is scored separately, and legacy
profile/query-heat writers stay frozen.

- [ ] **Step 2: Run static contract checks**

```bash
python infra/scripts/validate_migrations.py
python infra/scripts/validate_openapi.py
python infra/scripts/validate_flood_potential_import.py docs/runbooks/flood-potential-import.production.yaml --production-complete
rg -n "assess_risk\(|AssessmentService" apps/api/app/api/routes/public.py
rg -n "write_query_heat|upsert_risk_profile|persist_profile|tile.*write" apps/api/app apps/workers/app
```

Review the two `rg` outputs, do not merely require zero matches: the public route
must contain the service path and no legacy `public_risk.assess_risk` call; legacy
functions may remain defined or used by admin/rollback tests, but production
public and scheduler entrypoints must not invoke their writers.

- [ ] **Step 3: Run all automated gates in separate project processes**

```bash
(cd apps/api && python -m pytest -q)
(cd apps/api && python -m ruff check app tests)
(cd apps/api && python -m mypy app)
(cd apps/workers && python -m pytest -q)
(cd apps/workers && python -m ruff check app tests)
(cd apps/workers && python -m mypy app/jobs/v1_baseline.py app/cli/v1_baseline_cli.py app/pipelines/promotion.py app/adapters/wra/historical_flood.py app/adapters/cwa/heavy_rain_warning.py app/adapters/ncdr/cap_alerts.py)
python -m pytest tests -q
(cd apps/web && npm test)
(cd apps/web && npm run typecheck)
(cd apps/web && npm run lint)
(cd apps/web && npm run build)
(cd apps/web && npm run e2e)
```

Expected: PASS. API and worker pytest commands remain separate because both use
the import name `app`.

- [ ] **Step 4: Run database concurrency and privacy acceptance**

Apply migrations to an empty PostGIS database and exercise the 0037→0038 path
through `tests/test_apply_migrations_script.py`, then run these mandatory
real-database suites:

```bash
docker compose up -d postgres
docker compose --profile tools run --rm migrate
docker compose exec -T postgres dropdb --if-exists --force -U flood_risk flood_risk_acceptance_empty
docker compose exec -T postgres dropdb --if-exists --force -U flood_risk flood_risk_acceptance_upgrade
docker compose exec -T postgres createdb -U flood_risk flood_risk_acceptance_empty
docker compose exec -T postgres createdb -U flood_risk flood_risk_acceptance_upgrade
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 OFFICIAL_EMPTY_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:${POSTGRES_PORT:-5432}/flood_risk_acceptance_empty" OFFICIAL_UPGRADE_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:${POSTGRES_PORT:-5432}/flood_risk_acceptance_upgrade" python -m pytest tests/test_v1_official_migration_postgres.py -q -rs
(cd apps/api && OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 EVIDENCE_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:${POSTGRES_PORT:-5432}/flood_risk" python -m pytest tests/test_evidence_repository_postgres.py -q -rs)
(cd apps/workers && OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 PROMOTION_TEST_DATABASE_URL="postgresql://flood_risk:change-me-local@127.0.0.1:${POSTGRES_PORT:-5432}/flood_risk" python -m pytest tests/test_promotion_monotonicity_postgres.py -q -rs)
OFFICIAL_DB_ACCEPTANCE_REQUIRED=1 python -m pytest tests/test_apply_migrations_script.py -q -rs
```

The two `dropdb` targets are exact dedicated acceptance databases and contain no
application data; do not substitute a workspace/default database name. Expected:
all commands PASS and all three database suites report zero skips. Their
completion sentinel makes missing environment/database configuration a failure,
so a skip-only result cannot satisfy this gate. Verify:

- central-first and local-first duplicates yield one authoritative
  `official_realtime_latest` row while a superseded local `evidence` audit row
  may remain and is never scored as a second current observation;
- an idempotent replay terminalizes its staging row;
- a conflicting replay is rejected/quarantined and cannot overwrite canonical
  evidence;
- advisory locking protects the absent-row case;
- exact query coordinates do not appear in `risk_assessments.result_snapshot`,
  logs, CLI output, or error payloads;
- separate latest/history/coverage/health failures expose their own availability
  flag and do not silently rewrite a risk level.

- [ ] **Step 5: Run one isolated staging cycle per source while catalog rows stay disabled**

For each key in `V1_BASELINE_ADAPTER_KEYS`, enable only that source in a staging
settings object, run the Task 14 wrapper, inspect its run/staging/promotion counts,
then disable its runtime/API gates before moving to the next key. Keep the
corresponding `data_sources.is_enabled=false` during this ingestion proof so it
cannot accidentally become public-ready. For warning feeds, an empty valid poll
must record `no_active_event`; for historical/context sources, promoted rows must
be absent from the current-official scorer. Do not enable Kaohsiung or Pingtung
local candidates in v1.

- [ ] **Step 6: Exercise and document explicit post-migration activation**

Migration 0038 intentionally resets every v1 catalog row to
`data_sources.is_enabled=false`; configuration gates alone therefore cannot make
readiness healthy. After a source passes Step 5, use the documented operator
transaction in staging to enable exactly that one catalog row, reopen only its
runtime/API gates, run one more cycle, and verify source health plus an assessment
in its applicable jurisdiction. Disable both the catalog row and gates again
before testing the next source.

Document production promotion as the same explicit per-source transaction. The
five national realtime rows may be enabled only after their individual proofs;
`local.tainan.flood_sensor` is enabled only after its local feed proof. WRA
history and flood-potential context may be enabled independently after their
artifact proofs and never count toward realtime-low completeness. Rollback sets
the catalog row false first, then closes its gates. No deployment or migration
automatically activates a source.

- [ ] **Step 7: Commit final documentation**

```bash
git add apps/api/README.md apps/workers/README.md apps/web/README.md docs/runbooks/worker-scheduler-deployment.md docs/data-sources/official/official-source-catalog.yaml
git commit -m "docs: publish v1 official baseline operations"
```

## Completion Gate

The core official baseline is complete only when all of the following are true:

1. The public route constructs `AssessmentService` once and performs no direct
   upstream network calls.
2. Current official and historical/planning evidence use separate `score_risk`
   calls; `compose_base_overall()` alone selects the core base decision.
3. Latest, history, coverage, health, and jurisdiction reads fail independently,
   and all absence/low claims are query-local and server-jurisdiction-authorized.
4. Promotion is monotonic under central/local concurrency, terminalizes every
   processed staging row, and filters `None` promotion outcomes. CAP identity,
   exact Update/Cancel references, concurrent same-area warnings, lifecycle
   tombstones, and no-active generations pass both commit orders.
5. New API fields are additive/defaulted; an old API response still renders via
   the Web fallback and `unknown` never becomes `low`.
6. Legacy profile/query-heat/tile writers are unreachable from production public
   and scheduler entrypoints, while their modules remain for rollback.
7. WRA history uses metadata -> KML, CWA uses CAP, NCDR uses datastore -> dump,
   and each new source remains disabled until its isolated staging proof passes;
   production readiness requires an explicit, audited catalog-row activation in
   addition to both configuration gates.
8. `docs/runbooks/flood-potential-import.production.yaml` contains measured,
   validator-approved evidence for every metadata-advertised archive in one
   scenario, plus a deterministic merged output and explicit 22-jurisdiction
   covered/known-gap partition; a template, single-county archive, or synthetic
   fixture does not satisfy this gate.
9. Migration 0038 passes both real empty-database and real 0037→0038 paths;
   evidence geography and promotion concurrency run against migrated PostGIS
   with the completion sentinel and zero skips. Its checksum/schema sentinel,
   the full API suite, the full worker suite, root tests, and the complete Web
   gate all pass.

If any item is unmet, leave the affected gates off and report the concrete
blocker; do not substitute a placeholder, synthetic polygon, guessed source
contract, or manually asserted checksum.
