from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import warnings
from uuid import UUID

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
import pytest
import yaml  # type: ignore[import-untyped]

from app.api.schemas import DependencyReadiness, LatLng, PlaceCandidate
from app.api.routes import health as health_routes
from app.api.routes import public as public_routes
from app.core.config import get_settings
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    EvidenceUpsert,
    QueryHeatSnapshot,
)
from app.domain.history import HistoricalFloodRecord, OfficialFloodDisasterLookup
from app.domain.layers import LayerRecord, LayerRepositoryUnavailable
from app.domain.profiles import RiskProfileRecord
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
)
from app.domain.realtime import official as official_realtime
from app.main import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema import RefResolver  # type: ignore[import-untyped]


client = TestClient(create_app())
RISK_LEVELS = {"低", "中", "高", "極高", "未知"}
CONFIDENCE_LEVELS = {"低", "中", "高", "未知"}
REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_SPEC = yaml.safe_load((REPO_ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def fallback_to_local_historical_records(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(**_kwargs: object) -> tuple[EvidenceRecord, ...]:
        raise EvidenceRepositoryUnavailable("database unavailable in contract tests")

    def layers_unavailable(**_kwargs: object) -> tuple[LayerRecord, ...]:
        raise LayerRepositoryUnavailable("database unavailable in contract tests")

    def profile_unavailable(**_kwargs: object) -> None:
        raise public_routes.RiskProfileRepositoryUnavailable(
            "profile database unavailable in contract tests"
        )

    monkeypatch.setattr(public_routes, "query_nearby_evidence", unavailable)
    monkeypatch.setattr(public_routes, "fetch_query_heat_snapshot", unavailable)
    monkeypatch.setattr(public_routes, "persist_risk_assessment", unavailable)
    monkeypatch.setattr(public_routes, "fetch_map_layers", layers_unavailable)
    monkeypatch.setattr(public_routes, "fetch_best_profile_for_point", profile_unavailable)


def assert_iso_datetime(value: str) -> None:
    datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_error_envelope(payload: dict) -> None:
    assert set(payload) == {"error"}
    assert {"code", "message"}.issubset(payload["error"])


def assert_openapi_schema(payload: dict, schema_name: str) -> None:
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": OPENAPI_SPEC["components"],
    }
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema))
    errors = list(validator.iter_errors(payload))
    assert errors == []


def test_health_contract() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"status", "service", "version", "deployment_sha", "checked_at"}
    assert payload["status"] == "ok"
    assert payload["service"] == "flood-risk-api"
    assert_iso_datetime(payload["checked_at"])
    assert_openapi_schema(payload, "HealthResponse")


def test_ready_contract_when_dependencies_are_healthy(monkeypatch) -> None:
    dependency = DependencyReadiness(
        status="healthy",
        checked_at=datetime.fromisoformat("2026-04-29T03:00:00+00:00"),
        message=None,
    )
    monkeypatch.setattr(health_routes, "_check_database", lambda _url: dependency)
    monkeypatch.setattr(health_routes, "_check_redis", lambda _url: dependency)

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "deployment_sha" in payload
    assert set(payload["dependencies"]) == {"database", "redis"}
    assert_openapi_schema(payload, "ReadyResponse")


def test_ready_returns_503_when_dependency_fails(monkeypatch) -> None:
    checked_at = datetime.fromisoformat("2026-04-29T03:00:00+00:00")
    healthy = DependencyReadiness(status="healthy", checked_at=checked_at, message=None)
    failed = DependencyReadiness(status="failed", checked_at=checked_at, message="connection refused")
    monkeypatch.setattr(health_routes, "_check_database", lambda _url: healthy)
    monkeypatch.setattr(health_routes, "_check_redis", lambda _url: failed)

    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "down"
    assert payload["dependencies"]["redis"]["status"] == "failed"
    assert_openapi_schema(payload, "ReadyResponse")


def test_metrics_endpoint_exposes_prometheus_text() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "flood_risk_api_up 1" in text
    assert 'flood_risk_api_info{service="flood-risk-api",' in text
    assert 'version="' in text


def test_runtime_openapi_exposes_health_and_readiness_schemas() -> None:
    runtime_spec = client.get("/openapi.json").json()

    health_schema = runtime_spec["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    ready_responses = runtime_spec["paths"]["/ready"]["get"]["responses"]

    assert health_schema == {"$ref": "#/components/schemas/HealthResponse"}
    assert ready_responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReadyResponse"
    }
    assert ready_responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReadyResponse"
    }


