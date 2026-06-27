from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.civil_iot import (
    POND_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    RIVER_WATER_LEVEL_METADATA,
    SEWER_WATER_LEVEL,
    CivilIotRiverApiAdapter,
    StaWaterLevelAdapter,
    StaWaterLevelApiAdapter,
    parse_sta_things_payload,
)
from app.adapters.contracts import EventType, SourceFamily
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters
from app.pipelines.promotion import (
    PostgresEvidencePromotionWriter,
    PromotionCandidate,
    build_evidence_promotion_payload,
)
from app.pipelines.staging import build_staging_batch


FETCHED_AT = datetime(2026, 6, 15, 3, 10, tzinfo=UTC)


def _water_level_payload(datastream_name: str, value: float) -> dict:
    return {
        "value": [
            {
                "@iot.id": 3001,
                "name": f"{datastream_name}測站",
                "properties": {"stationID": "WL-A", "authority": "機關", "city": "臺南市"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [120.2, 23.0]}}
                ],
                "Datastreams": [
                    {
                        "name": datastream_name,
                        "unitOfMeasurement": {"symbol": "m"},
                        "Observations": [
                            {"phenomenonTime": "2026-06-15T03:00:00.000Z", "result": value}
                        ],
                    }
                ],
            }
        ]
    }


def _pump_payload() -> dict:
    return {
        "value": [
            {
                "@iot.id": 4001,
                "name": "中山抽水站",
                "properties": {"stationID": "PUMP-1", "authority": "臺北市", "city": "臺北市"},
                "Locations": [
                    {"location": {"type": "Point", "coordinates": [121.5, 25.05]}}
                ],
                "Datastreams": [
                    {
                        "name": "內水位",
                        "unitOfMeasurement": {"symbol": "m"},
                        "Observations": [
                            {"phenomenonTime": "2026-06-15T03:00:00.000Z", "result": 1.1}
                        ],
                    },
                    {
                        "name": "外水位",
                        "unitOfMeasurement": {"symbol": "m"},
                        "Observations": [
                            {"phenomenonTime": "2026-06-15T03:01:00.000Z", "result": 2.7}
                        ],
                    },
                ],
            }
        ]
    }


def _candidate_from_staging_payload(payload: dict, *, adapter_key: str) -> PromotionCandidate:
    return PromotionCandidate(
        staging_evidence_id="staging-id",
        raw_snapshot_id="raw-snapshot-id",
        raw_ref="raw/civil-iot/water-level/wl-a.json",
        data_source_id="data-source-id",
        source_id="WL-A:2026-06-15T03:00:00+00:00",
        source_type="official",
        event_type="water_level",
        title="Civil IoT water level",
        summary="Civil IoT water level observation",
        url="https://example.test/iow12",
        occurred_at=FETCHED_AT,
        observed_at=FETCHED_AT,
        confidence=0.9,
        validation_status="accepted",
        payload={
            **payload,
            "adapter_key": adapter_key,
        },
    )


def test_pond_and_sewer_adapters_normalize_water_level() -> None:
    for source, datastream in ((POND_WATER_LEVEL, "埤塘水位"), (SEWER_WATER_LEVEL, "下水道水位")):
        adapter = StaWaterLevelApiAdapter(
            source,
            fetched_at=FETCHED_AT,
            fetch_json=lambda url, timeout, ds=datastream: _water_level_payload(ds, 3.14),
        )

        result = adapter.run()

        assert len(result.normalized) == 1
        evidence = result.normalized[0]
        assert evidence.event_type is EventType.WATER_LEVEL
        assert evidence.source_family is SourceFamily.OFFICIAL
        assert "3.14 公尺" in evidence.summary
        assert result.fetched[0].payload["water_level_m"] == 3.14


def test_river_water_level_adapter_exposes_water_level_metric_in_raw_payload() -> None:
    adapter = CivilIotRiverApiAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _water_level_payload("河川水位", 4.21),
    )

    result = adapter.run()

    assert len(result.normalized) == 1
    assert result.normalized[0].adapter_key == RIVER_WATER_LEVEL_METADATA.key
    assert result.fetched[0].payload["water_level_m"] == 4.21


