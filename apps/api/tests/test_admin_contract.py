from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import warnings

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
import pytest
import yaml  # type: ignore[import-untyped]

from app.api.routes import admin as admin_route
from app.core.config import get_settings
from app.domain.reports import (
    UserReportModerationRecord,
    UserReportPrivacyRedactionRecord,
    UserReportRepositoryUnavailable,
)
from app.main import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema import RefResolver  # type: ignore[import-untyped]


REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_SPEC = yaml.safe_load((REPO_ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))


def assert_openapi_schema(payload: dict, schema_name: str) -> None:
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": OPENAPI_SPEC["components"],
    }
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema))
    assert list(validator.iter_errors(payload)) == []


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.params: list[str] | None = None
        self.query: str | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: list[str]) -> None:
        self.query = query
        self.params = params

    def fetchall(self) -> list[dict]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


@pytest.fixture(autouse=True)
def fail_db_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise OSError("database unavailable")

    monkeypatch.setattr(admin_route.psycopg, "connect", unavailable)


def test_admin_endpoints_require_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/jobs")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_admin_report_moderation_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/reports/pending")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_admin_endpoints_return_403_when_auth_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_BEARER_TOKEN", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/jobs", headers={"Authorization": "Bearer any-token"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_admin_jobs_contract_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    cursor = FakeCursor(
        [
            {
                "job_key": "ingest.cwa.rainfall",
                "adapter_key": "official.cwa.rainfall",
                "started_at": datetime.fromisoformat("2026-04-28T12:50:00+00:00"),
                "finished_at": datetime.fromisoformat("2026-04-28T12:55:00+00:00"),
                "status": "succeeded",
                "items_fetched": 120,
                "items_promoted": 118,
                "items_rejected": 2,
                "error_code": None,
                "error_message": None,
                "source_timestamp_min": datetime.fromisoformat("2026-04-28T12:00:00+00:00"),
                "source_timestamp_max": datetime.fromisoformat("2026-04-28T12:50:00+00:00"),
            }
        ]
    )
    monkeypatch.setattr(
        admin_route.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/jobs",
        params={"status": "succeeded", "job_key": "ingest.cwa.rainfall"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["jobs"]) == 1
    job = payload["jobs"][0]
    assert job["job_key"] == "ingest.cwa.rainfall"
    assert job["status"] == "succeeded"
    assert cursor.params == ["succeeded", "ingest.cwa.rainfall"]
    datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
    assert_openapi_schema(payload, "AdminJobsResponse")


def test_admin_sources_contract_filters_and_null_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    cursor = FakeCursor(
        [
            {
                "id": "8e83f8ed-87c3-4ec9-8411-d5a2bb05a456",
                "name": "Nullable source metadata",
                "adapter_key": "official.nullable",
                "source_type": "official",
                "license": None,
                "update_frequency": None,
                "last_success_at": None,
                "last_failure_at": None,
                "health_status": "unknown",
                "legal_basis": "L1",
                "source_timestamp_min": None,
                "source_timestamp_max": None,
            }
        ]
    )
    monkeypatch.setattr(
        admin_route.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        params={"health_status": "unknown"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) == 1
    source = payload["sources"][0]
    assert source["health_status"] == "unknown"
    assert source["license"] == ""
    assert source["update_frequency"] == ""
    assert cursor.params == ["unknown"]
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_sources_include_realtime_diagnostics_and_disabled_sources_are_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setenv("SOURCE_CWA_API_ENABLED", "true")
    monkeypatch.setattr(
        admin_route,
        "_now",
        lambda: datetime.fromisoformat("2026-04-28T13:00:00+00:00"),
    )
    get_settings.cache_clear()
    cursor = FakeCursor(
        [
            {
                "id": "cwa-rainfall",
                "name": "CWA rainfall observations",
                "adapter_key": "official.cwa.rainfall",
                "source_type": "official",
                "license": "Government open data",
                "update_frequency": "PT10M",
                "last_success_at": datetime.fromisoformat("2026-04-28T12:56:00+00:00"),
                "last_failure_at": None,
                "health_status": "healthy",
                "legal_basis": "L1",
                "source_timestamp_min": datetime.fromisoformat("2026-04-28T12:40:00+00:00"),
                "source_timestamp_max": datetime.fromisoformat("2026-04-28T12:50:00+00:00"),
                "is_enabled": True,
                "latest_observed_at": datetime.fromisoformat("2026-04-28T12:50:00+00:00"),
                "latest_fetched_at": datetime.fromisoformat("2026-04-28T12:55:00+00:00"),
                "latest_ingested_at": datetime.fromisoformat("2026-04-28T12:56:00+00:00"),
                "row_count": 7,
                "upstream_status": "succeeded",
                "covered_counties": ["新北市", "臺北市"],
                "covered_county_count": 2,
                "fresh_county_count": 1,
                "stale_county_count": 1,
                "station_count_by_county": {"新北市": 3, "臺北市": 4},
            },
            {
                "id": "ncdr-cap",
                "name": "NCDR CAP alert feed",
                "adapter_key": "official.ncdr.cap",
                "source_type": "official",
                "license": "Government open data",
                "update_frequency": "event_driven",
                "last_success_at": None,
                "last_failure_at": None,
                "health_status": "failed",
                "legal_basis": "L1",
                "source_timestamp_min": None,
                "source_timestamp_max": None,
                "is_enabled": False,
                "latest_observed_at": None,
                "latest_fetched_at": None,
                "latest_ingested_at": None,
                "row_count": 0,
                "upstream_status": "failed",
                "covered_counties": [],
                "covered_county_count": 0,
                "fresh_county_count": 0,
                "stale_county_count": 0,
                "station_count_by_county": {},
            },
        ]
    )
    monkeypatch.setattr(
        admin_route.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "official_realtime_latest" in (cursor.query or "")
    cwa = next(source for source in payload["sources"] if source["adapter_key"] == "official.cwa.rainfall")
    assert cwa["latest_observed_at"] == "2026-04-28T12:50:00Z"
    assert cwa["latest_fetched_at"] == "2026-04-28T12:55:00Z"
    assert cwa["latest_ingested_at"] == "2026-04-28T12:56:00Z"
    assert cwa["lag_seconds"] == 600
    assert cwa["row_count"] == 7
    assert cwa["covered_counties"] == ["新北市", "臺北市"]
    assert cwa["covered_county_count"] == 2
    assert cwa["fresh_county_count"] == 1
    assert cwa["stale_county_count"] == 1
    assert cwa["station_count_by_county"] == {"新北市": 3, "臺北市": 4}
    assert "連江縣" in cwa["missing_counties"]
    assert cwa["freshness_state"] == "fresh"
    assert cwa["upstream_status"] == "succeeded"
    assert cwa["is_enabled"] is True
    assert cwa["enabled_gates"] == ["data_sources.is_enabled", "SOURCE_CWA_API_ENABLED"]
    disabled = next(source for source in payload["sources"] if source["adapter_key"] == "official.ncdr.cap")
    assert disabled["health_status"] == "disabled"
    assert disabled["freshness_state"] == "stale"
    assert disabled["upstream_status"] == "disabled"
    assert disabled["is_enabled"] is False
    assert disabled["enabled_gates"] == []
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_enabled_gates_include_flood_sensor_live_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_FLOOD_SENSOR_ENABLED", "true")
    monkeypatch.setenv("SOURCE_FLOOD_SENSOR_API_ENABLED", "true")
    monkeypatch.setenv("SOURCE_FLOOD_SENSOR_USE_LIVE", "true")

    assert admin_route._enabled_gates(
        "official.civil_iot.flood_sensor",
        is_enabled=True,
    ) == [
        "data_sources.is_enabled",
        "SOURCE_FLOOD_SENSOR_ENABLED",
        "SOURCE_FLOOD_SENSOR_API_ENABLED",
        "SOURCE_FLOOD_SENSOR_USE_LIVE",
    ]


@pytest.mark.parametrize(
    "adapter_key",
    [
        "official.cwa.tide_level",
        "official.wra_iow.flood_depth",
        "local.taipei.sewer_water_level",
        "local.taipei.river_water_level",
        "local.taipei.pump_station",
        "local.taoyuan.flood_sensor",
        "local.taoyuan.water_level",
        "local.taoyuan.rainfall",
        "local.chiayi_city.water_level",
        "local.chiayi_city.rainfall",
        "local.taichung.water_level",
        "local.keelung.water_level",
        "local.keelung.flood_sensor",
        "local.keelung.rainfall",
        "local.kaohsiung.rainfall",
        "local.yunlin.water_level",
        "official.civil_iot.gate_water_level",
    ],
)
def test_admin_freshness_uses_realtime_cadence_for_new_backbone_sources(
    monkeypatch: pytest.MonkeyPatch,
    adapter_key: str,
) -> None:
    monkeypatch.setattr(
        admin_route,
        "_now",
        lambda: datetime.fromisoformat("2026-04-28T13:00:00+00:00"),
    )

    assert (
        admin_route._freshness_state(
            adapter_key=adapter_key,
            health_status="healthy",
            is_enabled=True,
            source_timestamp_min=None,
            source_timestamp_max=datetime.fromisoformat("2026-04-28T12:15:00+00:00"),
            latest_observed_at=datetime.fromisoformat("2026-04-28T12:15:00+00:00"),
            upstream_status="succeeded",
        )
        == "stale"
    )


@pytest.mark.parametrize(
    ("adapter_key", "gate_names"),
    [
        (
            "official.cwa.tide_level",
            (
                "SOURCE_CWA_ENABLED",
                "SOURCE_CWA_API_ENABLED",
            ),
        ),
        (
            "official.wra_iow.flood_depth",
            (
                "SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED",
                "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED",
            ),
        ),
        (
            "local.taipei.sewer_water_level",
            (
                "SOURCE_TAIPEI_SEWER_WATER_LEVEL_ENABLED",
                "SOURCE_TAIPEI_SEWER_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "local.taipei.river_water_level",
            (
                "SOURCE_TAIPEI_RIVER_WATER_LEVEL_ENABLED",
                "SOURCE_TAIPEI_RIVER_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "local.taipei.pump_station",
            (
                "SOURCE_TAIPEI_PUMP_STATION_ENABLED",
                "SOURCE_TAIPEI_PUMP_STATION_API_ENABLED",
            ),
        ),
        (
            "local.taoyuan.flood_sensor",
            (
                "SOURCE_TAOYUAN_FLOOD_SENSOR_ENABLED",
                "SOURCE_TAOYUAN_FLOOD_SENSOR_API_ENABLED",
            ),
        ),
        (
            "local.taoyuan.water_level",
            (
                "SOURCE_TAOYUAN_WATER_LEVEL_ENABLED",
                "SOURCE_TAOYUAN_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "local.taoyuan.rainfall",
            (
                "SOURCE_TAOYUAN_RAINFALL_ENABLED",
                "SOURCE_TAOYUAN_RAINFALL_API_ENABLED",
            ),
        ),
        (
            "local.chiayi_city.water_level",
            (
                "SOURCE_CHIAYI_CITY_WATER_LEVEL_ENABLED",
                "SOURCE_CHIAYI_CITY_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "local.chiayi_city.rainfall",
            (
                "SOURCE_CHIAYI_CITY_RAINFALL_ENABLED",
                "SOURCE_CHIAYI_CITY_RAINFALL_API_ENABLED",
            ),
        ),
        (
            "local.taichung.water_level",
            (
                "SOURCE_TAICHUNG_WATER_LEVEL_ENABLED",
                "SOURCE_TAICHUNG_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "local.keelung.water_level",
            (
                "SOURCE_KEELUNG_WATER_LEVEL_ENABLED",
                "SOURCE_KEELUNG_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "local.keelung.flood_sensor",
            (
                "SOURCE_KEELUNG_FLOOD_SENSOR_ENABLED",
                "SOURCE_KEELUNG_FLOOD_SENSOR_API_ENABLED",
            ),
        ),
        (
            "local.keelung.rainfall",
            (
                "SOURCE_KEELUNG_RAINFALL_ENABLED",
                "SOURCE_KEELUNG_RAINFALL_API_ENABLED",
            ),
        ),
        (
            "local.kaohsiung.rainfall",
            (
                "SOURCE_KAOHSIUNG_RAINFALL_ENABLED",
                "SOURCE_KAOHSIUNG_RAINFALL_API_ENABLED",
            ),
        ),
        (
            "local.yunlin.water_level",
            (
                "SOURCE_YUNLIN_WATER_LEVEL_ENABLED",
                "SOURCE_YUNLIN_WATER_LEVEL_API_ENABLED",
            ),
        ),
        (
            "official.civil_iot.gate_water_level",
            (
                "SOURCE_CIVIL_IOT_GATE_ENABLED",
                "SOURCE_CIVIL_IOT_GATE_API_ENABLED",
            ),
        ),
    ],
)
def test_admin_enabled_gates_include_new_backbone_source_gates(
    monkeypatch: pytest.MonkeyPatch,
    adapter_key: str,
    gate_names: tuple[str, str],
) -> None:
    for gate_name in gate_names:
        monkeypatch.setenv(gate_name, "true")

    assert admin_route._enabled_gates(adapter_key, is_enabled=True) == [
        "data_sources.is_enabled",
        *gate_names,
    ]


def test_admin_sources_marks_expired_ncdr_cap_window_stale_not_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setattr(
        admin_route,
        "_now",
        lambda: datetime.fromisoformat("2026-04-28T13:00:00+00:00"),
    )
    get_settings.cache_clear()
    cursor = FakeCursor(
        [
            {
                "id": "ncdr-cap",
                "name": "NCDR CAP alert feed",
                "adapter_key": "official.ncdr.cap",
                "source_type": "official",
                "license": "Government open data",
                "update_frequency": "event_driven",
                "last_success_at": datetime.fromisoformat("2026-04-28T12:56:00+00:00"),
                "last_failure_at": None,
                "health_status": "healthy",
                "legal_basis": "L1",
                "source_timestamp_min": datetime.fromisoformat("2026-04-28T11:00:00+00:00"),
                "source_timestamp_max": datetime.fromisoformat("2026-04-28T12:00:00+00:00"),
                "is_enabled": True,
                "latest_observed_at": datetime.fromisoformat("2026-04-28T12:00:00+00:00"),
                "latest_fetched_at": datetime.fromisoformat("2026-04-28T12:55:00+00:00"),
                "latest_ingested_at": datetime.fromisoformat("2026-04-28T12:56:00+00:00"),
                "row_count": 0,
                "upstream_status": "succeeded",
            },
        ]
    )
    monkeypatch.setattr(
        admin_route.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    source = payload["sources"][0]
    assert source["adapter_key"] == "official.ncdr.cap"
    assert source["health_status"] == "healthy"
    assert source["upstream_status"] == "succeeded"
    assert source["freshness_state"] == "stale"
    assert source["latest_observed_at"] == "2026-04-28T12:00:00Z"
    assert source["latest_fetched_at"] == "2026-04-28T12:55:00Z"
    assert source["latest_ingested_at"] == "2026-04-28T12:56:00Z"
    assert source["lag_seconds"] == 3600
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_sources_disabled_filter_includes_disabled_rows_with_unknown_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    cursor = FakeCursor(
        [
            {
                "id": "seeded-disabled",
                "name": "Seeded disabled source",
                "adapter_key": "official.seeded.disabled",
                "source_type": "official",
                "license": None,
                "update_frequency": None,
                "last_success_at": None,
                "last_failure_at": None,
                "health_status": "unknown",
                "legal_basis": "L1",
                "source_timestamp_min": None,
                "source_timestamp_max": None,
                "is_enabled": False,
                "latest_observed_at": None,
                "latest_fetched_at": None,
                "latest_ingested_at": None,
                "row_count": 0,
                "upstream_status": "unknown",
            }
        ]
    )
    monkeypatch.setattr(
        admin_route.psycopg,
        "connect",
        lambda *args, **kwargs: FakeConnection(cursor),
    )
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        params={"health_status": "disabled"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    assert "(ds.health_status = %s OR ds.is_enabled = false)" in (cursor.query or "")
    assert cursor.params == ["disabled"]
    payload = response.json()
    assert len(payload["sources"]) == 1
    source = payload["sources"][0]
    assert source["adapter_key"] == "official.seeded.disabled"
    assert source["is_enabled"] is False
    assert source["health_status"] == "disabled"
    assert source["freshness_state"] == "stale"
    assert source["upstream_status"] == "disabled"
    assert source["enabled_gates"] == []
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_pending_reports_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    calls: list[dict[str, object]] = []

    def list_reports(**kwargs: object) -> list[UserReportModerationRecord]:
        calls.append(kwargs)
        return [
            UserReportModerationRecord(
                id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
                status="pending",
                summary="Water at ankle depth.",
                lat=25.033,
                lng=121.5654,
                created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
                reviewed_at=None,
            )
        ]

    monkeypatch.setattr(admin_route, "list_pending_user_reports", list_reports)
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/reports/pending",
        params={"limit": 25},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["reports"]) == 1
    report = payload["reports"][0]
    assert set(report) == {"report_id", "status", "point", "summary", "created_at", "reviewed_at"}
    assert report["report_id"] == "0d51d545-dc6a-4e4b-8f8e-0e42d454d050"
    assert report["status"] == "pending"
    assert report["point"] == {"lat": 25.033, "lng": 121.5654}
    assert report["summary"] == "Water at ankle depth."
    assert report["reviewed_at"] is None
    assert calls == [{"database_url": get_settings().database_url, "limit": 25}]
    assert_openapi_schema(payload, "AdminUserReportsResponse")


def test_admin_report_moderation_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    calls: list[dict[str, object]] = []

    def moderate_report(**kwargs: object) -> UserReportModerationRecord:
        calls.append(kwargs)
        return UserReportModerationRecord(
            id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            status="approved",
            summary="Water at ankle depth.",
            lat=25.033,
            lng=121.5654,
            created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
            reviewed_at=datetime(2026, 4, 29, 12, 5, tzinfo=UTC),
        )

    monkeypatch.setattr(admin_route, "moderate_user_report", moderate_report)
    client = TestClient(create_app())

    response = client.patch(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/moderation",
        json={"status": "approved", "reason_code": "verified_flood_signal"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["status"] == "approved"
    assert payload["report"]["reviewed_at"] == "2026-04-29T12:05:00Z"
    assert calls == [
        {
            "database_url": get_settings().database_url,
            "report_id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            "status": "approved",
            "reason_code": "verified_flood_signal",
            "actor_ref": "admin_api",
        }
    ]
    assert_openapi_schema(payload, "UserReportModerationResponse")


def test_admin_report_privacy_redaction_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    calls: list[dict[str, object]] = []

    def redact_report(**kwargs: object) -> UserReportPrivacyRedactionRecord:
        calls.append(kwargs)
        return UserReportPrivacyRedactionRecord(
            id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            status="deleted",
            privacy_level="redacted",
            redacted_at=datetime(2026, 4, 29, 12, 10, tzinfo=UTC),
        )

    monkeypatch.setattr(admin_route, "redact_user_report_privacy", redact_report)
    client = TestClient(create_app())

    response = client.post(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/privacy-redaction",
        json={"reason_code": "private_data_exposure"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["redaction"] == {
        "report_id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        "status": "deleted",
        "privacy_level": "redacted",
        "redacted_at": "2026-04-29T12:10:00Z",
    }
    assert calls == [
        {
            "database_url": get_settings().database_url,
            "report_id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            "reason_code": "private_data_exposure",
            "actor_ref": "admin_api",
        }
    ]
    assert_openapi_schema(payload, "UserReportPrivacyRedactionResponse")


def test_admin_report_moderation_rejects_invalid_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    called = False

    def moderate_report(**_kwargs: object) -> UserReportModerationRecord:
        nonlocal called
        called = True
        raise AssertionError("moderation repository should not be called")

    monkeypatch.setattr(admin_route, "moderate_user_report", moderate_report)
    client = TestClient(create_app())

    response = client.patch(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/moderation",
        json={"status": "pending"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    assert called is False


def test_admin_report_moderation_rejects_reason_for_wrong_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    called = False

    def moderate_report(**_kwargs: object) -> UserReportModerationRecord:
        nonlocal called
        called = True
        raise AssertionError("moderation repository should not be called")

    monkeypatch.setattr(admin_route, "moderate_user_report", moderate_report)
    client = TestClient(create_app())

    response = client.patch(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/moderation",
        json={"status": "approved", "reason_code": "abuse_or_spam"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "bad_request"
    assert "reason_code" in str(payload["error"]["details"])
    assert called is False


def test_admin_pending_reports_return_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()

    def unavailable(**_kwargs: object) -> list[UserReportModerationRecord]:
        raise UserReportRepositoryUnavailable("database unavailable")

    monkeypatch.setattr(admin_route, "list_pending_user_reports", unavailable)
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/reports/pending",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "repository_unavailable"


def test_admin_jobs_return_503_when_database_is_unavailable_in_hosted_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("ADMIN_SAMPLE_DATA_ENABLED", raising=False)
    monkeypatch.delenv("DEMO_MODE_ENABLED", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/jobs",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "repository_unavailable"
    assert "jobs repository" in payload["error"]["message"]


def test_admin_sources_return_503_when_database_is_unavailable_in_hosted_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.delenv("ADMIN_SAMPLE_DATA_ENABLED", raising=False)
    monkeypatch.delenv("DEMO_MODE_ENABLED", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "repository_unavailable"
    assert "sources repository" in payload["error"]["message"]


def test_admin_sources_fall_back_to_sample_data_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        params={"health_status": "healthy"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) >= 2
    assert {source["health_status"] for source in payload["sources"]} == {"healthy"}
    cwa = next(
        source
        for source in payload["sources"]
        if source["adapter_key"] == "official.cwa.rainfall"
    )
    assert cwa["latest_observed_at"] is not None
    assert cwa["latest_fetched_at"] is not None
    assert cwa["latest_ingested_at"] is not None
    assert cwa["lag_seconds"] is not None
    assert cwa["row_count"] == 2
    assert cwa["upstream_status"] == "succeeded"
    assert cwa["freshness_state"] in {"fresh", "degraded"}
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_local_source_coverage_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/local-source-coverage",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    summary = payload["summary"]
    assert summary["total_counties"] == 22
    assert summary["local_direct_complete_count"] == 20
    assert summary["local_direct_incomplete_count"] == 2
    assert summary["central_backbone_minimum_complete_count"] == 22
    assert summary["central_backbone_minimum_incomplete_count"] == 0
    assert summary["counties_missing_hydrologic_backbone"] == []
    assert summary["request_official_authorization_count"] == 2
    assert summary["verify_live_smoke_count"] == 0
    assert summary["verify_public_api_contract_count"] == 3
    assert summary["counties_requiring_official_authorization"] == ["花蓮縣", "金門縣"]
    assert summary["counties_requiring_live_smoke"] == []
    assert summary["counties_requiring_public_api_contract"] == [
        "苗栗縣",
        "屏東縣",
        "臺東縣",
    ]
    assert summary["counties_requiring_metadata_release_monitoring"] == [
        "連江縣",
    ]
    assert summary["counties_requiring_official_discovery"] == [
        "連江縣",
    ]
    assert "連江縣" in summary["local_direct_incomplete_counties"]
    assert summary["central_backbone_required_families"] == [
        "CWA",
        "WRA",
        "NCDR",
        "Civil IoT",
    ]
    assert summary["central_backbone_missing_families"] == []
    assert summary["central_backbone_family_complete"] is True
    assert summary["central_backbone_required_adapter_keys"] == [
        "official.cwa.rainfall",
        "official.cwa.tide_level",
        "official.wra.water_level",
        "official.ncdr.cap",
        "official.wra_iow.flood_depth",
        "official.civil_iot.flood_sensor",
        "official.civil_iot.sewer_water_level",
        "official.civil_iot.pump_water_level",
        "official.civil_iot.gate_water_level",
    ]
    assert summary["central_backbone_missing_adapter_keys"] == []
    counties = {county["county"]: county for county in payload["counties"]}
    assert len(counties) == 22
    assert counties["臺北市"]["local_direct_statuses"] == [
        "ready_implemented",
    ]
    assert counties["臺北市"]["local_direct_complete"] is True
    assert counties["臺北市"]["next_action_code"] == "operate_adapter"
    assert counties["臺北市"]["candidate_source_urls"] == []
    assert counties["臺北市"]["status_only_available"] is True
    assert counties["臺北市"]["status_only_source_names"] == ["臺北市水門啟閉狀態"]
    assert counties["臺北市"]["status_only_source_urls"] == [
        "https://wic.gov.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
    ]
    assert counties["臺北市"]["status_only_signal_types"] == ["gate_status"]
    assert counties["臺北市"]["flood_depth_available"] is False
    assert "flood_depth" in counties["臺北市"]["missing_signal_types"]
    assert counties["臺北市"]["blocking_reason"] is None
    assert counties["臺南市"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["臺南市"]["local_direct_complete"] is True
    assert counties["臺南市"]["central_backbone_available"] is True
    assert counties["臺南市"]["production_adapter_keys"] == ["local.tainan.flood_sensor"]
    assert counties["臺南市"]["production_source_urls"] == [
        "https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c",
    ]
    assert counties["臺南市"]["next_action_code"] == "operate_adapter"
    assert counties["臺南市"]["upgrade_priority"] == 5
    assert counties["高雄市"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["高雄市"]["production_adapter_keys"] == [
        "local.kaohsiung.sewer_water_level",
        "local.kaohsiung.flood_sensor",
        "local.kaohsiung.rainfall",
    ]
    assert counties["高雄市"]["next_action_code"] == "operate_adapter"
    assert counties["新北市"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["新北市"]["local_direct_complete"] is True
    assert counties["新北市"]["central_backbone_available"] is True
    assert counties["新北市"]["central_backbone_signal_types"] == [
        "rainfall",
        "river_water_level",
        "cap_alert",
        "flood_depth",
        "sewer_water_level",
    ]
    assert counties["新北市"]["central_backbone_required_signal_types"] == [
        "rainfall",
        "cap_alert",
        "hydrologic_observation",
    ]
    assert counties["新北市"]["central_backbone_minimum_complete"] is True
    assert counties["新北市"]["central_backbone_missing_signal_types"] == []
    assert counties["新北市"]["central_backbone_coverage_level"] == "minimum_met"
    assert counties["新北市"]["rainfall_available"] is True
    assert counties["新北市"]["water_level_available"] is True
    assert counties["新北市"]["flood_depth_available"] is True
    assert counties["新北市"]["sewer_water_level_available"] is True
    assert counties["新北市"]["pump_or_gate_status_available"] is False
    assert counties["新北市"]["status_only_available"] is False
    assert counties["新北市"]["missing_signal_types"] == [
        "pump_or_gate_status",
    ]
    assert "https://data.ntpc.gov.tw/datasets/3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296" in counties[
        "新北市"
    ]["metadata_source_urls"]
    assert counties["新北市"]["production_adapter_keys"] == [
        "local.new_taipei.water_level",
        "local.new_taipei.flood_sensor",
        "local.new_taipei.rainfall",
        "local.new_taipei.drainage_water_level",
    ]
    assert counties["新北市"]["next_action_code"] == "operate_adapter"
    assert counties["新北市"]["blocking_reason"] is None
    assert "official.civil_iot.flood_sensor" in counties["新北市"][
        "central_backbone_adapter_keys"
    ]
    assert counties["基隆市"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["基隆市"]["local_direct_complete"] is True
    assert counties["基隆市"]["production_adapter_keys"] == [
        "local.keelung.water_level",
        "local.keelung.flood_sensor",
        "local.keelung.rainfall",
    ]
    assert counties["基隆市"]["next_action_code"] == "operate_adapter"
    assert "sewer_water_level" in counties["基隆市"]["central_backbone_signal_types"]
    assert counties["基隆市"]["upgrade_priority"] == 5
    assert counties["新竹市"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["新竹市"]["local_direct_complete"] is True
    assert counties["新竹市"]["production_adapter_keys"] == [
        "local.hsinchu_city.sewer_water_level",
        "local.hsinchu_city.flood_sensor",
    ]
    assert counties["新竹市"]["next_action_code"] == "operate_adapter"
    assert counties["新竹縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["新竹縣"]["production_adapter_keys"] == [
        "local.hsinchu_county.flood_sensor",
    ]
    assert counties["新竹縣"]["next_action_code"] == "operate_adapter"
    assert "sewer_water_level" in counties["新竹縣"]["central_backbone_signal_types"]
    assert "sewer_water_level" in counties["苗栗縣"]["central_backbone_signal_types"]
    assert counties["苗栗縣"]["local_direct_complete"] is True
    assert counties["苗栗縣"]["production_adapter_keys"] == [
        "local.miaoli.flood_sensor",
    ]
    assert counties["南投縣"]["central_backbone_signal_types"] == [
        "rainfall",
        "river_water_level",
        "cap_alert",
        "flood_depth",
        "sewer_water_level",
    ]
    assert counties["南投縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["南投縣"]["production_adapter_keys"] == [
        "local.nantou.sewer_water_level",
    ]
    assert "sewer_water_level" in counties["彰化縣"]["central_backbone_signal_types"]
    assert "gate_water_level" in counties["彰化縣"]["central_backbone_signal_types"]
    assert counties["彰化縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["彰化縣"]["production_adapter_keys"] == [
        "local.changhua.flood_sensor",
    ]
    assert counties["雲林縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["雲林縣"]["local_direct_complete"] is True
    assert counties["雲林縣"]["production_adapter_keys"] == [
        "local.yunlin.water_level",
    ]
    assert counties["雲林縣"]["next_action_code"] == "operate_adapter"
    yunlin_notes = " ".join(counties["雲林縣"]["notes"])
    assert "alarmState" in yunlin_notes
    assert "不以其假造淹水深度" in yunlin_notes
    assert counties["雲林縣"]["status_only_available"] is True
    assert counties["雲林縣"]["status_only_source_names"] == [
        "雲林 iflood 淹水感測狀態",
    ]
    assert counties["雲林縣"]["status_only_signal_types"] == ["flood_sensor_status"]
    assert counties["雲林縣"]["flood_depth_available"] is False
    assert "flood_depth" in counties["雲林縣"]["missing_signal_types"]
    assert "sewer_water_level" in counties["嘉義縣"]["central_backbone_signal_types"]
    assert "gate_water_level" in counties["嘉義縣"]["central_backbone_signal_types"]
    assert counties["嘉義縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["嘉義縣"]["production_adapter_keys"] == [
        "local.chiayi_county.flood_sensor",
    ]
    assert counties["嘉義縣"]["next_action_code"] == "operate_adapter"
    assert counties["屏東縣"]["local_direct_statuses"] == [
        "ready_implemented",
        "candidate",
    ]
    assert counties["屏東縣"]["local_direct_complete"] is True
    assert counties["屏東縣"]["production_adapter_keys"] == [
        "local.pingtung.flood_sensor",
    ]
    assert counties["屏東縣"]["next_action_code"] == "verify_public_api_contract"
    assert any(
        "pteoc.pthg.gov.tw/RainStation" in url
        for url in counties["屏東縣"]["candidate_source_urls"]
    )
    assert counties["宜蘭縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["宜蘭縣"]["production_adapter_keys"] == [
        "local.yilan.flood_sensor",
        "local.yilan.water_level",
    ]
    assert counties["宜蘭縣"]["next_action_code"] == "operate_adapter"
    assert counties["澎湖縣"]["local_direct_statuses"] == ["ready_implemented"]
    assert counties["澎湖縣"]["production_adapter_keys"] == [
        "local.penghu.water_level",
    ]
    assert counties["澎湖縣"]["next_action_code"] == "operate_adapter"
    assert "ph3dgis.penghu.gov.tw" in counties["澎湖縣"]["production_source_urls"][0]
    assert counties["花蓮縣"]["local_direct_statuses"] == [
        "ready_implemented",
        "needs_application",
    ]
    assert counties["花蓮縣"]["local_direct_complete"] is True
    assert counties["花蓮縣"]["production_adapter_keys"] == [
        "local.hualien.flood_sensor",
    ]
    assert counties["花蓮縣"]["next_action_code"] == "request_official_authorization"
    assert counties["花蓮縣"]["requires_application"] is True
    assert counties["臺東縣"]["local_direct_complete"] is True
    assert counties["臺東縣"]["production_adapter_keys"] == [
        "local.taitung.flood_sensor",
    ]
    assert counties["金門縣"]["local_direct_statuses"] == ["needs_application"]
    assert counties["金門縣"]["next_action_code"] == "request_official_authorization"
    assert counties["金門縣"]["upgrade_priority"] == 1
    assert counties["金門縣"]["requires_application"] is True
    assert "KWIS" in (counties["金門縣"]["application_note"] or "")
    assert any("KWIS" in url for url in counties["金門縣"]["application_urls"])
    assert counties["連江縣"]["local_direct_statuses"] == ["metadata_only", "not_found"]
    assert counties["連江縣"]["production_adapter_keys"] == []
    assert counties["連江縣"]["central_backbone_adapter_keys"] == [
        "official.cwa.rainfall",
        "official.cwa.tide_level",
        "official.ncdr.cap",
    ]
    assert counties["連江縣"]["central_backbone_signal_types"] == [
        "rainfall",
        "tide_level",
        "cap_alert",
    ]
    assert counties["連江縣"]["central_backbone_minimum_complete"] is True
    assert counties["連江縣"]["central_backbone_missing_signal_types"] == []
    assert counties["連江縣"]["central_backbone_coverage_level"] == "minimum_met"
    assert counties["連江縣"]["rainfall_available"] is True
    assert counties["連江縣"]["water_level_available"] is True
    assert counties["連江縣"]["flood_depth_available"] is False
    assert counties["連江縣"]["sewer_water_level_available"] is False
    assert counties["連江縣"]["pump_or_gate_status_available"] is False
    assert counties["連江縣"]["status_only_available"] is False
    assert counties["連江縣"]["non_qualifying_source_names"] == [
        "連江自來水廠水庫水位月報",
        "連江縣資訊公開查詢系統即時監測值",
    ]
    assert counties["連江縣"]["non_qualifying_source_urls"] == [
        "https://www.matsuwater.gov.tw/load_page/reservoir_water_level_page",
        "http://erbwater.matsu.gov.tw/PUBLIC/RealTime/Get_AVGR.aspx",
    ]
    assert "放流水環保 CEMS" in " ".join(
        counties["連江縣"]["non_qualifying_source_reasons"]
    )
    assert counties["連江縣"]["missing_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    assert_openapi_schema(payload, "AdminLocalSourceCoverageResponse")


def test_admin_local_source_action_plan_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/local-source-action-plan",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_at"] == "2026-06-29T00:00:00Z"
    plan = payload["plan"]
    assert plan["local_direct_complete_count"] == 20
    assert plan["local_direct_remaining_count"] == 2
    assert plan["central_backbone_minimum_complete_count"] == 22
    assert plan["central_backbone_remaining_count"] == 0
    assert [item["county"] for item in plan["authorization_requests"]] == [
        "花蓮縣",
        "金門縣",
    ]
    assert [item["county"] for item in plan["metadata_release_monitors"]] == ["連江縣"]
    assert [item["county"] for item in plan["public_api_contract_reviews"]] == [
        "苗栗縣",
        "屏東縣",
        "臺東縣",
    ]
    assert [item["county"] for item in plan["live_smoke_reviews"]] == []
    assert [item["county"] for item in plan["integration_priority_queue"][:3]] == [
        "連江縣",
        "金門縣",
        "花蓮縣",
    ]
    top_priority = plan["integration_priority_queue"][0]
    assert top_priority["priority_tier"] == "P0"
    assert top_priority["workstream"] == "monitor_open_data_release"
    assert top_priority["completion_gate"]
    assert top_priority["central_backbone_missing_signal_types"] == []
    assert top_priority["missing_signal_types"] == [
        "flood_depth",
        "sewer_water_level",
        "pump_or_gate_status",
    ]
    signal_gaps = {item["county"]: item for item in plan["sensor_signal_gap_reviews"]}
    assert "臺北市" in signal_gaps
    assert signal_gaps["臺北市"]["tracking_status"] == "needs_signal_gap_review"
    assert signal_gaps["臺北市"]["missing_signal_types"] == ["flood_depth"]
    assert signal_gaps["臺北市"]["status_only_signal_types"] == ["gate_status"]
    assert "嘉義市" in signal_gaps
    assert signal_gaps["嘉義市"]["tracking_status"] == "needs_signal_gap_review"
    assert "flood_depth" in signal_gaps["嘉義市"]["missing_signal_types"]
    assert "雲林縣" in signal_gaps
    assert signal_gaps["雲林縣"]["missing_signal_types"] == ["flood_depth"]
    assert signal_gaps["雲林縣"]["status_only_source_urls"] == [
        "https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5"
    ]
    assert signal_gaps["雲林縣"]["status_only_signal_types"] == [
        "flood_sensor_status"
    ]
    assert "高雄市" not in signal_gaps
    hualien = plan["authorization_requests"][0]
    assert hualien["requested_counterparty"] == "花蓮縣政府 / Senslink 行動水情維運窗口"
    kinmen = plan["authorization_requests"][1]
    assert "KWIS" in kinmen["reason"]
    assert "observed_at" in kinmen["required_read_api_fields"]
    assert kinmen["requested_counterparty"] == "金門縣政府 / KWIS 維運窗口"
    assert kinmen["tracking_status"] == "needs_authorization_request"
    assert kinmen["last_followed_up_at"] is None
    lienchiang = plan["metadata_release_monitors"][0]
    assert lienchiang["central_backbone_missing_signal_types"] == []
    assert lienchiang["requested_counterparty"] == "連江縣政府公開資料或防災水利窗口"
    assert lienchiang["tracking_status"] == "monitoring_open_data_release"
    assert lienchiang["last_followed_up_at"] is None
    assert lienchiang["non_qualifying_source_names"] == [
        "連江自來水廠水庫水位月報",
        "連江縣資訊公開查詢系統即時監測值",
    ]
    assert "月報 PDF" in " ".join(lienchiang["non_qualifying_source_reasons"])
    assert "measurement_value" in lienchiang["required_read_api_fields"]
    assert_openapi_schema(payload, "AdminLocalSourceActionPlanResponse")


def test_admin_sources_can_use_sample_data_with_explicit_demo_flag_in_hosted_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    monkeypatch.setenv("APP_ENV", "production-beta")
    monkeypatch.setenv("ADMIN_SAMPLE_DATA_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/sources",
        params={"health_status": "healthy"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) >= 2
    assert {source["health_status"] for source in payload["sources"]} == {"healthy"}


def test_admin_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/sources", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
