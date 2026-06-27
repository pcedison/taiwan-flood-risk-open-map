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
