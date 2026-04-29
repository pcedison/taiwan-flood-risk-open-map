from __future__ import annotations

from datetime import datetime
from pathlib import Path
import warnings

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import pytest
import yaml

from app.core.config import get_settings
from app.main import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema import RefResolver


REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_SPEC = yaml.safe_load((REPO_ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))


def assert_openapi_schema(payload: dict, schema_name: str) -> None:
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": OPENAPI_SPEC["components"],
    }
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema))
    assert list(validator.iter_errors(payload)) == []


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
    datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
    assert_openapi_schema(payload, "AdminJobsResponse")


def test_admin_sources_contract_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert {source["legal_basis"] for source in payload["sources"]} <= {"L1", "L2"}
    assert_openapi_schema(payload, "AdminSourcesResponse")


def test_admin_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/sources", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
