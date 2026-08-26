#!/usr/bin/env python3
"""Render manual, public-safe official incident request packets.

The script only prints or writes text. It has no send, dispatch, login,
credential, browser, or webhook capability, and it imports no network or mail
client. Submitting a packet is always a human action performed outside this
repository.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.ops.official_incident_request_packets import (
    build_official_incident_request_packets,
    render_official_incident_request_packets_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render the fixed public-safe official incident request packets for "
            "manual human submission. This script never submits anything."
        )
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    parser.add_argument(
        "--output",
        help="Optional output file. When omitted, content is written to stdout.",
    )
    args = parser.parse_args()

    packets = build_official_incident_request_packets()
    if args.format == "json":
        content = json.dumps(_jsonable(packets), ensure_ascii=False, indent=2) + "\n"
    else:
        content = render_official_incident_request_packets_markdown(packets)
    return _write_output(content, args.output)


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_output(content: str, output: str | None) -> int:
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"Wrote {output_path}", file=sys.stderr)
        return 0
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
