import secrets

import pytest

from app.domain.reports.challenge import (
    StaticUserReportChallengeVerifier,
    UserReportChallengeFailed,
)


def test_static_verifier_rejects_mismatched_token_using_constant_time_compare(monkeypatch):
    calls: list[tuple[str, str]] = []
    original_compare_digest = secrets.compare_digest

    def recording_compare_digest(a: str, b: str) -> bool:
        calls.append((a, b))
        return original_compare_digest(a, b)

    monkeypatch.setattr(
        "app.domain.reports.challenge.secrets.compare_digest",
        recording_compare_digest,
    )

    verifier = StaticUserReportChallengeVerifier(expected_token="expected-token")

    with pytest.raises(UserReportChallengeFailed):
        verifier.verify(token="wrong-token")

    assert calls == [("wrong-token", "expected-token")]


def test_static_verifier_accepts_matching_token():
    verifier = StaticUserReportChallengeVerifier(expected_token="expected-token")

    verifier.verify(token="expected-token")
