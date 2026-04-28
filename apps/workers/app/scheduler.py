from __future__ import annotations

import os
import time

from app.jobs.sample import run_sample_job
from app.logging import log_event


def main() -> None:
    interval_seconds = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "300"))
    log_event("scheduler.started", interval_seconds=interval_seconds)
    while True:
        run_sample_job(job_key="maintenance.placeholder")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()

