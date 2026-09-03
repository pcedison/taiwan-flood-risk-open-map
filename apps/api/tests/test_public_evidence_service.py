from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.api.services import public_evidence
from app.domain.evidence import EvidenceRecord, HistoricalEvidencePagePosition
from app.domain.history import HistoricalFloodRecord
from app.domain.realtime import OfficialRealtimeObservation


def _record(
    *,
    evidence_id: str,
    source_id: str,
    event_type: str,
    occurred_at: datetime,
    observed_at: datetime | None = None,
    distance_to_query_m: float = 100.0,
    url: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        source_id=source_id,
        source_type="official",
        event_type=event_type,
        title=f"official {event_type}",
        summary=f"official {event_type} summary",
        url=url,
        occurred_at=occurred_at,
        observed_at=observed_at,
        ingested_at=datetime(2026, 8, 24, tzinfo=UTC),
        lat=23.0,
        lng=120.2,
        geometry={"type": "Point", "coordinates": [120.2, 23.0]},
        distance_to_query_m=distance_to_query_m,
        confidence=0.9,
        freshness_score=0.8,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=f"raw:{source_id}",
    )


@pytest.mark.parametrize(
    ("event_type", "expected_url"),
    [
        ("rainfall", "https://data.gov.tw/dataset/9177"),
        ("water_level", "https://data.gov.tw/dataset/25768"),
        ("flood_potential", "https://data.gov.tw/dataset/25766"),
        ("flood_report", "https://data.gov.tw/dataset/130016"),
    ],
)
def test_official_evidence_uses_canonical_data_gov_url(
    event_type: str,
    expected_url: str,
) -> None:
    evidence = public_evidence.evidence_from_record(
        _record(
            evidence_id=f"evidence:{event_type}",
            source_id=f"official:{event_type}",
            event_type=event_type,
            occurred_at=datetime(2024, 7, 25, tzinfo=UTC),
        )
    )

    assert evidence.url == expected_url


def test_official_evidence_preserves_adapter_specific_source_url() -> None:
    tainan_url = (
        "https://data.tainan.gov.tw/DataSet/Detail/"
        "03dd4536-3fe7-46ec-9920-a120cb5c502c"
    )
    evidence = public_evidence.evidence_from_record(
        _record(
            evidence_id="tainan-current-flood-depth",
            source_id="362:2026-08-29T02:00:00Z",
            event_type="flood_report",
            occurred_at=datetime(2026, 8, 29, 2, tzinfo=UTC),
            observed_at=datetime(2026, 8, 29, 2, tzinfo=UTC),
            url=tainan_url,
        )
    )

    assert evidence.url == tainan_url


def test_generated_realtime_and_historical_evidence_publish_explicit_scope() -> None:
    observed_at = datetime(2026, 8, 29, tzinfo=UTC)
    realtime = public_evidence.official_realtime_evidence(
        OfficialRealtimeObservation(
            source_id="cwa:rainfall:demo",
            source_name="CWA rainfall",
            event_type="rainfall",
            title="Nearby rainfall",
            summary="1-hour rainfall 0 mm",
            observed_at=observed_at,
            ingested_at=observed_at,
            lat=23.0,
            lng=120.2,
            distance_to_query_m=400.0,
            confidence=0.95,
            freshness_score=1.0,
            source_weight=1.0,
            risk_factor=0.0,
        )
    )
    historical = public_evidence.historical_record_evidence(
        HistoricalFloodRecord(
            source_id="history:demo",
            source_name="Historical flood record",
            source_type="official",
            event_type="flood_report",
            title="Historical flood",
            summary="Reviewed historical flood record",
            url="https://data.gov.tw/dataset/130016",
            occurred_at=datetime(2020, 8, 1, tzinfo=UTC),
            ingested_at=observed_at,
            lat=23.0,
            lng=120.2,
            confidence=0.9,
            freshness_score=1.0,
            source_weight=1.0,
            risk_factor=1.0,
        ),
        distance_to_query_m=500.0,
    )

    assert realtime.evidence_scope == "current"
    assert public_evidence.evidence_preview(realtime).evidence_scope == "current"
    assert historical.evidence_scope == "historical"
    assert public_evidence.evidence_preview(historical).evidence_scope == "historical"


