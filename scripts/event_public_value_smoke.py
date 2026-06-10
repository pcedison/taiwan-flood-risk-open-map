from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import sys
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.api.routes import public as public_routes  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.domain.geocoding.providers import load_taiwan_admin_areas  # noqa: E402
from app.domain.realtime import (  # noqa: E402
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
)
from app.main import create_app  # noqa: E402


DEFAULT_EVENT_ID = "taiwan-meiyu-heavy-rain-2026-06-08-09"
DEFAULT_SEED = DEFAULT_EVENT_ID
DEFAULT_SAMPLE_SIZE = 100
DEFAULT_MODE = "no-network"
ORIGINAL_FETCH_OFFICIAL_REALTIME_BUNDLE = public_routes.fetch_official_realtime_bundle
ORIGINAL_CACHED_NOMINATIM_CANDIDATES = public_routes._cached_nominatim_candidates
ORIGINAL_CACHED_WIKIMEDIA_CANDIDATES = public_routes._cached_wikimedia_candidates

GEOCODER_DATA_PATHS = (
    ROOT / "apps" / "api" / "app" / "data" / "geocoder" / "villages.normalized.jsonl.gz",
    ROOT / "apps" / "api" / "app" / "data" / "geocoder" / "roads-114.normalized.jsonl.gz",
    ROOT / "apps" / "api" / "app" / "data" / "geocoder" / "shelters.normalized.jsonl.gz",
)

TAIWAN_COUNTIES = (
    "基隆市",
    "臺北市",
    "新北市",
    "桃園市",
    "新竹市",
    "新竹縣",
    "苗栗縣",
    "臺中市",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義市",
    "嘉義縣",
    "臺南市",
    "高雄市",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "臺東縣",
    "澎湖縣",
    "金門縣",
    "連江縣",
)

COUNTY_ALIASES = {
    "台北市": "臺北市",
    "台中市": "臺中市",
    "台南市": "臺南市",
    "台東縣": "臺東縣",
}

EVENT_HIGH_CONCERN_COUNTIES = {
    "桃園市",
    "苗栗縣",
    "臺中市",
    "南投縣",
    "雲林縣",
    "嘉義市",
    "嘉義縣",
    "臺南市",
    "高雄市",
    "屏東縣",
    "臺東縣",
    "澎湖縣",
}

EVENT_CORE_ALERT_COUNTIES = {
    "嘉義市",
    "嘉義縣",
    "臺南市",
    "高雄市",
    "屏東縣",
}

EVENT_SOURCES = (
    {
        "label": "CWA Rain Warning Product",
        "url": "https://www.cwa.gov.tw/V8/C/P/Warning/W26.html",
        "note": "Official rain-warning product and rainfall warning threshold context for Meiyu fronts and southwest-flow heavy-rain events.",
    },
    {
        "label": "PTS 2026-06-08",
        "url": "https://news.pts.org.tw/article/811953",
        "note": "CWA said southern Taiwan had short-duration heavy rain around 40 mm/hr and issued heavy-rain advisories from Chiayi southward; 2026-06-09 front plus stronger southwest flow would raise heavy-rain risk nationwide, especially central/southern mountains.",
    },
    {
        "label": "PTS 2026-06-09",
        "url": "https://news.pts.org.tw/article/812170",
        "note": "Stationary front and southwest flow affected Taiwan; CWA heavy-rain advisory highlighted short-duration heavy rain, with local torrential rain or extremely heavy rain possible in Kaohsiung/Pingtung mountain areas.",
    },
    {
        "label": "UDN 2026-06-09",
        "url": "https://udn.com/news/story/7266/9554160",
        "note": "Reported CWA advisory counties including Kaohsiung/Pingtung mountain areas and local heavy/torrential rain risk in western Taiwan, Penghu, and Taitung mountains.",
    },
)

SOURCE_LABELS = {
    "taiwan-admin-area-bundled": "admin-area",
    "moi-village-boundary-twd97-geographic": "village",
    "moi-national-road-names": "road",
    "nfa-evacuation-shelter-locations": "shelter",
}

