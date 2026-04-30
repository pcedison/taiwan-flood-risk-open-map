from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.adapters.contracts import DataSourceAdapter
from app.config import WorkerSettings
from app.jobs.official_demo import build_official_demo_adapters
from app.logging import log_event


def build_runtime_adapters(
    settings: WorkerSettings,
    *,
    fetched_at: datetime | None = None,
) -> Mapping[str, DataSourceAdapter]:
    if not settings.runtime_fixtures_enabled:
        log_event(
            "runtime.adapters.noop",
            reason="fixture_runtime_disabled",
            enabled_adapter_keys=settings.enabled_adapter_keys,
        )
        return {}

    adapters = build_official_demo_adapters(fetched_at=fetched_at or datetime.now(UTC))
    log_event(
        "runtime.adapters.fixture_mode.enabled",
        available_adapter_keys=tuple(adapters),
    )
    return adapters
