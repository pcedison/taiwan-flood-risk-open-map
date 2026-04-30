from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.domain.reports import (
    create_pending_user_report,
    list_pending_user_reports,
    moderate_user_report,
)


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


def test_list_pending_user_reports_reads_pending_reports_without_media_ref() -> None:
    created_at = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    connection = _FakeConnection(
        rows=[
            {
                "id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
                "status": "pending",
                "summary": "Water at ankle depth.",
                "lat": 25.033,
                "lng": 121.5654,
                "created_at": created_at,
                "reviewed_at": None,
            }
        ]
    )

    reports = list_pending_user_reports(
        database_url="postgresql://example.test/flood",
        limit=25,
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "FROM user_reports" in sql
    assert "WHERE status = 'pending'" in sql
    assert "ORDER BY created_at ASC, id ASC" in sql
    assert "media_ref" not in sql
    assert params == (25,)
    assert len(reports) == 1
    assert reports[0].id == "0d51d545-dc6a-4e4b-8f8e-0e42d454d050"
    assert reports[0].status == "pending"
    assert reports[0].summary == "Water at ankle depth."
    assert reports[0].lat == 25.033
    assert reports[0].lng == 121.5654
    assert reports[0].created_at == created_at
    assert reports[0].reviewed_at is None


def test_moderate_user_report_updates_status_and_writes_audit_log() -> None:
    created_at = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    reviewed_at = datetime(2026, 4, 29, 12, 5, tzinfo=UTC)
    connection = _FakeConnection(
        row={
            "id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            "status": "approved",
            "summary": "Water at ankle depth.",
            "lat": 25.033,
            "lng": 121.5654,
            "created_at": created_at,
            "reviewed_at": reviewed_at,
        }
    )

    report = moderate_user_report(
        database_url="postgresql://example.test/flood",
        report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        status="approved",
        reason_code="verified_flood_signal",
        actor_ref="admin_api",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "WITH target_report AS" in sql
    assert "UPDATE user_reports" in sql
    assert "status = %s" in sql
    assert "reviewed_at = now()" in sql
    assert "INSERT INTO audit_logs" in sql
    assert "user_report.moderated" in sql
    assert "previous_status" in sql
    assert "reason_code" in sql
    assert "reviewed_by" in sql
    assert "media_ref" not in sql
    assert params == (
        "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        "approved",
        "admin_api",
        "verified_flood_signal",
        "admin_api",
    )
    assert report is not None
    assert report.status == "approved"
    assert report.reviewed_at == reviewed_at


def test_moderate_user_report_returns_none_when_report_is_missing() -> None:
    connection = _FakeConnection(row=None)

    report = moderate_user_report(
        database_url="postgresql://example.test/flood",
        report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        status="rejected",
        reason_code="not_flood_related",
        actor_ref="admin_api",
        connection_factory=lambda: connection,
    )

    assert report is None


def test_moderate_user_report_rejects_invalid_status_before_sql() -> None:
    connection = _FakeConnection(row=None)

    with pytest.raises(ValueError):
        moderate_user_report(
            database_url="postgresql://example.test/flood",
            report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            status=cast(Any, "pending"),
            reason_code="not_flood_related",
            actor_ref="admin_api",
            connection_factory=lambda: connection,
        )

    assert connection.cursor_instance.executions == []


def test_moderate_user_report_rejects_reason_for_wrong_status_before_sql() -> None:
    connection = _FakeConnection(row=None)

    with pytest.raises(ValueError):
        moderate_user_report(
            database_url="postgresql://example.test/flood",
            report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            status="spam",
            reason_code="verified_flood_signal",
            actor_ref="admin_api",
            connection_factory=lambda: connection,
        )

    assert connection.cursor_instance.executions == []


class _FakeConnection:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.cursor_instance = _FakeCursor(row=row, rows=rows)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return self.cursor_instance


class _FakeCursor:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchone(self) -> dict[str, object] | None:
        return self._row

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows
