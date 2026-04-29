from __future__ import annotations

import time

from app.adapters.registry import enabled_adapter_keys
from app.config import load_worker_settings
from app.jobs.sample import run_sample_job
from app.logging import log_event


def main() -> None:
    settings = load_worker_settings()
    log_event(
        "scheduler.started",
        interval_seconds=settings.scheduler_interval_seconds,
        enabled_adapters=enabled_adapter_keys(settings),
    )
    while True:
        run_sample_job(
            job_key="maintenance.placeholder",
            enabled_adapters=enabled_adapter_keys(settings),
        )
        time.sleep(settings.scheduler_interval_seconds)


if __name__ == "__main__":
    main()
