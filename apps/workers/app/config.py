from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class WorkerSettings:
    source_cwa_enabled: bool | None
    source_wra_enabled: bool | None
    source_flood_potential_enabled: bool | None
    source_news_enabled: bool
    source_forum_enabled: bool
    source_ptt_enabled: bool
    source_dcard_enabled: bool
    source_terms_review_ack: bool
    source_sample_data_enabled: bool
    worker_idle_seconds: int
    scheduler_interval_seconds: int


def load_worker_settings(env: Mapping[str, str] | None = None) -> WorkerSettings:
    values = env if env is not None else os.environ
    return WorkerSettings(
        source_cwa_enabled=env_bool(values, "SOURCE_CWA_ENABLED"),
        source_wra_enabled=env_bool(values, "SOURCE_WRA_ENABLED"),
        source_flood_potential_enabled=env_bool(values, "SOURCE_FLOOD_POTENTIAL_ENABLED"),
        source_news_enabled=env_flag(values, "SOURCE_NEWS_ENABLED"),
        source_forum_enabled=env_flag(values, "SOURCE_FORUM_ENABLED"),
        source_ptt_enabled=env_flag(values, "SOURCE_PTT_ENABLED"),
        source_dcard_enabled=env_flag(values, "SOURCE_DCARD_ENABLED"),
        source_terms_review_ack=env_flag(values, "SOURCE_TERMS_REVIEW_ACK"),
        source_sample_data_enabled=env_flag(values, "SOURCE_SAMPLE_DATA_ENABLED"),
        worker_idle_seconds=env_int(values, "WORKER_IDLE_SECONDS", default=60),
        scheduler_interval_seconds=env_int(values, "SCHEDULER_INTERVAL_SECONDS", default=300),
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
