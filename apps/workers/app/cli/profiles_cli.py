"""Precomputed risk-profile CLI commands: seed, rebuild, and refresh-job worker."""

from __future__ import annotations

import json
import time

from app.config import WorkerSettings
from app.jobs.profiles import (
    ProfileRefreshJobUnavailable,
    claim_profile_refresh_jobs,
    complete_profile_refresh_job,
    rebuild_risk_profile,
    seed_admin_area_profiles_from_geocoder,
    seed_grid_profiles_from_query_heat,
)
from app.logging import log_event


def seed_risk_profiles(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    profile_kind: str,
    source_key: str,
    limit: int | None,
    grid_system: str,
    grid_resolution: str,
    include_privacy_bucket_fallback: bool,
    enqueue_refresh: bool,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if limit is not None and limit < 1:
        log_event("profiles.seed.failed", error="profile seed limit must be positive")
        return 1
    if not resolved_database_url:
        log_event("profiles.seed.noop", reason="no_database_url")
        return 0

    summaries = []
    try:
        if profile_kind in {"admin_area", "all"}:
            summaries.append(
                seed_admin_area_profiles_from_geocoder(
                    database_url=resolved_database_url,
                    source_key=source_key,
                    limit=limit,
                    enqueue_refresh=enqueue_refresh,
                )
            )
        if profile_kind in {"risk_grid", "all"}:
            summaries.append(
                seed_grid_profiles_from_query_heat(
                    database_url=resolved_database_url,
                    grid_system=grid_system,
                    grid_resolution=grid_resolution,
                    limit=limit,
                    include_privacy_bucket_fallback=include_privacy_bucket_fallback,
                    enqueue_refresh=enqueue_refresh,
                )
            )
    except (ProfileRefreshJobUnavailable, ValueError) as exc:
        log_event("profiles.seed.failed", error=str(exc))
        return 1

    payload = {
        "profile_seed": [
            {
                "profile_kind": summary.profile_kind,
                "seeded": summary.seeded,
                "refresh_jobs_enqueued": summary.refresh_jobs_enqueued,
                "source": summary.source,
            }
            for summary in summaries
        ]
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    log_event("profiles.seed.completed", summaries=payload["profile_seed"])
    return 0


def rebuild_one_risk_profile(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    profile_kind: str | None,
    profile_key: str | None,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if not resolved_database_url:
        log_event("profiles.rebuild.noop", reason="no_database_url")
        return 0
    if not profile_kind or not profile_key:
        log_event("profiles.rebuild.failed", error="--profile-kind and --profile-key are required")
        return 1

    try:
        summary = rebuild_risk_profile(
            database_url=resolved_database_url,
            profile_kind=profile_kind,
            profile_key=profile_key,
        )
    except (ProfileRefreshJobUnavailable, ValueError) as exc:
        log_event("profiles.rebuild.failed", error=str(exc))
        return 1

    if summary is None:
        print(
            json.dumps(
                {
                    "profile_rebuild": {
                        "profile_kind": profile_kind,
                        "profile_key": profile_key,
                        "status": "missing",
                    }
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "profile_rebuild": {
                    "profile_kind": summary.profile_kind,
                    "profile_key": summary.profile_key,
                    "evidence_count": summary.evidence_count,
                    "top_evidence_ids": summary.top_evidence_ids,
                    "realtime_level": summary.realtime_level,
                    "historical_level": summary.historical_level,
                    "confidence_level": summary.confidence_level,
                    "computed_at": summary.computed_at.isoformat(),
                    "status": "succeeded",
                }
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def work_profile_refresh_jobs(
    *,
    settings: WorkerSettings,
    database_url: str | None,
    worker_id: str | None,
    limit: int,
    lease_seconds: int,
    statement_timeout_ms: int,
    cooldown_seconds: int,
) -> int:
    resolved_database_url = database_url or settings.database_url
    if limit < 1:
        log_event("profiles.refresh.failed", error="profile refresh limit must be positive")
        return 1
    if lease_seconds < 1:
        log_event("profiles.refresh.failed", error="profile refresh lease seconds must be positive")
        return 1
    if statement_timeout_ms < 1:
        log_event("profiles.refresh.failed", error="profile refresh statement timeout must be positive")
        return 1
    if cooldown_seconds < 0:
        log_event("profiles.refresh.failed", error="profile refresh cooldown cannot be negative")
        return 1
    if not resolved_database_url:
        log_event("profiles.refresh.noop", reason="no_database_url")
        return 0

    resolved_worker_id = worker_id or f"profile-worker:{settings.metrics_instance}"
    try:
        jobs = claim_profile_refresh_jobs(
            database_url=resolved_database_url,
            worker_id=resolved_worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
        )
    except ProfileRefreshJobUnavailable as exc:
        log_event("profiles.refresh.claim_failed", error=str(exc))
        return 1

    results: list[dict[str, object]] = []
    for index, job in enumerate(jobs):
        if index > 0 and cooldown_seconds > 0:
            time.sleep(cooldown_seconds)
        try:
            summary = rebuild_risk_profile(
                database_url=resolved_database_url,
                profile_kind=job.profile_kind,
                profile_key=job.profile_key,
                statement_timeout_ms=statement_timeout_ms,
            )
            if summary is None:
                complete_profile_refresh_job(
                    database_url=resolved_database_url,
                    job_id=job.id,
                    status="skipped",
                    error_message=None,
                )
                results.append(
                    {
                        "job_id": job.id,
                        "profile_kind": job.profile_kind,
                        "profile_key": job.profile_key,
                        "status": "skipped",
                        "reason": "profile_missing",
                    }
                )
                continue
            complete_profile_refresh_job(
                database_url=resolved_database_url,
                job_id=job.id,
                status="succeeded",
                error_message=None,
            )
            results.append(
                {
                    "job_id": job.id,
                    "profile_kind": summary.profile_kind,
                    "profile_key": summary.profile_key,
                    "status": "succeeded",
                    "evidence_count": summary.evidence_count,
                    "historical_level": summary.historical_level,
                    "realtime_level": summary.realtime_level,
                }
            )
        except (ProfileRefreshJobUnavailable, ValueError) as exc:
            error_message = str(exc)
            try:
                complete_profile_refresh_job(
                    database_url=resolved_database_url,
                    job_id=job.id,
                    status="failed",
                    error_message=error_message,
                )
            except ProfileRefreshJobUnavailable:
                pass
            results.append(
                {
                    "job_id": job.id,
                    "profile_kind": job.profile_kind,
                    "profile_key": job.profile_key,
                    "status": "failed",
                    "error": error_message,
                }
            )
            if _is_transient_profile_refresh_database_error(error_message):
                log_event(
                    "profiles.refresh.aborted",
                    reason="transient_database_error",
                    error=error_message,
                    processed_jobs=len(results),
                    claimed_jobs=len(jobs),
                )
                break

    print(json.dumps({"profile_refresh_jobs": results}, ensure_ascii=False, sort_keys=True))
    return 1 if any(result["status"] == "failed" for result in results) else 0


def _is_transient_profile_refresh_database_error(error_message: str) -> bool:
    normalized = error_message.casefold()
    if "statement timeout" in normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "administrator command",
            "connection timeout expired",
            "connection refused",
            "could not connect",
            "server closed the connection",
            "terminating connection",
            "connection is closed",
            "ssl syscall",
            "eof detected",
        )
    )
