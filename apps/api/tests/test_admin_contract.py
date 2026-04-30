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
from app.domain.reports import UserReportModerationRecord, UserReportRepositoryUnavailable
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

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: list[str]) -> None:
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
        json={"status": "approved"},
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
            "actor_ref": "admin_api",
        }
    ]
    assert_openapi_schema(payload, "UserReportModerationResponse")


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
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/sources", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
