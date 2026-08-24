import inspect
import warnings
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.api.routes import health as health_routes
from app.api.routes import public as public_routes
from app.api.schemas import (
    DependencyReadiness,
    LatLng,
    NearbyCoverageSignal,
    NearbyRealtimeCoverage,
    NearbySourceHealth,
    PlaceCandidate,
    RiskAssessmentResponse,
)
from app.api.services.assessment import AssessmentService
from app.core.config import get_settings
from app.domain.assessment import AssessmentData, AssessmentSourceState
from app.domain.evidence import (
    EvidenceRecord,
)
from app.domain.layers import LayerRecord, LayerRepositoryUnavailable
from app.domain.realtime import (
    build_nearby_realtime_coverage,
)
from app.domain.risk import score_risk
from app.main import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema import RefResolver  # type: ignore[import-untyped]


client = TestClient(create_app())
RISK_LEVELS = {"低", "中", "高", "極高", "未知"}
CONFIDENCE_LEVELS = {"低", "中", "高", "未知"}
REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_SPEC = yaml.safe_load((REPO_ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))


ROUTE_NOW = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
RAIN_ID = "26900bf0-f51c-4326-8f75-68d03a36560e"
WATER_ID = "911d1bdf-0cc9-49bc-896d-f92680054b08"
HISTORY_ID = "0ca7e95a-7cfa-4e8d-b7e3-a0ca4b1836ec"


class RouteRepository:
    def __init__(self, data: AssessmentData) -> None:
        self.data = data
        self.loads: list[dict[str, object]] = []

    def load(self, **kwargs: object) -> AssessmentData:
        self.loads.append(kwargs)
        radius_m = int(kwargs["radius_m"])
        coverage = self.data.nearby_coverage.model_copy(
            update={"query_radius_m": radius_m}
        )
        return replace(self.data, nearby_coverage=coverage)

    def persist(self, _assessment: object) -> None:
        return


def _route_record(
    evidence_id: str,
    *,
    event_type: str,
    evidence_scope: str,
    source_type: str = "official",
    realtime_risk_factor: float = 0.0,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        source_id=f"route:{evidence_id}",
        source_type=source_type,
        event_type=event_type,
        title=f"route {event_type}",
        summary=f"route {event_type} evidence",
        url=None,
        occurred_at=ROUTE_NOW,
        observed_at=ROUTE_NOW,
        ingested_at=ROUTE_NOW,
        lat=22.9997,
        lng=120.227,
        geometry={"type": "Point", "coordinates": [120.227, 22.9997]},
        distance_to_query_m=20.0,
        confidence=0.9,
        freshness_score=1.0,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=None,
        realtime_risk_factor=realtime_risk_factor,
        evidence_scope=evidence_scope,  # type: ignore[arg-type]
        adapter_key=(
            "official.wra.water_level"
            if event_type == "water_level"
            else "official.cwa.rainfall"
        ),
        location_precision="map_click",
    )


def _route_coverage():
    coverage = build_nearby_realtime_coverage(
        rows=(),
        query_radius_m=1000,
        evaluated_at=ROUTE_NOW,
        jurisdiction_status="verified",
    )
    return coverage.model_copy(
        update={
            "signal_breakdown": [
                NearbyCoverageSignal(
                    signal_type=signal_type,
                    label=signal_type,
                    coverage_level="high",
                    availability_state="fresh_nearby",
                    nearest_distance_m=20.0,
                    counts_by_radius_m={"1000": 1},
                    fresh_count=1,
                    stale_count=0,
                    status_only_count=0,
                )
                for signal_type in ("rainfall", "water_level")
            ],
            "source_health_checked": True,
            "jurisdiction_checked": True,
            "jurisdiction_catalog_complete": True,
        }
    )