def test_annual_historical_record_never_fabricates_an_exact_date() -> None:
    annual = public_evidence.historical_record_evidence(
        HistoricalFloodRecord(
            source_id="data-gov-130016:2025:demo:1",
            source_name="官方淹水災點",
            source_type="official",
            event_type="flood_report",
            title="2025 官方淹水災點",
            summary="來源只提供年度。",
            url="https://data.gov.tw/dataset/130016",
            occurred_at=None,
            ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
            lat=23.0,
            lng=120.2,
            confidence=0.9,
            freshness_score=0.8,
            source_weight=1.0,
            risk_factor=1.0,
            event_year=2025,
            temporal_precision="year",
        ),
        distance_to_query_m=100.0,
    )

    assert annual.event_year == 2025
    assert annual.temporal_precision == "year"
    assert annual.occurred_at is None
    assert annual.observed_at is None
    assert annual.event_start_at is None
    assert annual.event_end_at is None


def test_history_cursor_round_trip_is_bound_to_assessment() -> None:
    assessment_id = "d315d0e6-9c1e-475a-9118-f299d12d5c62"
    position = HistoricalEvidencePagePosition(
        event_year=2025,
        event_time=datetime(2025, 1, 1, tzinfo=UTC),
        evidence_id="b3f22a36-7316-4e2a-92b6-c6f6443c8528",
    )

    cursor = public_evidence.encode_history_cursor(
        assessment_id=assessment_id,
        position=position,
    )

    assert public_evidence.decode_history_cursor(
        cursor,
        assessment_id=assessment_id,
    ) == position
    with pytest.raises(ValueError, match="invalid history cursor"):
        public_evidence.decode_history_cursor(
            cursor,
            assessment_id="018f3bd2-6e4a-7b10-8d21-3d7fd9676c11",
        )


@pytest.mark.parametrize("cursor", ["%%%", "e30", "", "a" * 2049])
def test_history_cursor_rejects_malformed_values(cursor: str) -> None:
    with pytest.raises(ValueError, match="invalid history cursor"):
        public_evidence.decode_history_cursor(
            cursor,
            assessment_id="d315d0e6-9c1e-475a-9118-f299d12d5c62",
        )


def test_history_page_uses_extra_row_to_emit_stable_cursor() -> None:
    assessment_id = "d315d0e6-9c1e-475a-9118-f299d12d5c62"
    base = _record(
        evidence_id="b3f22a36-7316-4e2a-92b6-c6f6443c8528",
        source_id="history:1",
        event_type="flood_report",
        occurred_at=datetime(2025, 8, 1, tzinfo=UTC),
    )
    records = (
        replace(base, event_year=2025, temporal_precision="instant"),
        replace(
            base,
            id="62f677b5-ae0c-44d7-9e65-f0567a92a5ca",
            source_id="history:2",
            occurred_at=datetime(2024, 8, 1, tzinfo=UTC),
            event_year=2024,
            temporal_precision="instant",
        ),
        replace(
            base,
            id="0ca7e95a-7cfa-4e8d-b7e3-a0ca4b1836ec",
            source_id="history:3",
            occurred_at=datetime(2023, 8, 1, tzinfo=UTC),
            event_year=2023,
            temporal_precision="instant",
        ),
    )
    calls: list[dict[str, object]] = []

    def fetch_history(**kwargs: object) -> tuple[EvidenceRecord, ...]:
        calls.append(kwargs)
        return records

    page = public_evidence.list_assessment_history(
        assessment_id,
        cursor=None,
        page_size=2,
        fetch_history=fetch_history,
    )

    assert [item.id for item in page.items] == [records[0].id, records[1].id]
    assert page.next_cursor is not None
    assert calls == [
        {"assessment_id": assessment_id, "page_size": 2, "after": None}
    ]
    decoded = public_evidence.decode_history_cursor(
        page.next_cursor,
        assessment_id=assessment_id,
    )
    assert decoded.event_year == 2024
    assert decoded.evidence_id == records[1].id


