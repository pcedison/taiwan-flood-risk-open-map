from __future__ import annotations

from collections.abc import Iterable

from app.logging import log_event


def run_sample_job(
    job_key: str = "sample.healthcheck",
    *,
    enabled_adapters: Iterable[str] = (),
) -> None:
    log_event(
        "job.completed",
        job_key=job_key,
        adapter_key="placeholder",
        status="success",
        enabled_adapters=tuple(enabled_adapters),
        items_fetched=0,
        items_promoted=0,
        items_rejected=0,
    )
