from __future__ import annotations

from datetime import datetime
from pathlib import Path
import warnings

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
import pytest
import yaml  # type: ignore[import-untyped]

from app.api.routes import admin as admin_route
from app.core.config import get_settings
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
