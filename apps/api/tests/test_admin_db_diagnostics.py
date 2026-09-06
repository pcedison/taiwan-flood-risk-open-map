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
        "staging_status_counts": {
            "status": "ok",
            "method": "exact",
            "rows": [
                {
                    "validation_status": "rejected",
                    "rows": 11_600_000,
                    "oldest": datetime(2026, 6, 13, tzinfo=UTC),
                    "newest": datetime(2026, 9, 5, 11, 55, tzinfo=UTC),
                },
                {
                    "validation_status": "accepted",
                    "rows": 2_400_000,
                    "oldest": datetime(2026, 6, 13, 0, 10, tzinfo=UTC),
                    "newest": datetime(2026, 9, 5, 11, 55, tzinfo=UTC),
                },
            ],
            "error": None,
        },
        "staging_used_by_evidence_estimate": {
            "status": "ok",
            "method": "exact",
            "rows": 2_310_000,
            "index_name": "idx_evidence_staging_evidence_id",
            "error": None,
        },
        "query_plans": [
            {
                "name": "nearby_evidence",
                "radius_m": 500,
                "status": "ok",
                "plan": [{"Plan": {"Node Type": "Limit"}, "Execution Time": 5624.1}],
                "error": None,
                "note": "matches the request path",
            },
            {
                "name": "coverage_supplement",
                "radius_m": 15000,
                "status": "timeout",
                "plan": None,
                "error": "timeout",
                "note": "the request path abandons this query after 250 ms",
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
    # Each plan states the radius it searched and how it relates to a request.
    assert plans["nearby_evidence"]["radius_m"] == 500
    assert plans["coverage_supplement"]["radius_m"] == 15000
    assert "abandons" in plans["coverage_supplement"]["note"]
    # A query that could not finish is reported, not raised.
    assert plans["coverage_supplement"]["status"] == "timeout"
    assert plans["coverage_supplement"]["error"] == "timeout"
    assert payload["statements"] is None
    # #367 turns on the staging status split, so it has to survive the contract.
    staging = payload["staging_status_counts"]
    assert staging["status"] == "ok"
    assert staging["method"] == "exact"
    assert [row["validation_status"] for row in staging["rows"]] == [
        "rejected",
        "accepted",
    ]
    assert staging["rows"][0]["rows"] == 11_600_000
    assert payload["staging_used_by_evidence_estimate"] == {
        "status": "ok",
        "method": "exact",
        "rows": 2_310_000,
        "index_name": "idx_evidence_staging_evidence_id",
        "error": None,
    }
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
        15_000,
        _statement,
        "postgresql://example",
        lambda: _FakeConnection(cursor),
    )

    assert result["status"] == "timeout"
    assert result["error"] == "timeout"
    assert result["plan"] is None
    assert result["radius_m"] == 15_000
    # The probe budget is larger than the request path allows, so the payload
    # must say so rather than letting the number read as request latency.
    assert "250 ms" in result["note"]
    assert "not as request latency" in result["note"]
    # Read-only first, then the budget, then the EXPLAIN.
    assert cursor.executed[0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in cursor.executed[1]
    assert cursor.executed[2].startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ")


def test_explain_never_leaks_the_connection_string() -> None:
    secret_url = "postgresql://flood_risk:super-secret@db.internal:5432/flood_risk"
    cursor = _FakeCursor(psycopg.OperationalError(f'could not connect to "{secret_url}"'))

    result = db_diagnostics._explain(
        "jurisdiction", 500, _statement, secret_url, lambda: _FakeConnection(cursor)
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
        "nearby_evidence",
        500,
        _statement,
        "postgresql://example",
        lambda: _FakeConnection(cursor),
    )

    assert result["status"] == "ok"
    assert result["plan"] == plan
    assert result["error"] is None


def test_explain_skips_when_the_statement_cannot_be_built() -> None:
    def broken() -> tuple[str, tuple[()]]:
        raise RuntimeError("reader changed shape")

    result = db_diagnostics._explain(
        "nearby_evidence", 500, broken, "postgresql://example", lambda: None
    )

    assert result["status"] == "skipped"
    assert result["error"] == "sql_unavailable"
    assert result["plan"] is None


def test_statement_sources_cover_all_three_risk_path_segments() -> None:
    sources = {
        name: (radius, fn) for name, radius, fn in db_diagnostics._statement_sources()
    }

    assert list(sources) == [
        "nearby_evidence",
        "coverage_supplement",
        "jurisdiction",
    ]
    for name, (_radius, statement) in sources.items():
        captured = statement()
        assert captured is not None, name
        sql, _params = captured
        assert "SELECT" in sql, name


def test_jurisdiction_probe_uses_the_request_radius_not_the_reader_default() -> None:
    sources = {name: radius for name, radius, _fn in db_diagnostics._statement_sources()}

    # The reader defaults to 15 km, which the request path never passes; probing
    # at that radius resolves a different set of county polygons.
    assert sources["jurisdiction"] == db_diagnostics.SAMPLE_RADIUS_M == 500
    assert sources["nearby_evidence"] == db_diagnostics.SAMPLE_RADIUS_M
    assert sources["coverage_supplement"] == max(db_diagnostics.SAMPLE_COVERAGE_BUCKETS_M)

    _name, _radius, jurisdiction = db_diagnostics._statement_sources()[2]
    captured = jurisdiction()
    assert captured is not None
    _sql, params = captured
    assert params[-1] == db_diagnostics.SAMPLE_RADIUS_M


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
    assert diagnostics["staging_status_counts"] == {
        "status": "unavailable",
        "method": None,
        "rows": [],
        "error": "OSError",
    }
    assert diagnostics["staging_used_by_evidence_estimate"] == {
        "status": "unavailable",
        "method": None,
        "rows": None,
        "index_name": db_diagnostics.STAGING_USE_INDEX,
        "error": "OSError",
    }
    assert [plan["status"] for plan in diagnostics["query_plans"]] == [
        "unavailable",
        "unavailable",
        "unavailable",
    ]
    assert all(plan["note"] for plan in diagnostics["query_plans"])


class _ScriptedCursor:
    """Cursor answering each statement from a scripted (error, row) pair."""

    def __init__(self, script: list[tuple[BaseException | None, Any]]) -> None:
        self._script = script
        self._row: Any = None
        self.executed: list[str] = []

    def __enter__(self) -> "_ScriptedCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: object = None) -> None:
        self.executed.append(query)
        if query.startswith("SET ") or "set_config" in query:
            return
        error, row = self._script.pop(0)
        if error is not None:
            raise error
        self._row = row

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._row if isinstance(self._row, list) else []


def _scripted(script: list[tuple[BaseException | None, Any]]) -> Any:
    cursor = _ScriptedCursor(script)
    return lambda: _FakeConnection(cursor), cursor


def test_staging_status_counts_returns_the_exact_group_by() -> None:
    rows = [
        {
            "validation_status": "rejected",
            "rows": 11_600_000,
            "oldest": datetime(2026, 6, 13, tzinfo=UTC),
            "newest": datetime(2026, 9, 5, tzinfo=UTC),
        }
    ]
    factory, cursor = _scripted([(None, rows)])

    section = db_diagnostics._staging_status_counts("postgresql://example", factory)

    assert section["status"] == "ok"
    assert section["method"] == "exact"
    assert section["rows"] == rows
    assert section["error"] is None
    # Read-only and the shared budget come first, as everywhere else here.
    assert cursor.executed[0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in cursor.executed[1]
    aggregate = cursor.executed[2]
    assert "GROUP BY staging.validation_status" in aggregate
    assert "min(staging.created_at)" in aggregate
    assert "max(staging.created_at)" in aggregate


def test_staging_status_counts_falls_back_to_sampled_statistics_on_timeout() -> None:
    """The exact aggregate is a heap scan, so on the hosted node it times out.

    A timeout must still answer the question #367 asks -- the proportions --
    rather than returning nothing.
    """

    estimate_row = {
        "common_values": ["rejected", "accepted"],
        "common_freqs": [0.83, 0.17],
        "reltuples": 14_003_032.0,
    }
    factory, _cursor = _scripted(
        [
            (psycopg.errors.QueryCanceled("canceling statement"), None),
            (None, estimate_row),
        ]
    )

    factory_cursor = factory()
    section = db_diagnostics._staging_status_counts("postgresql://example", factory)

    # most_common_vals is anyarray: a direct ::text[] cast is a hard error, so
    # the double cast is load-bearing and a fake cursor cannot catch losing it.
    assert "most_common_vals::text::text[]" in factory_cursor.cursor().executed[-1]
    assert section["status"] == "timeout"
    assert section["error"] == "timeout"
    # The method is what tells a reader these are estimates, not counts.
    assert section["method"] == "pg_stats_estimate"
    assert section["rows"] == [
        {
            "validation_status": "rejected",
            "rows": 11_622_517,
            "oldest": None,
            "newest": None,
        },
        {
            "validation_status": "accepted",
            "rows": 2_380_515,
            "oldest": None,
            "newest": None,
        },
    ]


def test_staging_status_counts_reports_a_timeout_with_no_usable_statistics() -> None:
    # reltuples is -1 until the table has been analyzed once; that is not an
    # estimate and must not be presented as one.
    factory, _cursor = _scripted(
        [
            (psycopg.errors.QueryCanceled("canceling statement"), None),
            (None, {"common_values": ["rejected"], "common_freqs": [1.0], "reltuples": -1}),
        ]
    )

    section = db_diagnostics._staging_status_counts("postgresql://example", factory)

    assert section["status"] == "timeout"
    assert section["method"] is None
    assert section["rows"] == []


def test_staging_status_counts_never_leaks_the_connection_string() -> None:
    secret_url = "postgresql://flood_risk:super-secret@db.internal:5432/flood_risk"
    factory, _cursor = _scripted(
        [(psycopg.OperationalError(f'could not connect to "{secret_url}"'), None)]
    )

    section = db_diagnostics._staging_status_counts(secret_url, factory)

    assert section["status"] == "unavailable"
    assert section["error"] == "OperationalError"
    assert "super-secret" not in repr(section)
    assert "db.internal" not in repr(section)


def test_staging_used_by_evidence_counts_rows_carrying_a_staging_id() -> None:
    factory, cursor = _scripted([(None, {"rows": 2_310_000})])

    section = db_diagnostics._staging_used_by_evidence_estimate(
        "postgresql://example", factory
    )

    assert section == {
        "status": "ok",
        "method": "exact",
        "rows": 2_310_000,
        "index_name": "idx_evidence_staging_evidence_id",
        "error": None,
    }
    # The jsonb existence operator is what migration 0042's partial index covers.
    assert "properties ? 'staging_evidence_id'" in cursor.executed[2]


def test_staging_used_by_evidence_falls_back_to_the_index_row_estimate() -> None:
    factory, _cursor = _scripted(
        [
            (psycopg.errors.QueryCanceled("canceling statement"), None),
            (None, {"rows": 2_298_400.0}),
        ]
    )

    section = db_diagnostics._staging_used_by_evidence_estimate(
        "postgresql://example", factory
    )

    assert section["status"] == "timeout"
    assert section["method"] == "index_reltuples_estimate"
    assert section["rows"] == 2_298_400
    assert section["index_name"] == db_diagnostics.STAGING_USE_INDEX
    # relname alone matches a same-named index in any schema, including the
    # throwaway ones the acceptance suites build.
    estimate_sql = _cursor.executed[-1]
    assert "cls.relnamespace = current_schema()::regnamespace" in estimate_sql


def test_staging_used_by_evidence_reports_an_unanalyzed_index_as_no_estimate() -> None:
    factory, _cursor = _scripted(
        [
            (psycopg.errors.QueryCanceled("canceling statement"), None),
            (None, {"rows": -1.0}),
        ]
    )

    section = db_diagnostics._staging_used_by_evidence_estimate(
        "postgresql://example", factory
    )

    assert section["status"] == "timeout"
    assert section["method"] is None
    assert section["rows"] is None
