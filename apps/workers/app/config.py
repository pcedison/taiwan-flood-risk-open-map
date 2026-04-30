from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str | None
    source_cwa_enabled: bool | None
    source_wra_enabled: bool | None
    source_flood_potential_enabled: bool | None
    source_news_enabled: bool | None
    source_forum_enabled: bool | None
    source_ptt_enabled: bool | None
    source_dcard_enabled: bool | None
    source_terms_review_ack: bool
    source_sample_data_enabled: bool
    enabled_adapter_keys: tuple[str, ...] | None
    worker_idle_seconds: int
    scheduler_interval_seconds: int
    scheduler_max_ticks: int | None
    scheduler_lease_ttl_seconds: int
    freshness_max_age_seconds: int
    runtime_fixtures_enabled: bool
    runtime_job_lease_seconds: int
    metrics_instance: str
    worker_metrics_textfile_path: str | None
    scheduler_metrics_textfile_path: str | None


def load_worker_settings(env: Mapping[str, str] | None = None) -> WorkerSettings:
    values = env if env is not None else os.environ
    return WorkerSettings(
        database_url=env_str(values, "WORKER_DATABASE_URL") or env_str(values, "DATABASE_URL"),
        source_cwa_enabled=env_bool(values, "SOURCE_CWA_ENABLED"),
        source_wra_enabled=env_bool(values, "SOURCE_WRA_ENABLED"),
        source_flood_potential_enabled=env_bool(values, "SOURCE_FLOOD_POTENTIAL_ENABLED"),
        source_news_enabled=env_bool(values, "SOURCE_NEWS_ENABLED"),
        source_forum_enabled=env_bool(values, "SOURCE_FORUM_ENABLED"),
        source_ptt_enabled=env_bool(values, "SOURCE_PTT_ENABLED"),
        source_dcard_enabled=env_bool(values, "SOURCE_DCARD_ENABLED"),
        source_terms_review_ack=env_flag(values, "SOURCE_TERMS_REVIEW_ACK"),
        source_sample_data_enabled=env_flag(values, "SOURCE_SAMPLE_DATA_ENABLED"),
        enabled_adapter_keys=env_list(values, "WORKER_ENABLED_ADAPTER_KEYS"),
        worker_idle_seconds=env_int(values, "WORKER_IDLE_SECONDS", default=60),
        scheduler_interval_seconds=env_int(values, "SCHEDULER_INTERVAL_SECONDS", default=300),
        scheduler_max_ticks=env_optional_int(values, "SCHEDULER_MAX_TICKS"),
        scheduler_lease_ttl_seconds=env_int(
            values,
            "SCHEDULER_LEASE_TTL_SECONDS",
            default=600,
        ),
        freshness_max_age_seconds=env_int(
            values,
            "FRESHNESS_MAX_AGE_SECONDS",
            default=6 * 60 * 60,
        ),
        runtime_fixtures_enabled=env_flag(values, "WORKER_RUNTIME_FIXTURES_ENABLED"),
        runtime_job_lease_seconds=env_int(values, "WORKER_RUNTIME_JOB_LEASE_SECONDS", default=300),
        metrics_instance=(
            env_str(values, "WORKER_INSTANCE")
            or env_str(values, "HOSTNAME")
            or env_str(values, "COMPUTERNAME")
            or "local"
        ),
        worker_metrics_textfile_path=env_str(values, "WORKER_METRICS_TEXTFILE_PATH"),
        scheduler_metrics_textfile_path=env_str(values, "SCHEDULER_METRICS_TEXTFILE_PATH"),
    )


def env_bool(
    env: Mapping[str, str],
    name: str,
    *,
    default: bool | None = None,
) -> bool | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def env_flag(env: Mapping[str, str], name: str) -> bool:
    return env_bool(env, name, default=False) is True


def env_int(env: Mapping[str, str], name: str, *, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def env_optional_int(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def env_list(env: Mapping[str, str], name: str) -> tuple[str, ...] | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    values = tuple(
        dict.fromkeys(part.strip() for part in raw.replace("\n", ",").split(",") if part.strip())
    )
    return values or None


def env_str(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()
