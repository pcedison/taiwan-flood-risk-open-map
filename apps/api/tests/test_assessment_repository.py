from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.assessment.repository import (
    PostgresAssessmentRepository,
    _complete_signal_types,
    _historical_only,
    _official_current,
)
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    NearbyCoverageRow,
    RealtimeJurisdictionContext,
    RealtimeJurisdictionSignalContract,
    RealtimeJurisdictionSourceMapping,
    RealtimeSourceHealthRow,
    RiskAssessmentPersistence,
)
from app.domain.evidence.repository import _official_event_origin_key

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
POINT = {"lat": 22.9997, "lng": 120.2270, "radius_m": 750, "as_of": NOW}


def _record(
    id: str,
    *,
    adapter_key: str = "official.cwa.rainfall",
    source_type: str = "official",
    event_type: str = "rainfall",
    evidence_scope: str = "current",
    origin: str | None = None,
    observed_at: datetime | None = NOW,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=id,
        source_id=f"source:{id}",
        source_type=source_type,
        event_type=event_type,
        title=id,
        summary=id,
        url=None,
        occurred_at=observed_at,
        observed_at=observed_at,
        ingested_at=NOW,
        lat=22.9997,
        lng=120.2270,
        geometry={"type": "Point", "coordinates": [120.2270, 22.9997]},
        distance_to_query_m=20.0,
        confidence=0.9,
        freshness_score=0.9,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=None,
        evidence_scope=evidence_scope,
        adapter_key=adapter_key,
        official_event_origin_key=origin,
    )


LATEST = _record("latest")
HISTORY = _record(
    "history",
    adapter_key="official.wra.water_level",
    event_type="water_level",
    evidence_scope="historical",
)
OBSERVED_FLOOD_HISTORY = _record(
    "observed-flood-history",
    adapter_key="local.tainan.flood_sensor",
    event_type="flood_report",
    evidence_scope="historical",
    observed_at=NOW - timedelta(days=14),
)
POLICE_CONTEXT = _record(
    "police-context",
    adapter_key="official.npa.police_radio_traffic",
    event_type="status_only",
    evidence_scope="context",
)
WRA_CONTEXT = _record(
    "wra-context",
    adapter_key="official.wra.flood_warning",
    event_type="status_only",
    evidence_scope="context",
)


def _mapping(
    adapter_key: str,
    signal_type: str,
    *,
    role: str = "required",
    jurisdiction_code: str = "67000000",
    revision: str = "2026-08-24-v1-baseline",
    redundancy_of_adapter_key: str | None = None,
) -> RealtimeJurisdictionSourceMapping:
    return RealtimeJurisdictionSourceMapping(
        adapter_key=adapter_key,
        signal_type=signal_type,
        coverage_scope="national" if adapter_key.startswith("official.") else "local",
        jurisdiction_code=jurisdiction_code,
        jurisdiction_name="臺南市",
        requirement_role=role,
        mapping_revision=revision,
        redundancy_of_adapter_key=redundancy_of_adapter_key,
    )


def _context(
    code: str = "67000000",
    name: str = "臺南市",
    mappings: tuple[RealtimeJurisdictionSourceMapping, ...] | None = None,
    additional_contracts: tuple[RealtimeJurisdictionSignalContract, ...] = (),
) -> RealtimeJurisdictionContext:
    resolved_mappings = mappings or (
        _mapping("official.cwa.rainfall", "rainfall", jurisdiction_code=code),
        _mapping("official.wra.water_level", "water_level", jurisdiction_code=code),
        _mapping("official.wra_iow.flood_depth", "flood_depth", jurisdiction_code=code),
    )
    contracts = tuple(
        RealtimeJurisdictionSignalContract(
            jurisdiction_code=code,
            jurisdiction_name=name,
            signal_type=signal_type,
            catalog_status="reviewed_complete",
            mapping_revision="2026-08-24-v1-baseline",
            mapping_proof_valid=True,
        )
        for signal_type in ("rainfall", "water_level", "flood_depth")
    ) + additional_contracts
    return RealtimeJurisdictionContext(
        resolution_status="verified",
        home_jurisdiction_code=code,
        home_jurisdiction_name=name,
        considered_jurisdictions=((code, name),),
        signal_contracts=contracts,
        source_mappings=resolved_mappings,
    )


