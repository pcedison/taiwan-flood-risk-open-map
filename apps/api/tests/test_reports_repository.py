from typing import Any, cast

from app.domain.reports import create_pending_user_report


def test_create_pending_user_report_inserts_minimized_pending_report() -> None:
    connection = _FakeConnection(
        row={"id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050", "status": "pending"}
    )

    report = create_pending_user_report(
        database_url="postgresql://example.test/flood",
        lat=25.033,
        lng=121.5654,
        summary="Water at ankle depth.",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "INSERT INTO user_reports" in sql
    assert "ST_SetSRID(ST_MakePoint(%s, %s), 4326)" in sql
    assert "media_ref" in sql
    assert "NULL" in sql
    assert "'pending'" in sql
    assert "'redacted'" in sql
    assert "INSERT INTO audit_logs" in sql
    assert "user_report.submitted" in sql
    assert params[:3] == (121.5654, 25.033, "Water at ankle depth.")
    assert cast(Any, params[3]).obj == {
        "status": "pending",
        "privacy_level": "redacted",
        "media_ref": None,
    }
    assert report.id == "0d51d545-dc6a-4e4b-8f8e-0e42d454d050"
    assert report.status == "pending"


class _FakeConnection:
    def __init__(self, *, row: dict[str, object] | None = None) -> None:
        self.cursor_instance = _FakeCursor(row=row)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return self.cursor_instance


class _FakeCursor:
    def __init__(self, *, row: dict[str, object] | None = None) -> None:
        self._row = row
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object] | None:
        return self._row
