from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.domain.reports import (
    InMemoryUserReportRateLimiter,
    RedisUserReportRateLimiter,
    StaticUserReportChallengeVerifier,
    TurnstileUserReportChallengeVerifier,
    UserReportChallengeFailed,
    UserReportChallengeUnavailable,
    UserReportRateLimitExceeded,
    UserReportRateLimitPolicy,
    UserReportRateLimitUnavailable,
    create_pending_user_report,
    list_pending_user_reports,
    moderate_user_report,
    redact_user_report_privacy,
    verify_user_report_challenge,
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
    assert "email" not in sql
    assert "media_ref" not in sql
    assert "private" not in sql.lower()
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
    assert "email" not in sql
    assert "media_ref" not in sql
    assert "private" not in sql.lower()
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


def test_redact_user_report_privacy_tombstones_report_and_writes_audit_log() -> None:
    redacted_at = datetime(2026, 4, 29, 12, 10, tzinfo=UTC)
    connection = _FakeConnection(
        row={
            "id": "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            "status": "deleted",
            "privacy_level": "redacted",
            "redacted_at": redacted_at,
        }
    )

    redaction = redact_user_report_privacy(
        database_url="postgresql://example.test/flood",
        report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        reason_code="private_data_exposure",
        actor_ref="admin_api",
        connection_factory=lambda: connection,
    )

    sql, params = connection.cursor_instance.executions[0]
    assert "WITH target_report AS" in sql
    assert "UPDATE user_reports" in sql
    assert "summary = '[redacted]'" in sql
    assert "media_ref = NULL" in sql
    assert "status = 'deleted'" in sql
    assert "redacted_at = now()" in sql
    assert "redaction_reason = %s" in sql
    assert "INSERT INTO audit_logs" in sql
    assert "user_report.privacy_redacted" in sql
    assert "previous_status" in sql
    assert "previous_privacy_level" in sql
    assert "media_ref_cleared" in sql
    assert params == (
        "0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        "private_data_exposure",
        "admin_api",
        "private_data_exposure",
        "admin_api",
    )
    assert redaction is not None
    assert redaction.status == "deleted"
    assert redaction.privacy_level == "redacted"
    assert redaction.redacted_at == redacted_at


def test_redact_user_report_privacy_returns_none_when_report_is_missing() -> None:
    connection = _FakeConnection(row=None)

    redaction = redact_user_report_privacy(
        database_url="postgresql://example.test/flood",
        report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
        reason_code="reporter_request",
        actor_ref="admin_api",
        connection_factory=lambda: connection,
    )

    assert redaction is None


def test_redact_user_report_privacy_rejects_invalid_reason_before_sql() -> None:
    connection = _FakeConnection(row=None)

    with pytest.raises(ValueError):
        redact_user_report_privacy(
            database_url="postgresql://example.test/flood",
            report_id="0d51d545-dc6a-4e4b-8f8e-0e42d454d050",
            reason_code=cast(Any, "not_a_reason"),
            actor_ref="admin_api",
            connection_factory=lambda: connection,
        )

    assert connection.cursor_instance.executions == []


def test_user_report_rate_limiter_allows_configured_window() -> None:
    clock = _FakeClock(100.0)
    limiter = InMemoryUserReportRateLimiter(clock=clock.now)
    policy = UserReportRateLimitPolicy(max_requests=2, window_seconds=60)

    limiter.check(client_key="client-a", policy=policy)
    limiter.check(client_key="client-a", policy=policy)

    with pytest.raises(UserReportRateLimitExceeded) as exc_info:
        limiter.check(client_key="client-a", policy=policy)

    assert exc_info.value.retry_after_seconds == 60
    assert exc_info.value.policy == policy


def test_user_report_rate_limiter_is_per_client_and_prunes_old_entries() -> None:
    clock = _FakeClock(100.0)
    limiter = InMemoryUserReportRateLimiter(clock=clock.now)
    policy = UserReportRateLimitPolicy(max_requests=1, window_seconds=60)

    limiter.check(client_key="client-a", policy=policy)
    limiter.check(client_key="client-b", policy=policy)

    clock.advance(61.0)
    limiter.check(client_key="client-a", policy=policy)


def test_redis_user_report_rate_limiter_maps_script_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis(eval_result=[0, 41000])
    monkeypatch.setattr("app.domain.reports.abuse.redis.Redis.from_url", lambda *_, **__: fake_redis)
    limiter = RedisUserReportRateLimiter(redis_url="redis://example.test:6379/0", clock=lambda: 100.0)
    policy = UserReportRateLimitPolicy(max_requests=2, window_seconds=60)

    with pytest.raises(UserReportRateLimitExceeded) as exc_info:
        limiter.check(client_key="client-a", policy=policy)

    assert exc_info.value.retry_after_seconds == 41
    assert fake_redis.closed is True
    assert fake_redis.eval_calls[0][1:4] == (
        2,
        "flood-risk:user-report-rate:client-a",
        "flood-risk:user-report-rate-seq:client-a",
    )


def test_redis_user_report_rate_limiter_fails_closed_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise redis.RedisError("redis down")

    fake_redis = _FakeRedis(eval_side_effect=unavailable)
    monkeypatch.setattr("app.domain.reports.abuse.redis.Redis.from_url", lambda *_, **__: fake_redis)
    limiter = RedisUserReportRateLimiter(redis_url="redis://example.test:6379/0", clock=lambda: 100.0)

    with pytest.raises(UserReportRateLimitUnavailable):
        limiter.check(
            client_key="client-a",
            policy=UserReportRateLimitPolicy(max_requests=2, window_seconds=60),
        )

    assert fake_redis.closed is True


def test_static_user_report_challenge_verifier_accepts_expected_token() -> None:
    verifier = StaticUserReportChallengeVerifier(expected_token="expected-token")

    verifier.verify(token="expected-token", remote_ip="127.0.0.1")


def test_static_user_report_challenge_verifier_rejects_wrong_token() -> None:
    verifier = StaticUserReportChallengeVerifier(expected_token="expected-token")

    with pytest.raises(UserReportChallengeFailed) as exc_info:
        verifier.verify(token="wrong-token", remote_ip="127.0.0.1")

    assert exc_info.value.error_codes == ("invalid-input-response",)


def test_verify_user_report_challenge_rejects_blank_token_before_provider() -> None:
    class NeverCalledVerifier:
        def verify(self, *, token: str, remote_ip: str | None = None) -> None:
            raise AssertionError("verifier should not be called for blank tokens")

    with pytest.raises(UserReportChallengeFailed) as exc_info:
        verify_user_report_challenge(
            token="   ",
            remote_ip=None,
            provider="static",
            secret_key=None,
            static_token="expected-token",
            verify_url="https://challenge.example.test/siteverify",
            timeout_seconds=0.5,
            verifier=NeverCalledVerifier(),
        )

    assert exc_info.value.error_codes == ("missing-input-response",)


def test_turnstile_user_report_challenge_verifier_maps_success_response() -> None:
    fake_response = _FakeHttpResponse({"success": True})
    verifier = TurnstileUserReportChallengeVerifier(
        secret_key="secret",
        verify_url="https://challenge.example.test/siteverify",
        timeout_seconds=0.5,
        opener=lambda *_args, **_kwargs: fake_response,
    )

    verifier.verify(token="token", remote_ip="127.0.0.1")

    assert fake_response.read_called is True


def test_turnstile_user_report_challenge_verifier_maps_failure_response() -> None:
    verifier = TurnstileUserReportChallengeVerifier(
        secret_key="secret",
        verify_url="https://challenge.example.test/siteverify",
        timeout_seconds=0.5,
        opener=lambda *_args, **_kwargs: _FakeHttpResponse(
            {"success": False, "error-codes": ["invalid-input-response"]}
        ),
    )

    with pytest.raises(UserReportChallengeFailed) as exc_info:
        verifier.verify(token="bad-token", remote_ip="127.0.0.1")

    assert exc_info.value.error_codes == ("invalid-input-response",)


def test_turnstile_user_report_challenge_verifier_fails_closed_without_secret() -> None:
    verifier = TurnstileUserReportChallengeVerifier(secret_key=None)

    with pytest.raises(UserReportChallengeUnavailable):
        verifier.verify(token="token", remote_ip="127.0.0.1")


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


class _FakeClock:
    def __init__(self, now: float) -> None:
        self._now = now

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class _FakeRedis:
    def __init__(
        self,
        *,
        eval_result: list[int] | None = None,
        eval_side_effect: object | None = None,
    ) -> None:
        self.eval_result = eval_result or [1, 0]
        self.eval_side_effect = eval_side_effect
        self.eval_calls: list[tuple[object, ...]] = []
        self.closed = False

    def eval(self, *args: object) -> list[int]:
        self.eval_calls.append(args)
        if callable(self.eval_side_effect):
            self.eval_side_effect(*args)
        return self.eval_result

    def close(self) -> None:
        self.closed = True


class _FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.read_called = False

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        import json

        self.read_called = True
        return json.dumps(self._payload).encode("utf-8")