def test_geocode_contract_and_limit() -> None:
    response = client.post(
        "/v1/geocode",
        json={"query": "Taipei 101", "input_type": "landmark", "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"candidates"}
    assert len(payload["candidates"]) == 2
    candidate = payload["candidates"][0]
    assert set(candidate) == {
        "place_id",
        "name",
        "type",
        "point",
        "admin_code",
        "source",
        "confidence",
        "precision",
        "matched_query",
        "requires_confirmation",
        "limitations",
    }
    assert UUID(candidate["place_id"])
    assert candidate["name"] == "Taipei 101"
    assert candidate["type"] == "landmark"
    assert candidate["precision"] == "poi"
    assert candidate["requires_confirmation"] is False
    assert candidate["limitations"]
    assert set(candidate["point"]) == {"lat", "lng"}
    assert 0 <= candidate["confidence"] <= 1
    assert_openapi_schema(payload, "GeocodeResponse")


def test_geocoder_open_data_status_reports_no_secret_summary(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example.invalid/db")
    monkeypatch.setattr(
        public_routes,
        "fetch_postgis_geocoder_summary",
        lambda _url: {
            "row_count": 2,
            "source_counts": [{"source_key": "moi-national-road-names", "row_count": 2}],
        },
    )

    try:
        response = client.get("/v1/geocoder/open-data/status")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["row_count"] == 2
    assert payload["source_counts"] == [{"source_key": "moi-national-road-names", "row_count": 2}]
    assert "postgresql" not in response.text
    assert "password" not in response.text


def test_geocode_returns_taipei_main_station_coordinate() -> None:
    response = client.post(
        "/v1/geocode",
        json={"query": "台北火車站", "input_type": "landmark", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "台北火車站"
    assert candidate["point"] == {"lat": 25.04776, "lng": 121.51706}


def test_geocode_uses_external_provider_when_local_lookup_misses(monkeypatch) -> None:
    external_candidate = PlaceCandidate(
        place_id="external-place",
        name="斗六車站",
        type="landmark",
        point=LatLng(lat=23.71148, lng=120.54175),
        admin_code=None,
        source="openstreetmap-nominatim",
        confidence=0.9,
        precision="poi",
    )
    monkeypatch.setattr(
        public_routes,
        "_cached_nominatim_candidates",
        lambda *_args: (external_candidate,),
    )

    response = client.post(
        "/v1/geocode",
        json={"query": "斗六車站", "input_type": "landmark", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "斗六車站"
    assert candidate["point"] == {"lat": 23.71148, "lng": 120.54175}
    assert candidate["source"] == "openstreetmap-nominatim"


def test_geocode_falls_back_from_house_number_to_lane(monkeypatch) -> None:
    lane_candidate = PlaceCandidate(
        place_id="lane-place",
        name="培安路305巷",
        type="address",
        point=LatLng(lat=23.038818, lng=120.213493),
        admin_code=None,
        source="openstreetmap-nominatim",
        confidence=0.9,
    )

    def fake_cached_nominatim(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        if query == "培安路305巷":
            return (lane_candidate,)
        return ()

    monkeypatch.setattr(public_routes, "_cached_nominatim_candidates", fake_cached_nominatim)

    response = client.post(
        "/v1/geocode",
        json={"query": "培安路305巷5號", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "培安路305巷（由門牌定位到巷道）"
    assert candidate["point"] == {"lat": 23.038818, "lng": 120.213493}
    assert candidate["source"] == "openstreetmap-nominatim-address-fallback"
    assert candidate["confidence"] == 0.78
    assert candidate["precision"] == "road_or_lane"
    assert candidate["matched_query"] == "培安路305巷"
    assert candidate["requires_confirmation"] is False
    assert "原始門牌未能精準定位" in " ".join(candidate["limitations"])


def test_geocode_returns_admin_area_candidate_that_requires_confirmation() -> None:
    response = client.post(
        "/v1/geocode",
        json={"query": "宜蘭縣礁溪鄉", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "宜蘭縣礁溪鄉"
    assert candidate["type"] == "admin_area"
    assert candidate["source"] == "local-taiwan-admin-centroid"
    assert candidate["precision"] == "admin_area"
    assert candidate["requires_confirmation"] is True
    assert "定位只到行政區代表點" in " ".join(candidate["limitations"])
    assert_openapi_schema(response.json(), "GeocodeResponse")


def test_geocode_matches_spaced_taiwan_admin_area_before_external_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "_cached_nominatim_candidates",
        lambda *_args: pytest.fail("local admin area should resolve before external lookup"),
    )
    monkeypatch.setattr(
        public_routes,
        "_cached_wikimedia_candidates",
        lambda *_args: pytest.fail("local admin area should resolve before Wikimedia fallback"),
    )

    response = client.post(
        "/v1/geocode",
        json={"query": "高雄 左營", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "高雄市左營區"
    assert candidate["type"] == "admin_area"
    assert candidate["source"] == "local-taiwan-admin-centroid"
    assert candidate["precision"] == "admin_area"
    assert candidate["matched_query"] in {"高雄左營", "高雄市左營", "高雄左營區", "高雄市左營區"}
    assert candidate["requires_confirmation"] is True
    assert "定位只到行政區代表點" in " ".join(candidate["limitations"])


def test_geocode_returns_admin_centroid_for_uncovered_taiwan_address(monkeypatch) -> None:
    monkeypatch.setattr(public_routes, "_cached_nominatim_candidates", lambda *_args: ())
    monkeypatch.setattr(public_routes, "_cached_wikimedia_candidates", lambda *_args: ())

    response = client.post(
        "/v1/geocode",
        json={"query": "新竹市東區光復路二段101號", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "新竹市東區（由地址退回行政區代表點）"
    assert candidate["source"] == "taiwan-admin-centroid-fallback"
    assert candidate["precision"] == "admin_area"
    assert candidate["requires_confirmation"] is True
    assert candidate["confidence"] >= 0.65
    assert "退回行政區代表點" in " ".join(candidate["limitations"])
    assert_openapi_schema(response.json(), "GeocodeResponse")


def test_geocode_returns_tainan_cigu_salt_mountain() -> None:
    response = client.post(
        "/v1/geocode",
        json={"query": "台南七股鹽山", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "台南七股鹽山"
    assert candidate["source"] == "local-taiwan-gazetteer"
    assert candidate["confidence"] >= 0.9
    assert abs(candidate["point"]["lat"] - 23.152758) < 0.0001
    assert abs(candidate["point"]["lng"] - 120.102489) < 0.0001


def test_geocode_returns_zuoying_taoziyuan_road_for_event_query() -> None:
    response = client.post(
        "/v1/geocode",
        json={"query": "2024 高雄左營桃子園路 淹水", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "2024 高雄左營桃子園路 淹水"
    assert candidate["source"] == "local-taiwan-gazetteer"
    assert candidate["admin_code"] == "64000000"
    assert abs(candidate["point"]["lat"] - 22.6731) < 0.0001
    assert abs(candidate["point"]["lng"] - 120.2862) < 0.0001


def test_geocode_normalizes_event_query_before_external_lookup(monkeypatch) -> None:
    external_candidate = PlaceCandidate(
        place_id="normalized-place",
        name="高雄市岡山區嘉新東路",
        type="address",
        point=LatLng(lat=22.8052, lng=120.3034),
        admin_code=None,
        source="openstreetmap-nominatim",
        confidence=0.9,
    )
    queries: list[str] = []

    def fake_cached_nominatim(query: str, *_args: object) -> tuple[PlaceCandidate, ...]:
        queries.append(query)
        if query == "高雄市岡山區嘉新東路":
            return (external_candidate,)
        return ()

    monkeypatch.setattr(public_routes, "_cached_nominatim_candidates", fake_cached_nominatim)

    response = client.post(
        "/v1/geocode",
        json={"query": "2024 高雄岡山嘉新東路 豪雨淹水新聞", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert queries[0] == "高雄市岡山嘉新東路"
    assert "高雄市岡山區嘉新東路" in queries
    assert candidate["name"] == "高雄市岡山區嘉新東路（由查詢文字萃取地名）"
    assert candidate["source"] == "openstreetmap-nominatim-taiwan-normalized"
    assert candidate["point"] == {"lat": 22.8052, "lng": 120.3034}
    assert candidate["precision"] == "road_or_lane"
    assert candidate["matched_query"] == "高雄市岡山區嘉新東路"
    assert "查詢文字已先清理" in " ".join(candidate["limitations"])


def test_geocode_uses_wikimedia_poi_fallback_when_osm_misses(monkeypatch) -> None:
    wiki_candidate = PlaceCandidate(
        place_id="wiki-place",
        name="知名景點",
        type="landmark",
        point=LatLng(lat=23.1, lng=120.2),
        admin_code=None,
        source="wikimedia-coordinates",
        confidence=0.84,
        precision="poi",
        matched_query="知名景點",
        limitations=["定位結果是地標座標，不代表門牌精準位置。"],
    )
    monkeypatch.setattr(public_routes, "_cached_nominatim_candidates", lambda *_args: ())
    monkeypatch.setattr(public_routes, "_cached_wikimedia_candidates", lambda *_args: (wiki_candidate,))

    response = client.post(
        "/v1/geocode",
        json={"query": "不在本地清單的知名景點", "input_type": "address", "limit": 1},
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["name"] == "知名景點"
    assert candidate["type"] == "landmark"
    assert candidate["source"] == "wikimedia-coordinates"
    assert candidate["precision"] == "poi"
    assert candidate["requires_confirmation"] is False
    assert candidate["point"] == {"lat": 23.1, "lng": 120.2}


def test_risk_assess_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _official_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "nearest_public_news_location_text",
        lambda **_kwargs: None,
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 25.033, "lng": 121.5654},
            "radius_m": 500,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "assessment_id",
        "location",
        "radius_m",
        "score_version",
        "created_at",
        "expires_at",
        "realtime",
        "historical",
        "confidence",
        "explanation",
        "evidence",
        "data_freshness",
        "query_heat",
    }
    assert UUID(payload["assessment_id"])
    assert payload["location"] == {"lat": 25.033, "lng": 121.5654}
    assert payload["radius_m"] == 500
    assert_iso_datetime(payload["created_at"])
    assert_iso_datetime(payload["expires_at"])
    assert set(payload["realtime"]) == {"level"}
    assert set(payload["historical"]) == {"level"}
    assert set(payload["confidence"]) == {"level"}
    assert payload["realtime"]["level"] in RISK_LEVELS
    assert payload["historical"]["level"] == "未知"
    assert payload["confidence"]["level"] in CONFIDENCE_LEVELS
    assert len(payload["evidence"]) >= 2
    assert payload["explanation"]["missing_sources"] == [
        "查詢半徑內尚未匯入實際歷史淹水事件或公開新聞紀錄；"
        "目前資料不足，淹水潛勢圖資只能作為情境參考，不能標記為低風險或購屋安全。"
    ]
    assert set(payload["evidence"][0]) == {
        "id",
        "source_type",
        "event_type",
        "title",
        "summary",
        "occurred_at",
        "observed_at",
        "ingested_at",
        "distance_to_query_m",
        "confidence",
        "url",
    }
    assert payload["data_freshness"][0]["health_status"] == "healthy"
    assert payload["data_freshness"][0]["source_id"] == "cwa-rainfall"
    assert payload["query_heat"]["period"] == "P7D"
    assert payload["query_heat"]["attention_level"] in RISK_LEVELS
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_official_evidence_links_to_data_gov_catalog() -> None:
    rainfall, water_level = _official_realtime_bundle().observations

    rainfall_evidence = public_routes._official_realtime_evidence(rainfall)
    water_level_evidence = public_routes._official_realtime_evidence(water_level)
    flood_potential_evidence = public_routes._evidence_from_record(_flood_potential_record())

    assert rainfall_evidence.url == "https://data.gov.tw/dataset/9177"
    assert water_level_evidence.url == "https://data.gov.tw/dataset/25768"
    assert flood_potential_evidence.url == "https://data.gov.tw/dataset/25766"


def test_risk_assess_surfaces_official_flood_disaster_points(
    monkeypatch,
    tmp_path,
) -> None:
    csv_path = tmp_path / "flood_points.csv"
    csv_path.write_text(
        "\n".join(
            (
                "FID,year,X_97,Y_97,source",
                "0,2023,172956.00,2543478.00,EMIC",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OFFICIAL_FLOOD_DISASTER_POINTS_ENABLED", "true")
    monkeypatch.setenv("OFFICIAL_FLOOD_DISASTER_POINTS_PATH", str(csv_path))
    monkeypatch.setenv("HISTORICAL_NEWS_ON_DEMAND_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 22.990947, "lng": 120.248506},
                "radius_m": 300,
                "time_context": "now",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "中"
    assert any(item["source_type"] == "official" for item in payload["evidence"])
    assert any("官方淹水災害情資點位" in item["title"] for item in payload["evidence"])
    assert not any(
        "尚未匯入實際歷史淹水事件" in source
        for source in payload["explanation"]["missing_sources"]
    )
    official_status = next(
        item for item in payload["data_freshness"] if item["source_id"] == "official-flood-disaster-points"
    )
    assert official_status["health_status"] == "degraded"
    assert "命中 1 筆" in official_status["message"]
    assert "尚未涵蓋 2024-2026" in official_status["message"]
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_keeps_single_old_official_hit_with_potential_context_at_medium(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HISTORICAL_NEWS_ON_DEMAND_ENABLED", "false")
    get_settings.cache_clear()
    now = datetime.fromisoformat("2026-06-10T14:30:00+00:00")
    official_record = HistoricalFloodRecord(
        source_id="data-gov-130016:2021:EMIC:4972",
        source_name="官方資料：淹水災點快照",
        source_type="official",
        event_type="flood_report",
        title="2021 官方淹水災害情資點位（EMIC #4972）",
        summary=(
            "data.gov.tw dataset 130016 彙整防救災部會署淹水災害情資點位；"
            "此筆資料提供年度與座標點，未提供完整事件時間、淹水深度或地址。"
        ),
        url="https://data.gov.tw/dataset/130016",
        occurred_at=datetime.fromisoformat("2021-12-31T12:00:00+08:00"),
        ingested_at=now,
        lat=23.59045,
        lng=120.29340,
        confidence=0.82,
        freshness_score=0.74,
        source_weight=1.0,
        risk_factor=1.0,
    )
    first_potential = replace(
        _flood_potential_record(),
        id="potential-context-1",
        source_id="dprc-taiwan-flood-potential-context-1",
        lat=23.59100,
        lng=120.29320,
        distance_to_query_m=185.0,
        freshness_score=1.0,
        source_weight=1.0,
    )
    second_potential = replace(
        first_potential,
        id="potential-context-2",
        source_id="dprc-taiwan-flood-potential-context-2",
        distance_to_query_m=240.0,
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (first_potential, second_potential),
    )
    monkeypatch.setattr(
        public_routes,
        "lookup_official_flood_disaster_points",
        lambda **_kwargs: OfficialFloodDisasterLookup(
            attempted=True,
            source_id="official-flood-disaster-points",
            name="官方資料：淹水災點快照（2018-2022）",
            health_status="degraded",
            message="官方淹水災點快照命中 1 筆。",
            records=((official_record, 101.0),),
            observed_at=official_record.occurred_at,
            ingested_at=now,
        ),
    )

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 23.59132, "lng": 120.29373},
                "radius_m": 500,
                "time_context": "now",
                "location_text": "劉厝",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["realtime"]["level"] == "未知"
    assert payload["historical"]["level"] == "中"
    assert "歷史與淹水潛勢參考為中" in payload["explanation"]["summary"]
    assert any("官方淹水災害情資點位" in item["title"] for item in payload["evidence"])
    assert any("官方淹水潛勢規劃圖資" in item["title"] for item in payload["evidence"])
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_display_evidence_items_collapses_repeated_official_disaster_points() -> None:
    now = datetime.fromisoformat("2026-05-13T02:00:00+00:00")
    items = [
        public_routes.Evidence(
            id="official-2018",
            source_id="data-gov-130016:2018:EMIC:1",
            source_type="official",
            event_type="flood_report",
            title="2018 官方淹水災害情資點位（EMIC #1）",
            summary="官方淹水災點快照命中。",
            url="https://data.gov.tw/dataset/130016",
            occurred_at=datetime.fromisoformat("2018-12-31T12:00:00+08:00"),
            observed_at=datetime.fromisoformat("2018-12-31T12:00:00+08:00"),
            ingested_at=now,
            point=public_routes.LatLng(lat=23.0, lng=120.2),
            geometry=public_routes.GeoJsonGeometry(type="Point", coordinates=[120.2, 23.0]),
            distance_to_query_m=42.0,
            confidence=0.82,
            freshness_score=0.74,
            source_weight=1.0,
            privacy_level="public",
            raw_ref="historical-record:data-gov-130016:2018:EMIC:1",
        ),
        public_routes.Evidence(
            id="official-2020",
            source_id="data-gov-130016:2020:EMIC:2",
            source_type="official",
            event_type="flood_report",
            title="2020 官方淹水災害情資點位（EMIC #2）",
            summary="官方淹水災點快照命中。",
            url="https://data.gov.tw/dataset/130016",
            occurred_at=datetime.fromisoformat("2020-12-31T12:00:00+08:00"),
            observed_at=datetime.fromisoformat("2020-12-31T12:00:00+08:00"),
            ingested_at=now,
            point=public_routes.LatLng(lat=23.0, lng=120.2),
            geometry=public_routes.GeoJsonGeometry(type="Point", coordinates=[120.2, 23.0]),
            distance_to_query_m=80.0,
            confidence=0.86,
            freshness_score=0.82,
            source_weight=1.0,
            privacy_level="public",
            raw_ref="historical-record:data-gov-130016:2020:EMIC:2",
        ),
    ]

    displayed = public_routes._display_evidence_items(items)

    assert len(displayed) == 1
    assert displayed[0].source_id == "data-gov-130016:summary"
    assert displayed[0].title == "官方淹水災害情資點位彙整（2018、2020）"
    assert "命中 2 筆" in displayed[0].summary
    assert "風險計分仍使用原始命中點位" in displayed[0].summary


def test_official_disaster_summary_uses_latest_available_timestamp() -> None:
    now = datetime.fromisoformat("2026-05-13T02:00:00+00:00")

    def evidence(
        *,
        item_id: str,
        source_id: str,
        distance_to_query_m: float,
        observed_at: datetime | None,
        occurred_at: datetime | None,
    ) -> public_routes.Evidence:
        return public_routes.Evidence(
            id=item_id,
            source_id=source_id,
            source_type="official",
            event_type="flood_report",
            title="Official flood disaster point",
            summary="Official flood disaster point summary.",
            url="https://data.gov.tw/dataset/130016",
            occurred_at=occurred_at,
            observed_at=observed_at,
            ingested_at=now,
            point=public_routes.LatLng(lat=23.0, lng=120.2),
            geometry=public_routes.GeoJsonGeometry(type="Point", coordinates=[120.2, 23.0]),
            distance_to_query_m=distance_to_query_m,
            confidence=0.82,
            freshness_score=0.74,
            source_weight=1.0,
            privacy_level="public",
            raw_ref=f"historical-record:{source_id}",
        )

    nearest_without_time = evidence(
        item_id="official-nearest",
        source_id="data-gov-130016:nearest",
        distance_to_query_m=10.0,
        observed_at=None,
        occurred_at=None,
    )
    older_observed = evidence(
        item_id="official-observed",
        source_id="data-gov-130016:observed",
        distance_to_query_m=50.0,
        observed_at=datetime.fromisoformat("2020-12-31T12:00:00+08:00"),
        occurred_at=None,
    )
    latest_occurred = evidence(
        item_id="official-occurred",
        source_id="data-gov-130016:occurred",
        distance_to_query_m=90.0,
        observed_at=None,
        occurred_at=datetime.fromisoformat("2022-12-31T12:00:00+08:00"),
    )

    summary = public_routes._official_flood_disaster_summary_item(
        [nearest_without_time, older_observed, latest_occurred]
    )

    assert summary.distance_to_query_m == 10.0
    assert summary.observed_at == datetime.fromisoformat("2022-12-31T12:00:00+08:00")
    assert summary.occurred_at == datetime.fromisoformat("2022-12-31T12:00:00+08:00")


def test_public_news_failure_is_not_promoted_when_history_exists() -> None:
    now = datetime.fromisoformat("2026-05-13T02:00:00+00:00")
    official_record = HistoricalFloodRecord(
        source_id="official-flood-disaster-points:test",
        source_name="官方資料：淹水災點快照",
        source_type="official",
        event_type="flood_report",
        title="2020 官方淹水災害情資點位",
        summary="官方資料命中。",
        url="https://data.gov.tw/dataset/130016",
        occurred_at=datetime.fromisoformat("2020-12-31T12:00:00+08:00"),
        ingested_at=now,
        lat=23.0,
        lng=120.2,
        confidence=0.82,
        freshness_score=0.82,
        source_weight=1.0,
        risk_factor=1.0,
    )
    limitations = public_routes._visible_source_limitations(
        public_routes.OfficialRealtimeBundle(observations=(), source_statuses=()),
        ((official_record, 30.0),),
        None,
        public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="公開新聞、RSS 或百科索引暫時無法完整回應；保留既有資料。",
            records=(),
            health_status="degraded",
        ),
    )

    assert limitations == []


def test_visible_source_limitations_respects_persisted_official_realtime_evidence() -> None:
    now = datetime.fromisoformat("2026-06-10T03:00:00+00:00")
    rainfall = public_routes.Evidence(
        id="official-rainfall",
        source_id="cwa-rainfall:test",
        source_type="official",
        event_type="rainfall",
        title="Persisted rainfall",
        summary="Persisted CWA rainfall snapshot.",
        url="https://data.gov.tw/dataset/9177",
        occurred_at=None,
        observed_at=now,
        ingested_at=now,
        point=public_routes.LatLng(lat=25.0, lng=121.5),
        geometry=public_routes.GeoJsonGeometry(type="Point", coordinates=[121.5, 25.0]),
        distance_to_query_m=100.0,
        confidence=0.92,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="raw/cwa/rainfall/test.json",
    )
    historical_news = public_routes.Evidence(
        id="historical-news",
        source_id="news:test",
        source_type="news",
        event_type="flood_report",
        title="Historical flood evidence",
        summary="Historical observed flood evidence.",
        url="https://example.test/news",
        occurred_at=now,
        observed_at=now,
        ingested_at=now,
        point=public_routes.LatLng(lat=25.0, lng=121.5),
        geometry=public_routes.GeoJsonGeometry(type="Point", coordinates=[121.5, 25.0]),
        distance_to_query_m=100.0,
        confidence=0.8,
        freshness_score=0.8,
        source_weight=0.85,
        privacy_level="public",
        raw_ref="raw/news/test.json",
    )

    limitations = public_routes._visible_source_limitations(
        public_routes.OfficialRealtimeBundle(
            observations=(),
            source_statuses=(
                public_routes.OfficialRealtimeSourceStatus(
                    source_id="cwa-rainfall",
                    name="CWA rainfall",
                    health_status="degraded",
                    observed_at=None,
                    ingested_at=now,
                    message="rainfall missing",
                ),
                public_routes.OfficialRealtimeSourceStatus(
                    source_id="wra-water-level",
                    name="WRA water level",
                    health_status="degraded",
                    observed_at=None,
                    ingested_at=now,
                    message="water level missing",
                ),
            ),
        ),
        (),
        (rainfall, historical_news),
        public_routes.OnDemandNewsSearchResult(
            attempted=False,
            source_id="on-demand-public-news",
            message="not attempted",
            records=(),
        ),
    )

    assert limitations == ["water level missing"]


def test_risk_assess_surfaces_nearby_historical_flood_records(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["realtime"]["level"] == "未知"
    assert payload["historical"]["level"] == "高"
    assert any(item["source_type"] == "news" for item in payload["evidence"])
    assert any("2025-08-02" in item["title"] for item in payload["evidence"])
    assert any(
        item["source_type"] == "news" and item["url"]
        for item in payload["evidence"]
    )
    assert payload["data_freshness"][-1]["source_id"] == "historical-flood-records"
    assert "2 筆" in payload["data_freshness"][-1]["message"]
    assert payload["data_freshness"][-1]["feature_count"] == 2


def test_risk_assess_uses_db_evidence_when_repository_is_available(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_db_evidence_record(),),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["source_id"] for item in payload["data_freshness"]][-1] == "db-evidence"
    assert "已審核歷史資料" in payload["data_freshness"][-1]["message"]
    assert payload["data_freshness"][-1]["feature_count"] == 1
    assert payload["evidence"][0]["id"] == "b3f22a36-7316-4e2a-92b6-c6f6443c8528"
    assert payload["evidence"][0]["source_type"] == "news"
    assert not any("甇瑕" in source for source in payload["explanation"]["missing_sources"])
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_uses_curated_history_when_db_only_has_flood_potential(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_flood_potential_record(),),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.65646, "lng": 120.32574},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "三民區本和里大豐一路",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "高"
    assert any("本和里" in item["title"] for item in payload["evidence"])
    assert any(item["event_type"] == "flood_potential" for item in payload["evidence"])
    assert not any(
        "尚未匯入實際歷史淹水事件" in source
        for source in payload["explanation"]["missing_sources"]
    )
    assert payload["data_freshness"][-1]["source_id"] == "db-evidence"
    assert payload["data_freshness"][-1]["health_status"] == "healthy"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_attempts_on_demand_news_when_db_only_has_flood_potential(
    monkeypatch,
) -> None:
    now = datetime.fromisoformat("2026-05-04T03:00:00+00:00")
    enrichment_record = EvidenceUpsert(
        id="b495328e-994b-5430-9bda-7a701494d966",
        adapter_key="news.public_web.gdelt_backfill",
        source_id="gdelt-on-demand:test-sanmin",
        source_type="news",
        event_type="flood_report",
        title="高雄三民區大豐一路淹水 地下室災情嚴重",
        summary="公開新聞索引標題與查詢地點及淹水關鍵字相符。",
        url="https://example.test/news/sanmin-flood",
        occurred_at=now,
        observed_at=now,
        ingested_at=now,
        lat=22.65646,
        lng=120.32574,
        distance_to_query_m=0.0,
        confidence=0.9,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="gdelt-doc:test-sanmin",
        properties={"full_text_stored": False},
    )
    calls: list[str | None] = []

    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_flood_potential_record(),),
    )
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)

    def search(**kwargs: object) -> public_routes.OnDemandNewsSearchResult:
        calls.append(kwargs.get("location_text"))
        return public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="已從公開新聞索引補查並整理 1 筆候選淹水事件。",
            records=(enrichment_record,),
        )

    monkeypatch.setattr(public_routes, "search_public_flood_news", search)
    monkeypatch.setattr(public_routes, "upsert_public_evidence", lambda **_kwargs: ())

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.65646, "lng": 120.32574},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "三民區本和里大豐一路",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == ["三民區本和里大豐一路"]
    assert any("大豐一路" in item["title"] for item in payload["evidence"])
    assert any(item["event_type"] == "flood_potential" for item in payload["evidence"])
    assert payload["data_freshness"][-1]["source_id"] == "on-demand-public-news"
    assert payload["data_freshness"][-1]["health_status"] == "healthy"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_attempts_on_demand_news_when_official_history_has_no_news(
    monkeypatch,
) -> None:
    now = datetime.fromisoformat("2026-05-13T02:00:00+00:00")
    official_record = HistoricalFloodRecord(
        source_id="official-flood-disaster-points:test",
        source_name="官方資料：淹水災點快照",
        source_type="official",
        event_type="flood_report",
        title="2025 官方淹水災害情資點位",
        summary="官方資料命中，但沒有新聞連結。",
        url="https://data.gov.tw/dataset/130016",
        occurred_at=datetime.fromisoformat("2025-12-31T12:00:00+08:00"),
        ingested_at=now,
        lat=25.068,
        lng=121.628,
        confidence=0.82,
        freshness_score=0.95,
        source_weight=1.0,
        risk_factor=1.0,
    )
    enrichment_record = EvidenceUpsert(
        id="fd3615cf-849f-5e52-a2f3-9ce4a6a9f96b",
        adapter_key="news.public_web.gdelt_backfill",
        source_id="gdelt-on-demand:test-official-cross-check",
        source_type="news",
        event_type="flood_report",
        title="新北汐止區康寧街水淹 住戶清理積水",
        summary="公開新聞索引 metadata 與查詢地點及淹水關鍵字相符。",
        url="https://example.test/news/xizhi-flood",
        occurred_at=now,
        observed_at=now,
        ingested_at=now,
        lat=25.068,
        lng=121.628,
        distance_to_query_m=0.0,
        confidence=0.88,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="gdelt-doc:test-official-cross-check",
        properties={"full_text_stored": False},
    )
    calls: list[str | None] = []

    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_flood_potential_record(),),
    )
    monkeypatch.setattr(
        public_routes,
        "_official_flood_disaster_lookup",
        lambda *_args, **_kwargs: OfficialFloodDisasterLookup(
            attempted=True,
            source_id="official-flood-disaster-points",
            name="官方資料：淹水災點快照（2025）",
            health_status="degraded",
            message="官方淹水災點快照命中 1 筆；本地快照涵蓋 2025；",
            records=((official_record, 80.0),),
            observed_at=official_record.occurred_at,
            ingested_at=now,
        ),
    )
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)

    def search(**kwargs: object) -> public_routes.OnDemandNewsSearchResult:
        calls.append(kwargs.get("location_text"))
        return public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="已從公開新聞索引補查並整理 1 筆候選淹水事件。",
            records=(enrichment_record,),
        )

    monkeypatch.setattr(public_routes, "search_public_flood_news", search)
    monkeypatch.setattr(public_routes, "upsert_public_evidence", lambda **_kwargs: ())

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 25.068, "lng": 121.628},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "新北汐止康寧街",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == ["新北汐止康寧街"]
    assert any(item["source_type"] == "official" for item in payload["evidence"])
    assert any(item["source_type"] == "news" for item in payload["evidence"])
    assert payload["data_freshness"][-1]["source_id"] == "on-demand-public-news"
    assert payload["data_freshness"][-1]["health_status"] == "healthy"
    assert payload["data_freshness"][-1]["feature_count"] == 1
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_attempts_on_demand_news_for_map_click_with_nearby_village(
    monkeypatch,
) -> None:
    calls: list[str | None] = []
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_flood_potential_record(),),
    )
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)

    def search(**kwargs: object) -> public_routes.OnDemandNewsSearchResult:
        calls.append(kwargs.get("location_text"))
        return public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="公開新聞索引暫時沒有可採用候選事件。",
            records=(),
        )

    monkeypatch.setattr(public_routes, "search_public_flood_news", search)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.65646, "lng": 120.32574},
            "radius_m": 500,
            "time_context": "now",
            "location_text": None,
        },
    )

    assert response.status_code == 200
    assert calls == ["高雄市三民區本和里"]


def test_risk_assess_attempts_on_demand_news_when_history_store_is_unavailable(
    monkeypatch,
) -> None:
    calls: list[str | None] = []
    monkeypatch.setenv("EVIDENCE_REPOSITORY_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "_official_flood_disaster_lookup",
        lambda *_args, **_kwargs: OfficialFloodDisasterLookup(
            attempted=True,
            source_id="official-flood-disaster-points",
            name="官方資料：淹水災點快照（2018-2022）",
            health_status="degraded",
            message="官方淹水災點快照已查詢；本地快照涵蓋 2018-2022；此單一官方快照來源半徑內 0 筆命中。",
            records=(),
        ),
    )

    def search(**kwargs: object) -> public_routes.OnDemandNewsSearchResult:
        calls.append(kwargs.get("location_text"))
        return public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="公開新聞索引未找到可通過地點與淹水關鍵字比對的候選事件。",
            records=(),
        )

    monkeypatch.setattr(public_routes, "search_public_flood_news", search)

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 24.676, "lng": 121.77},
                "radius_m": 500,
                "time_context": "now",
                "location_text": "宜蘭羅東中正路",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert calls == ["宜蘭羅東中正路"]
    assert payload["data_freshness"][-1]["source_id"] == "on-demand-public-news"
    assert payload["data_freshness"][-1]["health_status"] == "unknown"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_marks_flood_potential_only_history_as_limited(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_flood_potential_record(),),
    )
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "search_public_flood_news",
        lambda **_kwargs: public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="公開新聞索引暫時沒有可採用候選事件。",
            records=(),
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.65646, "lng": 120.32574},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "三民區本和里大豐一路",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    db_status = next(item for item in payload["data_freshness"] if item["source_id"] == "db-evidence")
    assert db_status["health_status"] == "degraded"
    assert "不是實際歷史淹水事件" in db_status["message"]
    assert any(
        "尚未匯入實際歷史淹水事件" in source
        for source in payload["explanation"]["missing_sources"]
    )
    assert any(
        "不代表該地點沒有淹水紀錄" in source
        for source in payload["explanation"]["missing_sources"]
    )
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_uses_db_query_heat_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_query_heat_snapshot",
        lambda **_kwargs: QueryHeatSnapshot(
            period="P7D",
            query_count=17,
            unique_approx_count=6,
            query_count_bucket="10-49",
            unique_approx_count_bucket="1-9",
            updated_at=datetime.fromisoformat("2026-04-30T03:00:00+00:00"),
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_heat"]["period"] == "P7D"
    assert payload["query_heat"]["query_count_bucket"] == "10-49"
    assert payload["query_heat"]["unique_approx_count_bucket"] == "1-9"
    assert payload["query_heat"]["updated_at"] == "2026-04-30T03:00:00Z"


def test_risk_assess_persists_before_query_heat_snapshot(monkeypatch) -> None:
    persisted: list[object] = []

    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    def persist(**kwargs: object) -> None:
        persisted.append(kwargs["assessment"])

    def heat(**_kwargs: object) -> QueryHeatSnapshot:
        assert persisted
        return QueryHeatSnapshot(
            period="P7D",
            query_count=1,
            unique_approx_count=1,
            query_count_bucket="1-9",
            unique_approx_count_bucket="1-9",
            updated_at=datetime.fromisoformat("2026-04-30T03:00:00+00:00"),
        )

    monkeypatch.setattr(public_routes, "persist_risk_assessment", persist)
    monkeypatch.setattr(public_routes, "fetch_query_heat_snapshot", heat)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
            "location_text": "Tainan Annan",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assessment = persisted[0]
    assert getattr(assessment, "assessment_id") == payload["assessment_id"]
    assert getattr(assessment, "lat") == 23.038818
    assert getattr(assessment, "lng") == 120.213493
    assert getattr(assessment, "radius_m") == 300
    assert getattr(assessment, "location_text") == "Tainan Annan"
    assert getattr(assessment, "explanation")["summary"]
    assert getattr(assessment, "data_freshness")
    assert getattr(assessment, "result_snapshot")["location"] == {
        "lat": 23.038818,
        "lng": 120.213493,
    }
    assert getattr(assessment, "result_snapshot")["radius_m"] == 300
    assert getattr(assessment, "result_snapshot")["levels"]["historical"]
    assert payload["query_heat"]["query_count_bucket"] == "1-9"


def test_risk_assess_marks_query_heat_limited_when_db_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    def unavailable(**_kwargs: object) -> QueryHeatSnapshot:
        raise EvidenceRepositoryUnavailable("query heat unavailable")

    monkeypatch.setattr(public_routes, "fetch_query_heat_snapshot", unavailable)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_heat"]["query_count_bucket"] == "limited-db-unavailable"
    assert payload["query_heat"]["unique_approx_count_bucket"] == "limited-db-unavailable"


def test_risk_assess_skips_db_when_evidence_repository_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_REPOSITORY_ENABLED", "false")
    get_settings.cache_clear()

    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: pytest.fail("query_nearby_evidence should not be called"),
    )
    monkeypatch.setattr(
        public_routes,
        "persist_risk_assessment",
        lambda **_kwargs: pytest.fail("persist_risk_assessment should not be called"),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_query_heat_snapshot",
        lambda **_kwargs: pytest.fail("fetch_query_heat_snapshot should not be called"),
    )

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 23.05753, "lng": 120.20144},
                "radius_m": 500,
                "time_context": "now",
                "location_text": "台南市安南區長溪路二段410巷16弄1號",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "中"
    assert payload["query_heat"]["query_count_bucket"] == "limited-db-disabled"
    assert payload["query_heat"]["unique_approx_count_bucket"] == "limited-db-disabled"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_reuses_hosted_response_cache(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("EVIDENCE_REPOSITORY_ENABLED", "false")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS", "120")
    monkeypatch.setenv("RISK_ASSESSMENT_RESPONSE_CACHE_BACKEND", "memory")
    get_settings.cache_clear()
    public_routes._RISK_ASSESSMENT_RESPONSE_CACHE.clear()

    calls = {"realtime": 0}

    def upstream_lookup(**_kwargs):
        calls["realtime"] += 1
        raise AssertionError("hosted risk assess must not hit official upstream")

    monkeypatch.setattr(official_realtime, "_nearest_rainfall_observation", upstream_lookup)
    monkeypatch.setattr(official_realtime, "_nearest_water_level_observation", upstream_lookup)

    try:
        payload = {
            "point": {"lat": 23.05753, "lng": 120.20144},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "台南市安南區長溪路二段",
        }
        first_response = client.post("/v1/risk/assess", json=payload)
        second_response = client.post("/v1/risk/assess", json=payload)
    finally:
        public_routes._RISK_ASSESSMENT_RESPONSE_CACHE.clear()
        get_settings.cache_clear()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert calls["realtime"] == 0
    first_payload = first_response.json()
    assert second_response.json()["assessment_id"] == first_payload["assessment_id"]
    realtime_statuses = [
        item for item in first_payload["data_freshness"]
        if item["source_id"] in {"cwa-rainfall", "wra-water-level"}
    ]
    assert {item["health_status"] for item in realtime_statuses} == {"degraded"}
    messages = [item["message"] for item in realtime_statuses]
    assert all("正式站採用背景工作保存" in message for message in messages)
    assert all("不是直接呼叫" in message for message in messages)
    assert all("worker-persisted" not in message for message in messages)
    assert len(set(messages)) == 2


def test_risk_assess_allows_hosted_realtime_diagnostic_fallback_when_explicit(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("EVIDENCE_REPOSITORY_ENABLED", "false")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("REALTIME_OFFICIAL_DIAGNOSTIC_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS", "0")
    get_settings.cache_clear()

    calls = {"realtime": 0}

    def realtime_bundle(**_kwargs):
        calls["realtime"] += 1
        return _empty_realtime_bundle()

    monkeypatch.setattr(public_routes, "fetch_official_realtime_bundle", realtime_bundle)

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 23.05753, "lng": 120.20144},
                "radius_m": 500,
                "time_context": "now",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert calls["realtime"] == 1


def test_risk_assess_uses_persisted_official_realtime_freshness_in_hosted(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("PUBLIC_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RISK_ASSESSMENT_RESPONSE_CACHE_SECONDS", "0")
    get_settings.cache_clear()

    calls = {"realtime": 0}
    observed_at = datetime.now(UTC).replace(microsecond=0)
    rainfall_record = replace(
        _db_evidence_record(),
        id="870ae36d-28c9-4a08-8aa6-4b0cb4fa9bb4",
        source_id="cwa-rainfall:test-station",
        source_type="official",
        event_type="rainfall",
        title="CWA persisted rainfall near query point",
        summary="Worker-promoted official rainfall evidence.",
        url="https://data.gov.tw/dataset/9177",
        occurred_at=None,
        observed_at=observed_at,
        ingested_at=observed_at,
        freshness_score=0.95,
        source_weight=1.0,
        raw_ref="raw/cwa/rainfall/test-station.json",
    )

    def upstream_lookup(**_kwargs):
        calls["realtime"] += 1
        raise AssertionError("hosted risk assess must not hit official upstream")

    monkeypatch.setattr(official_realtime, "_nearest_rainfall_observation", upstream_lookup)
    monkeypatch.setattr(official_realtime, "_nearest_water_level_observation", upstream_lookup)
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: (rainfall_record,))

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 23.038818, "lng": 120.213493},
                "radius_m": 300,
                "time_context": "now",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert calls["realtime"] == 0
    assert payload["realtime"]["level"] != "未知"
    cwa_status = next(item for item in payload["data_freshness"] if item["source_id"] == "cwa-rainfall")
    wra_status = next(item for item in payload["data_freshness"] if item["source_id"] == "wra-water-level")
    assert cwa_status["health_status"] == "healthy"
    assert cwa_status["feature_count"] == 1
    assert "系統定期保存的中央氣象署即時雨量" in cwa_status["message"]
    assert wra_status["health_status"] == "degraded"
    assert "背景工作保存的水利署水位" in wra_status["message"]
    assert "on-demand realtime API fallback" not in wra_status["message"]


