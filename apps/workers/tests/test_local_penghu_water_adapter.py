from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.local_penghu import (
    PENGHU_WATER_LEVEL_LAYER_URL,
    PenghuWaterLevelArcgisAdapter,
)
from app.config import load_worker_settings
from app.jobs.runtime import build_runtime_adapters


FETCHED_AT = datetime(2026, 6, 28, 9, 45, tzinfo=UTC)


def _penghu_water_level_layer_payload() -> dict[str, Any]:
    return {
        "features": [
            {
                "attributes": {
                    "OBJECTID": 37,
                    "device_id": "7013",
                    "SttName": "林投排水",
                    "SttNo": "10016-000098",
                    "CountyCode": "10016020",
                    "UrbanPlan": "林投風景區特定區",
                    "PipeNum": "林投大排",
                    "ManholeDepth": 2.15,
                    "Manager": "澎湖縣工務處",
                    "Addr": "林投排水",
                    "SttPurpose": "區排監測",
                    "FullHeight": 2.15,
                    "HalfHeight": 1.4,
                    "battery": 96.57,
                    "rssi": 20,
                    "water_level": 1782.7,
                    "water_level_percent": 82.916,
                    "water_level_status": "L",
                    "measure_time": 1782667802000,
                    "upload_time": 1782668085000,
                },
                "geometry": {"x": 119.64554599971, "y": 23.561330999504204},
            },
            {
                "attributes": {
                    "device_id": "OLD7013",
                    "SttName": "舊水位計",
                    "SttNo": "10016-OLD",
                    "Manager": "澎湖縣工務處",
                    "water_level": 0.0,
                    "measure_time": 1782570000000,
                },
                "geometry": {"x": 119.64, "y": 23.56},
            },
        ]
    }


def test_penghu_arcgis_water_level_layer_outputs_water_level_and_rejects_stale() -> None:
    adapter = PenghuWaterLevelArcgisAdapter(
        fetched_at=FETCHED_AT,
        fetch_json=lambda url, timeout: _penghu_water_level_layer_payload(),
    )

    result = adapter.run()

    assert result.adapter_key == "local.penghu.water_level"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 1
    assert result.rejected == ("10016-OLD:2026-06-27T06:20:00+00:00",)
    raw_payload = result.fetched[0].payload
    assert raw_payload["station_id"] == "10016-000098"
    assert raw_payload["station_name"] == "林投排水"
    assert raw_payload["observed_at"] == "2026-06-28T09:30:02+00:00"
    assert raw_payload["water_level_m"] == 1.7827
    assert raw_payload["water_level_mm"] == 1782.7
    assert raw_payload["water_level_percent"] == 82.916
    assert raw_payload["warning_level_m"] == 1.4
    assert raw_payload["red_alert_level_m"] == 2.15
    assert raw_payload["battery_percent"] == 96.57
    assert raw_payload["rssi"] == 20
    assert raw_payload["geometry"] == {
        "type": "Point",
        "coordinates": [119.64554599971, 23.561330999504204],
    }
    evidence = result.normalized[0]
    assert evidence.event_type is EventType.WATER_LEVEL
    assert evidence.source_family is SourceFamily.OFFICIAL
    assert "1.78 公尺" in evidence.summary
    assert "local_penghu" in evidence.tags
    assert "water_level" in evidence.tags


def test_build_runtime_adapters_wires_penghu_source_when_gates_are_on() -> None:
    settings = load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": "local.penghu.water_level",
            "SOURCE_PENGHU_WATER_LEVEL_ENABLED": "true",
            "SOURCE_PENGHU_WATER_LEVEL_API_ENABLED": "true",
            "LOCAL_WATER_TIMEOUT_SECONDS": "5",
        }
    )

    adapters = build_runtime_adapters(
        settings,
        fetched_at=FETCHED_AT,
        penghu_water_level_fetch_json=lambda url, timeout: _penghu_water_level_layer_payload(),
    )

    assert tuple(adapters) == ("local.penghu.water_level",)
    assert len(adapters["local.penghu.water_level"].run().normalized) == 1
    assert PENGHU_WATER_LEVEL_LAYER_URL.startswith("https://ph3dgis.penghu.gov.tw/")