def test_display_evidence_preserves_and_sorts_official_disaster_points_newest_first() -> None:
    closest_older = public_evidence.evidence_from_record(
        _record(
            evidence_id="disaster:older",
            source_id="data-gov-130016:older",
            event_type="flood_report",
            occurred_at=datetime(2020, 8, 1, tzinfo=UTC),
            distance_to_query_m=45.0,
        )
    )
    farther_latest = public_evidence.evidence_from_record(
        _record(
            evidence_id="disaster:latest",
            source_id="data-gov-130016:latest",
            event_type="flood_report",
            occurred_at=datetime(2024, 7, 25, tzinfo=UTC),
            observed_at=datetime(2024, 7, 26, tzinfo=UTC),
            distance_to_query_m=180.0,
        )
    )

    displayed = public_evidence.display_evidence_items(
        [closest_older, farther_latest]
    )
    reversed_displayed = public_evidence.display_evidence_items(
        [farther_latest, closest_older]
    )

    assert [item.id for item in displayed] == ["disaster:latest", "disaster:older"]
    assert [item.id for item in reversed_displayed] == [
        "disaster:latest",
        "disaster:older",
    ]


def test_display_evidence_sorts_year_precision_history_by_event_year() -> None:
    base = _record(
        evidence_id="annual:older",
        source_id="data-gov-130016:2021:demo:1",
        event_type="flood_report",
        occurred_at=datetime(2021, 1, 1, tzinfo=UTC),
    )
    older = public_evidence.evidence_from_record(
        replace(
            base,
            occurred_at=None,
            observed_at=None,
            ingested_at=datetime(2026, 9, 2, tzinfo=UTC),
            event_year=2021,
            temporal_precision="year",
            evidence_scope="historical",
        )
    )
    newer = public_evidence.evidence_from_record(
        replace(
            base,
            id="annual:newer",
            source_id="data-gov-130016:2022:demo:2",
            occurred_at=None,
            observed_at=None,
            ingested_at=datetime(2026, 9, 1, tzinfo=UTC),
            event_year=2022,
            temporal_precision="year",
            evidence_scope="historical",
        )
    )

    displayed = public_evidence.display_evidence_items([older, newer])

    assert [item.id for item in displayed] == ["annual:newer", "annual:older"]


def test_preview_reserves_current_signal_families_and_historical_context() -> None:
    observed_at = datetime(2026, 8, 29, tzinfo=UTC)
    flood_sensors = [
        public_evidence.evidence_from_record(
            _record(
                evidence_id=f"current-flood:{index}",
                source_id=f"sensor:{index}",
                event_type="flood_report",
                occurred_at=observed_at,
                observed_at=observed_at,
                distance_to_query_m=float(index + 1),
            )
        ).model_copy(update={"evidence_scope": "current"})
        for index in range(12)
    ]
    water = public_evidence.evidence_from_record(
        _record(
            evidence_id="current-water",
            source_id="water:1",
            event_type="water_level",
            occurred_at=observed_at,
            observed_at=observed_at,
        )
    ).model_copy(update={"evidence_scope": "current"})
    rainfall = public_evidence.evidence_from_record(
        _record(
            evidence_id="current-rainfall",
            source_id="rainfall:1",
            event_type="rainfall",
            occurred_at=observed_at,
            observed_at=observed_at,
        )
    ).model_copy(update={"evidence_scope": "current"})
    history = public_evidence.evidence_from_record(
        _record(
            evidence_id="history-flood",
            source_id="history:1",
            event_type="flood_report",
            occurred_at=datetime(2020, 8, 1, tzinfo=UTC),
        )
    ).model_copy(update={"evidence_scope": "historical"})

    preview = public_evidence.select_evidence_preview_items(
        [*flood_sensors, water, rainfall, history],
        limit=10,
    )

    assert len(preview) == 10
    assert preview[:4] == [flood_sensors[0], water, rainfall, history]
    assert {item.event_type for item in preview} >= {
        "flood_report",
        "water_level",
        "rainfall",
    }
    assert any(item.evidence_scope == "historical" for item in preview)

    public_preview = public_evidence.evidence_preview(history)
    assert public_preview.evidence_scope == "historical"
    assert public_preview.model_dump(mode="json")["evidence_scope"] == "historical"
