from datetime import UTC, datetime

import pytest

from app.api.services import public_evidence
from app.domain.evidence import EvidenceRecord
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
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        source_id=source_id,
        source_type="official",
        event_type=event_type,
        title=f"official {event_type}",
        summary=f"official {event_type} summary",
        url="https://fallback.invalid/evidence",
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


def test_display_evidence_collapses_official_disaster_points_stably() -> None:
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

    collapsed = public_evidence.display_evidence_items(
        [closest_older, farther_latest]
    )
    reversed_collapsed = public_evidence.display_evidence_items(
        [farther_latest, closest_older]
    )

    assert len(collapsed) == 1
    summary = collapsed[0]
    assert summary.distance_to_query_m == 45.0
    assert summary.observed_at == datetime(2024, 7, 26, tzinfo=UTC)
    assert summary.occurred_at == datetime(2024, 7, 26, tzinfo=UTC)
    assert summary.source_id == "data-gov-130016:summary"
    assert summary.title == "官方淹水災害情資點位彙整（2020、2024）"
    assert summary.raw_ref == "historical-record:data-gov-130016:summary:2"
    assert reversed_collapsed[0].id == summary.id
    assert reversed_collapsed[0].source_id == summary.source_id
    assert reversed_collapsed[0].title == summary.title


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