def test_risk_assess_uses_precomputed_profile_fast_path_for_cold_lookup(monkeypatch) -> None:
    computed_at = datetime.fromisoformat("2026-05-08T03:00:00+00:00")
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())
    monkeypatch.setattr(
        public_routes,
        "fetch_best_profile_for_point",
        lambda **_kwargs: RiskProfileRecord(
            profile_kind="risk_grid",
            profile_key="h3:842ab57ffffffff",
            profile_scope="h3:8",
            profile_radius_m=1000,
            score_version="risk-v0.1.0",
            realtime_level="unknown",
            historical_level="high",
            confidence_level="medium",
            evidence_counts={"news:flood_report": 2, "official:flood_potential": 1},
            top_evidence_ids=("b3f22a36-7316-4e2a-92b6-c6f6443c8528",),
            latest_observed_at=None,
            latest_occurred_at=computed_at,
            latest_ingested_at=computed_at,
            coverage_gaps=("historical_news_backfill_partial",),
            missing_sources=("rainfall", "water_level"),
            computed_at=computed_at,
            expires_at=None,
            status="healthy",
            distance_to_query_m=88.0,
        ),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_evidence_by_ids",
        lambda **_kwargs: (
            EvidenceRecord(
                id="b3f22a36-7316-4e2a-92b6-c6f6443c8528",
                source_id="news:kaohsiung-2024-flood",
                source_type="news",
                event_type="flood_report",
                title="2024 representative flood news from profile top evidence",
                summary="A reviewed top evidence row selected by the precomputed profile.",
                url="https://example.test/profile-top-news",
                occurred_at=computed_at,
                observed_at=computed_at,
                ingested_at=computed_at,
                lat=22.65646,
                lng=120.32574,
                geometry={"type": "Point", "coordinates": [120.32574, 22.65646]},
                distance_to_query_m=88.0,
                confidence=0.9,
                freshness_score=0.8,
                source_weight=0.72,
                privacy_level="public",
                raw_ref="news:profile-top",
            ),
        ),
    )
    enqueued: list[dict[str, object]] = []
    monkeypatch.setattr(
        public_routes,
        "enqueue_profile_refresh_job",
        lambda **kwargs: enqueued.append(kwargs) or "job-id",
    )
    monkeypatch.setattr(
        public_routes,
        "search_public_flood_news",
        lambda **_kwargs: pytest.fail("profile fast path should not trigger on-demand news"),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.65646, "lng": 120.32574},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "高雄市三民區本和里",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "中"
    assert payload["confidence"]["level"] == "中"
    assert len(payload["evidence"]) == 2
    profile_evidence_types = {
        (item["source_type"], item["event_type"])
        for item in payload["evidence"]
    }
    assert profile_evidence_types == {
        ("news", "flood_report"),
        ("official", "flood_potential"),
    }
    assert any(
        item["title"] == "2024 representative flood news from profile top evidence"
        for item in payload["evidence"]
    )
    assert any("profile 摘要" in item["title"] for item in payload["evidence"])
    assert all(item["distance_to_query_m"] == 88.0 for item in payload["evidence"])
    evidence_response = client.get(f"/v1/evidence/{payload['assessment_id']}")
    assert evidence_response.status_code == 200
    evidence_payload = evidence_response.json()
    assert len(evidence_payload["items"]) == 2
    source_ids = {item["source_id"] for item in evidence_payload["items"]}
    assert "news:kaohsiung-2024-flood" in source_ids
    assert "precomputed-risk-profile:official:flood_potential" in source_ids
    profile_freshness = next(
        item for item in payload["data_freshness"] if item["source_id"] == "precomputed-risk-profile"
    )
    assert profile_freshness["health_status"] == "healthy"
    assert "預先計算" in profile_freshness["message"]
    assert any("profile" in reason for reason in payload["explanation"]["main_reasons"])
    assert "profile 未納入即時雨量來源；這會限制即時風險，不代表歷史參考沒有依據。" in payload["explanation"]["missing_sources"]
    assert enqueued[0]["profile_kind"] == "risk_grid"
    assert enqueued[0]["profile_key"] == "h3:842ab57ffffffff"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_skips_profile_fast_path_without_observed_history(monkeypatch) -> None:
    computed_at = datetime.fromisoformat("2026-05-12T02:01:34+00:00")
    monkeypatch.setenv("HISTORICAL_NEWS_ON_DEMAND_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "fetch_best_profile_for_point",
        lambda **_kwargs: RiskProfileRecord(
            profile_kind="risk_grid",
            profile_key="h3:8:flood-potential-only",
            profile_scope="h3:8",
            profile_radius_m=1000,
            score_version="risk-v0.1.0",
            realtime_level="low",
            historical_level="severe",
            confidence_level="high",
            evidence_counts={"official:flood_potential": 58},
            top_evidence_ids=(),
            latest_observed_at=None,
            latest_occurred_at=None,
            latest_ingested_at=computed_at,
            coverage_gaps=("historical_news_backfill_partial",),
            missing_sources=("rainfall", "water_level"),
            computed_at=computed_at,
            expires_at=None,
            status="healthy",
            distance_to_query_m=0.0,
        ),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_evidence_by_ids",
        lambda **_kwargs: pytest.fail("flood-potential-only profile should not load top evidence"),
    )
    monkeypatch.setattr(
        public_routes,
        "enqueue_profile_refresh_job",
        lambda **_kwargs: pytest.fail("flood-potential-only profile should not be returned"),
    )

    try:
        response = client.post(
            "/v1/risk/assess",
            json={
                "point": {"lat": 23.908362, "lng": 120.781026},
                "radius_m": 1000,
                "time_context": "now",
                "location_text": "profile flood-potential-only regression",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "未知"
    assert payload["evidence"] == []
    assert not any(
        item["source_id"] == "precomputed-risk-profile" for item in payload["data_freshness"]
    )
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_skips_official_only_profile_to_try_public_news(monkeypatch) -> None:
    computed_at = datetime.fromisoformat("2026-05-12T02:01:34+00:00")
    enrichment_record = EvidenceUpsert(
        id="66d18e99-0239-50bf-9fe2-7c68b4ca8b17",
        adapter_key="news.public_web.gdelt_backfill",
        source_id="gdelt-on-demand:test-profile-cross-check",
        source_type="news",
        event_type="flood_report",
        title="彰化員林中山路水淹 店家清理積水",
        summary="公開新聞索引 metadata 與查詢地點及淹水關鍵字相符。",
        url="https://example.test/news/yuanlin-flood",
        occurred_at=computed_at,
        observed_at=computed_at,
        ingested_at=computed_at,
        lat=23.956,
        lng=120.57,
        distance_to_query_m=0.0,
        confidence=0.88,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="gdelt-doc:test-profile-cross-check",
        properties={"full_text_stored": False},
    )
    calls: list[str | None] = []

    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "fetch_best_profile_for_point",
        lambda **_kwargs: RiskProfileRecord(
            profile_kind="risk_grid",
            profile_key="h3:8:official-history-only",
            profile_scope="h3:8",
            profile_radius_m=1000,
            score_version="risk-v0.1.0",
            realtime_level="unknown",
            historical_level="high",
            confidence_level="medium",
            evidence_counts={"official:flood_report": 2, "official:flood_potential": 1},
            top_evidence_ids=("official-profile-evidence",),
            latest_observed_at=None,
            latest_occurred_at=computed_at,
            latest_ingested_at=computed_at,
            coverage_gaps=("historical_news_backfill_partial",),
            missing_sources=("rainfall", "water_level"),
            computed_at=computed_at,
            expires_at=None,
            status="healthy",
            distance_to_query_m=88.0,
        ),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_evidence_by_ids",
        lambda **_kwargs: pytest.fail("official-only profile should not short-circuit"),
    )
    monkeypatch.setattr(
        public_routes,
        "enqueue_profile_refresh_job",
        lambda **_kwargs: pytest.fail("official-only profile should not be returned"),
    )

    def search(**kwargs: object) -> public_routes.OnDemandNewsSearchResult:
        calls.append(kwargs.get("location_text"))
        return public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="已從公開新聞索引補查並整理 1 筆候選淹水事件。",
            records=(enrichment_record,),
        )

    monkeypatch.setattr(public_routes, "search_public_flood_news", search)
    monkeypatch.setattr(public_routes, "upsert_public_evidence", lambda **_kwargs: ())

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.956, "lng": 120.57},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "彰化員林中山路",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == ["彰化員林中山路"]
    assert any(item["source_type"] == "news" for item in payload["evidence"])
    assert not any(
        item["source_id"] == "precomputed-risk-profile" for item in payload["data_freshness"]
    )
    assert payload["data_freshness"][-1]["source_id"] == "on-demand-public-news"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_keeps_exact_radius_evidence_ahead_of_profile_fast_path(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(
        public_routes,
        "query_nearby_evidence",
        lambda **_kwargs: (_db_evidence_record(),),
    )
    monkeypatch.setattr(
        public_routes,
        "fetch_best_profile_for_point",
        lambda **_kwargs: pytest.fail("profile fast path must not run after exact evidence"),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.65646, "lng": 120.32574},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "高雄市三民區本和里",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"][0]["title"] == "2025-08-02 accepted flood evidence near Annan"
    assert not any(item["source_id"] == "precomputed-risk-profile" for item in payload["data_freshness"])
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_uses_local_historical_fallback_when_local_db_returns_empty(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "高"
    assert any("2025-08-02" in item["title"] for item in payload["evidence"])
    assert payload["data_freshness"][-1]["source_id"] == "historical-flood-records"
    assert payload["data_freshness"][-1]["health_status"] == "healthy"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_does_not_use_local_fallback_when_gate_is_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "nearest_public_news_location_text",
        lambda **_kwargs: None,
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "未知"
    assert payload["confidence"]["level"] == "未知"
    assert payload["evidence"] == []
    assert "資料不足" in payload["explanation"]["summary"]
    assert "不能判定風險高低" in payload["explanation"]["main_reasons"][0]
    assert any("資料不足" in item for item in payload["explanation"]["missing_sources"])
    assert payload["data_freshness"][-1]["source_id"] == "db-evidence"
    assert payload["data_freshness"][-1]["health_status"] == "unknown"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_on_demand_news_enrichment_writes_back_and_scores(
    monkeypatch,
) -> None:
    now = datetime.fromisoformat("2026-05-04T03:00:00+00:00")
    enrichment_record = EvidenceUpsert(
        id="f442ec3f-f013-58d2-8fcb-93f62db8d51c",
        adapter_key="news.public_web.gdelt_backfill",
        source_id="gdelt-on-demand:test-okshan",
        source_type="news",
        event_type="flood_report",
        title="高雄岡山嘉新東路豪雨淹水 地下道一度封閉",
        summary="公開新聞索引標題與查詢地點及淹水關鍵字相符。",
        url="https://example.test/news/okshan-flood",
        occurred_at=now,
        observed_at=now,
        ingested_at=now,
        lat=22.8052,
        lng=120.3034,
        distance_to_query_m=0.0,
        confidence=0.9,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="gdelt-doc:test-okshan",
        properties={"full_text_stored": False},
    )
    persisted: list[EvidenceUpsert] = []

    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "search_public_flood_news",
        lambda **_kwargs: public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="已從公開新聞索引補查並整理 1 筆候選淹水事件。",
            records=(enrichment_record,),
        ),
    )

    def upsert(**kwargs: object) -> tuple[EvidenceRecord, ...]:
        records = kwargs["records"]
        assert isinstance(records, tuple)
        persisted.extend(records)
        return (_evidence_record_from_upsert(enrichment_record),)

    monkeypatch.setattr(public_routes, "upsert_public_evidence", upsert)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.8052, "lng": 120.3034},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "2024 高雄岡山嘉新東路 豪雨淹水",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert persisted == [enrichment_record]
    assert payload["historical"]["level"] == "中"
    assert any("嘉新東路" in item["title"] for item in payload["evidence"])
    assert payload["data_freshness"][-1]["source_id"] == "on-demand-public-news"
    assert "公開新聞索引補查" in payload["data_freshness"][-1]["message"]
    assert payload["data_freshness"][-1]["feature_count"] == 1
    assert payload["explanation"]["missing_sources"] == [
        "即時雨量來源正常，查詢半徑內未採用測站。",
        "即時水位來源正常，查詢半徑內未採用測站。",
    ]
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_surfaces_on_demand_news_gap_as_source_limitation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())
    monkeypatch.setattr(public_routes, "_use_local_historical_fallback", lambda _app_env: False)
    monkeypatch.setattr(
        public_routes,
        "search_public_flood_news",
        lambda **_kwargs: public_routes.OnDemandNewsSearchResult(
            attempted=True,
            source_id="on-demand-public-news",
            message="公開新聞索引暫時無法回應；保留既有資料，不阻塞風險查詢。",
            records=(),
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.8052, "lng": 120.3034},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "2024 高雄岡山嘉新東路 豪雨淹水",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "未知"
    assert any(
        "公開新聞補查未取得可用事件" in source
        for source in payload["explanation"]["missing_sources"]
    )
    assert any(
        "不代表該地點沒有淹水紀錄" in source
        for source in payload["explanation"]["missing_sources"]
    )
    assert payload["data_freshness"][-1]["source_id"] == "on-demand-public-news"
    assert payload["data_freshness"][-1]["health_status"] == "unknown"
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_surfaces_zuoying_taoziyuan_2024_flood_records(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )
    monkeypatch.setattr(public_routes, "query_nearby_evidence", lambda **_kwargs: ())

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.6731, "lng": 120.2862},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "2024 高雄左營桃子園路 淹水",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["realtime"]["level"] == "未知"
    assert payload["historical"]["level"] == "高"
    assert any("桃子園路" in item["title"] for item in payload["evidence"])
    assert any("2024-07-25" in item["title"] for item in payload["evidence"])
    assert payload["data_freshness"][-1]["source_id"] == "historical-flood-records"
    assert "2 筆" in payload["data_freshness"][-1]["message"]
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_surfaces_changxi_road_historical_flood_records(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.04697, "lng": 120.20344},
            "radius_m": 500,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["realtime"]["level"] == "未知"
    assert payload["historical"]["level"] == "高"
    assert any("長溪路二段" in item["title"] for item in payload["evidence"])
    assert payload["explanation"]["missing_sources"] == [
        "即時雨量來源正常，查詢半徑內未採用測站。",
        "即時水位來源正常，查詢半徑內未採用測站。",
    ]
    assert "3 筆" in payload["data_freshness"][-1]["message"]


