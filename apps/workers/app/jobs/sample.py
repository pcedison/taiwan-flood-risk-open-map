from __future__ import annotations

from app.logging import log_event


def run_sample_job(job_key: str = "sample.healthcheck") -> None:
    log_event(
        "job.completed",
        job_key=job_key,
        adapter_key="placeholder",
        status="success",
        items_fetched=0,
        items_promoted=0,
        items_rejected=0,
    )

