from __future__ import annotations

import argparse
import os
import time

from app.jobs.sample import run_sample_job
from app.logging import log_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Flood Risk worker runtime")
    parser.add_argument("--once", action="store_true", help="Run one sample job and exit.")
    args = parser.parse_args()

    if args.once:
        run_sample_job()
        return 0

    log_event("worker.started", mode="placeholder")
    idle_seconds = int(os.getenv("WORKER_IDLE_SECONDS", "60"))
    while True:
        run_sample_job()
        time.sleep(idle_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
