from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from app.api.schemas import (
    LatLng,
    NearbyCoverageSignal,
    RiskAssessmentResponse,
    RiskAssessRequest,
)
from app.api.services.assessment import AssessmentService
from app.domain.assessment import AssessmentData, AssessmentSourceState
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    RiskAssessmentPersistence,
)
from app.domain.realtime import build_nearby_realtime_coverage
from app.domain.risk import RiskEvidenceSignal, RiskScoringResult, score_risk

NOW = datetime(2026, 8, 24, 5, 30, tzinfo=UTC)
CURRENT_ID = "26900bf0-f51c-4326-8f75-68d03a36560e"
HISTORY_ID = "911d1bdf-0cc9-49bc-896d-f92680054b08"
POLICE_CONTEXT_ID = "3b3a3f0f-0b6a-4f0a-9b4a-8c1f5b6a2d31"
WRA_CONTEXT_ID = "5f2c1a44-8f2b-4d4c-9a2e-1c7d3e9b6a52"
POLICE_LIMITATION = "警廣即時路況通報，尚未由淹水感測器確認。"


@dataclass
class FakeRepository:
    data: AssessmentData
    persisted: list[RiskAssessmentPersistence] = field(default_factory=list)
    fail_persist: bool = False
    programming_error: BaseException | None = None

    def load(self, **_kwargs: object) -> AssessmentData:
        return self.data

    def persist(self, assessment: RiskAssessmentPersistence) -> None:
        if self.programming_error is not None:
            raise self.programming_error
        if self.fail_persist:
            raise EvidenceRepositoryUnavailable("audit write unavailable")
        self.persisted.append(assessment)


def _record(
    evidence_id: str,
    *,
    event_type: str,
    evidence_scope: str,
    source_type: str = "official",
    adapter_key: str = "official.cwa.rainfall",
    limitations: tuple[str, ...] = ("位置為道路尺度",),
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        source_id=f"source:{evidence_id}",
        source_type=source_type,
        event_type=event_type,
        title=f"title:{evidence_id}",
        summary=f"summary:{evidence_id}",
        url=None,
        occurred_at=NOW,
        observed_at=NOW,
        ingested_at=NOW,
        lat=22.99974,
        lng=120.22704,
        geometry={"type": "Point", "coordinates": [120.22704, 22.99974]},
        distance_to_query_m=30.0,
        confidence=0.9,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=None,
        rainfall_mm_1h=0.0 if event_type == "rainfall" else None,
        evidence_scope=evidence_scope,  # type: ignore[arg-type]
        adapter_key=adapter_key,
        location_precision="road_or_lane",
        limitations=limitations,
    )


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def risk_request() -> RiskAssessRequest:
    return RiskAssessRequest(
        point=LatLng(lat=22.99974, lng=120.22704),
        radius_m=750,
        time_context="now",
        location_text="臺南市永康區中華路機密查詢文字",
    )


@pytest.fixture
def data(now: datetime) -> AssessmentData:
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=750,
        evaluated_at=now,
        repository_unavailable=True,
        source_health_unavailable=True,
        jurisdiction_status="unavailable",
    )
    return AssessmentData(
        current_official=(_record(CURRENT_ID, event_type="rainfall", evidence_scope="current"),),
        historical=(
            _record(
                HISTORY_ID,
                event_type="flood_potential",
                evidence_scope="context",
                source_type="derived",
            ),
        ),
        nearby_coverage=coverage,
        source_states=(
            AssessmentSourceState(
                source_key="official.cwa.rainfall",
                signal_type="rainfall",
                state="fresh",
                observed_at=now,
                checked_at=now,
                message=None,
            ),
            AssessmentSourceState(
                source_key="official.wra.water_level",
                signal_type="water_level",
                state="failed",
                observed_at=None,
                checked_at=now,
                message="官方水位來源暫時無法使用",
            ),
        ),
        required_realtime_source_keys=frozenset(
            {"official.cwa.rainfall", "official.wra.water_level"}
        ),
        current_available=True,
        historical_available=True,
        coverage_available=False,
        health_available=False,
        jurisdiction_available=False,
        resolved_admin_code=None,
        resolved_admin_name=None,
        local_machine_feed_missing=("地方政府機器介面尚未核准",),
    )


