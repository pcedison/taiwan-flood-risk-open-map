from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes import reports as reports_routes
from app.domain.reports import (
    PendingUserReport,
    UserReportRateLimitExceeded,
    UserReportRateLimitPolicy,
    UserReportRepositoryUnavailable,
)
from app.main import create_app


client = TestClient(create_app())


def _settings(*, enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        service_id="flood-risk-api",
        app_env="test",
        user_reports_enabled=enabled,
        user_reports_rate_limit_enabled=True,
        user_reports_rate_limit_backend="redis",
        user_reports_rate_limit_max_requests=5,
        user_reports_rate_limit_window_seconds=60,
        user_reports_rate_limit_client_header=None,
        abuse_hash_salt="test-salt",
        database_url="postgresql://example.test/flood",
        redis_url="redis://example.test:6379/0",
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
    monkeypatch.setattr(
        reports_routes,
        "check_user_report_intake_rate_limit",
        lambda **_kwargs: None,
    )

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


def test_user_report_enabled_path_checks_rate_limit_before_repository(
    monkeypatch,
) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))
    calls: list[dict[str, object]] = []

    def rate_limit(**kwargs: object) -> None:
        calls.append(kwargs)

    def create_report(**_kwargs: object) -> PendingUserReport:
        return PendingUserReport(id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050", status="pending")

    monkeypatch.setattr(reports_routes, "check_user_report_intake_rate_limit", rate_limit)
    monkeypatch.setattr(reports_routes, "create_pending_user_report", create_report)

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "Water over curb."},
    )

    assert response.status_code == 202
    assert len(calls) == 1
    assert calls[0]["max_requests"] == 5
    assert calls[0]["window_seconds"] == 60
    assert calls[0]["backend"] == "redis"
    assert calls[0]["redis_url"] == "redis://example.test:6379/0"
    assert isinstance(calls[0]["client_key"], str)
    assert calls[0]["client_key"] != "testclient"


def test_user_report_rate_limited_returns_429_before_repository(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))
    repository_called = False

    def rate_limit(**_kwargs: object) -> None:
        raise UserReportRateLimitExceeded(
            retry_after_seconds=41,
            policy=UserReportRateLimitPolicy(max_requests=5, window_seconds=60),
        )

    def create_report(**_kwargs: object) -> PendingUserReport:
        nonlocal repository_called
        repository_called = True
        raise AssertionError("repository should not be called when rate limited")

    monkeypatch.setattr(reports_routes, "check_user_report_intake_rate_limit", rate_limit)
    monkeypatch.setattr(reports_routes, "create_pending_user_report", create_report)

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "Water over curb."},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "41"
    assert repository_called is False
    payload = response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "rate_limited"
    assert payload["error"]["details"] == {
        "retry_after_seconds": 41,
        "window_seconds": 60,
    }


def test_user_report_disabled_gate_does_not_consume_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=False))
    called = False

    def rate_limit(**_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(reports_routes, "check_user_report_intake_rate_limit", rate_limit)

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "Water over curb."},
    )

    assert response.status_code == 404
    assert called is False


def test_user_report_db_unavailable_returns_503(monkeypatch) -> None:
    monkeypatch.setattr(reports_routes, "get_settings", lambda: _settings(enabled=True))

    def unavailable(**_kwargs: object) -> PendingUserReport:
        raise UserReportRepositoryUnavailable("database unavailable")

    monkeypatch.setattr(
        reports_routes,
        "check_user_report_intake_rate_limit",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(reports_routes, "create_pending_user_report", unavailable)

    response = client.post(
        "/v1/reports",
        json={"point": {"lat": 25.033, "lng": 121.5654}, "summary": "Water over curb."},
    )

    assert response.status_code == 503
    payload = response.json()
    assert_error_envelope(payload)
    assert payload["error"]["code"] == "repository_unavailable"