def _route_data(
    *,
    current: tuple[EvidenceRecord, ...] | None = None,
    historical: tuple[EvidenceRecord, ...] = (),
    states: tuple[AssessmentSourceState, ...] | None = None,
    current_available: bool = True,
    historical_available: bool = True,
    coverage_available: bool = True,
    health_available: bool = True,
    jurisdiction_available: bool = True,
    resolved_admin_code: str = "67000000",
    resolved_admin_name: str = "臺南市",
    local_machine_feed_missing: tuple[str, ...] = (),
) -> AssessmentData:
    if current is None:
        current = (
            _route_record(RAIN_ID, event_type="rainfall", evidence_scope="current"),
            _route_record(WATER_ID, event_type="water_level", evidence_scope="current"),
        )
    states = states or tuple(
        AssessmentSourceState(
            source_key=source_key,
            signal_type=signal_type,
            state="fresh",
            observed_at=ROUTE_NOW,
            checked_at=ROUTE_NOW,
            message=None,
        )
        for source_key, signal_type in (
            ("official.cwa.rainfall", "rainfall"),
            ("official.wra.water_level", "water_level"),
        )
    )
    return AssessmentData(
        current_official=current,
        historical=historical,
        nearby_coverage=_route_coverage(),
        source_states=states,
        required_realtime_source_keys=frozenset(
            {"official.cwa.rainfall", "official.wra.water_level"}
        ),
        current_available=current_available,
        historical_available=historical_available,
        coverage_available=coverage_available,
        health_available=health_available,
        jurisdiction_available=jurisdiction_available,
        resolved_admin_code=resolved_admin_code,
        resolved_admin_name=resolved_admin_name,
        local_machine_feed_missing=local_machine_feed_missing,
    )


def _install_route_data(
    monkeypatch: pytest.MonkeyPatch,
    data: AssessmentData,
) -> RouteRepository:
    repository = RouteRepository(data)
    service = AssessmentService(repository, score_risk)
    monkeypatch.setattr(public_routes, "_assessment_service", lambda _settings: service)
    monkeypatch.setattr(public_routes, "_now", lambda: ROUTE_NOW)
    return repository


@pytest.fixture(autouse=True)
def repository_service_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    def layers_unavailable(**_kwargs: object) -> tuple[LayerRecord, ...]:
        raise LayerRepositoryUnavailable("database unavailable in contract tests")

    _install_route_data(monkeypatch, _route_data())
    monkeypatch.setattr(public_routes, "fetch_map_layers", layers_unavailable)


def assert_iso_datetime(value: str) -> None:
    datetime.fromisoformat(value)


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


def test_risk_response_schema_exposes_additive_v1_fields() -> None:
    properties = RiskAssessmentResponse.model_json_schema()["properties"]
    assert {
        "as_of",
        "community",
        "overall",
        "dominant_mode",
        "data_status",
        "community_refresh",
    } <= properties.keys()


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


def test_required_schema_readiness_checks_latest_migration_and_relations() -> None:
    captured: dict[str, object] = {}

    class FakeCursor:
        def execute(self, sql: str, params: tuple[object, ...]) -> None:
            captured["sql"] = sql
            captured["params"] = params

        def fetchone(self) -> tuple[bool, ...]:
            return (True, True, True, True, True, True, True)

    health_routes._check_required_schema(FakeCursor())

    assert "FROM schema_migrations" in str(captured["sql"])
    assert "checksum = %s" in str(captured["sql"])
    assert "MAX(version) = %s" in str(captured["sql"])
    assert captured["params"] == (
        37,
        "0037_yilan_mobile_pump_status_source.sql",
        "4a5215f6d32f83a7710a5782bdbd8168811affb306740c5acfb0cf45d0eb9447",
        37,
        "public.station_inventory_snapshots",
        "public.realtime_jurisdiction_boundary_snapshots",
        "public.realtime_jurisdiction_boundaries",
        "public.realtime_jurisdiction_signal_contracts",
        "public.realtime_source_jurisdictions",
    )


def test_required_schema_readiness_rejects_partial_migration() -> None:
    class FakeCursor:
        def execute(self, _sql: str, _params: tuple[object, ...]) -> None:
            return None

        def fetchone(self) -> tuple[bool, ...]:
            return (True, True, True, True, False, True, True)

    with pytest.raises(RuntimeError, match="required database schema migration 0037 is incomplete"):
        health_routes._check_required_schema(FakeCursor())


def test_required_schema_checksum_matches_migration_loader_algorithm() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    migration = (
        repository_root / "infra" / "migrations" / health_routes.REQUIRED_SCHEMA_FILENAME
    )
    normalized_sql = migration.read_text(encoding="utf-8").strip()

    assert sha256(normalized_sql.encode("utf-8")).hexdigest() == (
        health_routes.REQUIRED_SCHEMA_CHECKSUM
    )


