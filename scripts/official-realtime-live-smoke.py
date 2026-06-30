#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKERS_APP = ROOT / "apps" / "workers"
sys.path.insert(0, str(WORKERS_APP))

from app.ops.official_realtime_live_smoke import (  # noqa: E402
    OfficialRealtimeSmokeResult,
    load_env_file,
    run_official_realtime_live_smoke,
)


EVIDENCE_SCHEMA_VERSION = "official-realtime-live-smoke/v1"


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
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument(
        "--evidence-output",
        help="Optional UTF-8 JSON evidence artifact path for this live smoke run.",
    )
    args = parser.parse_args()

    env = load_env_file(Path(args.env_file), base_env=os.environ)
    result = run_official_realtime_live_smoke(
        env=env,
        timeout_seconds=max(1, args.timeout_seconds),
    )
    print(result.to_json())
    _write_evidence(
        args.evidence_output,
        result=result,
        captured_at=args.captured_at
        or datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    if not result.healthy:
        return 1
    if args.fail_on_skipped and any(item.status == "skipped" for item in result.results):
        return 1
    return 0


def _write_evidence(
    output_path: str | None,
    *,
    result: OfficialRealtimeSmokeResult,
    captured_at: str,
) -> None:
    if output_path is None:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "result": result.to_dict(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
