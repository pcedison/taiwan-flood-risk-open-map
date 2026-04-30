from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import DataSourceAdapter
from app.adapters.cwa import CwaRainfallAdapter
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