def test_risk_assess_matches_historical_records_by_location_text(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.05753, "lng": 120.20144},
            "radius_m": 500,
            "time_context": "now",
            "location_text": "長溪路二段",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["historical"]["level"] == "中"
    assert "歷史與淹水潛勢參考為中" in payload["explanation"]["summary"]
    assert any("長溪路二段" in item["title"] for item in payload["evidence"])


def _db_evidence_record() -> EvidenceRecord:
    return EvidenceRecord(
        id="b3f22a36-7316-4e2a-92b6-c6f6443c8528",
        source_id="news:tainan-annan:2025-08-02",
        source_type="news",
        event_type="flood_report",
        title="2025-08-02 accepted flood evidence near Annan",
        summary="Accepted public evidence stored in the evidence table.",
        url="https://example.test/news/tainan-flood",
        occurred_at=datetime.fromisoformat("2025-08-02T08:00:00+08:00"),
        observed_at=datetime.fromisoformat("2025-08-02T08:00:00+08:00"),
        ingested_at=datetime.fromisoformat("2026-04-29T03:00:00+00:00"),
        lat=23.038818,
        lng=120.213493,
        geometry={"type": "Point", "coordinates": [120.213493, 23.038818]},
        distance_to_query_m=15.0,
        confidence=0.86,
        freshness_score=0.95,
        source_weight=1.0,
        privacy_level="public",
        raw_ref="raw/news/accepted.json",
    )