def _unavailable(**_kwargs):
    raise EvidenceRepositoryUnavailable("read unavailable")


def _repository(monkeypatch: pytest.MonkeyPatch, **overrides) -> PostgresAssessmentRepository:
    import app.domain.assessment.repository as module

    values = {
        "query_realtime_jurisdiction_context": lambda **_: _context(),
        "query_nearby_latest_official": lambda **_: (LATEST,),
        "query_nearby_evidence": lambda **_: (HISTORY,),
        "query_nearby_observed_flood_history": lambda **_: (),
        "query_nearby_realtime_coverage_rows": lambda **_: (),
        "query_realtime_source_health_rows": lambda **_: (),
        "query_nearby_recent_context": lambda **_: (POLICE_CONTEXT, WRA_CONTEXT),
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setattr(module, name, value)
    return PostgresAssessmentRepository("postgresql://example.test/flood")


def test_repository_resolves_jurisdiction_from_point_not_client_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    repository = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **kwargs: captured.update(kwargs) or _context(),
    )

    signature = inspect.signature(PostgresAssessmentRepository.load)
    assert "admin_code" not in signature.parameters
    repository.load(**POINT)

    assert captured == {
        "database_url": "postgresql://example.test/flood",
        "lat": 22.9997,
        "lng": 120.227,
        "search_radius_m": 750,
    }