def test_database_readiness_does_not_expose_malformed_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    database_url = "postgresql://private-user:pa%ZZword@example.test/production"

    def reject_dsn(*_args: object, **_kwargs: object) -> None:
        raise psycopg.ProgrammingError(f"invalid percent-encoded DSN: {database_url}")

    monkeypatch.setattr(psycopg, "connect", reject_dsn)

    dependency = health_routes._check_database(database_url)

    assert dependency.status == "failed"
    assert dependency.message == health_routes.DATABASE_READINESS_FAILURE_MESSAGE
    assert database_url not in dependency.model_dump_json()
    assert "pa%ZZword" not in dependency.model_dump_json()


def test_redis_readiness_does_not_expose_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    redis_url = "redis://default:private-password@example.test/0"

    def reject_url(*_args: object, **_kwargs: object) -> None:
        raise ValueError(f"invalid Redis URL: {redis_url}")

    monkeypatch.setattr(redis.Redis, "from_url", reject_url)

    dependency = health_routes._check_redis(redis_url)

    assert dependency.status == "failed"
    assert dependency.message == health_routes.REDIS_READINESS_FAILURE_MESSAGE
    assert redis_url not in dependency.model_dump_json()
    assert "private-password" not in dependency.model_dump_json()


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


def test_nearby_coverage_signal_requires_diagnostic_counts() -> None:
    required_diagnostics = {
        "counts_by_radius_m",
        "fresh_count",
        "stale_count",
        "status_only_count",
    }

    pydantic_required = set(NearbyCoverageSignal.model_json_schema()["required"])
    runtime_required = set(
        client.get("/openapi.json").json()["components"]["schemas"]["NearbyCoverageSignal"][
            "required"
        ]
    )
    documented_required = set(
        OPENAPI_SPEC["components"]["schemas"]["NearbyCoverageSignal"]["required"]
    )

    assert required_diagnostics <= pydantic_required
    assert required_diagnostics <= runtime_required
    assert required_diagnostics <= documented_required


def test_nearby_realtime_coverage_requires_top_level_contract_fields() -> None:
    expected_required = {
        "overall_level",
        "evaluated_at",
        "query_radius_m",
        "radius_buckets_m",
        "summary",
        "signal_breakdown",
        "missing_signal_types",
        "limitations",
        "county_level_note",
    }

    pydantic_required = set(NearbyRealtimeCoverage.model_json_schema()["required"])
    runtime_required = set(
        client.get("/openapi.json").json()["components"]["schemas"]["NearbyRealtimeCoverage"][
            "required"
        ]
    )
    documented_required = set(
        OPENAPI_SPEC["components"]["schemas"]["NearbyRealtimeCoverage"]["required"]
    )

    assert pydantic_required == expected_required
    assert runtime_required == expected_required
    assert documented_required == expected_required


def test_nearby_source_health_contract_is_public_safe_and_documented() -> None:
    expected_fields = {
        "source_id",
        "name",
        "signal_types",
        "coverage_scope",
        "health_status",
        "reason_code",
        "observed_at",
        "checked_at",
        "station_count",
        "upstream_station_count",
        "pages_fetched",
        "pagination_complete",
        "inventory_manifest_sha256",
        "inventory_proof_status",
        "inventory_complete",
        "jurisdictions",
        "required_for_absence",
        "message",
    }
    forbidden_fields = {
        "adapter_key",
        "error_code",
        "error_message",
        "metadata",
        "parameters",
        "raw_ref",
        "holder_id",
        "database_url",
    }
    runtime_schema = client.get("/openapi.json").json()["components"]["schemas"]
    documented_schema = OPENAPI_SPEC["components"]["schemas"]

    assert set(NearbySourceHealth.model_json_schema()["properties"]) == expected_fields
    assert set(runtime_schema["NearbySourceHealth"]["properties"]) == expected_fields
    assert set(documented_schema["NearbySourceHealth"]["properties"]) == expected_fields
    assert forbidden_fields.isdisjoint(expected_fields)
    assert documented_schema["NearbySourceHealth"]["additionalProperties"] is False
    assert set(documented_schema["NearbyCoverageSignal"]["properties"]["missing_cause"]["enum"]) == {
        "none",
        "no_station_in_range",
        "inventory_unverified",
        "stale_observation",
        "source_degraded",
        "source_failed",
        "update_pipeline_stalled",
        "source_not_configured",
        "jurisdiction_unverified",
        "health_unknown",
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


def test_risk_assess_contract() -> None:
    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.227},
            "radius_m": 1000,
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
        "nearby_realtime_coverage",
        "as_of",
        "dominant_mode",
        "community",
        "overall",
        "data_status",
        "community_refresh",
    }
    assert UUID(payload["assessment_id"])
    assert payload["location"] == {"lat": 22.9997, "lng": 120.227}
    assert payload["radius_m"] == 1000
    assert payload["realtime"]["level"] == "低"
    assert payload["overall"]["level"] == "低"
    assert payload["dominant_mode"] == "realtime"
    assert payload["query_heat"]["period"] == "frozen"
    assert payload["nearby_realtime_coverage"]["query_radius_m"] == 1000
    assert_openapi_schema(payload, "RiskAssessmentResponse")


