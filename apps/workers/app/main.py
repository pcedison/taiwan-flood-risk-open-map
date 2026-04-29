from __future__ import annotations

import argparse
import time

from app.adapters.registry import enabled_adapter_keys
from app.config import load_worker_settings
from app.jobs.sample import run_sample_job
from app.logging import log_event


def main() -> int:
    parser = argparse.ArgumentParser(description="Flood Risk worker runtime")
    parser.add_argument("--once", action="store_true", help="Run one sample job and exit.")
    parser.add_argument(
        "--list-adapters",
        action="store_true",
        help="Print enabled adapter keys and exit.",
    )
    args = parser.parse_args()
    settings = load_worker_settings()

    if args.list_adapters:
        for adapter_key in enabled_adapter_keys(settings):
            print(adapter_key)
        return 0

    if args.once:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        return 0

    log_event("worker.started", mode="placeholder", enabled_adapters=enabled_adapter_keys(settings))
    while True:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        time.sleep(settings.worker_idle_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