def test_service_scores_current_and_history_in_separate_calls(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    calls: list[tuple[RiskEvidenceSignal, ...]] = []

    def scorer(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult:
        calls.append(signals)
        return score_risk(signals, now=now)

    response = AssessmentService(FakeRepository(data), scorer).assess(risk_request, now=now)

    assert len(calls) == 2
    assert {signal.source_type for signal in calls[0]} == {"official"}
    assert {signal.event_type for signal in calls[1]} <= {
        "flood_potential",
        "flood_report",
        "road_closure",
    }
    assert response.community.state == "none"


def test_service_enriches_history_when_latest_observed_event_is_over_one_year_old(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    old_date = now - timedelta(days=365 * 10)
    old_history = replace(
        _record(HISTORY_ID, event_type="flood_report", evidence_scope="historical"),
        occurred_at=old_date,
        observed_at=old_date,
    )
    recent_id = "00000000-0000-0000-0000-000000000099"
    recent_history = replace(
        _record(
            recent_id,
            event_type="flood_report",
            evidence_scope="historical",
            adapter_key="official.gov_tw.flood_citation",
            limitations=("行政區事件，非門牌實測。",),
        ),
        occurred_at=now - timedelta(days=7),
        observed_at=now - timedelta(days=7),
        location_precision="admin_area",
        distance_to_query_m=None,
    )
    calls: list[RiskAssessRequest] = []

    def lookup(
        request: RiskAssessRequest,
        _data: AssessmentData,
        *,
        now: datetime,
    ) -> tuple[EvidenceRecord, ...]:
        assert now == NOW
        calls.append(request)
        return (recent_history,)

    response = AssessmentService(
        FakeRepository(replace(data, historical=(old_history,))),
        score_risk,
        recent_history_lookup=lookup,
    ).assess(risk_request, now=now)

    assert calls == [risk_request]
    assert [item.id for item in response.evidence].index(recent_id) < [
        item.id for item in response.evidence
    ].index(HISTORY_ID)
    recent_preview = next(item for item in response.evidence if item.id == recent_id)
    assert recent_preview.evidence_scope == "historical"
    assert recent_preview.location_precision == "admin_area"


def test_service_skips_enrichment_when_recent_observed_history_exists(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    recent_history = replace(
        _record(HISTORY_ID, event_type="flood_report", evidence_scope="historical"),
        occurred_at=now - timedelta(days=30),
        observed_at=now - timedelta(days=30),
    )

    def fail(*_args: object, **_kwargs: object) -> tuple[EvidenceRecord, ...]:
        raise AssertionError("recent history must not trigger official news lookup")

    AssessmentService(
        FakeRepository(replace(data, historical=(recent_history,))),
        score_risk,
        recent_history_lookup=fail,
    ).assess(risk_request, now=now)


def test_service_refreshes_history_when_latest_event_is_over_30_days_old(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    previous_history = replace(
        _record(HISTORY_ID, event_type="flood_report", evidence_scope="historical"),
        occurred_at=now - timedelta(days=31),
        observed_at=now - timedelta(days=31),
    )
    calls: list[RiskAssessRequest] = []

    def lookup(
        request: RiskAssessRequest,
        _data: AssessmentData,
        *,
        now: datetime,
    ) -> tuple[EvidenceRecord, ...]:
        assert now == NOW
        calls.append(request)
        return ()

    AssessmentService(
        FakeRepository(replace(data, historical=(previous_history,))),
        score_risk,
        recent_history_lookup=lookup,
    ).assess(risk_request, now=now)

    assert calls == [risk_request]


def test_historical_scorer_missing_sources_do_not_leak_into_current_explanation(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    def scorer(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult:
        result = score_risk(signals, now=now)
        marker = (
            "目前即時資料缺口"
            if any(signal.evidence_scope == "current" for signal in signals)
            else "歷史評分器不應輸出的即時資料缺口"
        )
        return replace(result, missing_sources=(marker,))

    response = AssessmentService(FakeRepository(data), scorer).assess(risk_request, now=now)

    assert "目前即時資料缺口" in response.explanation.missing_sources
    assert "歷史評分器不應輸出的即時資料缺口" not in response.explanation.missing_sources


def test_optional_disabled_source_is_diagnostic_not_a_required_limitation(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    optional_message = "選用來源目前未啟用"
    optional_state = AssessmentSourceState(
        source_key="official.cwa.heavy_rain_warning",
        signal_type="flood_warning",
        state="disabled",
        observed_at=None,
        checked_at=now,
        message=optional_message,
    )
    response = AssessmentService(
        FakeRepository(replace(data, source_states=(*data.source_states, optional_state))),
        score_risk,
    ).assess(risk_request, now=now)

    assert any(
        source.source_key == optional_state.source_key for source in response.data_status.sources
    )
    assert optional_message not in response.data_status.missing
    assert optional_message not in response.explanation.missing_sources


def _context_records() -> tuple[EvidenceRecord, ...]:
    return (
        _record(
            POLICE_CONTEXT_ID,
            event_type="status_only",
            evidence_scope="context",
            adapter_key="official.npa.police_radio_traffic",
            limitations=(POLICE_LIMITATION,),
        ),
        _record(
            WRA_CONTEXT_ID,
            event_type="status_only",
            evidence_scope="context",
            adapter_key="official.wra.flood_warning",
            limitations=("官方警戒範圍為情境背景，尚未經淹水感測器逐點確認。",),
        ),
    )


def test_recent_context_is_display_only_and_never_changes_the_score(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    without_calls: list[tuple[RiskEvidenceSignal, ...]] = []
    with_calls: list[tuple[RiskEvidenceSignal, ...]] = []

    def _scorer(sink: list[tuple[RiskEvidenceSignal, ...]]):
        def scorer(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult:
            sink.append(signals)
            return score_risk(signals, now=now)

        return scorer

    without_context = AssessmentService(FakeRepository(data), _scorer(without_calls)).assess(
        risk_request, now=now
    )
    with_data = replace(data, recent_incident_context=_context_records())
    with_context = AssessmentService(FakeRepository(with_data), _scorer(with_calls)).assess(
        risk_request, now=now
    )

    assert with_context.realtime == without_context.realtime
    assert with_context.historical == without_context.historical
    assert with_context.overall == without_context.overall
    assert with_context.confidence == without_context.confidence
    assert with_context.explanation == without_context.explanation
    assert with_context.nearby_realtime_coverage == without_context.nearby_realtime_coverage

    assert len(with_calls) == 2
    assert with_calls == without_calls

    displayed = {item.id for item in with_context.evidence}
    assert POLICE_CONTEXT_ID in displayed
    assert WRA_CONTEXT_ID in displayed
    police = next(item for item in with_context.evidence if item.id == POLICE_CONTEXT_ID)
    assert POLICE_LIMITATION in police.limitations


def test_recent_context_is_ordered_after_current_and_before_historical(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    with_data = replace(data, recent_incident_context=_context_records())

    response = AssessmentService(FakeRepository(with_data), score_risk).assess(
        risk_request, now=now
    )

    ordered = [item.id for item in response.evidence]
    assert ordered.index(CURRENT_ID) < ordered.index(POLICE_CONTEXT_ID)
    assert ordered.index(POLICE_CONTEXT_ID) < ordered.index(HISTORY_ID)


def test_response_preview_is_not_crowded_out_by_dense_flood_sensors(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    flood_sensors = tuple(
        _record(
            f"00000000-0000-0000-0000-{index:012d}",
            event_type="flood_report",
            evidence_scope="current",
            adapter_key="local.tainan.flood_sensor",
        )
        for index in range(1, 13)
    )
    water = _record(
        "00000000-0000-0000-0000-000000000101",
        event_type="water_level",
        evidence_scope="current",
        adapter_key="official.wra.water_level",
    )
    rainfall = _record(
        "00000000-0000-0000-0000-000000000102",
        event_type="rainfall",
        evidence_scope="current",
    )
    crowded = replace(
        data,
        current_official=(*flood_sensors, water, rainfall),
    )

    response = AssessmentService(FakeRepository(crowded), score_risk).assess(risk_request, now=now)

    assert len(response.evidence) == 10
    assert {item.event_type for item in response.evidence} >= {
        "flood_report",
        "water_level",
        "rainfall",
        "flood_potential",
    }


def test_core_service_never_calls_a_community_composer() -> None:
    source = inspect.getsource(AssessmentService.assess)
    assert "compose_base_overall" in source
    assert "compose_with_community" not in source
    assert "CommunityDecision" not in source


def test_persist_failure_does_not_change_successful_response(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    response = AssessmentService(FakeRepository(data, fail_persist=True), score_risk).assess(
        risk_request, now=now
    )
    assert response.assessment_id
    assert response.overall is not None


def test_persist_programming_error_is_not_swallowed(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    repository = FakeRepository(data, programming_error=TypeError("bad persistence code"))

    with pytest.raises(TypeError, match="bad persistence code"):
        AssessmentService(repository, score_risk).assess(risk_request, now=now)


def test_persisted_snapshot_is_coarsened_and_has_no_raw_query(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    repository = FakeRepository(data)
    AssessmentService(repository, score_risk).assess(risk_request, now=now)
    snapshot = repository.persisted[0].result_snapshot
    assert snapshot["location"] == {
        "lat": round(risk_request.point.lat, 2),
        "lng": round(risk_request.point.lng, 2),
    }
    assert snapshot["location_text"] is None
    assert risk_request.location_text not in json.dumps(snapshot, ensure_ascii=False)


def test_persistence_keeps_only_valid_uuid_evidence_ids(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    repository = FakeRepository(
        replace(
            data,
            historical=(
                *data.historical,
                _record("not-a-uuid", event_type="flood_report", evidence_scope="historical"),
            ),
        )
    )

    AssessmentService(repository, score_risk).assess(risk_request, now=now)

    assert repository.persisted[0].evidence_ids == (CURRENT_ID, HISTORY_ID)
    assert repository.persisted[0].result_snapshot["evidence_ids"] == [
        CURRENT_ID,
        HISTORY_ID,
    ]


def test_required_current_read_failure_is_unknown_not_low(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    coverage = data.nearby_coverage.model_copy(
        update={
            "signal_breakdown": [
                NearbyCoverageSignal(
                    signal_type=signal_type,
                    label=signal_type,
                    coverage_level="high",
                    availability_state="fresh_nearby",
                    nearest_distance_m=20.0,
                    counts_by_radius_m={"750": 1},
                    fresh_count=1,
                    stale_count=0,
                    status_only_count=0,
                )
                for signal_type in ("rainfall", "water_level")
            ],
            "source_health_checked": True,
            "jurisdiction_checked": True,
            "jurisdiction_catalog_complete": True,
        }
    )
    available_data = replace(
        data,
        nearby_coverage=coverage,
        source_states=tuple(replace(state, state="fresh") for state in data.source_states),
        coverage_available=True,
        health_available=True,
        jurisdiction_available=True,
    )
    available_response = AssessmentService(FakeRepository(available_data), score_risk).assess(
        risk_request, now=now
    )
    response = AssessmentService(
        FakeRepository(replace(available_data, current_available=False)), score_risk
    ).assess(risk_request, now=now)

    assert available_response.realtime.level == "低"
    assert response.realtime.level == "未知"
    assert response.overall is not None
    assert response.overall.level != "低"


def test_response_uses_same_data_for_status_freshness_and_coverage(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    response = AssessmentService(FakeRepository(data), score_risk).assess(risk_request, now=now)

    assert response.nearby_realtime_coverage is data.nearby_coverage
    assert {item.source_key for item in response.data_status.sources} == {
        state.source_key for state in data.source_states
    }
    assert {item.source_id for item in response.data_freshness} == {
        state.source_key for state in data.source_states
    }
    assert "官方水位來源暫時無法使用" in response.data_status.missing
    assert "地方政府機器介面尚未核准" in response.data_status.missing
    assert response.query_heat.period == "frozen"
    assert response.query_heat.attention_level == "未知"


def test_response_preserves_evidence_precision_and_limitations(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    response = AssessmentService(FakeRepository(data), score_risk).assess(risk_request, now=now)

    current = response.evidence[0]
    assert current.location_precision == "road_or_lane"
    assert current.limitations == ["位置為道路尺度"]


@dataclass
class FakeResponseCache:
    cached: RiskAssessmentResponse | None = None
    get_calls: list[RiskAssessRequest] = field(default_factory=list)
    set_calls: list[tuple[RiskAssessRequest, RiskAssessmentResponse]] = field(
        default_factory=list
    )

    def get(
        self, request: RiskAssessRequest, *, now: datetime
    ) -> RiskAssessmentResponse | None:
        self.get_calls.append(request)
        return self.cached

    def set(
        self,
        request: RiskAssessRequest,
        response: RiskAssessmentResponse,
        *,
        now: datetime,
    ) -> None:
        self.set_calls.append((request, response))


class ExplodingRepository:
    def load(self, **_kwargs: object) -> AssessmentData:
        raise AssertionError("repository.load must not be called on a response cache hit")

    def persist(self, _assessment: RiskAssessmentPersistence) -> None:
        raise AssertionError("persist must not be called on a response cache hit")


def test_response_cache_hit_returns_cached_response_without_loading_repository(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    baseline = AssessmentService(FakeRepository(data), score_risk).assess(risk_request, now=now)
    cache = FakeResponseCache(cached=baseline)

    response = AssessmentService(
        ExplodingRepository(), score_risk, response_cache=cache
    ).assess(risk_request, now=now)

    assert response is baseline
    assert cache.get_calls == [risk_request]


def test_response_cache_is_populated_when_all_data_sources_are_available(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    available_data = replace(
        data,
        current_available=True,
        historical_available=True,
        coverage_available=True,
        health_available=True,
        jurisdiction_available=True,
    )
    cache = FakeResponseCache()

    response = AssessmentService(
        FakeRepository(available_data), score_risk, response_cache=cache
    ).assess(risk_request, now=now)

    assert cache.set_calls == [(risk_request, response)]


def test_response_cache_is_not_populated_when_current_data_is_unavailable(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    degraded_data = replace(
        data,
        current_available=False,
        historical_available=True,
        coverage_available=True,
        health_available=True,
        jurisdiction_available=True,
    )
    cache = FakeResponseCache()

    AssessmentService(
        FakeRepository(degraded_data), score_risk, response_cache=cache
    ).assess(risk_request, now=now)

    assert cache.set_calls == []


DELAYED_SUMMARY = "部分官方即時來源更新較慢（雨量、水位、下水道水位），仍可作當下參考。"
UPSTREAM_STALE_MESSAGE = "上游資料來源自 2026/08/24 03:00 起未更新；本站背景更新正常。"


def _station_count_message(fresh: int, delayed: int, active: int) -> str:
    return f"部分站點更新較慢（新鮮 {fresh}、較慢 {delayed}、活躍 {active}）。"


def _source_state(
    signal_type: str,
    *,
    state: str,
    message: str | None,
    now: datetime,
) -> AssessmentSourceState:
    return AssessmentSourceState(
        source_key=f"official.test.{signal_type}",
        signal_type=signal_type,
        state=state,  # type: ignore[arg-type]
        observed_at=now,
        checked_at=now,
        message=message,
    )


def _required_source_data(
    data: AssessmentData,
    states: tuple[AssessmentSourceState, ...],
) -> AssessmentData:
    """Isolate required-source messages from the other data-gap channels."""

    return replace(
        data,
        source_states=states,
        required_realtime_source_keys=frozenset(state.source_key for state in states),
        local_machine_feed_missing=(),
        coverage_available=True,
        health_available=True,
        jurisdiction_available=True,
    )


def test_degraded_required_sources_collapse_into_one_user_facing_sentence(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    states = (
        _source_state(
            "sewer_water_level",
            state="degraded",
            message=_station_count_message(0, 288, 358),
            now=now,
        ),
        _source_state(
            "water_level",
            state="degraded",
            message=_station_count_message(0, 1317, 1342),
            now=now,
        ),
        _source_state(
            "rainfall",
            state="degraded",
            message=_station_count_message(0, 1770, 1998),
            now=now,
        ),
    )

    response = AssessmentService(
        FakeRepository(_required_source_data(data, states)), score_risk
    ).assess(risk_request, now=now)

    assert response.data_status.missing == [DELAYED_SUMMARY]
    assert "新鮮" not in "".join(response.explanation.missing_sources)
    assert [source.message for source in response.data_status.sources] == [
        state.message for state in states
    ]


def test_failed_required_source_keeps_its_own_message_beside_the_summary(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    failed_message = "官方水位來源暫時無法使用。"
    states = (
        _source_state("water_level", state="failed", message=failed_message, now=now),
        _source_state(
            "rainfall",
            state="degraded",
            message=_station_count_message(0, 1770, 1998),
            now=now,
        ),
        _source_state(
            "sewer_water_level",
            state="degraded",
            message=_station_count_message(0, 288, 358),
            now=now,
        ),
    )

    response = AssessmentService(
        FakeRepository(_required_source_data(data, states)), score_risk
    ).assess(risk_request, now=now)

    assert response.data_status.missing == [
        failed_message,
        "部分官方即時來源更新較慢（雨量、下水道水位），仍可作當下參考。",
    ]


def test_fresh_required_sources_report_no_user_facing_gap(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    states = (
        _source_state("rainfall", state="fresh", message=None, now=now),
        _source_state("water_level", state="fresh", message=None, now=now),
    )

    response = AssessmentService(
        FakeRepository(_required_source_data(data, states)), score_risk
    ).assess(risk_request, now=now)

    assert response.data_status.missing == []


def test_upstream_stale_message_is_kept_verbatim_and_only_once(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    states = (
        _source_state(
            "water_level",
            state="degraded",
            message=UPSTREAM_STALE_MESSAGE,
            now=now,
        ),
        _source_state(
            "sewer_water_level",
            state="degraded",
            message=UPSTREAM_STALE_MESSAGE,
            now=now,
        ),
        _source_state(
            "rainfall",
            state="degraded",
            message=_station_count_message(0, 1770, 1998),
            now=now,
        ),
    )

    response = AssessmentService(
        FakeRepository(_required_source_data(data, states)), score_risk
    ).assess(risk_request, now=now)

    assert response.data_status.missing == [
        UPSTREAM_STALE_MESSAGE,
        "部分官方即時來源更新較慢（雨量），仍可作當下參考。",
    ]


def test_explanation_missing_sources_matches_data_status_missing(
    now: datetime,
    risk_request: RiskAssessRequest,
    data: AssessmentData,
) -> None:
    def scorer(signals: tuple[RiskEvidenceSignal, ...], *, now: datetime) -> RiskScoringResult:
        # Isolate the source-state channel from scorer-authored gaps.
        return replace(score_risk(signals, now=now), missing_sources=(), realtime_level="未知")

    states = (
        _source_state("water_level", state="failed", message="官方水位來源暫時無法使用。", now=now),
        _source_state(
            "rainfall",
            state="degraded",
            message=_station_count_message(0, 1770, 1998),
            now=now,
        ),
    )

    response = AssessmentService(
        FakeRepository(_required_source_data(data, states)), scorer
    ).assess(risk_request, now=now)

    assert response.explanation.missing_sources == response.data_status.missing
    assert response.data_status.missing == [
        "官方水位來源暫時無法使用。",
        "部分官方即時來源更新較慢（雨量），仍可作當下參考。",
    ]
