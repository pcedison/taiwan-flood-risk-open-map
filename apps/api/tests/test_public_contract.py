from datetime import datetime
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
from app.domain.evidence import EvidenceRecord, EvidenceRepositoryUnavailable, QueryHeatSnapshot
from app.domain.layers import LayerRecord, LayerRepositoryUnavailable
from app.domain.realtime import (
    OfficialRealtimeBundle,
    OfficialRealtimeObservation,
    OfficialRealtimeSourceStatus,
)
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

    monkeypatch.setattr(public_routes, "query_nearby_evidence", unavailable)
    monkeypatch.setattr(public_routes, "fetch_query_heat_snapshot", unavailable)
    monkeypatch.setattr(public_routes, "persist_risk_assessment", unavailable)
    monkeypatch.setattr(public_routes, "fetch_map_layers", layers_unavailable)


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
    assert set(payload) == {"status", "service", "version", "checked_at"}
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
    }
    assert UUID(candidate["place_id"])
    assert candidate["name"] == "Taipei 101"
    assert candidate["type"] == "landmark"
    assert set(candidate["point"]) == {"lat", "lng"}
    assert 0 <= candidate["confidence"] <= 1
    assert_openapi_schema(payload, "GeocodeResponse")


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
    )
    monkeypatch.setattr(public_routes, "_nominatim_candidates", lambda _request: [external_candidate])

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


def test_geocode_uses_wikimedia_poi_fallback_when_osm_misses(monkeypatch) -> None:
    wiki_candidate = PlaceCandidate(
        place_id="wiki-place",
        name="知名景點",
        type="landmark",
        point=LatLng(lat=23.1, lng=120.2),
        admin_code=None,
        source="wikimedia-coordinates",
        confidence=0.84,
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
    assert candidate["point"] == {"lat": 23.1, "lng": 120.2}


def test_risk_assess_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_official_realtime_bundle",
        lambda **_kwargs: _official_realtime_bundle(),
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
        "查詢半徑內尚未匯入歷史淹水紀錄；目前不應把即時低風險解讀為購屋安全。"
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
    }
    assert payload["data_freshness"][0]["health_status"] == "healthy"
    assert payload["data_freshness"][0]["source_id"] == "cwa-rainfall"
    assert payload["query_heat"]["period"] == "P7D"
    assert payload["query_heat"]["attention_level"] in RISK_LEVELS
    assert_openapi_schema(payload, "RiskAssessmentResponse")


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
    assert payload["data_freshness"][-1]["source_id"] == "historical-flood-records"
    assert "2 筆" in payload["data_freshness"][-1]["message"]


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
    assert "accepted evidence" in payload["data_freshness"][-1]["message"]
    assert payload["evidence"][0]["id"] == "b3f22a36-7316-4e2a-92b6-c6f6443c8528"
    assert payload["evidence"][0]["source_type"] == "news"
    assert not any("甇瑕" in source for source in payload["explanation"]["missing_sources"])
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


def test_risk_assess_does_not_fallback_to_fixture_when_db_returns_empty(monkeypatch) -> None:
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
    assert payload["historical"]["level"] in RISK_LEVELS
    assert payload["evidence"] == []
    assert payload["data_freshness"][-1]["source_id"] == "db-evidence"
    assert payload["data_freshness"][-1]["health_status"] == "unknown"
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
    assert payload["historical"]["level"] == "高"
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
    assert payload["tiles"] == ["https://tiles.local/db-flood/{z}/{x}/{y}.pbf"]
    assert payload["minzoom"] == 5
    assert payload["maxzoom"] == 13
    assert payload["bounds"] == [120.0, 22.0, 121.0, 23.0]
    assert payload["vector_layers"][0]["id"] == "db_flood_vector"
    assert payload["vector_layers"][0]["fields"] == {"risk": "Number", "source_id": "String"}
    assert_openapi_schema(payload, "TileJson")


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
    assert tilejson_response.status_code == 200
    tilejson = tilejson_response.json()
    assert {"tilejson", "name", "tiles"}.issubset(tilejson)
    assert tilejson["tilejson"] == "3.0.0"
    assert tilejson["tiles"]
    assert "tiles.example.test" not in tilejson["tiles"][0]
    assert len(tilejson["bounds"]) == 4
    assert tilejson["vector_layers"][0]["id"] == layer["id"].replace("-", "_")
    assert_openapi_schema(layers_payload, "LayersResponse")
    assert_openapi_schema(tilejson, "TileJson")


def test_validation_and_not_found_use_error_envelope() -> None:
    bad_request = client.post("/v1/geocode", json={"query": "", "unknown": True})
    assert bad_request.status_code == 400
    assert_error_envelope(bad_request.json())

    not_found = client.get("/v1/layers/not-a-layer/tilejson")
    assert not_found.status_code == 404
    assert_error_envelope(not_found.json())


def test_cors_allows_local_web_origin() -> None:
    response = client.options(
        "/v1/risk/assess",
        headers={
            "Access-Control-Request-Method": "POST",
            "Origin": "http://localhost:3000",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
