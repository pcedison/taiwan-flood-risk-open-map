from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import warnings

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
import psycopg
import pytest
import yaml  # type: ignore[import-untyped]

from app.api.routes import admin as admin_route
from app.core.config import get_settings
from app.main import create_app
from app.ops import db_diagnostics

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from jsonschema import RefResolver  # type: ignore[import-untyped]


REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_SPEC = yaml.safe_load(
    (REPO_ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8")
)
TOKEN = "test-admin-token"


def assert_openapi_schema(payload: dict, schema_name: str) -> None:
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": OPENAPI_SPEC["components"],
    }
    validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema))
    assert list(validator.iter_errors(payload)) == []


def _diagnostics_payload() -> dict[str, Any]:
    return {
        "captured_at": datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        "sample_point": {"lat": 25.033, "lng": 121.5654, "radius_m": 500},
        "tables": [
            {
                "relname": "evidence",
                "n_live_tup": 1_112_891,
                "n_dead_tup": 402_118,
                "dead_tuple_ratio": 0.2654,
                "last_autovacuum": datetime(2026, 9, 4, 3, 12, tzinfo=UTC),
                "total_relation_size_bytes": 1_819_680_768,
            }
        ],
        "indexes": [
            {
                "relname": "evidence",
                "indexrelname": "idx_evidence_geom_geography",
                "idx_scan": 91_233,
                "idx_tup_read": 8_412_990,
                "index_size_bytes": 153_092_096,
            }
        ],
        "query_plans": [
            {
                "name": "nearby_evidence",
                "status": "ok",
                "plan": [{"Plan": {"Node Type": "Limit"}, "Execution Time": 5624.1}],
                "error": None,
            },
            {
                "name": "coverage_supplement",
                "status": "timeout",
                "plan": None,
                "error": "timeout",
            },
        ],
        "statements": None,
    }


def test_db_diagnostics_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", TOKEN)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/admin/v1/db-diagnostics")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_db_diagnostics_rejects_a_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", TOKEN)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/db-diagnostics",
        headers={"Authorization": "Bearer not-the-admin-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_db_diagnostics_returns_403_when_auth_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_BEARER_TOKEN", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/db-diagnostics", headers={"Authorization": "Bearer any-token"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_db_diagnostics_returns_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", TOKEN)
    get_settings.cache_clear()
    monkeypatch.setattr(
        admin_route, "collect_db_diagnostics", lambda **kwargs: _diagnostics_payload()
    )
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/db-diagnostics", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sample_point"] == {"lat": 25.033, "lng": 121.5654, "radius_m": 500}
    table = payload["tables"][0]
    assert table["relname"] == "evidence"
    assert table["n_dead_tup"] == 402_118
    assert table["dead_tuple_ratio"] == pytest.approx(0.2654)
    assert payload["indexes"][0]["indexrelname"] == "idx_evidence_geom_geography"
    plans = {plan["name"]: plan for plan in payload["query_plans"]}
    assert plans["nearby_evidence"]["status"] == "ok"
    assert plans["nearby_evidence"]["plan"][0]["Execution Time"] == pytest.approx(5624.1)
    # A query that could not finish is reported, not raised.
    assert plans["coverage_supplement"]["status"] == "timeout"
    assert plans["coverage_supplement"]["error"] == "timeout"
    assert payload["statements"] is None
    datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00"))
    assert_openapi_schema(payload, "AdminDbDiagnosticsResponse")


def test_db_diagnostics_path_documents_admin_auth_and_error_responses() -> None:
    operation = OPENAPI_SPEC["paths"]["/admin/v1/db-diagnostics"]["get"]

    assert operation["security"] == [{"AdminBearerAuth": []}]
    assert "admin" in operation["x-required-roles"]
    for status_code in ("200", "401", "403", "503"):
        assert status_code in operation["responses"]


