from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from app.ops.local_source.local_source_action_plan import (
    REQUIRED_REALTIME_READ_API_FIELDS,
)


SCHEMA_VERSION = "public-api-contract-probe/v1"
Readiness = str
Fetcher = Callable[[str, float], "ProbeHttpResponse"]

FIELD_MARKERS: dict[str, tuple[str, ...]] = {
    "observed_at": (
        "observed_at",
        "observationtime",
        "observetime",
        "phenomenontime",
        "rectime",
        "measure_time",
        "measurementtime",
        "觀測時間",
        "更新時間",
    ),
    "station_or_device_id": (
        "station_id",
        "stationid",
        "stationno",
        "device_id",
        "deviceid",
        "sensorid",
    ),
    "measurement_value": (
        "measurement_value",
        "value",
        "waterlevel",
        "water_level",
        "waterdepth",
        "water_depth",
        "rainfall",
        "rain",
        "雨量",
        "水位",
        "淹水深度",
    ),
    "measurement_unit_or_type": (
        "measurement_unit",
        "unit",
        "mm",
        "cm",
        "公尺",
        "毫米",
        "雨量(mm)",
        "分鐘雨量",
        "小時雨量",
    ),
    "longitude_latitude_or_joinable_station_metadata": (
        "longitude",
        "latitude",
        "lon",
        "lat",
        "wgs84",
        "twd97",
        "經度",
        "緯度",
        "座標",
    ),
    "official_source_url_and_license": (
        "license",
        "授權",
        "政府資料開放授權",
        "著作權",
        "資料來源",
    ),
}


@dataclass(frozen=True)
class ProbeHttpResponse:
    url: str
    status_code: int
    content_type: str
    text: str
    error: str | None = None


def classify_contract_probe_response(response: ProbeHttpResponse) -> dict[str, Any]:
    detected = _detected_required_fields(response.text)
    missing = [
        field for field in REQUIRED_REALTIME_READ_API_FIELDS if field not in detected
    ]
    non_measurement_notes = _non_measurement_notes(response)
    readiness: Readiness

    if response.status_code != 200:
        readiness = "unreachable"
    elif not missing and _looks_machine_readable(response):
        readiness = "candidate_live_read_api"
    elif non_measurement_notes:
        readiness = "non_measurement_context"
    elif _looks_html(response):
        readiness = "public_html_missing_read_api_contract"
    else:
        readiness = "missing_required_read_api_contract"

    return {
        "url": response.url,
        "status_code": response.status_code,
        "content_type": response.content_type,
        "readiness": readiness,
        "detected_required_fields": [
            field for field in REQUIRED_REALTIME_READ_API_FIELDS if field in detected
        ],
        "missing_required_fields": missing,
        "non_measurement_notes": non_measurement_notes,
        "error": response.error,
    }


def build_public_api_contract_probe(
    action_plan: Mapping[str, Any],
    *,
    captured_at: str | None = None,
    timeout_seconds: float,
    fetcher: Fetcher,
) -> dict[str, Any]:
    captured = captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    counties: list[dict[str, Any]] = []
    live_count = 0
    probed_url_count = 0

    for review in action_plan.get("public_api_contract_reviews", []):
        if not isinstance(review, Mapping):
            continue
        probe_results = []
        for url in review.get("candidate_source_urls", []):
            response = fetcher(str(url), timeout_seconds)
            result = classify_contract_probe_response(response)
            probe_results.append(result)
            probed_url_count += 1
            if result["readiness"] == "candidate_live_read_api":
                live_count += 1
        counties.append(
            {
                "county": str(review.get("county", "")),
                "tracking_status": review.get("tracking_status"),
                "requested_counterparty": review.get("requested_counterparty"),
                "required_read_api_fields": list(
                    review.get("required_read_api_fields", [])
                ),
                "probe_results": probe_results,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured,
        "conclusion": (
            "candidate_live_read_api_found"
            if live_count
            else "no_candidate_live_read_api_found"
        ),
        "summary": {
            "public_api_contract_review_count": len(counties),
            "probed_url_count": probed_url_count,
            "candidate_live_read_api_count": live_count,
        },
        "counties": counties,
    }


def _detected_required_fields(text: str) -> set[str]:
    haystack = text.casefold()
    return {
        field
        for field, markers in FIELD_MARKERS.items()
        if any(marker.casefold() in haystack for marker in markers)
    }


def _non_measurement_notes(response: ProbeHttpResponse) -> list[str]:
    text = response.text
    haystack = text.casefold()
    url = response.url.casefold()
    notes: list[str] = []
    if "/crawler" in url:
        notes.append("image_only_cctv")
    if "/flood" in url and "警戒" in text and not any(
        marker.casefold() in haystack
        for marker in FIELD_MARKERS["station_or_device_id"]
    ):
        notes.append("warning_threshold_only")
    return notes


def _looks_html(response: ProbeHttpResponse) -> bool:
    return "html" in response.content_type.casefold() or "<html" in response.text.casefold()


def _looks_machine_readable(response: ProbeHttpResponse) -> bool:
    content_type = response.content_type.casefold()
    if any(kind in content_type for kind in ("json", "xml", "csv")):
        return True
    text = response.text.lstrip()
    return text.startswith(("{", "[", "<?xml"))
