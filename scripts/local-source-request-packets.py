#!/usr/bin/env python3
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
API_APP = ROOT / "apps" / "api"
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)
from app.domain.realtime.local_source_request_packets import (  # noqa: E402
    build_completion_evidence_template,
    build_official_request_packets,
    build_signal_gap_dispatch_evidence_template,
    build_signal_gap_request_batches,
    render_official_request_packets_markdown,
    render_signal_gap_request_batches_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate official request packets for unresolved local realtime water sources."
    )
    parser.add_argument(
        "--format",
        choices=(
            "markdown",
            "json",
            "evidence-template",
            "signal-gap-batches-json",
            "signal-gap-batches-markdown",
            "signal-gap-dispatch-evidence",
        ),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    parser.add_argument(
        "--county",
        action="append",
        dest="counties",
        help="Only include the given county/city. Repeatable.",
    )
    parser.add_argument(
        "--signal-type",
        action="append",
        dest="signal_types",
        help=(
            "Only include packets whose target signal types contain this value. "
            "Repeatable."
        ),
    )
    parser.add_argument(
        "--output",
        help="Optional output file. When omitted, content is written to stdout.",
    )
    parser.add_argument(
        "--dispatch-evidence-ref",
        help=(
            "Private evidence ref proving the official request dispatch. "
            "Required for signal-gap-dispatch-evidence."
        ),
    )
    parser.add_argument(
        "--dispatched-at",
        help=(
            "ISO-8601 dispatch timestamp. Required for "
            "signal-gap-dispatch-evidence."
        ),
    )
    args = parser.parse_args()

    plan = build_local_source_action_plan(list_local_source_coverage())
    if args.format in {
        "signal-gap-batches-json",
        "signal-gap-batches-markdown",
        "signal-gap-dispatch-evidence",
    }:
        batches = build_signal_gap_request_batches(
            plan,
            signal_types=set(args.signal_types) if args.signal_types else None,
        )
        if args.format == "signal-gap-dispatch-evidence":
            if not args.dispatch_evidence_ref:
                parser.error(
                    "--dispatch-evidence-ref is required for "
                    "signal-gap-dispatch-evidence"
                )
            if not args.dispatched_at:
                parser.error(
                    "--dispatched-at is required for signal-gap-dispatch-evidence"
                )
            template = build_signal_gap_dispatch_evidence_template(
                batches,
                dispatch_evidence_ref=args.dispatch_evidence_ref,
                dispatched_at=args.dispatched_at,
            )
            content = json.dumps(template, ensure_ascii=False, indent=2) + "\n"
            return _write_output(content, args.output)
        content = (
            json.dumps(list(batches), ensure_ascii=False, indent=2) + "\n"
            if args.format == "signal-gap-batches-json"
            else render_signal_gap_request_batches_markdown(batches)
        )
        return _write_output(content, args.output)

    packets = build_official_request_packets(
        plan,
        counties=set(args.counties) if args.counties else None,
        signal_types=set(args.signal_types) if args.signal_types else None,
    )

    content = _render_output(packets, output_format=args.format)
    return _write_output(content, args.output)


def _write_output(content: str, output: str | None) -> int:
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        print(f"Wrote {output_path}", file=sys.stderr)
        return 0
    print(content, end="")
    return 0


def _render_output(
    packets: tuple[dict[str, object], ...],
    *,
    output_format: str,
) -> str:
    if output_format == "json":
        return json.dumps(list(packets), ensure_ascii=False, indent=2) + "\n"
    if output_format == "evidence-template":
        template = build_completion_evidence_template(packets)
        return json.dumps(template, ensure_ascii=False, indent=2) + "\n"
    return render_official_request_packets_markdown(packets)


if __name__ == "__main__":
    raise SystemExit(main())
