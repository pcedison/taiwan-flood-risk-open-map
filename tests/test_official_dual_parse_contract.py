"""Anti-drift guardrail for the ADR-0010 dual CWA/WRA realtime parsers.

ADR-0010 (docs/adr/0010-realtime-bridge-as-local-diagnostic.md) deliberately keeps
two parallel implementations that each parse the same upstream CWA/WRA responses:

- The API bridge, used only as a local diagnostic tool:
  apps/api/app/domain/realtime/official.py
  (``_fetch_cwa_rainfall_stations`` / ``_fetch_wra_water_level_stations``)
- The workers adapters, the hosted runtime's source of truth:
  apps/workers/app/adapters/cwa/rainfall.py (``parse_cwa_rainfall_api_payload``)
  apps/workers/app/adapters/wra/water_level.py (``parse_wra_water_level_api_payload``)

The ADR accepts this duplication for now (collapsing it into a shared package would
break the editable-install layout both apps and CI rely on) but explicitly calls out
that "upstream schema 改變必須同時改兩處" ("an upstream schema change must be applied
in both places") is a rule that only lives in people's memory.

This test feeds the SAME raw upstream fixtures
(packages/contracts/fixtures/upstream/cwa-rainfall.json and wra-water-level.json)
into both parsers and asserts the station id, coordinates, observed value, and
observed time line up. If an upstream field is ever renamed/moved and only one side
is updated, this test goes red in CI instead of silently drifting until it's caught
in production.

Known, deliberate parser differences that are NOT covered here (see
docs/reviews/audit-2026-07-06-architecture.md, F2-A): the workers adapter keeps a
rainfall station if ANY precipitation window (10m/1h/24h) is valid, while the API
bridge requires the 1-hour window specifically. The shared CWA fixture's malformed
station is rejected by both sides for independent reasons, so this difference does
not need to be exercised here; it would only matter for a station whose only valid
window is 10m or 24h.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from app.adapters.wra import (
    parse_wra_station_metadata_payload,
    parse_wra_water_level_api_payload,
)
from app.adapters.cwa import parse_cwa_rainfall_api_payload
from app.domain.realtime import official as official_realtime


REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_FIXTURES_DIR = REPO_ROOT / "packages" / "contracts" / "fixtures" / "upstream"


def _load_json(name: str) -> Any:
    return json.loads((UPSTREAM_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AssertionError(f"expected a timezone-aware datetime, got {value!r}")
    return value.astimezone(official_realtime.UTC)


def test_cwa_rainfall_dual_parse_contract(monkeypatch) -> None:
    """Bridge and worker CWA rainfall parsers must agree on the same upstream sample."""
    payload = _load_json("cwa-rainfall.json")

    # --- API bridge side: exercise the real fetch/parse path, network stubbed out. ---
    monkeypatch.setattr(official_realtime, "_json_cache", {})

    def fake_fetch_json(url: str) -> Any:
        assert official_realtime.CWA_RAINFALL_URL in url
        return payload

    monkeypatch.setattr(official_realtime, "_fetch_json", fake_fetch_json)
    bridge_stations = official_realtime._fetch_cwa_rainfall_stations("test-token")
    bridge_by_id = {station.station_id: station for station in bridge_stations}

    # --- Workers side: same raw payload through the real adapter parser. ---
    worker_records = parse_cwa_rainfall_api_payload(
        payload,
        source_url="https://data.gov.tw/dataset/9177",
    )
    worker_by_id = {str(record["station_id"]): record for record in worker_records}

    # The fixture's malformed station (sentinel rainfall, missing coordinates) must
    # be rejected by both sides -- otherwise the two parsers disagree on what counts
    # as a usable observation.
    assert bridge_by_id.keys() == worker_by_id.keys()
    assert bridge_by_id.keys() == {"C0A560"}

    for station_id, bridge_station in bridge_by_id.items():
        worker_record = worker_by_id[station_id]

        assert bridge_station.station_name == worker_record["station_name"]

        assert math.isclose(bridge_station.lat, worker_record["latitude"], abs_tol=1e-9)
        assert math.isclose(bridge_station.lng, worker_record["longitude"], abs_tol=1e-9)

        assert bridge_station.rainfall_1h == worker_record["rainfall_mm_1h"]
        assert bridge_station.rainfall_10m == worker_record["rainfall_mm_10m"]
        assert bridge_station.rainfall_24h == worker_record["rainfall_mm_24h"]

        assert _as_utc(bridge_station.observed_at) == datetime.fromisoformat(
            worker_record["observed_at"]
        )


def test_wra_water_level_dual_parse_contract(monkeypatch) -> None:
    """Bridge and worker WRA water-level parsers must agree on the same upstream sample."""
    fixture = _load_json("wra-water-level.json")
    water_level_payload = fixture["water_level"]
    station_metadata_payload = fixture["station_metadata"]

    # --- API bridge side: exercise the real fetch/parse path, network stubbed out. ---
    monkeypatch.setattr(official_realtime, "_json_cache", {})

    def fake_fetch_json(url: str) -> Any:
        if official_realtime.WRA_WATER_LEVEL_URL in url:
            return water_level_payload
        if official_realtime.WRA_STATION_URL in url:
            return station_metadata_payload
        raise AssertionError(f"unexpected upstream URL requested: {url}")

    monkeypatch.setattr(official_realtime, "_fetch_json", fake_fetch_json)
    bridge_stations = official_realtime._fetch_wra_water_level_stations()
    bridge_by_id = {station.station_id: station for station in bridge_stations}

    # --- Workers side: same raw payloads through the real adapter parsers. ---
    worker_station_metadata = parse_wra_station_metadata_payload(station_metadata_payload)
    worker_records = parse_wra_water_level_api_payload(
        water_level_payload,
        source_url="https://data.gov.tw/dataset/25768",
        station_metadata=worker_station_metadata,
    )
    worker_by_id = {str(record["station_id"]): record for record in worker_records}

    # The fixture's malformed station (sentinel water level, abolished metadata
    # status) must be rejected by both sides.
    assert bridge_by_id.keys() == worker_by_id.keys()
    assert bridge_by_id.keys() == {"1010H006"}

    for station_id, bridge_station in bridge_by_id.items():
        worker_record = worker_by_id[station_id]

        assert bridge_station.station_name == worker_record["station_name"]
        assert bridge_station.river_name == worker_record["river_name"]

        assert math.isclose(bridge_station.lat, worker_record["latitude"], abs_tol=1e-9)
        assert math.isclose(bridge_station.lng, worker_record["longitude"], abs_tol=1e-9)

        assert bridge_station.water_level_m == worker_record["water_level_m"]

        assert _as_utc(bridge_station.observed_at) == datetime.fromisoformat(
            worker_record["observed_at"]
        )

        bridge_threshold = bridge_station.alert_level_2_m or bridge_station.alert_level_1_m
        assert bridge_threshold == worker_record["warning_level_m"]
