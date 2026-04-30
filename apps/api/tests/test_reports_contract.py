from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes import reports as reports_routes
from app.domain.reports import PendingUserReport, UserReportRepositoryUnavailable
from app.main import create_app


client = TestClient(create_app())


def _settings(*, enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        user_reports_enabled=enabled,
        database_url="postgresql://example.test/flood",
    )


def assert_error_envelope(payload: dict) -> None:
    assert set(payload) == {"error"}
    assert {"code", "message", "details"} == set(payload["error"])


def test_user_report_intake_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=False))

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "Water over curb."},
    )

    assert response.status_code == 404
    payload = response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "feature_disabled"
    assert "disabled" in payload["error"]["message"]


def test_user_report_rejects_media_and_private_fields_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))

    response = client.post(
        "/v1/reports",
        json={
            "point": {"lat": 25.033, "lng": 121.5654},
            "summary": "Flooding near the intersection.",
            "media": {"url": "https://example.test/photo.jpg"},
            "email": "reporter@example.test",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "bad_request"


def test_user_report_rejects_blank_summary_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "   "},
    )

    assert response.status_code == 400
    assert_error_envelope(response.json())


def test_user_report_enabled_path_returns_pending_report_with_mocked_repository(
    monkeypatch,
) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))
    calls: list[dict[str, object]] = []

    def create_report(**kwargs: object) -> PendingUserReport:
        calls.append(kwargs)
        return PendingUserReport(id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050", status="pending")

    monkeypatch.setattr(reports_routes, "create_pending_user_report", create_report)

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "  Water at ankle depth.  "},
    )

    assert response.status_code == 202
    payload = response.json()
    assert set(payload) == {"report_id", "status"}
    assert UUID(payload["report_id"])
    assert payload["status"] == "pending"
    assert calls == [
        {
            "database_url": "postgresql://example.test/flood",
            "lat": 25.033,
            "lng": 121.5654,
            "summary": "Water at ankle depth.",
        }
    ]


def test_user_report_db_unavailable_returns_503(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))

    def unavailable(**_kwargs: object) -> PendingUserReport:
        raise UserReportRepositoryUnavailable("database unavailable")

    monkeypatch.setattr(reports_routes, "create_pending_user_report", unavailable)

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "Water over curb."},
    )

    assert response.status_code == 503
    payload = response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "repository_unavailable"