def _flood_potential_record() -> EvidenceRecord:
    return EvidenceRecord(
        id="9497f7ec-cc75-4976-8b7a-80b3475adab8",
        source_id="dprc-taiwan-flood-potential-139",
        source_type="official",
        event_type="flood_potential",
        title="官方淹水潛勢規劃圖資",
        summary="查詢範圍與官方淹水潛勢規劃圖資相交。",
        url="https://www.dprcflood.org.tw/DPRC/02.html",
        occurred_at=None,
        observed_at=None,
        ingested_at=datetime.fromisoformat("2026-05-05T11:13:39+00:00"),
        lat=22.65646,
        lng=120.32574,
        geometry={"type": "Polygon", "coordinates": [[[120.325, 22.656], [120.326, 22.656], [120.326, 22.657], [120.325, 22.656]]]},
        distance_to_query_m=0.0,
        confidence=0.78,
        freshness_score=0.8,
        source_weight=0.9,
        privacy_level="public",
        raw_ref="raw/flood-potential/test.geojson",
    )


def _evidence_record_from_upsert(record: EvidenceUpsert) -> EvidenceRecord:
    return EvidenceRecord(
        id=record.id,
        source_id=record.source_id,
        source_type=record.source_type,
        event_type=record.event_type,
        title=record.title,
        summary=record.summary,
        url=record.url,
        occurred_at=record.occurred_at,
        observed_at=record.observed_at,
        ingested_at=record.ingested_at,
        lat=record.lat,
        lng=record.lng,
        geometry={"type": "Point", "coordinates": [record.lng, record.lat]},
        distance_to_query_m=record.distance_to_query_m,
        confidence=record.confidence,
        freshness_score=record.freshness_score,
        source_weight=record.source_weight,
        privacy_level=record.privacy_level,
        raw_ref=record.raw_ref,
    )


def _official_realtime_bundle() -> OfficialRealtimeBundle:
    observed_at = datetime.fromisoformat("2026-04-29T03:00:00+00:00")
    ingested_at = datetime.fromisoformat("2026-04-29T03:05:00+00:00")
    return OfficialRealtimeBundle(
        observations=(
            OfficialRealtimeObservation(
                source_id="cwa-rainfall:test",
                source_name="中央氣象署即時雨量",
                event_type="rainfall",
                title="中央氣象署雨量站：測試站",
                summary="最近雨量站「測試站」1 小時雨量 0.0 mm。",
                observed_at=observed_at,
                ingested_at=ingested_at,
                lat=25.04776,
                lng=121.51706,
                distance_to_query_m=120,
                confidence=0.92,
                freshness_score=0.95,
                source_weight=1.0,
                risk_factor=0.0,
            ),
            OfficialRealtimeObservation(
                source_id="wra-water-level:test",
                source_name="經濟部水利署即時水位",
                event_type="water_level",
                title="水利署水位站：測試站",
                summary="最近水位站「測試站」水位 1.20 m。",
                observed_at=observed_at,
                ingested_at=ingested_at,
                lat=25.047,
                lng=121.518,
                distance_to_query_m=180,
                confidence=0.88,
                freshness_score=0.95,
                source_weight=1.0,
                risk_factor=0.0,
            ),
        ),
        source_statuses=(
            OfficialRealtimeSourceStatus(
                source_id="cwa-rainfall",
                name="中央氣象署即時雨量",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=ingested_at,
                message="採用最近雨量站「測試站」。",
            ),
            OfficialRealtimeSourceStatus(
                source_id="wra-water-level",
                name="經濟部水利署即時水位",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=ingested_at,
                message="採用最近水位站「測試站」。",
            ),
        ),
    )