def test_current_reader_uses_reviewed_realtime_support_radius(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    repository = _repository(
        monkeypatch,
        query_nearby_latest_official=lambda **kwargs: captured.update(kwargs) or (LATEST,),
    )

    repository.load(**POINT)

    assert captured["radius_m"] == 5_000
    assert captured["as_of"] == NOW


def test_latest_failure_keeps_historical_result(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _repository(monkeypatch, query_nearby_latest_official=_unavailable).load(**POINT)
    assert data.current_available is False
    assert data.historical_available is True
    assert data.historical == (HISTORY,)


def test_history_failure_keeps_current_result(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _repository(monkeypatch, query_nearby_evidence=_unavailable).load(**POINT)
    assert data.current_available is True
    assert data.historical_available is False
    assert data.current_official == (LATEST,)


def test_retained_positive_sensor_observation_enters_historical_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    data = _repository(
        monkeypatch,
        query_nearby_observed_flood_history=(
            lambda **kwargs: captured.update(kwargs) or (OBSERVED_FLOOD_HISTORY,)
        ),
    ).load(**POINT)

    assert data.historical == (OBSERVED_FLOOD_HISTORY, HISTORY)
    assert data.historical_available is True
    assert captured["radius_m"] == 1_000
    assert captured["as_of"] == NOW


def test_observed_flood_history_failure_marks_history_incomplete_but_keeps_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _repository(
        monkeypatch,
        query_nearby_observed_flood_history=_unavailable,
    ).load(**POINT)

    assert data.historical == (HISTORY,)
    assert data.historical_available is False


@pytest.mark.parametrize(
    ("boundary", "function"),
    [
        ("coverage", "query_nearby_realtime_coverage_rows"),
        ("health", "query_realtime_source_health_rows"),
        ("jurisdiction", "query_realtime_jurisdiction_context"),
    ],
)
def test_coverage_health_and_jurisdiction_fail_independently(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    function: str,
) -> None:
    data = _repository(monkeypatch, **{function: _unavailable}).load(**POINT)
    assert data.current_official == (LATEST,)
    assert data.historical == (HISTORY,)
    assert getattr(data, f"{boundary}_available") is False


def test_load_keeps_current_historical_and_context_disjoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _repository(monkeypatch).load(**POINT)

    assert data.current_official == (LATEST,)
    assert data.historical == (HISTORY,)
    assert data.recent_incident_context == (POLICE_CONTEXT, WRA_CONTEXT)


def test_recent_context_reader_receives_the_selected_radius_and_as_of(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    repository = _repository(
        monkeypatch,
        query_nearby_recent_context=lambda **kwargs: captured.update(kwargs) or (),
    )

    repository.load(**POINT)

    assert captured["radius_m"] == 750
    assert captured["as_of"] == NOW
    assert captured["lat"] == 22.9997
    assert captured["lng"] == 120.227


def test_recent_context_failure_never_degrades_current_or_historical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _repository(monkeypatch, query_nearby_recent_context=_unavailable).load(**POINT)

    assert data.recent_incident_context == ()
    assert data.current_official == (LATEST,)
    assert data.historical == (HISTORY,)
    assert data.current_available is True
    assert data.historical_available is True


def test_historical_only_rejects_status_only_context_rows() -> None:
    records = (POLICE_CONTEXT, WRA_CONTEXT, HISTORY)

    assert {item.id for item in _historical_only(records)} == {"history"}


def test_assessment_data_context_field_defaults_to_empty() -> None:
    from app.domain.assessment.models import AssessmentData

    fields = list(AssessmentData.__dataclass_fields__)
    assert fields[-1] == "recent_incident_context"
    assert AssessmentData.__dataclass_fields__[
        "recent_incident_context"
    ].default_factory() == ()


def test_recent_news_forum_and_social_never_enter_core_scoring_partitions() -> None:
    records = (
        _record("news", source_type="news", evidence_scope="historical"),
        _record("forum", source_type="forum", evidence_scope="historical"),
        _record("social", source_type="social", evidence_scope="historical"),
        _record(
            "potential",
            source_type="derived",
            event_type="flood_potential",
            evidence_scope="context",
        ),
        HISTORY,
    )
    assert {item.id for item in _historical_only(records)} == {"potential", "history"}


def test_historical_or_context_scope_never_enters_current_even_if_latest_is_dirty() -> None:
    records = (
        _record("history-dirty", evidence_scope="historical"),
        _record("context-dirty", event_type="flood_warning", evidence_scope="context"),
        LATEST,
    )
    assert _official_current(records) == (LATEST,)


def test_same_cap_republished_by_ncdr_is_scored_once() -> None:
    origin = _official_event_origin_key(
        sender="sender@example.tw",
        identifier="same-cap",
        sent=NOW,
        admin_code="67000000",
    )
    cwa = _record(
        "cwa-cap",
        adapter_key="official.cwa.heavy_rain_warning",
        event_type="flood_warning",
        origin=origin,
    )
    ncdr = _record(
        "ncdr-cap",
        adapter_key="official.ncdr.cap",
        event_type="flood_warning",
        origin=origin,
        observed_at=NOW + timedelta(minutes=1),
    )
    assert _official_current((ncdr, cwa)) == (cwa,)


def test_cap_origin_requires_exact_sender_identifier_sent_and_admin() -> None:
    components = (
        ("sender@example.tw", "alert-1", NOW, "67000000"),
        ("other@example.tw", "alert-1", NOW, "67000000"),
        ("sender@example.tw", "alert-2", NOW, "67000000"),
        ("sender@example.tw", "alert-1", NOW + timedelta(seconds=1), "67000000"),
        ("sender@example.tw", "alert-1", NOW, "64000000"),
    )
    origins = tuple(
        _official_event_origin_key(
            sender=sender,
            identifier=identifier,
            sent=sent,
            admin_code=admin_code,
        )
        for sender, identifier, sent, admin_code in components
    )
    records = tuple(
        _record(
            f"cap-{index}",
            adapter_key="official.ncdr.cap",
            event_type="flood_warning",
            origin=origin,
        )
        for index, origin in enumerate(origins)
    )
    assert len(set(origins)) == 5
    assert len(_official_current(records)) == 5


def test_enabled_but_unmapped_legacy_source_cannot_score_or_satisfy_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = _record("legacy", adapter_key="local.legacy.tide", event_type="water_level")
    local = _record(
        "tainan",
        adapter_key="local.tainan.flood_sensor",
        event_type="flood_report",
    )
    mappings = (_mapping("local.tainan.flood_sensor", "flood_depth"),)
    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: _context(mappings=mappings),
        query_nearby_latest_official=lambda **_: (legacy, local),
    ).load(**POINT)
    assert data.current_official == (local,)


def test_jurisdiction_read_failure_keeps_only_reviewed_national_current_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tainan = _record("tainan", adapter_key="local.tainan.flood_sensor")
    legacy = _record("legacy", adapter_key="local.legacy.tide")
    wra_current = _record(
        "wra-current", adapter_key="official.wra.water_level", event_type="water_level"
    )
    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=_unavailable,
        query_nearby_latest_official=lambda **_: (LATEST, wra_current, tainan, legacy),
    ).load(**POINT)
    assert {item.adapter_key for item in data.current_official} == {
        "official.cwa.rainfall",
        "official.wra.water_level",
    }
    assert data.jurisdiction_available is False


def test_missing_required_health_row_synthesizes_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _repository(monkeypatch).load(**POINT)
    state = next(item for item in data.source_states if item.source_key == "official.cwa.rainfall")
    assert state.state == "disabled"


def test_redundant_warning_mapping_is_applicable_but_not_required_for_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "2026-08-28-v1-warning-alignment"
    mappings = (
        _mapping("official.ncdr.cap", "flood_warning", revision=revision),
        _mapping(
            "official.cwa.heavy_rain_warning",
            "flood_warning",
            role="redundant_subset",
            revision=revision,
            redundancy_of_adapter_key="official.ncdr.cap",
        ),
    )
    jurisdiction = _context(mappings=mappings)

    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: jurisdiction,
    ).load(**POINT)

    assert data.required_realtime_source_keys == frozenset({"official.ncdr.cap"})
    assert {mapping.adapter_key for mapping in jurisdiction.source_mappings} >= {
        "official.ncdr.cap",
        "official.cwa.heavy_rain_warning",
    }


def test_reviewed_sewer_mapping_reaches_public_coverage_and_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_key = "official.civil_iot.sewer_water_level"
    revision = "2026-08-29-sewer-publication"
    mapping = _mapping(adapter_key, "sewer_water_level", revision=revision)
    sewer_contract = RealtimeJurisdictionSignalContract(
        jurisdiction_code="67000000",
        jurisdiction_name="臺南市",
        signal_type="sewer_water_level",
        catalog_status="reviewed_complete",
        mapping_revision=revision,
        mapping_proof_valid=True,
    )
    jurisdiction = _context(
        mappings=(mapping,),
        additional_contracts=(sewer_contract,),
    )
    nearby = NearbyCoverageRow(
        adapter_key=adapter_key,
        source_id="sewer-001:2026-08-24T03:58:00+00:00",
        event_type="water_level",
        station_id="sewer-001",
        observed_at=NOW - timedelta(minutes=2),
        ingested_at=NOW,
        distance_to_query_m=6_144.5,
        freshness_state="fresh",
    )
    health = RealtimeSourceHealthRow(
        adapter_key=adapter_key,
        name="Civil IoT sewer water level",
        is_enabled=True,
        configured_health_status="healthy",
        last_success_at=NOW,
        last_failure_at=None,
        latest_run_status="succeeded",
        latest_run_at=NOW,
        latest_observed_at=NOW - timedelta(minutes=2),
        latest_ingested_at=NOW,
        station_count=2_033,
        inventory_complete=True,
        fresh_station_count=2_033,
    )
    sewer_current = _record(
        "sewer-current",
        adapter_key=adapter_key,
        event_type="water_level",
    )
    health_query: dict[str, object] = {}

    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: jurisdiction,
        query_nearby_latest_official=lambda **_: (sewer_current,),
        query_nearby_realtime_coverage_rows=lambda **_: (nearby,),
        query_realtime_source_health_rows=lambda **kwargs: (
            health_query.update(kwargs) or (health,)
        ),
    ).load(**POINT)

    assert health_query["adapter_keys"] == (adapter_key,)
    assert data.current_official == ()
    sewer = next(
        item
        for item in data.nearby_coverage.signal_breakdown
        if item.signal_type == "sewer_water_level"
    )
    assert sewer.nearest_distance_m == 6_144.5
    assert sewer.missing_cause != "source_not_configured"
    assert {item.source_id for item in data.nearby_coverage.source_health} == {
        "official-civil-iot-sewer-water-level"
    }

    no_station = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: jurisdiction,
        query_nearby_latest_official=lambda **_: (sewer_current,),
        query_nearby_realtime_coverage_rows=lambda **_: (),
        query_realtime_source_health_rows=lambda **_: (health,),
    ).load(**POINT)
    sewer_without_station = next(
        item
        for item in no_station.nearby_coverage.signal_breakdown
        if item.signal_type == "sewer_water_level"
    )
    assert sewer_without_station.missing_cause == "no_station_in_range"
    assert "sewer_water_level" not in no_station.nearby_coverage.jurisdiction_unverified_signal_types