def test_risk_assess_partial_current_source_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _route_data()
    states = (
        base.source_states[0],
        replace(
            base.source_states[1],
            state="failed",
            observed_at=None,
            message="官方水位來源暫時無法使用",
        ),
    )
    _install_route_data(
        monkeypatch,
        _route_data(
            current=(
                _route_record(
                    RAIN_ID,
                    event_type="rainfall",
                    evidence_scope="current",
                ),
            ),
            states=states,
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.227},
            "radius_m": 1000,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    assert response.json()["realtime"]["level"] == "未知"
    assert response.json()["overall"]["level"] != "低"


def test_risk_assess_current_high(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_route_data(
        monkeypatch,
        _route_data(
            current=(
                _route_record(
                    RAIN_ID,
                    event_type="rainfall",
                    evidence_scope="current",
                    realtime_risk_factor=1.0,
                ),
                _route_record(
                    WATER_ID,
                    event_type="water_level",
                    evidence_scope="current",
                    realtime_risk_factor=1.0,
                ),
            ),
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.227},
            "radius_m": 1000,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    assert response.json()["realtime"]["level"] == "高"
    assert response.json()["overall"]["level"] == "高"
    assert response.json()["dominant_mode"] == "realtime"


def test_risk_assess_history_only_is_historical_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_route_data(
        monkeypatch,
        _route_data(
            current=(),
            historical=(
                _route_record(
                    HISTORY_ID,
                    event_type="flood_report",
                    evidence_scope="historical",
                    realtime_risk_factor=1.0,
                ),
            ),
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.227},
            "radius_m": 1000,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    assert response.json()["realtime"]["level"] == "未知"
    assert response.json()["historical"]["level"] == "中"
    assert response.json()["dominant_mode"] == "historical_context"


@pytest.mark.parametrize(
    "availability_field",
    [
        "current_available",
        "historical_available",
        "coverage_available",
        "health_available",
        "jurisdiction_available",
    ],
)
def test_risk_assess_reader_failures_are_independent(
    monkeypatch: pytest.MonkeyPatch,
    availability_field: str,
) -> None:
    data = replace(_route_data(), **{availability_field: False})
    _install_route_data(monkeypatch, data)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.227},
            "radius_m": 1000,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    assert response.json()["data_status"]["missing"]


@pytest.mark.parametrize(
    ("admin_code", "admin_name", "gap"),
    [
        ("67000000", "臺南市", "臺南市地方淹水感測器尚未可用"),
        ("64000000", "高雄市", "高雄市地方政府機器介面尚未核准"),
        ("10013000", "屏東縣", "屏東縣地方政府機器介面尚未核准"),
    ],
)
def test_risk_assess_exposes_server_resolved_local_feed_gaps(
    monkeypatch: pytest.MonkeyPatch,
    admin_code: str,
    admin_name: str,
    gap: str,
) -> None:
    _install_route_data(
        monkeypatch,
        _route_data(
            resolved_admin_code=admin_code,
            resolved_admin_name=admin_name,
            local_machine_feed_missing=(gap,),
        ),
    )

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.227},
            "radius_m": 1000,
            "time_context": "now",
        },
    )

    assert response.status_code == 200
    assert gap in response.json()["data_status"]["missing"]


