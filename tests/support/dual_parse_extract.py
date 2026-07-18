"""Parse a shared upstream fixture with ONE side's parser and print JSON.

The API bridge (apps/api) and the worker adapters (apps/workers) are separate
regular packages that both expose a top-level ``app`` package, so importing
both in a single interpreter is unreliable — whichever is found first hides the
other. This helper is therefore run as a subprocess with the working directory
set to exactly one app root, so ``app`` resolves unambiguously to that side.
The dual-parse contract test runs it four times and compares the JSON.

Usage: ``python dual_parse_extract.py <mode> <fixture.json>``
where mode is one of: cwa-bridge, cwa-worker, wra-bridge, wra-worker.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _iso(value: Any) -> str | None:
    """Normalize a timestamp to a UTC ISO string so the two sides compare.

    The bridge yields timezone-aware datetimes (local +08:00); the worker
    yields UTC ISO strings. Both are collapsed to the same UTC representation.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return datetime.fromisoformat(str(value)).astimezone(timezone.utc).isoformat()


def _cwa_bridge(payload: Any) -> list[dict[str, Any]]:
    from app.domain.realtime import official as official_realtime

    official_realtime._json_cache = {}
    official_realtime._fetch_json = lambda _url: payload  # type: ignore[assignment]
    stations = official_realtime._fetch_cwa_rainfall_stations("test-token")
    return [
        {
            "station_id": station.station_id,
            "station_name": station.station_name,
            "lat": station.lat,
            "lng": station.lng,
            "rainfall_1h": station.rainfall_1h,
            "rainfall_10m": station.rainfall_10m,
            "rainfall_24h": station.rainfall_24h,
            "observed_at": _iso(station.observed_at),
        }
        for station in stations
    ]


def _cwa_worker(payload: Any) -> list[dict[str, Any]]:
    from app.adapters.cwa import parse_cwa_rainfall_api_payload

    records = parse_cwa_rainfall_api_payload(
        payload, source_url="https://data.gov.tw/dataset/9177"
    )
    return [
        {
            "station_id": str(record["station_id"]),
            "station_name": record["station_name"],
            "lat": record["latitude"],
            "lng": record["longitude"],
            "rainfall_1h": record["rainfall_mm_1h"],
            "rainfall_10m": record["rainfall_mm_10m"],
            "rainfall_24h": record["rainfall_mm_24h"],
            "observed_at": _iso(record["observed_at"]),
        }
        for record in records
    ]


def _wra_bridge(fixture: Any) -> list[dict[str, Any]]:
    from app.domain.realtime import official as official_realtime

    water_level_payload = fixture["water_level"]
    station_metadata_payload = fixture["station_metadata"]

    def fake_fetch_json(url: str) -> Any:
        if official_realtime.WRA_WATER_LEVEL_URL in url:
            return water_level_payload
        if official_realtime.WRA_STATION_URL in url:
            return station_metadata_payload
        raise AssertionError(f"unexpected upstream URL requested: {url}")

    official_realtime._json_cache = {}
    official_realtime._fetch_json = fake_fetch_json  # type: ignore[assignment]
    stations = official_realtime._fetch_wra_water_level_stations()
    return [
        {
            "station_id": station.station_id,
            "station_name": station.station_name,
            "river_name": station.river_name,
            "lat": station.lat,
            "lng": station.lng,
            "water_level_m": station.water_level_m,
            "observed_at": _iso(station.observed_at),
            "warning_level_m": station.alert_level_2_m or station.alert_level_1_m,
        }
        for station in stations
    ]


def _wra_worker(fixture: Any) -> list[dict[str, Any]]:
    from app.adapters.wra import (
        parse_wra_station_metadata_payload,
        parse_wra_water_level_api_payload,
    )

    metadata = parse_wra_station_metadata_payload(fixture["station_metadata"])
    records = parse_wra_water_level_api_payload(
        fixture["water_level"],
        source_url="https://data.gov.tw/dataset/25768",
        station_metadata=metadata,
    )
    return [
        {
            "station_id": str(record["station_id"]),
            "station_name": record["station_name"],
            "river_name": record["river_name"],
            "lat": record["latitude"],
            "lng": record["longitude"],
            "water_level_m": record["water_level_m"],
            "observed_at": _iso(record["observed_at"]),
            "warning_level_m": record["warning_level_m"],
        }
        for record in records
    ]


_MODES = {
    "cwa-bridge": _cwa_bridge,
    "cwa-worker": _cwa_worker,
    "wra-bridge": _wra_bridge,
    "wra-worker": _wra_worker,
}


def main() -> int:
    mode, fixture_path = sys.argv[1], sys.argv[2]
    payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    records = _MODES[mode](payload)
    # Write UTF-8 bytes directly so the result is independent of the console
    # codepage (Windows defaults to a non-UTF-8 locale encoding on the pipe).
    sys.stdout.buffer.write(
        json.dumps(records, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