def _empty_realtime_bundle() -> OfficialRealtimeBundle:
    observed_at = datetime.fromisoformat("2026-04-29T03:00:00+00:00")
    return OfficialRealtimeBundle(
        observations=(),
        source_statuses=(
            OfficialRealtimeSourceStatus(
                source_id="cwa-rainfall",
                name="中央氣象署即時雨量",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=observed_at,
                message="即時雨量來源正常，查詢半徑內未採用測站。",
            ),
            OfficialRealtimeSourceStatus(
                source_id="wra-water-level",
                name="經濟部水利署即時水位",
                health_status="healthy",
                observed_at=observed_at,
                ingested_at=observed_at,
                message="即時水位來源正常，查詢半徑內未採用測站。",
            ),
        ),
    )


def test_evidence_list_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _empty_realtime_bundle(),
    )

    risk_response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 23.038818, "lng": 120.213493},
            "radius_m": 300,
            "time_context": "now",
        },
    )
    assessment_id = risk_response.json()["assessment_id"]
    response = client.get(f"/v1/evidence/{assessment_id}", params={"page_size": 1})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"assessment_id", "items", "next_cursor"}
    assert payload["assessment_id"] == assessment_id
    assert payload["next_cursor"] is None
    evidence = payload["items"][0]
    assert set(evidence) == {
        "id",
        "source_type",
        "event_type",
        "title",
        "summary",
        "occurred_at",
        "observed_at",
        "ingested_at",
        "distance_to_query_m",
        "confidence",
        "source_id",
        "url",
        "point",
        "geometry",
        "freshness_score",
        "source_weight",
        "privacy_level",
        "raw_ref",
    }
    assert UUID(evidence["id"])
    assert evidence["geometry"] == {"type": "Point", "coordinates": [120.213493, 23.038818]}
    assert_openapi_schema(payload, "EvidenceListResponse")