def test_kaohsiung_gap_comes_from_server_resolved_home_jurisdiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: _context("64000000", "高雄市"),
    ).load(**POINT)
    assert data.resolved_admin_code == "64000000"
    assert data.local_machine_feed_missing == ("高雄市地方政府機器介面尚未核准",)


def test_tainan_gap_clears_only_for_fresh_or_degraded_mapped_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _mapping("local.tainan.flood_sensor", "flood_depth")
    health = RealtimeSourceHealthRow(
        adapter_key="local.tainan.flood_sensor",
        name="臺南淹水感測",
        is_enabled=True,
        configured_health_status="healthy",
        last_success_at=NOW,
        last_failure_at=None,
        latest_run_status="succeeded",
        latest_run_at=NOW,
        latest_observed_at=NOW,
        latest_ingested_at=NOW,
        station_count=1,
        inventory_complete=True,
        fresh_station_count=1,
    )
    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: _context(mappings=(mapping,)),
        query_realtime_source_health_rows=lambda **_: (health,),
    ).load(**POINT)
    assert data.local_machine_feed_missing == ()


def test_tainan_gap_describes_a_current_update_failure_not_a_missing_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = _mapping("local.tainan.flood_sensor", "flood_depth")
    data = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: _context(
            "67000000",
            "臺南市",
            mappings=(mapping,),
        ),
        query_realtime_source_health_rows=lambda **_: (),
    ).load(**POINT)

    assert data.local_machine_feed_missing == (
        "臺南市地方淹水感測目前暫無可用更新",
    )
    assert "尚未可用" not in data.local_machine_feed_missing[0]