def test_water_level_staging_and_promotion_latest_keep_metrics_for_risk_factor() -> None:
    records = tuple(
        {
            **record,
            "warning_level_m": 4.0,
        }
        for record in parse_sta_things_payload(
            _water_level_payload("埤塘水位", 3.2),
            source_url="https://example.test/iow12",
        )
    )
    adapter = StaWaterLevelAdapter(POND_WATER_LEVEL, records, fetched_at=FETCHED_AT)

    result = adapter.run()
    staging = build_staging_batch(result, raw_ref="raw/civil-iot/water-level/wl-a.json")

    assert staging.accepted[0].payload["water_level_m"] == 3.2
    assert staging.accepted[0].payload["warning_level_m"] == 4.0

    promotion_payload = build_evidence_promotion_payload(
        _candidate_from_staging_payload(
            staging.accepted[0].payload,
            adapter_key=POND_WATER_LEVEL.metadata.key,
        )
    )
    connection = _FakePromotionConnection(evidence_id="evidence-id")
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    writer.write_evidence(promotion_payload)

    latest_sql, latest_params = connection.cursor_instance.executions[1]
    assert "INSERT INTO official_realtime_latest" in latest_sql
    assert latest_params[11] == 3.2
    assert latest_params[13] == 4.0
    assert latest_params[16] == 0.8


def test_pump_adapter_reads_external_water_level_datastream() -> None:
    adapter = StaWaterLevelApiAdapter(
        PUMP_WATER_LEVEL,
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _pump_payload(),
    )

    result = adapter.run()

    assert len(result.normalized) == 1
    # The external (外水位 = 2.7 m) datastream is selected, not internal (1.1 m).
    assert "2.70 公尺" in result.normalized[0].summary
    assert result.fetched[0].payload["water_level_m"] == 2.7


def test_water_level_fixture_adapter_drops_invalid_sentinel() -> None:
    records = parse_sta_things_payload(
        _water_level_payload("埤塘水位", -999.0),
        source_url="https://example.test/iow12",
    )
    adapter = StaWaterLevelAdapter(POND_WATER_LEVEL, records, fetched_at=FETCHED_AT)

    result = adapter.run()

    assert len(result.normalized) == 0
    assert len(result.rejected) == 1


def test_new_water_level_sources_registered_and_disabled_by_default() -> None:
    default_keys = enabled_adapter_keys(load_worker_settings({}))
    for key in (
        "official.civil_iot.pond_water_level",
        "official.civil_iot.sewer_water_level",
        "official.civil_iot.pump_water_level",
    ):
        assert key in ADAPTER_REGISTRY
        assert ADAPTER_REGISTRY[key].enabled_by_default is False
        assert key not in default_keys


def test_new_water_level_flags_enable_and_wire_runtime() -> None:
    settings = load_worker_settings(
        {
            "SOURCE_CIVIL_IOT_POND_ENABLED": "true",
            "SOURCE_CIVIL_IOT_POND_API_ENABLED": "true",
            "SOURCE_CIVIL_IOT_SEWER_ENABLED": "true",
            "SOURCE_CIVIL_IOT_SEWER_API_ENABLED": "true",
            "SOURCE_CIVIL_IOT_PUMP_ENABLED": "true",
            "SOURCE_CIVIL_IOT_PUMP_API_ENABLED": "true",
        }
    )

    keys = enabled_adapter_keys(settings)
    assert "official.civil_iot.pond_water_level" in keys
    assert "official.civil_iot.sewer_water_level" in keys
    assert "official.civil_iot.pump_water_level" in keys

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        civil_iot_pond_fetch_json=lambda url, timeout: _water_level_payload("埤塘水位", 2.0),
        civil_iot_sewer_fetch_json=lambda url, timeout: _water_level_payload("下水道水位", 1.5),
        civil_iot_pump_fetch_json=lambda url, timeout: _pump_payload(),
    )

    assert "official.civil_iot.pond_water_level" in adapters
    assert "official.civil_iot.sewer_water_level" in adapters
    assert "official.civil_iot.pump_water_level" in adapters
    assert len(adapters["official.civil_iot.pump_water_level"].run().normalized) == 1


class _FakePromotionConnection:
    def __init__(self, *, evidence_id: str) -> None:
        self.cursor_instance = _FakePromotionCursor(evidence_id=evidence_id)
        self.committed = False

    def __enter__(self) -> "_FakePromotionConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakePromotionCursor":
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


class _FakePromotionCursor:
    def __init__(self, *, evidence_id: str) -> None:
        self._evidence_id = evidence_id
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakePromotionCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> tuple[str]:
        return (self._evidence_id,)
