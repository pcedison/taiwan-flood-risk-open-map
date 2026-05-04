from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from types import TracebackType
from typing import Literal, Protocol, Self, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen


UserReportChallengeProvider = Literal["turnstile", "static"]
DEFAULT_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class UserReportChallengeFailed(RuntimeError):
    def __init__(self, *, error_codes: tuple[str, ...] = ()) -> None:
        super().__init__("user report challenge verification failed")
        self.error_codes = error_codes


class UserReportChallengeUnavailable(RuntimeError):
    """Raised when the configured challenge provider cannot verify submissions."""


class UserReportChallengeVerifier(Protocol):
    def verify(self, *, token: str, remote_ip: str | None = None) -> None:
        """Raise when a challenge token is invalid or cannot be verified."""


class UserReportChallengeHttpResponse(Protocol):
    def __enter__(self) -> Self:
        """Enter response context."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit response context."""

    def read(self) -> bytes:
        """Read response body bytes."""


ChallengeOpener = Callable[..., UserReportChallengeHttpResponse]


@dataclass(frozen=True)
class StaticUserReportChallengeVerifier:
    expected_token: str | None

    def verify(self, *, token: str, remote_ip: str | None = None) -> None:
        del remote_ip
        if not self.expected_token:
            raise UserReportChallengeUnavailable("static challenge token is not configured")
        if token != self.expected_token:
            raise UserReportChallengeFailed(error_codes=("invalid-input-response",))


class TurnstileUserReportChallengeVerifier:
    def __init__(
        self,
        *,
        secret_key: str | None,
        verify_url: str = DEFAULT_TURNSTILE_VERIFY_URL,
        timeout_seconds: float = 2.0,
        opener: ChallengeOpener | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._verify_url = verify_url
        self._timeout_seconds = timeout_seconds
        self._opener = opener or _urlopen_challenge_request

    def verify(self, *, token: str, remote_ip: str | None = None) -> None:
        if not self._secret_key:
            raise UserReportChallengeUnavailable("turnstile secret key is not configured")

        payload = {
            "secret": self._secret_key,
            "response": token,
        }
        if remote_ip:
            payload["remoteip"] = remote_ip

        request = Request(
            self._verify_url,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            with response:
                raw_body = response.read()
            body = json.loads(raw_body.decode("utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise UserReportChallengeUnavailable(str(exc)) from exc

        if not isinstance(body, dict):
            raise UserReportChallengeUnavailable("unexpected challenge provider response")
        if body.get("success") is True:
            return

        error_codes = body.get("error-codes", ())
        if not isinstance(error_codes, list | tuple):
            error_codes = ()
        raise UserReportChallengeFailed(
        error_codes=tuple(str(error_code) for error_code in error_codes)
    )


def _urlopen_challenge_request(
    request: Request,
    *,
    timeout: float,
) -> UserReportChallengeHttpResponse:
    return cast(UserReportChallengeHttpResponse, urlopen(request, timeout=timeout))


def build_user_report_challenge_verifier(
    *,
    provider: UserReportChallengeProvider,
    secret_key: str | None,
    static_token: str | None,
    verify_url: str,
    timeout_seconds: float,
) -> UserReportChallengeVerifier:
    if provider == "static":
        return StaticUserReportChallengeVerifier(expected_token=static_token)
    return TurnstileUserReportChallengeVerifier(
        secret_key=secret_key,
        verify_url=verify_url,
        timeout_seconds=timeout_seconds,
    )


def verify_user_report_challenge(
    *,
    token: str,
    remote_ip: str | None,
    provider: UserReportChallengeProvider,
    secret_key: str | None,
    static_token: str | None,
    verify_url: str,
    timeout_seconds: float,
    verifier: UserReportChallengeVerifier | None = None,
) -> None:
    normalized_token = token.strip()
    if not normalized_token:
        raise UserReportChallengeFailed(error_codes=("missing-input-response",))

    challenge_verifier = verifier or build_user_report_challenge_verifier(
        provider=provider,
        secret_key=secret_key,
        static_token=static_token,
        verify_url=verify_url,
        timeout_seconds=timeout_seconds,
    )
    challenge_verifier.verify(token=normalized_token, remote_ip=remote_ip)