def test_completeness_requires_every_considered_jurisdiction_per_required_signal() -> None:
    contracts = tuple(
        RealtimeJurisdictionSignalContract(
            jurisdiction_code=code,
            jurisdiction_name=name,
            signal_type=signal_type,
            catalog_status=(
                "reviewed_complete"
                if not (code == "64000000" and signal_type == "water_level")
                else "unreviewed"
            ),
            mapping_revision="2026-08-24-v1-baseline",
            mapping_proof_valid=not (
                code == "64000000" and signal_type == "water_level"
            ),
        )
        for code, name in (("67000000", "臺南市"), ("64000000", "高雄市"))
        for signal_type in ("rainfall", "water_level", "flood_depth")
    )
    context = RealtimeJurisdictionContext(
        resolution_status="verified",
        home_jurisdiction_code="67000000",
        home_jurisdiction_name="臺南市",
        considered_jurisdictions=(("67000000", "臺南市"), ("64000000", "高雄市")),
        signal_contracts=contracts,
        source_mappings=(),
    )

    assert _complete_signal_types(context) == ("flood_depth", "rainfall")


def test_completeness_accepts_only_the_reviewed_sewer_revision() -> None:
    reviewed = RealtimeJurisdictionSignalContract(
        jurisdiction_code="67000000",
        jurisdiction_name="臺南市",
        signal_type="sewer_water_level",
        catalog_status="reviewed_complete",
        mapping_revision="2026-08-29-sewer-publication",
        mapping_proof_valid=True,
    )
    stale_revision = RealtimeJurisdictionSignalContract(
        jurisdiction_code="67000000",
        jurisdiction_name="臺南市",
        signal_type="sewer_water_level",
        catalog_status="reviewed_complete",
        mapping_revision="2026-08-24-v1-baseline",
        mapping_proof_valid=True,
    )

    assert "sewer_water_level" in _complete_signal_types(
        _context(additional_contracts=(reviewed,))
    )
    assert "sewer_water_level" not in _complete_signal_types(
        _context(additional_contracts=(stale_revision,))
    )


