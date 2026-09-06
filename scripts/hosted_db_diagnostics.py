"""Capture hosted database diagnostics for latency triage.

Calls ``GET /admin/v1/db-diagnostics`` and writes the payload as a monitoring
artifact.  The hosted database has no external client access, so this is the
only way to see production table bloat, autovacuum lag, index usage and real
query plans for the risk-assessment path.

This is evidence collection, not a smoke test: it never fails the workflow on
diagnostic content.  It exits non-zero only when it was asked to collect and
genuinely could not (missing token, unreachable endpoint), and the workflow step
is expected to tolerate that too.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://floodrisk.cc"
DEFAULT_ADMIN_TOKEN_ENV = "ADMIN_BEARER_TOKEN"
DIAGNOSTICS_PATH = "/admin/v1/db-diagnostics"
EVIDENCE_SCHEMA_VERSION = "hosted-db-diagnostics/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture /admin/v1/db-diagnostics table, index, plan and statement "
            "evidence for hosted latency triage."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--admin-token-env", default=DEFAULT_ADMIN_TOKEN_ENV)
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    # Every section of the endpoint carries its own 8 s budget: three tables,
    # indexes and statements catalog reads, three EXPLAIN ANALYZE probes, and
    # the two staging sections, each of which can spend its budget on the exact
    # query and then fall back to a catalog estimate. That is about 80 s of
    # server work in the worst case, so the client has to outwait the server
    # rather than the other way round.
    parser.add_argument("--timeout-seconds", type=float, default=200.0)
    parser.add_argument(
        "--output",
        required=True,
        help="JSON file capturing the hosted database diagnostics payload.",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    admin_token = os.environ.get(args.admin_token_env)

    evidence: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "base_url": base_url,
        "path": DIAGNOSTICS_PATH,
        "status": "collected",
        "failures": [],
        "diagnostics": None,
    }

    if not admin_token:
        evidence["status"] = "skipped"
        evidence["failures"].append(
            f"{args.admin_token_env} is not set; cannot call {DIAGNOSTICS_PATH}"
        )
        write_output(args.output, evidence)
        print(f"SKIP db diagnostics | {args.admin_token_env} is not configured")
        return 1

    response = request_json(
        f"{base_url}{DIAGNOSTICS_PATH}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout_seconds=args.timeout_seconds,
    )
    evidence["status_code"] = response["status_code"]
    if response["status_code"] != 200:
        evidence["status"] = "unavailable"
        evidence["failures"].append(
            f"{DIAGNOSTICS_PATH} returned HTTP {response['status_code']}: "
            f"{response['error'] or response['payload']}"
        )
        write_output(args.output, evidence)
        print(f"FAIL db diagnostics | HTTP {response['status_code']}")
        return 1

    diagnostics = response["payload"]
    evidence["diagnostics"] = diagnostics
    evidence["summary"] = summarize(diagnostics)
    write_output(args.output, evidence)
    for line in summary_lines(evidence["summary"]):
        print(line)
    return 0


def summarize(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Reduce the payload to the numbers a triage reader looks at first."""

    tables = diagnostics.get("tables") or []
    plans = diagnostics.get("query_plans") or []
    return {
        "tables": [
            {
                "relname": table.get("relname"),
                "n_live_tup": table.get("n_live_tup"),
                "n_dead_tup": table.get("n_dead_tup"),
                "dead_tuple_ratio": table.get("dead_tuple_ratio"),
                "last_autovacuum": table.get("last_autovacuum"),
                "total_relation_size_bytes": table.get("total_relation_size_bytes"),
            }
            for table in tables
        ],
        "query_plans": [
            {
                "name": plan.get("name"),
                "status": plan.get("status"),
                "execution_time_ms": plan_execution_time_ms(plan),
            }
            for plan in plans
        ],
        "staging_status_counts": diagnostics.get("staging_status_counts") or {},
        "staging_used_by_evidence_estimate": (
            diagnostics.get("staging_used_by_evidence_estimate") or {}
        ),
        "index_count": len(diagnostics.get("indexes") or []),
        "statements_available": diagnostics.get("statements") is not None,
    }


def plan_execution_time_ms(plan: dict[str, Any]) -> float | None:
    nodes = plan.get("plan")
    if not isinstance(nodes, list) or not nodes:
        return None
    root = nodes[0]
    if not isinstance(root, dict):
        return None
    execution_time = root.get("Execution Time")
    return execution_time if isinstance(execution_time, (int, float)) else None


def summary_lines(summary: dict[str, Any]) -> list[str]:
    lines = []
    for table in summary.get("tables", []):
        lines.append(
            f"TABLE {table['relname']} | live={table['n_live_tup']} "
            f"dead={table['n_dead_tup']} dead_ratio={table['dead_tuple_ratio']} "
            f"last_autovacuum={table['last_autovacuum']}"
        )
    lines.extend(staging_status_lines(summary.get("staging_status_counts") or {}))
    lines.extend(
        staging_use_lines(summary.get("staging_used_by_evidence_estimate") or {})
    )
    for plan in summary.get("query_plans", []):
        lines.append(
            f"PLAN {plan['name']} | status={plan['status']} "
            f"execution_ms={plan['execution_time_ms']}"
        )
    return lines


def staging_status_lines(section: dict[str, Any]) -> list[str]:
    """Print the staging split, saying plainly when the numbers are estimates.

    #367 turns on which share of staging_evidence is terminal `rejected`, so a
    reader must never mistake a sampled estimate for a count.
    """

    if not section:
        return []
    status = section.get("status")
    method = section.get("method")
    rows = section.get("rows") or []
    if not rows:
        return [f"STAGING STATUS | status={status} method={method} rows=none"]
    total = sum(row.get("rows") or 0 for row in rows)
    lines = []
    for row in rows:
        count = row.get("rows") or 0
        share = f"{count / total:.1%}" if total else "n/a"
        lines.append(
            f"STAGING {row.get('validation_status')} | rows={count} share={share} "
            f"oldest={row.get('oldest')} newest={row.get('newest')} "
            f"method={method} probe={status}"
        )
    return lines


def staging_use_lines(section: dict[str, Any]) -> list[str]:
    if not section:
        return []
    return [
        f"STAGING USED BY EVIDENCE | rows={section.get('rows')} "
        f"method={section.get('method')} probe={section.get('status')} "
        f"index={section.get('index_name')}"
    ]


def write_output(output: str, evidence: dict[str, Any]) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return {
                "status_code": response.status,
                "payload": json.loads(response.read().decode("utf-8")),
                "error": None,
            }
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        return {"status_code": exc.code, "payload": payload, "error": str(exc)}
    except (TimeoutError, URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"status_code": 0, "payload": {}, "error": str(exc)}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
