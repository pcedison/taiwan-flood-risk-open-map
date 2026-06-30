from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.adapters.civil_iot import (
    GATE_WATER_LEVEL,
    POND_WATER_LEVEL,
    PUMP_WATER_LEVEL,
    SEWER_WATER_LEVEL,
    FloodSensorAdapter,
    StaWaterLevelAdapter,
)
from app.adapters.contracts import DataSourceAdapter
from app.adapters.cwa import (
    CWA_TIDE_LEVEL_DATASET_URL,
    CwaRainfallAdapter,
    CwaTideLevelAdapter,
)
from app.adapters.flood_potential import FloodPotentialGeoJsonAdapter
from app.adapters.wra import WraWaterLevelAdapter


def build_official_demo_adapters(
    *,
    fetched_at: datetime | None = None,
) -> Mapping[str, DataSourceAdapter]:
    resolved_fetched_at = fetched_at or datetime.now(UTC)
    observed_at = resolved_fetched_at.isoformat()
    adapters: tuple[DataSourceAdapter, ...] = (
        CwaRainfallAdapter(
            (
                {
                    "station_id": "CWA-DEMO-TPE-001",
                    "station_name": "Taipei Demo Station",
                    "county": "Taipei City",
                    "town": "Zhongzheng District",
                    "observed_at": observed_at,
                    "rainfall_mm_1h": 38.5,
                    "rainfall_mm_24h": 112.0,
                    "source_url": "https://example.test/official/cwa/rainfall-demo",
                    "confidence": 0.93,
                    "attribution": "Central Weather Administration demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/cwa-rainfall.json",
        ),
        CwaTideLevelAdapter(
            (
                {
                    "station_id": "CWA-DEMO-MATSU-TIDE-001",
                    "station_name": "Matsu Demo Tide Station",
                    "county": "Lienchiang County",
                    "town": "Nangan Township",
                    "observed_at": observed_at,
                    "water_level_m": 2.16,
                    "source_url": CWA_TIDE_LEVEL_DATASET_URL,
                    "confidence": 0.9,
                    "source_weight": 0.65,
                    "station_type": "tide_level",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [119.9428, 26.1617],
                    },
                    "attribution": "Central Weather Administration demo fixture",
                    "quality_flags": {
                        "coastal_context_only": True,
                    },
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/cwa-tide-level.json",
        ),
        WraWaterLevelAdapter(
            (
                {
                    "station_id": "WRA-DEMO-001",
                    "station_name": "Dahan Bridge Demo Gauge",
                    "river_name": "Dahan River",
                    "observed_at": observed_at,
                    "water_level_m": 8.42,
                    "warning_level_m": 8.3,
                    "source_url": "https://example.test/official/wra/water-level-demo",
                    "confidence": 0.91,
                    "attribution": "Water Resources Agency demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/wra-water-level.json",
        ),
        FloodPotentialGeoJsonAdapter(
            _demo_flood_potential_feature_collection(observed_at),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/flood-potential.geojson",
        ),
        FloodSensorAdapter(
            (
                {
                    "station_id": "CIVIL-IOT-FLOOD-DEMO-001",
                    "station_name": "Civil IoT Demo Road Flood Sensor",
                    "observed_at": observed_at,
                    "value": 9.5,
                    "location_text": "Civil IoT demo flood-prone road",
                    "source_url": "https://example.test/official/civil-iot/flood-sensor-demo",
                    "confidence": 0.9,
                    "attribution": "Civil IoT Taiwan demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/civil-iot-flood-sensor.json",
        ),
        StaWaterLevelAdapter(
            SEWER_WATER_LEVEL,
            (
                {
                    "station_id": "CIVIL-IOT-SEWER-DEMO-001",
                    "station_name": "Civil IoT Demo Sewer Gauge",
                    "observed_at": observed_at,
                    "water_level_m": 1.24,
                    "location_text": "Civil IoT demo rain sewer station",
                    "source_url": "https://example.test/official/civil-iot/sewer-water-level-demo",
                    "confidence": 0.9,
                    "attribution": "Civil IoT Taiwan demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/civil-iot-sewer-water-level.json",
        ),
        StaWaterLevelAdapter(
            PUMP_WATER_LEVEL,
            (
                {
                    "station_id": "CIVIL-IOT-PUMP-DEMO-001",
                    "station_name": "Civil IoT Demo Pump Station",
                    "observed_at": observed_at,
                    "water_level_m": 2.41,
                    "location_text": "Civil IoT demo pump station",
                    "source_url": "https://example.test/official/civil-iot/pump-water-level-demo",
                    "confidence": 0.9,
                    "attribution": "Civil IoT Taiwan demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/civil-iot-pump-water-level.json",
        ),
        StaWaterLevelAdapter(
            GATE_WATER_LEVEL,
            (
                {
                    "station_id": "CIVIL-IOT-GATE-DEMO-001",
                    "station_name": "Civil IoT Demo Water Gate",
                    "observed_at": observed_at,
                    "water_level_m": 2.87,
                    "location_text": "Civil IoT demo water gate",
                    "source_url": "https://example.test/official/civil-iot/gate-water-level-demo",
                    "confidence": 0.9,
                    "attribution": "Civil IoT Taiwan demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/civil-iot-gate-water-level.json",
        ),
        StaWaterLevelAdapter(
            POND_WATER_LEVEL,
            (
                {
                    "station_id": "CIVIL-IOT-POND-DEMO-001",
                    "station_name": "Civil IoT Demo Pond Gauge",
                    "observed_at": observed_at,
                    "water_level_m": 3.16,
                    "location_text": "Civil IoT demo pond gauge",
                    "source_url": "https://example.test/official/civil-iot/pond-water-level-demo",
                    "confidence": 0.9,
                    "attribution": "Civil IoT Taiwan demo fixture",
                },
            ),
            fetched_at=resolved_fetched_at,
            raw_snapshot_key="raw/official-demo/civil-iot-pond-water-level.json",
        ),
    )
    return {adapter.metadata.key: adapter for adapter in adapters}


def _demo_flood_potential_feature_collection(updated_at: str) -> Mapping[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "FP-DEMO-TPE-001",
                "properties": {
                    "area_id": "FP-DEMO-TPE-001",
                    "area_name": "Taipei Demo Low-Lying Area",
                    "updated_at": updated_at,
                    "depth_class": "0.5-1.0m",
                    "return_period_years": "10",
                    "source_url": "https://example.test/official/flood-potential-demo",
                    "confidence": 0.86,
                    "attribution": "Official flood potential demo fixture",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [121.50, 25.03],
                            [121.51, 25.03],
                            [121.51, 25.04],
                            [121.50, 25.04],
                            [121.50, 25.03],
                        ]
                    ],
                },
            }
        ],
    }