TAIWAN_BOUNDS = {
    "lat_min": 21.7,
    "lat_max": 26.5,
    "lng_min": 118.0,
    "lng_max": 122.5,
}


@dataclass(frozen=True)
class CandidateLocation:
    query: str
    source_key: str
    source_label: str
    county: str
    expected_precision: str
    expected_lat: float
    expected_lng: float
    event_focus: str


@dataclass
class SampleResult:
    index: int
    query: str
    county: str
    source_label: str
    event_focus: str
    geocode_status: int
    geocode_name: str | None
    geocode_source: str | None
    geocode_precision: str | None
    geocode_requires_confirmation: bool | None
    geocode_distance_m: float | None
    risk_status: int | None
    realtime_level: str | None
    historical_level: str | None
    confidence_level: str | None
    evidence_count: int
    freshness_count: int
    source_health: dict[str, str]
    explanation_summary: str | None
    missing_sources: list[str]
    pass_checks: list[str]
    warnings: list[str]
    failures: list[str]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate public-value behavior against the 2026-06-08 to 2026-06-09 "
            "Taiwan Meiyu/southwest-flow heavy-rain event."
        )
    )
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument(
        "--mode",
        choices=("no-network", "simulated-heavy-rain"),
        default=DEFAULT_MODE,
        help=(
            "no-network checks honesty when production sources are unavailable; "
            "simulated-heavy-rain injects recent official CWA/WRA signals to test propagation."
        ),
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument(
        "--generated-at",
        type=parse_generated_at,
        help="ISO 8601 timestamp for reproducible reports; timezone is required.",
    )
    args = parser.parse_args(argv)

    if args.sample_size < 100:
        raise SystemExit("--sample-size must be at least 100 for this event smoke")

    json_output = args.json_output or default_json_output(args.mode)
    markdown_output = args.markdown_output or default_markdown_output(args.mode)

    configure_event_mode(args.mode)
    samples = select_event_samples(load_candidate_locations(), sample_size=args.sample_size, seed=args.seed)
    client = TestClient(create_app())
    results = [
        check_location(client, sample, index=index + 1, mode=args.mode)
        for index, sample in enumerate(samples)
    ]
    payload = build_report_payload(
        results,
        sample_size=args.sample_size,
        seed=args.seed,
        mode=args.mode,
        generated_at=args.generated_at,
    )

    write_json_report(json_output, payload)
    write_markdown_report(markdown_output, payload, json_output=json_output)
    print_report_summary(payload, json_output, markdown_output)
    return 1 if payload["summary"]["failure_count"] else 0


def default_json_output(mode: str) -> Path:
    return ROOT / "test-results" / f"{DEFAULT_EVENT_ID}-{mode}-public-value-smoke.json"


def default_markdown_output(mode: str) -> Path:
    return ROOT / "docs" / "reviews" / f"{DEFAULT_EVENT_ID}-{mode}-public-value-smoke.md"


def configure_event_mode(mode: str) -> None:
    forced_env = {
        "APP_ENV": "test",
        "EVIDENCE_REPOSITORY_ENABLED": "false",
        "GEOCODER_BUNDLED_OPEN_DATA_ENABLED": "true",
        "GEOCODER_POSTGIS_ENABLED": "false",
        "HISTORICAL_NEWS_ON_DEMAND_ENABLED": "false",
        "HISTORICAL_NEWS_ON_DEMAND_WRITEBACK_ENABLED": "false",
        "OFFICIAL_FLOOD_DISASTER_POINTS_ENABLED": "true",
        "PUBLIC_RATE_LIMIT_ENABLED": "false",
        "REALTIME_OFFICIAL_ENABLED": "true" if mode == "simulated-heavy-rain" else "false",
        "SOURCE_CWA_API_ENABLED": "false",
        "SOURCE_NEWS_ENABLED": "false",
        "SOURCE_TERMS_REVIEW_ACK": "false",
        "SOURCE_WRA_API_ENABLED": "false",
    }
    for key, value in forced_env.items():
        os.environ[key] = value

    get_settings.cache_clear()
    public_routes._cached_nominatim_candidates = ORIGINAL_CACHED_NOMINATIM_CANDIDATES
    public_routes._cached_wikimedia_candidates = ORIGINAL_CACHED_WIKIMEDIA_CANDIDATES
    public_routes._cached_nominatim_candidates.cache_clear()
    public_routes._cached_wikimedia_candidates.cache_clear()
    public_routes._cached_nominatim_candidates = lambda *_args: ()
    public_routes._cached_wikimedia_candidates = lambda *_args: ()
    public_routes.fetch_official_realtime_bundle = ORIGINAL_FETCH_OFFICIAL_REALTIME_BUNDLE
    public_routes._ASSESSMENT_EVIDENCE_CACHE.clear()
    public_routes._RISK_ASSESSMENT_RESPONSE_CACHE.clear()
    if mode == "simulated-heavy-rain":
        public_routes.fetch_official_realtime_bundle = simulated_heavy_rain_bundle


def load_candidate_locations() -> list[CandidateLocation]:
    candidates = admin_area_candidate_locations()
    for path in GEOCODER_DATA_PATHS:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                candidate = candidate_location_from_payload(payload)
                if candidate is not None:
                    candidates.append(candidate)
    if not candidates:
        raise RuntimeError("no geocoder candidates loaded")
    return candidates


def admin_area_candidate_locations() -> list[CandidateLocation]:
    candidates: list[CandidateLocation] = []
    for area in load_taiwan_admin_areas():
        county = area.name if area.level == "county" else area.county
        if county not in TAIWAN_COUNTIES:
            continue
        candidates.append(
            CandidateLocation(
                query=area.name,
                source_key="taiwan-admin-area-bundled",
                source_label="admin-area",
                county=county,
                expected_precision="admin_area",
                expected_lat=area.lat,
                expected_lng=area.lng,
                event_focus=event_focus_for_county(county),
            )
        )
    return candidates


def candidate_location_from_payload(payload: dict[str, Any]) -> CandidateLocation | None:
    query = str(payload.get("name") or "").strip()
    if not query:
        return None
    lat = _float_or_none(payload.get("lat"))
    lng = _float_or_none(payload.get("lng"))
    if lat is None or lng is None or not within_taiwan_bounds(lat=lat, lng=lng):
        return None
    source_key = str(payload.get("source_key") or "unknown")
    county = derive_county(payload)
    if county is None:
        return None
    event_focus = event_focus_for_county(county)
    return CandidateLocation(
        query=query,
        source_key=source_key,
        source_label=SOURCE_LABELS.get(source_key, source_key),
        county=county,
        expected_precision=str(payload.get("precision") or "unknown"),
        expected_lat=lat,
        expected_lng=lng,
        event_focus=event_focus,
    )


def derive_county(payload: dict[str, Any]) -> str | None:
    values: list[str] = []
    for key in ("name", "aliases", "admin_code"):
        value = payload.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        raw = metadata.get("raw")
        if isinstance(raw, dict):
            values.extend(str(item) for item in raw.values() if item is not None)
    for value in values:
        normalized = normalize_county_name(value)
        for county in TAIWAN_COUNTIES:
            if county in normalized:
                return county
    return None


def normalize_county_name(value: str) -> str:
    normalized = value
    for source, target in COUNTY_ALIASES.items():
        normalized = normalized.replace(source, target)
    return normalized


def event_focus_for_county(county: str) -> str:
    if county in EVENT_CORE_ALERT_COUNTIES:
        return "core-alert"
    if county in EVENT_HIGH_CONCERN_COUNTIES:
        return "high-concern"
    return "nationwide-context"


def simulated_heavy_rain_bundle(
    *,
    lat: float,
    lng: float,
    now: datetime | None = None,
    **_kwargs: object,
) -> OfficialRealtimeBundle:
    observed_at = (now or datetime.now(UTC)) - timedelta(minutes=5)
    ingested_at = observed_at + timedelta(minutes=2)
    return OfficialRealtimeBundle(
        observations=(
            OfficialRealtimeObservation(
                source_id=f"cwa-rainfall:simulated:{round(lat, 4)}:{round(lng, 4)}",
                source_name="中央氣象署即時雨量",
                event_type="rainfall",
                title="中央氣象署雨量站：事件驗證模擬站",
                summary="最近雨量站「事件驗證模擬站」1 小時雨量 88.0 mm，10 分鐘雨量 24.0 mm。",
                observed_at=observed_at,
                ingested_at=ingested_at,
                lat=lat,
                lng=lng,
                distance_to_query_m=80.0,
                confidence=0.95,
                freshness_score=0.99,
                source_weight=1.0,
                risk_factor=1.0,
            ),
            OfficialRealtimeObservation(
                source_id=f"wra-water-level:simulated:{round(lat, 4)}:{round(lng, 4)}",
                source_name="經濟部水利署即時水位",
                event_type="water_level",
                title="水利署水位站：事件驗證模擬站",
                summary="最近水位站「事件驗證模擬站」水位已達一級警戒。",
                observed_at=observed_at,
                ingested_at=ingested_at,
                lat=lat,
                lng=lng,
                distance_to_query_m=120.0,
                confidence=0.92,
                freshness_score=0.99,
                source_weight=1.0,
                risk_factor=1.0,
            ),
        ),
        source_statuses=(
            OfficialRealtimeSourceStatus(
                source_id="cwa-rainfall",
                name="中央氣象署即時雨量",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=ingested_at,
                message="事件驗證模式：注入查詢點附近 88 mm/hr 的近期官方雨量訊號。",
            ),
            OfficialRealtimeSourceStatus(
                source_id="wra-water-level",
                name="經濟部水利署即時水位",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=ingested_at,
                message="事件驗證模式：注入查詢點附近達警戒的近期官方水位訊號。",
            ),
        ),
    )


def select_event_samples(
    candidates: list[CandidateLocation],
    *,
    sample_size: int,
    seed: str,
) -> list[CandidateLocation]:
    rng = random.Random(seed)
    selected: list[CandidateLocation] = []
    selected_keys: set[str] = set()

    by_county: dict[str, list[CandidateLocation]] = defaultdict(list)
    by_focus: dict[str, list[CandidateLocation]] = defaultdict(list)
    for candidate in candidates:
        by_county[candidate.county].append(candidate)
        by_focus[candidate.event_focus].append(candidate)

    for group in (*by_county.values(), *by_focus.values()):
        rng.shuffle(group)

    for county in TAIWAN_COUNTIES:
        if by_county[county]:
            append_unique(selected, selected_keys, by_county[county][0])

    targets = {
        "core-alert": max(30, sample_size * 35 // 100),
        "high-concern": max(25, sample_size * 35 // 100),
        "nationwide-context": sample_size,
    }
    for focus, target in targets.items():
        for candidate in by_focus[focus]:
            if len([item for item in selected if item.event_focus == focus]) >= target:
                break
            append_unique(selected, selected_keys, candidate)
            if len(selected) >= sample_size:
                break

    shuffled_candidates = candidates[:]
    rng.shuffle(shuffled_candidates)
    for candidate in shuffled_candidates:
        if len(selected) >= sample_size:
            break
        append_unique(selected, selected_keys, candidate)

    rng.shuffle(selected)
    return selected[:sample_size]


def append_unique(
    selected: list[CandidateLocation],
    selected_keys: set[str],
    candidate: CandidateLocation,
) -> None:
    key = stable_location_key(candidate)
    if key in selected_keys:
        return
    selected.append(candidate)
    selected_keys.add(key)


def stable_location_key(candidate: CandidateLocation) -> str:
    return hashlib.sha256(
        f"{candidate.source_key}|{candidate.query}|{candidate.expected_lat}|{candidate.expected_lng}".encode(
            "utf-8"
        )
    ).hexdigest()


def check_location(
    client: TestClient,
    sample: CandidateLocation,
    *,
    index: int,
    mode: str,
) -> SampleResult:
    pass_checks: list[str] = []
    warnings: list[str] = []
    failures: list[str] = []
    geocode = client.post(
        "/v1/geocode",
        json={"query": sample.query, "input_type": "address", "limit": 1},
    )
    if geocode.status_code != 200:
        return empty_result(
            index=index,
            sample=sample,
            geocode_status=geocode.status_code,
            failures=[f"geocode HTTP {geocode.status_code}"],
        )

    candidates = geocode.json().get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return empty_result(
            index=index,
            sample=sample,
            geocode_status=geocode.status_code,
            failures=["geocode returned no candidates"],
        )

    candidate = candidates[0]
    point = candidate.get("point") if isinstance(candidate, dict) else None
    if not isinstance(point, dict):
        return empty_result(
            index=index,
            sample=sample,
            geocode_status=geocode.status_code,
            failures=["geocode candidate has no point"],
        )

    lat = _float_or_none(point.get("lat"))
    lng = _float_or_none(point.get("lng"))
    if lat is None or lng is None or not within_taiwan_bounds(lat=lat, lng=lng):
        failures.append(f"geocode point outside Taiwan bounds: {point}")
    else:
        pass_checks.append("geocode_point_within_taiwan")

    distance_m = haversine_m(sample.expected_lat, sample.expected_lng, lat, lng)
    if distance_m > 7500:
        warnings.append(f"geocode point is {round(distance_m)}m from sampled source point")
    else:
        pass_checks.append("geocode_point_near_sample")

    precision = str(candidate.get("precision") or "unknown")
    if precision == "unknown":
        warnings.append("geocode precision is unknown")
    elif precision in {"admin_area", "road_or_lane"}:
        warnings.append(f"geocode precision is {precision}; UI must keep confirmation/limitations visible")
    else:
        pass_checks.append(f"geocode_precision_{precision}")

    risk_status: int | None = None
    risk_payload: dict[str, Any] = {}
    if not failures:
        risk = client.post(
            "/v1/risk/assess",
            json={
                "point": point,
                "radius_m": 500,
                "time_context": "now",
                "location_text": sample.query,
            },
        )
        risk_status = risk.status_code
        if risk.status_code != 200:
            failures.append(f"risk HTTP {risk.status_code}")
        else:
            risk_payload = risk.json()
            failures.extend(validate_risk_payload(risk_payload))
            failures.extend(simulated_heavy_rain_failures(risk_payload) if mode == "simulated-heavy-rain" else [])
            pass_checks.extend(public_truthfulness_checks(sample, risk_payload, warnings, mode=mode))

    return SampleResult(
        index=index,
        query=sample.query,
        county=sample.county,
        source_label=sample.source_label,
        event_focus=sample.event_focus,
        geocode_status=geocode.status_code,
        geocode_name=str(candidate.get("name")) if isinstance(candidate, dict) else None,
        geocode_source=str(candidate.get("source")) if isinstance(candidate, dict) else None,
        geocode_precision=precision,
        geocode_requires_confirmation=(
            bool(candidate.get("requires_confirmation")) if isinstance(candidate, dict) else None
        ),
        geocode_distance_m=round(distance_m, 1) if lat is not None and lng is not None else None,
        risk_status=risk_status,
        realtime_level=level_from_payload(risk_payload, "realtime"),
        historical_level=level_from_payload(risk_payload, "historical"),
        confidence_level=level_from_payload(risk_payload, "confidence"),
        evidence_count=len(risk_payload.get("evidence") or []),
        freshness_count=len(risk_payload.get("data_freshness") or []),
        source_health=source_health_from_payload(risk_payload),
        explanation_summary=risk_payload.get("explanation", {}).get("summary") if risk_payload else None,
        missing_sources=list(risk_payload.get("explanation", {}).get("missing_sources") or []),
        pass_checks=pass_checks,
        warnings=warnings,
        failures=failures,
    )


def empty_result(
    *,
    index: int,
    sample: CandidateLocation,
    geocode_status: int,
    failures: list[str],
) -> SampleResult:
    return SampleResult(
        index=index,
        query=sample.query,
        county=sample.county,
        source_label=sample.source_label,
        event_focus=sample.event_focus,
        geocode_status=geocode_status,
        geocode_name=None,
        geocode_source=None,
        geocode_precision=None,
        geocode_requires_confirmation=None,
        geocode_distance_m=None,
        risk_status=None,
        realtime_level=None,
        historical_level=None,
        confidence_level=None,
        evidence_count=0,
        freshness_count=0,
        source_health={},
        explanation_summary=None,
        missing_sources=[],
        pass_checks=[],
        warnings=[],
        failures=failures,
    )


def validate_risk_payload(payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for field in ("assessment_id", "realtime", "historical", "confidence", "explanation"):
        if field not in payload:
            failures.append(f"risk missing {field}")
    if not payload.get("explanation", {}).get("summary"):
        failures.append("risk missing explanation summary")
    if not isinstance(payload.get("data_freshness"), list):
        failures.append("risk data_freshness is not a list")
    if not isinstance(payload.get("evidence"), list):
        failures.append("risk evidence is not a list")
    return failures


def public_truthfulness_checks(
    sample: CandidateLocation,
    payload: dict[str, Any],
    warnings: list[str],
    *,
    mode: str,
) -> list[str]:
    checks: list[str] = []
    realtime_level = level_from_payload(payload, "realtime")
    historical_level = level_from_payload(payload, "historical")
    confidence_level = level_from_payload(payload, "confidence")
    summary = str(payload.get("explanation", {}).get("summary") or "")
    missing_sources = payload.get("explanation", {}).get("missing_sources") or []
    evidence = payload.get("evidence") or []
    freshness = payload.get("data_freshness") or []
    health = source_health_from_payload(payload)

    if summary:
        checks.append("risk_explanation_visible")
    if isinstance(missing_sources, list) and missing_sources:
        checks.append("missing_sources_visible")
    elif mode == "no-network":
        warnings.append("risk response does not list missing sources")

    if isinstance(freshness, list) and freshness:
        checks.append("data_freshness_visible")
    else:
        warnings.append("risk response has no data freshness records")

    if sample.event_focus in {"core-alert", "high-concern"}:
        if realtime_level == "低" and confidence_level in {"中", "高"} and not evidence:
            warnings.append("event high-concern location could read as false reassurance")
        elif realtime_level in {"未知", "中", "高"} or confidence_level == "未知":
            checks.append("event_uncertainty_not_hidden")

    if not evidence:
        warnings.append("risk response has no location-specific evidence")
    elif len(evidence) > 0:
        checks.append("location_evidence_visible")

    official_runtime_sources = {"cwa-rainfall", "wra-water-level"}
    missing_runtime = sorted(official_runtime_sources.difference(health))
    if missing_runtime:
        warnings.append(f"runtime official source statuses missing: {', '.join(missing_runtime)}")
    elif any(health[source] in {"degraded", "unavailable", "disabled"} for source in official_runtime_sources):
        checks.append("official_runtime_limitations_visible")
    else:
        checks.append("official_runtime_sources_visible")

    if historical_level == "低" and confidence_level == "高" and not evidence:
        warnings.append("high-confidence low historical risk has no evidence records")

    return checks


def simulated_heavy_rain_failures(payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    realtime_level = level_from_payload(payload, "realtime")
    confidence_level = level_from_payload(payload, "confidence")
    evidence = payload.get("evidence") or []
    health = source_health_from_payload(payload)
    if realtime_level != "高":
        failures.append(f"simulated heavy official rainfall/water-level should produce high realtime risk, got {realtime_level}")
    if confidence_level not in {"中", "高"}:
        failures.append(f"simulated heavy official data should produce medium/high confidence, got {confidence_level}")
    official_types = {
        item.get("event_type")
        for item in evidence
        if isinstance(item, dict) and item.get("source_type") == "official"
    }
    if not {"rainfall", "water_level"}.issubset(official_types):
        failures.append("simulated official rainfall and water-level evidence are not both visible")
    for source_id in ("cwa-rainfall", "wra-water-level"):
        if health.get(source_id) != "healthy":
            failures.append(f"{source_id} status should be healthy in simulated mode")
    return failures


def level_from_payload(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if isinstance(value, dict):
        level = value.get("level")
        return str(level) if level is not None else None
    return None


def source_health_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    health: dict[str, str] = {}
    freshness = payload.get("data_freshness")
    if not isinstance(freshness, list):
        return health
    for item in freshness:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        status = item.get("health_status")
        if isinstance(source_id, str) and isinstance(status, str):
            health[source_id] = status
    return health


def within_taiwan_bounds(*, lat: float, lng: float) -> bool:
    return (
        TAIWAN_BOUNDS["lat_min"] <= lat <= TAIWAN_BOUNDS["lat_max"]
        and TAIWAN_BOUNDS["lng_min"] <= lng <= TAIWAN_BOUNDS["lng_max"]
    )


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    earth_radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    r_lat1 = radians(lat1)
    r_lat2 = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lng / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def build_report_payload(
    results: list[SampleResult],
    *,
    sample_size: int,
    seed: str,
    mode: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    warning_count = sum(len(result.warnings) for result in results)
    failure_count = sum(len(result.failures) for result in results)
    by_county = Counter(result.county for result in results)
    by_focus = Counter(result.event_focus for result in results)
    by_source = Counter(result.source_label for result in results)
    geocode_precisions = Counter(result.geocode_precision or "none" for result in results)
    risk_levels = Counter(result.realtime_level or "none" for result in results)
    source_health: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        for source_id, status in result.source_health.items():
            source_health[source_id][status] += 1

    return {
        "schema_version": "event-public-value-smoke/v1",
        "event_id": DEFAULT_EVENT_ID,
        "generated_at": (generated_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "mode": mode,
        "sample_size": sample_size,
        "seed": seed,
        "event_sources": EVENT_SOURCES,
        "summary": {
            "checked": len(results),
            "failure_count": failure_count,
            "locations_with_failures": sum(1 for result in results if result.failures),
            "warning_count": warning_count,
            "locations_with_warnings": sum(1 for result in results if result.warnings),
            "geocode_success_count": sum(1 for result in results if result.geocode_status == 200),
            "risk_success_count": sum(1 for result in results if result.risk_status == 200),
            "county_coverage_count": len(by_county),
            "by_focus": dict(sorted(by_focus.items())),
            "by_source": dict(sorted(by_source.items())),
            "geocode_precisions": dict(sorted(geocode_precisions.items())),
            "realtime_levels": dict(sorted(risk_levels.items())),
            "source_health": {
                source_id: dict(sorted(counter.items())) for source_id, counter in sorted(source_health.items())
            },
        },
        "interpretation": interpretation(results, mode=mode),
        "samples": [asdict(result) for result in results],
    }


def interpretation(results: list[SampleResult], *, mode: str) -> dict[str, Any]:
    all_green = not any(result.failures for result in results)
    no_false_reassurance = not any(
        "event high-concern location could read as false reassurance" in result.warnings
        for result in results
    )
    missing_evidence_locations = sum(
        1 for result in results if "risk response has no location-specific evidence" in result.warnings
    )
    no_runtime_status_locations = sum(
        1
        for result in results
        if any(warning.startswith("runtime official source statuses missing") for warning in result.warnings)
    )
    if mode == "simulated-heavy-rain":
        high_realtime = sum(1 for result in results if result.realtime_level == "高")
        visible_official_evidence = sum(
            1
            for result in results
            if result.evidence_count >= 2 and not result.failures
        )
        return {
            "public_value_readiness": "simulated_official_signal_propagates" if all_green else "needs_fix",
            "primary_takeaways": [
                "Search and assessment API flow works for the sampled Taiwan locations."
                if all_green
                else "At least one sampled location failed geocode or assessment.",
                (
                    f"{high_realtime} sampled locations produced high realtime risk after injecting "
                    "recent official heavy-rain and water-level signals."
                ),
                (
                    f"{visible_official_evidence} sampled locations exposed official rainfall/water-level "
                    "evidence in the public response."
                ),
                "This is an architecture propagation smoke, not proof that production live data is accepted.",
            ],
        }

    return {
        "public_value_readiness": (
            "local_candidate_honest_but_not_event_complete" if all_green and no_false_reassurance else "needs_fix"
        ),
        "primary_takeaways": [
            "Search and assessment API flow works for the sampled Taiwan locations."
            if all_green
            else "At least one sampled location failed geocode or assessment.",
            "High-concern event areas are not presented as confident low risk without evidence."
            if no_false_reassurance
            else "Some high-concern event areas may read as false reassurance.",
            (
                f"{missing_evidence_locations} sampled locations lack location-specific evidence in "
                "no-network mode; this confirms production source/replay evidence is still required."
            ),
            (
                f"{no_runtime_status_locations} sampled locations do not expose both live CWA/WRA runtime "
                "source statuses in this mode; hosted public launch still needs accepted realtime source gates."
            ),
        ],
    }


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown_report(path: Path, payload: dict[str, Any], *, json_output: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    interpretation_payload = payload["interpretation"]
    lines = [
        "# 2026-06-08 to 2026-06-09 Taiwan Heavy-Rain Public-Value Smoke",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Event Baseline",
        "",
    ]
    for source in payload["event_sources"]:
        lines.append(f"- [{source['label']}]({source['url']}): {source['note']}")
    lines.extend(
        [
            "",
            "## Result",
            "",
            f"- Mode: `{payload['mode']}`",
            f"- Checked locations: `{summary['checked']}`",
            f"- Counties covered: `{summary['county_coverage_count']}`",
            f"- Geocode successes: `{summary['geocode_success_count']}`",
            f"- Risk successes: `{summary['risk_success_count']}`",
            f"- Failure count: `{summary['failure_count']}`",
            f"- Warning count: `{summary['warning_count']}`",
            f"- Public-value readiness: `{interpretation_payload['public_value_readiness']}`",
            "",
            "## Takeaways",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in interpretation_payload["primary_takeaways"])
    lines.extend(
        [
            "",
            "## Distribution",
            "",
            f"- Event focus: `{json.dumps(summary['by_focus'], ensure_ascii=False)}`",
            f"- Source mix: `{json.dumps(summary['by_source'], ensure_ascii=False)}`",
            f"- Geocode precision: `{json.dumps(summary['geocode_precisions'], ensure_ascii=False)}`",
            f"- Realtime levels: `{json.dumps(summary['realtime_levels'], ensure_ascii=False)}`",
            f"- Source health: `{json.dumps(summary['source_health'], ensure_ascii=False)}`",
            "",
            "## Highest-Signal Warnings",
            "",
        ]
    )
    warning_counts: Counter[str] = Counter(
        warning for sample in payload["samples"] for warning in sample["warnings"]
    )
    if warning_counts:
        lines.extend(f"- `{count}` x {warning}" for warning, count in warning_counts.most_common(12))
    else:
        lines.append("- None.")

    failing_samples = [sample for sample in payload["samples"] if sample["failures"]]
    lines.extend(["", "## Failures", ""])
    if failing_samples:
        for sample in failing_samples:
            lines.append(
                f"- #{sample['index']} {sample['query']} ({sample['county']}): "
                f"{'; '.join(sample['failures'])}"
            )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Evidence Artifact",
            "",
            f"- Local JSON details, gitignored: `{json_output.relative_to(ROOT)}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_report_summary(payload: dict[str, Any], json_output: Path, markdown_output: Path) -> None:
    summary = payload["summary"]
    interpretation_payload = payload["interpretation"]
    print(
        "EVENT_PUBLIC_VALUE_SMOKE "
        f"checked={summary['checked']} "
        f"failures={summary['failure_count']} "
        f"warnings={summary['warning_count']} "
        f"readiness={interpretation_payload['public_value_readiness']}"
    )
    for takeaway in interpretation_payload["primary_takeaways"]:
        print(f"- {takeaway}")
    print(f"json={json_output}")
    print(f"markdown={markdown_output}")


def parse_generated_at(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--generated-at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--generated-at must include a timezone offset")
    return parsed.astimezone(UTC)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