def _persistence_record() -> RiskAssessmentPersistence:
    return RiskAssessmentPersistence(
        assessment_id="d315d0e6-9c1e-475a-9118-f299d12d5c62",
        lat=22.9997,
        lng=120.227,
        radius_m=750,
        score_version="risk-v1",
        realtime_score=12.0,
        historical_score=23.0,
        confidence_score=0.8,
        realtime_level="中",
        historical_level="中",
        overall_level="中",
        dominant_mode="realtime",
        explanation={"summary": "persist boundary"},
        data_freshness=[],
        result_snapshot={"assessment_id": "d315d0e6-9c1e-475a-9118-f299d12d5c62"},
        evidence_ids=(),
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def test_persist_delegates_to_existing_evidence_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.domain.assessment.repository as module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        module,
        "persist_risk_assessment",
        lambda **kwargs: captured.update(kwargs),
    )
    assessment = _persistence_record()

    PostgresAssessmentRepository("postgresql://example.test/flood").persist(assessment)

    assert captured == {
        "database_url": "postgresql://example.test/flood",
        "assessment": assessment,
    }


def test_disabled_repository_persist_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.domain.assessment.repository as module

    monkeypatch.setattr(
        module,
        "persist_risk_assessment",
        lambda **_: pytest.fail("disabled repository must not persist"),
    )

    PostgresAssessmentRepository(
        "postgresql://example.test/flood", enabled=False
    ).persist(_persistence_record())


def test_disabled_repository_reports_every_read_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.domain.assessment.repository as module

    monkeypatch.setattr(
        module,
        "query_nearby_latest_official",
        lambda **_: pytest.fail("disabled repository must not query"),
    )
    data = PostgresAssessmentRepository("postgresql://example.test/flood", enabled=False).load(
        **POINT
    )
    assert not any(
        (
            data.current_available,
            data.historical_available,
            data.coverage_available,
            data.health_available,
            data.jurisdiction_available,
        )
    )


def test_verified_jurisdiction_without_mappings_reports_mapping_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is the production state: the boundary snapshot activates, so the point
    # resolves to a home county, but no source mapping matches the revision the
    # query demands.  applicable_keys is then empty, every evidence row is filtered
    # out and the health table is never read.  Calling that "source not configured"
    # blames the operator for a catalog fault and lets monitoring excuse it.
    empty_context = RealtimeJurisdictionContext(
        resolution_status="verified",
        home_jurisdiction_code="63000000",
        home_jurisdiction_name="臺北市",
        considered_jurisdictions=(("63000000", "臺北市"),),
        signal_contracts=(),
        source_mappings=(),
    )
    repository = _repository(
        monkeypatch,
        query_realtime_jurisdiction_context=lambda **_: empty_context,
    )

    data = repository.load(**POINT)

    rainfall = next(
        item
        for item in data.nearby_coverage.signal_breakdown
        if item.signal_type == "rainfall"
    )
    assert rainfall.missing_cause == "jurisdiction_mapping_missing"


GOV_CITATION = _record(
    "gov-citation",
    adapter_key="official.gov_tw.flood_citation",
    event_type="flood_report",
    evidence_scope="historical",
    observed_at=NOW - timedelta(days=3),
)


def test_excluded_adapter_keys_drop_persisted_request_time_lookups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository(
        monkeypatch,
        query_nearby_evidence=lambda **_: (HISTORY, GOV_CITATION),
        query_nearby_observed_flood_history=lambda **_: (GOV_CITATION, OBSERVED_FLOOD_HISTORY),
    )
    repository = PostgresAssessmentRepository(
        "postgresql://example.test/flood",
        excluded_adapter_keys=frozenset({"official.gov_tw.flood_citation"}),
    )

    data = repository.load(**POINT)

    assert [item.id for item in data.historical] == ["observed-flood-history", "history"]
    assert data.historical_available is True


def test_excluded_adapter_keys_default_to_keeping_every_persisted_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(
        monkeypatch,
        query_nearby_evidence=lambda **_: (HISTORY, GOV_CITATION),
    )

    data = repository.load(**POINT)

    assert "gov-citation" in [item.id for item in data.historical]
