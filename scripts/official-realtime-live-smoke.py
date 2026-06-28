#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKERS_APP = ROOT / "apps" / "workers"
sys.path.insert(0, str(WORKERS_APP))

from app.ops.official_realtime_live_smoke import (  # noqa: E402
    load_env_file,
    run_official_realtime_live_smoke,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live smoke official realtime backbone adapters."
    )
    parser.add_argument(
        "--env-file",
        default=str(ROOT / ".env"),
        help="Optional .env file to read before falling back to process environment.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=20,
        help="Per-source upstream request timeout.",
    )
    parser.add_argument(
        "--fail-on-skipped",
        action="store_true",
        help="Exit non-zero if any source is skipped, e.g. missing CWA key.",
    )
    args = parser.parse_args()

    env = load_env_file(Path(args.env_file), base_env=os.environ)
    result = run_official_realtime_live_smoke(
        env=env,
        timeout_seconds=max(1, args.timeout_seconds),
    )
    print(result.to_json())
    if not result.healthy:
        return 1
    if args.fail_on_skipped and any(item.status == "skipped" for item in result.results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
