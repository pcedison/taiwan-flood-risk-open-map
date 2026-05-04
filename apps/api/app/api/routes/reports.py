from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request

from app.api.errors import error_payload
from app.api.schemas import UserReportCreateRequest, UserReportCreateResponse
from app.core.config import Settings, get_settings
from app.domain.reports import (
    UserReportChallengeFailed,
    UserReportChallengeUnavailable,
    UserReportRateLimitExceeded,
    UserReportRateLimitUnavailable,
    UserReportRepositoryUnavailable,
    check_user_report_intake_rate_limit,
    create_pending_user_report,
    verify_user_report_challenge,
)

router = APIRouter(prefix="/v1", tags=["Public"])


@router.post("/reports", response_model=UserReportCreateResponse, status_code=202)
async def create_user_report(
    request: UserReportCreateRequest,
    http_request: Request,
) -> UserReportCreateResponse:
    settings = get_settings()
    if not settings.user_reports_enabled:
        raise HTTPException(
            status_code=404,
            detail=error_payload(
                "feature_disabled",
                "User report intake is disabled until legal, privacy, abuse, and moderation gates are approved.",
            )["error"],
        )

    challenge_gate = _user_report_challenge_gate(settings)
    if challenge_gate == "unavailable":
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "challenge_unavailable",
                "User report intake requires a configured bot-defense challenge in hosted environments.",
            )["error"],
        )

    if challenge_gate == "required":
        if request.challenge_token is None:
            raise HTTPException(
                status_code=400,
                detail=error_payload(
                    "challenge_required",
                    "User report intake requires a valid bot-defense challenge token.",
                )["error"],
            )
        try:
            verify_user_report_challenge(
                token=request.challenge_token,
                remote_ip=_challenge_remote_ip(http_request),
                provider=settings.user_reports_challenge_provider,
                secret_key=settings.user_reports_challenge_secret_key,
                static_token=settings.user_reports_challenge_static_token,
                verify_url=settings.user_reports_challenge_verify_url,
                timeout_seconds=settings.user_reports_challenge_timeout_seconds,
            )
        except UserReportChallengeFailed as exc:
            raise HTTPException(
                status_code=403,
                detail=error_payload(
                    "challenge_failed",
                    "User report intake challenge verification failed.",
                    {"error_codes": list(exc.error_codes)},
                )["error"],
            ) from exc
        except UserReportChallengeUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=error_payload(
                    "challenge_unavailable",
                    "User report intake challenge verification is temporarily unavailable.",
                )["error"],
            ) from exc

    if settings.user_reports_rate_limit_enabled:
        try:
            check_user_report_intake_rate_limit(
                client_key=_rate_limit_client_key(http_request),
                backend=settings.user_reports_rate_limit_backend,
                redis_url=settings.redis_url,
                max_requests=settings.user_reports_rate_limit_max_requests,
                window_seconds=settings.user_reports_rate_limit_window_seconds,
            )
        except UserReportRateLimitExceeded as exc:
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(exc.retry_after_seconds)},
                detail=error_payload(
                    "rate_limited",
                    "User report intake rate limit exceeded. Try again later.",
                    {
                        "retry_after_seconds": exc.retry_after_seconds,
                        "window_seconds": exc.policy.window_seconds,
                    },
                )["error"],
            ) from exc
        except UserReportRateLimitUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=error_payload(
                    "abuse_guard_unavailable",
                    "User report intake abuse guard is temporarily unavailable.",
                )["error"],
            ) from exc

    try:
        report = create_pending_user_report(
            database_url=settings.database_url,
            lat=request.point.lat,
            lng=request.point.lng,
            summary=request.summary,
        )
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report intake is temporarily unavailable.",
            )["error"],
        ) from exc

    return UserReportCreateResponse(report_id=report.id, status="pending")


def _rate_limit_client_key(request: Request) -> str:
    settings = get_settings()
    client_signal = _client_signal(request, settings.user_reports_rate_limit_client_header)
    salt = settings.abuse_hash_salt or f"{settings.service_id}:{settings.app_env}"
    return sha256(f"user-report-intake:{salt}:{client_signal}".encode()).hexdigest()


def _client_signal(request: Request, configured_header: str | None) -> str:
    if configured_header:
        header_value = request.headers.get(configured_header)
        if header_value:
            configured_signal = header_value.split(",", 1)[0].strip()
            if configured_signal:
                return configured_signal
    if request.client is None:
        return "unknown-client"
    return request.client.host


def _challenge_remote_ip(request: Request) -> str | None:
    settings = get_settings()
    client_signal = _client_signal(request, settings.user_reports_rate_limit_client_header)
    if client_signal == "unknown-client":
        return None
    return client_signal


def _user_report_challenge_gate(settings: Settings) -> str:
    if settings.user_reports_challenge_required:
        return "required"
    if not _is_hosted_or_production_like(settings.app_env):
        return "optional"
    if _non_production_challenge_bypass_allowed(settings):
        return "optional"
    if _hosted_challenge_provider_configured(settings):
        return "required"
    return "unavailable"


def _is_hosted_or_production_like(app_env: str) -> bool:
    normalized = app_env.strip().lower().replace("_", "-")
    tokens = {token for token in normalized.split("-") if token}
    return bool(tokens & {"production", "prod", "staging", "stage", "preview", "hosted"})


def _non_production_challenge_bypass_allowed(settings: Settings) -> bool:
    if not settings.user_reports_challenge_non_production_bypass:
        return False
    normalized = settings.app_env.strip().lower().replace("_", "-")
    return normalized not in {"production", "prod"} and not normalized.startswith(
        ("production-", "prod-")
    )


def _hosted_challenge_provider_configured(settings: Settings) -> bool:
    if settings.user_reports_challenge_provider == "turnstile":
        return settings.user_reports_challenge_secret_key is not None
    return False
