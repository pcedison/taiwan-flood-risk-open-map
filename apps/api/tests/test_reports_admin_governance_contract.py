from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from app.api.routes import admin as admin_route
from app.core.config import get_settings
from app.domain.reports import (
    UserReportModerationRecord,
    UserReportPrivacyRedactionRecord,
    UserReportRepositoryUnavailable,
)
from app.main import create_app


def _client_with_admin_token(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    return TestClient(create_app())


def _pending_report() -> UserReportModerationRecord:
    return UserReportModerationRecord(
        id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        status="pending",
        summary="Water at ankle depth.",
        lat=25.033,
        lng=121.5654,
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        reviewed_at=None,
    )


def _approved_report() -> UserReportModerationRecord:
    return UserReportModerationRecord(
        id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        status="approved",
        summary="Water at ankle depth.",
        lat=25.033,
        lng=121.5654,
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        reviewed_at=datetime(2026, 4, 29, 12, 5, tzinfo=UTC),
    )


def test_user_reports_feature_flag_defaults_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USER_REPORTS_ENABLED", raising=False)
    get_settings.cache_clear()

    assert get_settings().user_reports_enabled is False


def test_user_report_rate_limit_defaults_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USER_REPORTS_RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("USER_REPORTS_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("USER_REPORTS_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.user_reports_rate_limit_enabled is True
    assert settings.user_reports_rate_limit_backend == "redis"
    assert settings.user_reports_rate_limit_max_requests == 5
    assert settings.user_reports_rate_limit_window_seconds == 60


def test_user_report_rate_limit_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_REPORTS_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("USER_REPORTS_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("USER_REPORTS_RATE_LIMIT_MAX_REQUESTS", "2")
    monkeypatch.setenv("USER_REPORTS_RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("USER_REPORTS_RATE_LIMIT_CLIENT_HEADER", "x-forwarded-for")
    monkeypatch.setenv("ABUSE_HASH_SALT", "test-abuse-salt")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.user_reports_rate_limit_enabled is False
    assert settings.user_reports_rate_limit_backend == "memory"
    assert settings.user_reports_rate_limit_max_requests == 2
    assert settings.user_reports_rate_limit_window_seconds == 30
    assert settings.user_reports_rate_limit_client_header == "x-forwarded-for"
    assert settings.abuse_hash_salt == "test-abuse-salt"


def test_user_report_challenge_defaults_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USER_REPORTS_CHALLENGE_REQUIRED", raising=False)
    monkeypatch.delenv("USER_REPORTS_CHALLENGE_PROVIDER", raising=False)
    monkeypatch.delenv("USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.user_reports_challenge_required is False
    assert settings.user_reports_challenge_provider == "turnstile"
    assert settings.user_reports_challenge_timeout_seconds == 2.0
    assert settings.user_reports_challenge_non_production_bypass is False


def test_user_report_challenge_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_REQUIRED", "true")
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_PROVIDER", "static")
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_SECRET_KEY", "secret")
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_STATIC_TOKEN", "sandbox-token")
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_VERIFY_URL", "https://example.test/verify")
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("USER_REPORTS_CHALLENGE_NON_PRODUCTION_BYPASS", "true")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.user_reports_challenge_required is True
    assert settings.user_reports_challenge_provider == "static"
    assert settings.user_reports_challenge_secret_key == "secret"
    assert settings.user_reports_challenge_static_token == "sandbox-token"
    assert settings.user_reports_challenge_verify_url == "https://example.test/verify"
    assert settings.user_reports_challenge_timeout_seconds == 1.5
    assert settings.user_reports_challenge_non_production_bypass is True


def test_pending_report_admin_endpoint_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_admin_token(monkeypatch)

    response = client.get("/admin/v1/reports/pending")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_pending_report_admin_endpoint_returns_403_when_admin_token_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_BEARER_TOKEN", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get(
        "/admin/v1/reports/pending",
        headers={"Authorization": "Bearer any-token"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_pending_report_admin_endpoint_does_not_expose_private_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER_REPORTS_ENABLED", "false")
    client = _client_with_admin_token(monkeypatch)

    def list_reports(**_kwargs: object) -> list[UserReportModerationRecord]:
        return [_pending_report()]

    monkeypatch.setattr(admin_route, "list_pending_user_reports", list_reports)

    response = client.get(
        "/admin/v1/reports/pending",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    assert get_settings().user_reports_enabled is False
    payload = response.json()
    report = payload["reports"][0]
    assert set(report) == {"report_id", "status", "point", "summary", "created_at", "reviewed_at"}
    assert "email" not in report
    assert "media" not in report
    assert "media_ref" not in report
    assert "private_fields" not in report


def test_pending_report_admin_endpoint_returns_503_when_repository_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)

    def unavailable(**_kwargs: object) -> list[UserReportModerationRecord]:
        raise UserReportRepositoryUnavailable("database unavailable")

    monkeypatch.setattr(admin_route, "list_pending_user_reports", unavailable)

    response = client.get(
        "/admin/v1/reports/pending",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "repository_unavailable"


def test_moderation_endpoint_limits_status_and_reason_before_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)
    called = False

    def moderate_report(**_kwargs: object) -> UserReportModerationRecord:
        nonlocal called
        called = True
        raise AssertionError("moderation repository should not be called")

    monkeypatch.setattr(admin_route, "moderate_user_report", moderate_report)

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


def test_moderation_endpoint_returns_404_for_missing_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)

    def missing(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(admin_route, "moderate_user_report", missing)

    response = client.patch(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/moderation",
        json={"status": "rejected", "reason_code": "not_flood_related"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_moderation_endpoint_returns_redacted_report_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER_REPORTS_ENABLED", "false")
    client = _client_with_admin_token(monkeypatch)

    def moderate_report(**_kwargs: object) -> UserReportModerationRecord:
        return _approved_report()

    monkeypatch.setattr(admin_route, "moderate_user_report", moderate_report)

    response = client.patch(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/moderation",
        json={"status": "approved", "reason_code": "verified_flood_signal"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    assert get_settings().user_reports_enabled is False
    report = response.json()["report"]
    assert set(report) == {"report_id", "status", "point", "summary", "created_at", "reviewed_at"}
    assert report["status"] == "approved"
    assert "email" not in report
    assert "media" not in report
    assert "media_ref" not in report
    assert "private_fields" not in report


def test_privacy_redaction_endpoint_uses_repository_and_returns_tombstone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)
    called: list[dict[str, object]] = []
    redacted_at = datetime(2026, 4, 29, 12, 10, tzinfo=UTC)

    def redact_report(**kwargs: object) -> UserReportPrivacyRedactionRecord:
        called.append(kwargs)
        return UserReportPrivacyRedactionRecord(
            id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            status="deleted",
            privacy_level="redacted",
            redacted_at=redacted_at,
        )

    monkeypatch.setattr(admin_route, "redact_user_report_privacy", redact_report)

    response = client.post(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/privacy-redaction",
        json={"reason_code": "reporter_request"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    assert called == [
        {
            "database_url": get_settings().database_url,
            "report_id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            "reason_code": "reporter_request",
            "actor_ref": "admin_api",
        }
    ]
    redaction = response.json()["redaction"]
    assert redaction == {
        "report_id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        "status": "deleted",
        "privacy_level": "redacted",
        "redacted_at": "2026-04-29T12:10:00Z",
    }
    assert "summary" not in redaction
    assert "point" not in redaction
    assert "media_ref" not in redaction


def test_privacy_redaction_endpoint_rejects_invalid_reason_before_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)
    called = False

    def redact_report(**_kwargs: object) -> UserReportPrivacyRedactionRecord:
        nonlocal called
        called = True
        raise AssertionError("redaction repository should not be called")

    monkeypatch.setattr(admin_route, "redact_user_report_privacy", redact_report)

    response = client.post(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/privacy-redaction",
        json={"reason_code": "not_a_reason"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    assert called is False


def test_privacy_redaction_endpoint_returns_404_for_missing_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)

    def missing(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(admin_route, "redact_user_report_privacy", missing)

    response = client.post(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/privacy-redaction",
        json={"reason_code": "reporter_request"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_privacy_redaction_endpoint_returns_503_when_repository_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_admin_token(monkeypatch)

    def unavailable(**_kwargs: object) -> UserReportPrivacyRedactionRecord:
        raise UserReportRepositoryUnavailable("database unavailable")

    monkeypatch.setattr(admin_route, "redact_user_report_privacy", unavailable)

    response = client.post(
        "/admin/v1/reports/0d51d545-dc6a-4e4b-8f8e-0e42d454d050/privacy-redaction",
        json={"reason_code": "reporter_request"},
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "repository_unavailable"