def test_db_diagnostics_reports_503_when_collection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", TOKEN)
    get_settings.cache_clear()

    def unavailable(**kwargs: object) -> None:
        raise OSError("database unavailable")

    monkeypatch.setattr(admin_route, "collect_db_diagnostics", unavailable)
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/db-diagnostics", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "repository_unavailable"


class _FakeCursor:
    """Cursor that raises a chosen error on the EXPLAIN statement."""

    def __init__(self, error: BaseException | None, plan: object = None) -> None:
        self._error = error
        self._plan = plan
        self.executed: list[str] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.executed.append(query)
        if query.startswith("EXPLAIN") and self._error is not None:
            raise self._error

    def fetchone(self) -> Any:
        return {"QUERY PLAN": self._plan}

    def fetchall(self) -> list[Any]:
        return []


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _statement() -> tuple[str, tuple[()]]:
    return ("SELECT 1", ())


def test_explain_reports_timeout_without_raising() -> None:
    cursor = _FakeCursor(psycopg.errors.QueryCanceled("canceling statement"))

    result = db_diagnostics._explain(
        "coverage_supplement",
        _statement,
        "postgresql://example",
        lambda: _FakeConnection(cursor),
    )

    assert result == {
        "name": "coverage_supplement",
        "status": "timeout",
        "plan": None,
        "error": "timeout",
    }
    # The budget must be applied before the EXPLAIN runs.
    assert "statement_timeout" in cursor.executed[0]
    assert cursor.executed[1].startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ")


def test_explain_never_leaks_the_connection_string() -> None:
    secret_url = "postgresql://flood_risk:super-secret@db.internal:5432/flood_risk"
    cursor = _FakeCursor(psycopg.OperationalError(f'could not connect to "{secret_url}"'))

    result = db_diagnostics._explain(
        "jurisdiction", _statement, secret_url, lambda: _FakeConnection(cursor)
    )

    assert result["status"] == "unavailable"
    # Only the exception class name: psycopg renders the full conninfo in its
    # message, which would put the database host and password in the payload.
    assert result["error"] == "OperationalError"
    assert "super-secret" not in repr(result)
    assert "db.internal" not in repr(result)


def test_explain_returns_the_plan_on_success() -> None:
    plan = [{"Plan": {"Node Type": "Limit"}, "Execution Time": 12.5}]
    cursor = _FakeCursor(None, plan=plan)

    result = db_diagnostics._explain(
        "nearby_evidence", _statement, "postgresql://example", lambda: _FakeConnection(cursor)
    )

    assert result["status"] == "ok"
    assert result["plan"] == plan
    assert result["error"] is None


def test_explain_skips_when_the_statement_cannot_be_built() -> None:
    def broken() -> tuple[str, tuple[()]]:
        raise RuntimeError("reader changed shape")

    result = db_diagnostics._explain(
        "nearby_evidence", broken, "postgresql://example", lambda: None
    )

    assert result == {
        "name": "nearby_evidence",
        "status": "skipped",
        "plan": None,
        "error": "sql_unavailable",
    }


def test_statement_sources_cover_all_three_risk_path_segments() -> None:
    sources = dict(db_diagnostics._statement_sources())

    assert list(sources) == [
        "nearby_evidence",
        "coverage_supplement",
        "jurisdiction",
    ]
    for name, statement in sources.items():
        captured = statement()
        assert captured is not None, name
        sql, _params = captured
        assert "SELECT" in sql, name


def test_table_and_index_sections_survive_an_unavailable_database() -> None:
    def unavailable() -> None:
        raise OSError("database unavailable")

    diagnostics = db_diagnostics.collect_db_diagnostics(
        database_url="postgresql://example", connection_factory=unavailable
    )

    # A failed section returns empty rather than breaking the whole payload.
    assert diagnostics["tables"] == []
    assert diagnostics["indexes"] == []
    assert diagnostics["statements"] is None
    assert [plan["status"] for plan in diagnostics["query_plans"]] == [
        "unavailable",
        "unavailable",
        "unavailable",
    ]
