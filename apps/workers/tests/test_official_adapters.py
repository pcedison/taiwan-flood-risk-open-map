from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.contracts import EventType, SourceFamily
from app.adapters.cwa import CwaRainfallAdapter
from app.adapters.flood_potential import FloodPotentialGeoJsonAdapter
from app.adapters.wra import WraWaterLevelAdapter
from app.pipelines.validation import validate_evidence_for_promotion


FIXTURES_DIR = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 4, 28, 8, 10, tzinfo=timezone.utc)


def test_cwa_rainfall_adapter_normalizes_fixture_records() -> None:
    adapter = CwaRainfallAdapter(
        _load_json("cwa_rainfall_sample.json"),
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/cwa/rainfall/2026-04-28T08.json",
    )

    result = adapter.run()

    assert result.adapter_key == "official.cwa.rainfall"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.source_family is SourceFamily.OFFICIAL
    assert first.event_type is EventType.RAINFALL
    assert first.location_text == "Taipei City Zhongzheng District Taipei Station"
    assert first.confidence == 0.93
    assert "42.5 mm in 1 hour" in first.summary


def test_wra_water_level_adapter_normalizes_fixture_records() -> None:
    adapter = WraWaterLevelAdapter(
        _load_json("wra_water_level_sample.json"),
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/wra/water-level/2026-04-28T08.json",
    )

    result = adapter.run()

    assert result.adapter_key == "official.wra.water_level"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.source_family is SourceFamily.OFFICIAL
    assert first.event_type is EventType.WATER_LEVEL
    assert first.location_text == "Dahan River Dahan Bridge"
    assert "0.68 m below warning level" in first.summary


def test_flood_potential_geojson_adapter_normalizes_feature_collection() -> None:
    adapter = FloodPotentialGeoJsonAdapter(
        _load_json("flood_potential_sample.geojson"),
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/flood-potential/2026-04.geojson",
    )

    result = adapter.run()

    assert result.adapter_key == "official.flood_potential.geojson"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.source_family is SourceFamily.OFFICIAL
    assert first.event_type is EventType.FLOOD_POTENTIAL
    assert first.source_id == "FP-TPE-ZZ-001"
    assert first.location_text == "Taipei City Zhongzheng District low-lying area"
    assert "0.5-1.0m" in first.summary


def test_official_adapter_outputs_pass_promotion_validation() -> None:
    normalized = (
        *CwaRainfallAdapter(_load_json("cwa_rainfall_sample.json"), fetched_at=FETCHED_AT)
        .run()
        .normalized,
        *WraWaterLevelAdapter(_load_json("wra_water_level_sample.json"), fetched_at=FETCHED_AT)
        .run()
        .normalized,
        *FloodPotentialGeoJsonAdapter(
            _load_json("flood_potential_sample.geojson"), fetched_at=FETCHED_AT
        )
        .run()
        .normalized,
    )

    validation = validate_evidence_for_promotion(normalized)

    assert len(validation.accepted) == 6
    assert validation.rejected == ()


def _load_json(name: str) -> list[dict[str, object]] | dict[str, object]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