@pytest.mark.parametrize(
    ("client_kind", "location_text"),
    [
        ("address", "臺南市東區大學路一號"),
        ("landmark", "臺南火車站"),
        ("map-click", None),
    ],
)
def test_risk_assess_clients_do_not_send_admin_code(
    monkeypatch: pytest.MonkeyPatch,
    client_kind: str,
    location_text: str | None,
) -> None:
    repository = _install_route_data(monkeypatch, _route_data())
    request_json = {
        "point": {"lat": 22.9997, "lng": 120.227},
        "radius_m": 1000,
        "time_context": "now",
    }
    if location_text is not None:
        request_json["location_text"] = location_text

    response = client.post("/v1/risk/assess", json=request_json)

    assert response.status_code == 200, client_kind
    assert repository.loads == [
        {
            "lat": 22.9997,
            "lng": 120.227,
            "radius_m": 1000,
            "as_of": ROUTE_NOW,
        }
    ]
    assert "admin_code" not in request_json


def test_risk_assess_does_not_call_legacy_or_request_time_upstreams(monkeypatch) -> None:
    from app.api.services import public_response_cache
    from app.api.services import public_risk as legacy_public_risk
    from app.domain.history import news_enrichment
    from app.domain.realtime import official as official_realtime_module

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy/request-time risk path was called")

    monkeypatch.setattr(legacy_public_risk, "assess_risk", forbidden)
    monkeypatch.setattr(public_response_cache, "cached_response", forbidden)
    monkeypatch.setattr(public_response_cache, "store_response", forbidden)
    monkeypatch.setattr(official_realtime_module, "fetch_official_realtime_bundle", forbidden)
    monkeypatch.setattr(news_enrichment, "search_public_flood_news", forbidden)

    response = client.post(
        "/v1/risk/assess",
        json={
            "point": {"lat": 22.9997, "lng": 120.2270},
            "radius_m": 1000,
            "time_context": "now",
            "location_text": "臺南市東區",
        },
    )

    assert response.status_code == 200


def test_production_risk_route_has_no_legacy_or_sensitive_cache_wiring() -> None:
    source = inspect.getsource(public_routes)
    forbidden = (
        "public_risk.assess_risk",
        "RiskAssessmentDependencies",
        "fetch_official_realtime_bundle",
        "search_public_flood_news",
        "fetch_best_profile_for_point",
        "fetch_query_heat_snapshot",
        "enqueue_profile_refresh_job",
        "_risk_assessment_response_cache_key",
        "_cached_risk_assessment_response",
        "_cache_risk_assessment_response",
    )

    assert [symbol for symbol in forbidden if symbol in source] == []


def _db_evidence_record() -> EvidenceRecord:
    return EvidenceRecord(
        id="b3f22a36-7316-4e2a-92b6-c6f6443c8528",
        source_id="persisted-assessment-evidence",
        source_type="official",
        event_type="flood_report",
        title="Persisted assessment evidence",
        summary="Evidence loaded from the assessment relation.",
        url=None,
        occurred_at=ROUTE_NOW,
        observed_at=ROUTE_NOW,
        ingested_at=ROUTE_NOW,
        lat=23.038818,
        lng=120.213493,
        geometry={"type": "Point", "coordinates": [120.213493, 23.038818]},
        distance_to_query_m=25.0,
        confidence=0.9,
        freshness_score=0.9,
        source_weight=1.0,
        privacy_level="public",
        raw_ref=None,
        evidence_scope="historical",
        location_precision="point",
    )


def test_evidence_list_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        public_routes,
        "fetch_assessment_evidence",
        lambda **_kwargs: (_db_evidence_record(),),
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
        "location_precision",
        "limitations",
    }
    assert UUID(evidence["id"])
    assert evidence["geometry"] == {"type": "Point", "coordinates": [120.213493, 23.038818]}
    assert_openapi_schema(payload, "EvidenceListResponse")


def test_evidence_list_can_read_persisted_assessment_evidence(monkeypatch) -> None:
    assessment_id = "d315d0e6-9c1e-475a-9118-f299d12d5c62"
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