def test_evidence_list_can_read_persisted_assessment_evidence(monkeypatch) -> None:
    assessment_id = "d315d0e6-9c1e-475a-9118-f299d12d5c62"
    public_routes._ASSESSMENT_EVIDENCE_CACHE.clear()
    monkeypatch.setattr(
        public_routes,
        "fetch_assessment_evidence",
        lambda **_kwargs: (_db_evidence_record(),),
    )

    response = client.get(f"/v1/evidence/{assessment_id}", params={"page_size": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["assessment_id"] == assessment_id
    assert payload["items"][0]["id"] == "b3f22a36-7316-4e2a-92b6-c6f6443c8528"
    assert payload["items"][0]["point"] == {"lat": 23.038818, "lng": 120.213493}
    assert_openapi_schema(payload, "EvidenceListResponse")


def test_layers_uses_db_records_when_available(monkeypatch) -> None:
    layer_updated_at = datetime.fromisoformat("2026-04-30T03:00:00+00:00")
    db_layer = LayerRecord(
        id="db-flood",
        name="DB flood layer",
        description="Layer returned from map_layers.",
        category="flood_potential",
        status="degraded",
        minzoom=7,
        maxzoom=15,
        attribution="DB attribution",
        tilejson_url="/v1/layers/db-flood/tilejson",
        updated_at=layer_updated_at,
        metadata={"tiles": ["https://tiles.local/db-flood/{z}/{x}/{y}.pbf"]},
    )
    monkeypatch.setattr(public_routes, "fetch_map_layers", lambda **_kwargs: (db_layer,))

    response = client.get("/v1/layers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["layers"] == [
        {
            "id": "db-flood",
            "name": "DB flood layer",
            "description": "Layer returned from map_layers.",
            "category": "flood_potential",
            "status": "degraded",
            "minzoom": 7,
            "maxzoom": 15,
            "attribution": "DB attribution",
            "tilejson_url": "/v1/layers/db-flood/tilejson",
            "updated_at": "2026-04-30T03:00:00Z",
        }
    ]
    assert_openapi_schema(payload, "LayersResponse")


def test_layers_falls_back_when_db_unavailable(monkeypatch) -> None:
    def unavailable(**_kwargs: object) -> tuple[LayerRecord, ...]:
        raise LayerRepositoryUnavailable("database unavailable in contract tests")

    monkeypatch.setattr(public_routes, "fetch_map_layers", unavailable)

    response = client.get("/v1/layers")

    assert response.status_code == 200
    payload = response.json()
    assert [layer["id"] for layer in payload["layers"]] == ["flood-potential", "query-heat"]
    assert all(layer["status"] == "disabled" for layer in payload["layers"])
    assert_openapi_schema(payload, "LayersResponse")


def test_tilejson_uses_layer_record_metadata(monkeypatch) -> None:
    db_layer = LayerRecord(
        id="db-flood",
        name="DB flood layer",
        description=None,
        category="flood_potential",
        status="available",
        minzoom=5,
        maxzoom=13,
        attribution="DB attribution",
        tilejson_url="/v1/layers/db-flood/tilejson",
        updated_at=None,
        metadata={
            "version": "db-v1",
            "scheme": "xyz",
            "tiles": ["https://tiles.local/db-flood/{z}/{x}/{y}.pbf"],
            "bounds": [120.0, 22.0, 121.0, 23.0],
            "vector_layers": [
                {
                    "id": "db_flood_vector",
                    "fields": {"risk": "Number", "source_id": "String"},
                }
            ],
        },
    )
    monkeypatch.setattr(public_routes, "fetch_map_layers", lambda **_kwargs: (db_layer,))
    monkeypatch.setattr(public_routes, "fetch_map_layer", lambda **_kwargs: db_layer)

    response = client.get("/v1/layers/db-flood/tilejson")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "DB flood layer"
    assert payload["version"] == "db-v1"
    assert payload["attribution"] == "DB attribution"
    assert payload["status"] == "available"
    assert payload["tiles"] == ["https://tiles.local/db-flood/{z}/{x}/{y}.pbf"]
    assert payload["tile_url_source"] == "metadata"
    assert "cache_control" not in payload
    assert payload["minzoom"] == 5
    assert payload["maxzoom"] == 13
    assert payload["bounds"] == [120.0, 22.0, 121.0, 23.0]
    assert payload["vector_layers"][0]["id"] == "db_flood_vector"
    assert payload["vector_layers"][0]["fields"] == {"risk": "Number", "source_id": "String"}
    assert_openapi_schema(payload, "TileJson")


def test_tilejson_sanitizes_placeholder_tile_metadata(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("TILE_DYNAMIC_FALLBACK_ENABLED", raising=False)
    db_layer = LayerRecord(
        id="db-flood",
        name="DB flood layer",
        description=None,
        category="flood_potential",
        status="available",
        minzoom=5,
        maxzoom=13,
        attribution="DB attribution",
        tilejson_url="/v1/layers/db-flood/tilejson",
        updated_at=None,
        metadata={
            "tiles": [
                "https://tiles.placeholder.flood-risk.local/db-flood/{z}/{x}/{y}.pbf"
            ],
        },
    )
    monkeypatch.setattr(public_routes, "fetch_map_layers", lambda **_kwargs: (db_layer,))
    monkeypatch.setattr(public_routes, "fetch_map_layer", lambda **_kwargs: db_layer)

    response = client.get("/v1/layers/db-flood/tilejson")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tiles"] == ["/v1/tiles/db-flood/{z}/{x}/{y}.mvt"]
    assert payload["tile_url_source"] == "local_vector_tile_endpoint"
    assert payload["cache_control"] == "public, max-age=60"
    assert "tiles.placeholder.flood-risk.local" not in response.text
    assert_openapi_schema(payload, "TileJson")
    get_settings.cache_clear()


def test_tilejson_returns_404_for_missing_db_layer(monkeypatch) -> None:
    db_layer = LayerRecord(
        id="db-flood",
        name="DB flood layer",
        description=None,
        category="flood_potential",
        status="available",
        minzoom=5,
        maxzoom=13,
        attribution=None,
        tilejson_url="/v1/layers/db-flood/tilejson",
        updated_at=None,
        metadata={"tiles": ["https://tiles.local/db-flood/{z}/{x}/{y}.pbf"]},
    )
    monkeypatch.setattr(public_routes, "fetch_map_layers", lambda **_kwargs: (db_layer,))
    monkeypatch.setattr(public_routes, "fetch_map_layer", lambda **_kwargs: None)

    response = client.get("/v1/layers/not-a-layer/tilejson")

    assert response.status_code == 404
    assert_error_envelope(response.json())


def test_tilejson_returns_503_for_enabled_layer_without_tiles_in_hosted_env(
    monkeypatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("TILE_DYNAMIC_FALLBACK_ENABLED", raising=False)
    db_layer = LayerRecord(
        id="db-flood",
        name="DB flood layer",
        description=None,
        category="flood_potential",
        status="available",
        minzoom=5,
        maxzoom=13,
        attribution=None,
        tilejson_url="/v1/layers/db-flood/tilejson",
        updated_at=None,
        metadata={},
    )
    monkeypatch.setattr(public_routes, "fetch_map_layers", lambda **_kwargs: (db_layer,))
    monkeypatch.setattr(public_routes, "fetch_map_layer", lambda **_kwargs: db_layer)

    response = client.get("/v1/layers/db-flood/tilejson")

    assert response.status_code == 503
    payload = response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "tiles_unavailable"
    get_settings.cache_clear()


def test_layers_and_tilejson_contracts() -> None:
    layers_response = client.get("/v1/layers")

    assert layers_response.status_code == 200
    layers_payload = layers_response.json()
    assert set(layers_payload) == {"layers"}
    assert layers_payload["layers"]
    layer = layers_payload["layers"][0]
    assert set(layer) == {
        "id",
        "name",
        "description",
        "category",
        "status",
        "minzoom",
        "maxzoom",
        "attribution",
        "tilejson_url",
        "updated_at",
    }

    tilejson_response = client.get(layer["tilejson_url"])
    assert tilejson_response.status_code == 404
    payload = tilejson_response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "layer_disabled"
    assert_openapi_schema(layers_payload, "LayersResponse")


def test_validation_and_not_found_use_error_envelope() -> None:
    bad_request = client.post("/v1/geocode", json={"query": "", "unknown": True})
    assert bad_request.status_code == 400
    assert_error_envelope(bad_request.json())

    not_found = client.get("/v1/layers/not-a-layer/tilejson")
    assert not_found.status_code == 404
    assert_error_envelope(not_found.json())


def test_cors_allows_local_web_origins() -> None:
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        response = client.options(
            "/v1/risk/assess",
            headers={
                "Access-Control-Request-Method": "POST",
                "Origin": origin,
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_cors_rejects_unknown_web_origin() -> None:
    response = client.options(
        "/v1/risk/assess",
        headers={
            "Access-Control-Request-Method": "POST",
            "Origin": "http://example.test:3000",
        },
    )

    assert response.status_code == 400
