from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://floodrisk.cc"
DEFAULT_ADMIN_TOKEN_ENV = "ADMIN_BEARER_TOKEN"
DEFAULT_REQUIRED_ADAPTER_KEYS = (
    "official.cwa.rainfall",
    "official.wra.water_level",
)
EVIDENCE_SCHEMA_VERSION = "hosted-source-freshness-smoke/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
HOSTED_WORKER_GATE_KEY = "hosted_worker_persisted_evidence"
HOSTED_WORKER_REQUIREMENTS = [
    "freshness_policy",
    "worker_persisted_evidence_path",
]
ACCEPTABLE_HEALTH_STATUSES = {"healthy", "degraded"}
ACCEPTABLE_FRESHNESS_STATES = {"fresh", "degraded"}
REQUIRED_SOURCE_GATE = "data_sources.is_enabled"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hosted source freshness smoke: verify /admin/v1/sources exposes "
            "fresh worker-persisted official realtime source diagnostics."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--admin-token-env", default=DEFAULT_ADMIN_TOKEN_ENV)
    parser.add_argument(
        "--required-adapter-key",
        action="append",
        dest="required_adapter_keys",
        help=(
            "Required adapter key returned by /admin/v1/sources. Defaults to "
            "official.cwa.rainfall and official.wra.water_level when omitted."
        ),
    )
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--evidence-output",
        help="Optional JSON file capturing the hosted source freshness smoke result.",
    )
    parser.add_argument(
        "--completion-evidence-output",
        help=(
            "Optional local-source-completion-evidence/v1 JSON overlay containing "
            "only the hosted_worker_persisted_evidence requirements proven by "
            "/admin/v1/sources."
        ),
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    required_adapter_keys = tuple(args.required_adapter_keys or DEFAULT_REQUIRED_ADAPTER_KEYS)
    failures: list[str] = []

    admin_token = os.environ.get(args.admin_token_env)
    if not admin_token:
        failures.append(
            f"{args.admin_token_env} is not set; cannot call /admin/v1/sources"
        )

    health = request_json("GET", f"{base_url}/health", timeout_seconds=args.timeout_seconds)
    health_evidence = {
        "status_code": health.status_code,
        "service": health.payload.get("service"),
        "version": health.payload.get("version"),
        "deployment_sha": health.payload.get("deployment_sha"),
    }
    if health.status_code != 200:
        failures.append(f"/health returned HTTP {health.status_code}: {health.error or health.payload}")
    elif not health.payload.get("deployment_sha"):
        failures.append("/health did not expose deployment_sha")
    else:
        print(
            "PASS health | "
            f"version={health.payload.get('version')} | "
            f"deployment_sha={health.payload.get('deployment_sha')}"
        )

    sources_payload: dict[str, Any] = {}
    if admin_token:
        sources = request_json(
            "GET",
            f"{base_url}/admin/v1/sources",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout_seconds=args.timeout_seconds,
        )
        sources_payload = sources.payload
        if sources.status_code != 200:
            failures.append(
                f"/admin/v1/sources returned HTTP {sources.status_code}: "
                f"{sources.error or sources.payload}"
            )
        else:
            failures.extend(
                check_sources(sources_payload, required_adapter_keys=required_adapter_keys)
            )

    status = "failed" if failures else "passed"
    artifact = build_evidence_artifact(
        base_url=base_url,
        captured_at=captured_at,
        status=status,
        health=health_evidence,
        required_adapter_keys=required_adapter_keys,
        sources_payload=sources_payload,
        failures=failures,
    )
    _write_json(args.evidence_output, artifact)

    if failures:
        print("HOSTED_SOURCE_FRESHNESS_SMOKE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                evidence_ref=args.evidence_output
                or _default_completion_evidence_ref(base_url, health_evidence),
            ),
        )

    print(
        "HOSTED_SOURCE_FRESHNESS_SMOKE passed | "
        f"sources={','.join(required_adapter_keys)}"
    )
    return 0


def check_sources(
    payload: Mapping[str, Any],
    *,
    required_adapter_keys: Sequence[str],
) -> list[str]:
    failures: list[str] = []
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return ["/admin/v1/sources response missing sources array"]

    by_adapter_key = {
        str(source.get("adapter_key")): source
        for source in sources
        if isinstance(source, Mapping) and source.get("adapter_key")
    }
    for adapter_key in required_adapter_keys:
        source = by_adapter_key.get(adapter_key)
        if source is None:
            failures.append(f"required source {adapter_key} was not returned by /admin/v1/sources")
            continue
        failures.extend(_check_required_source(adapter_key, source))
    return failures


def build_evidence_artifact(
    *,
    base_url: str,
    captured_at: str,
    status: str,
    health: Mapping[str, Any],
    required_adapter_keys: Sequence[str],
    sources_payload: Mapping[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "base_url": base_url,
        "status": status,
        "health": dict(health),
        "required_adapter_keys": list(required_adapter_keys),
        "checked_sources": _checked_source_summaries(
            sources_payload,
            required_adapter_keys=required_adapter_keys,
        ),
        "completion_evidence_targets": [
            {
                "gate_key": HOSTED_WORKER_GATE_KEY,
                "status": "accepted",
                "satisfied_requirements": HOSTED_WORKER_REQUIREMENTS,
            }
        ],
        "failures": failures,
    }


def build_completion_evidence_overlay(
    *,
    captured_at: str,
    evidence_ref: str,
) -> dict[str, Any]:
    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "signal_family_gap_evidence": [],
        "source_contract_evidence": [],
        "production_gate_evidence": [
            {
                "gate_key": HOSTED_WORKER_GATE_KEY,
                "status": "accepted",
                "evidence_ref": evidence_ref,
                "satisfied_requirements": HOSTED_WORKER_REQUIREMENTS,
            }
        ],
    }


def _check_required_source(adapter_key: str, source: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if source.get("is_enabled") is not True:
        failures.append(f"required source {adapter_key} is not enabled")

    health_status = source.get("health_status")
    if health_status not in ACCEPTABLE_HEALTH_STATUSES:
        failures.append(f"required source {adapter_key} health_status is {health_status}")

    freshness_state = source.get("freshness_state")
    if freshness_state not in ACCEPTABLE_FRESHNESS_STATES:
        failures.append(f"required source {adapter_key} freshness_state is {freshness_state}")

    if not _non_empty_string(source.get("latest_observed_at")):
        failures.append(f"required source {adapter_key} missing latest_observed_at")
    if not _non_empty_string(source.get("latest_ingested_at")):
        failures.append(f"required source {adapter_key} missing latest_ingested_at")

    row_count = source.get("row_count")
    if not isinstance(row_count, int) or row_count <= 0:
        failures.append(f"required source {adapter_key} row_count must be greater than 0")

    lag_seconds = source.get("lag_seconds")
    if not isinstance(lag_seconds, int) or lag_seconds < 0:
        failures.append(f"required source {adapter_key} lag_seconds must be a non-negative integer")

    enabled_gates = source.get("enabled_gates")
    if not isinstance(enabled_gates, list) or REQUIRED_SOURCE_GATE not in enabled_gates:
        failures.append(f"required source {adapter_key} missing {REQUIRED_SOURCE_GATE} gate")
    return failures


def _checked_source_summaries(
    payload: Mapping[str, Any],
    *,
    required_adapter_keys: Sequence[str],
) -> list[dict[str, Any]]:
    sources = payload.get("sources")
    if not isinstance(sources, list):
        return []
    by_adapter_key = {
        str(source.get("adapter_key")): source
        for source in sources
        if isinstance(source, Mapping) and source.get("adapter_key")
    }
    summaries: list[dict[str, Any]] = []
    for adapter_key in required_adapter_keys:
        source = by_adapter_key.get(adapter_key)
        if not isinstance(source, Mapping):
            continue
        summaries.append(
            {
                "adapter_key": source.get("adapter_key"),
                "health_status": source.get("health_status"),
                "freshness_state": source.get("freshness_state"),
                "row_count": source.get("row_count"),
                "lag_seconds": source.get("lag_seconds"),
                "latest_observed_at": source.get("latest_observed_at"),
                "latest_ingested_at": source.get("latest_ingested_at"),
                "enabled_gates": source.get("enabled_gates") or [],
            }
        )
    return summaries


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _default_completion_evidence_ref(base_url: str, health: Mapping[str, Any]) -> str:
    deployment_sha = health.get("deployment_sha") or "unknown-sha"
    return f"{base_url}/admin/v1/sources#{deployment_sha}"


def _write_json(output_path: str | None, payload: Mapping[str, Any]) -> None:
    if output_path is None:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class JsonResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any],
        error: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.error = error


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
) -> JsonResponse:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return JsonResponse(
                status_code=response.status,
                payload=json.loads(response.read().decode("utf-8")),
            )
    except HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            error_payload = {}
        return JsonResponse(status_code=exc.code, payload=error_payload, error=str(exc))
    except (TimeoutError, URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return JsonResponse(status_code=0, payload={}, error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
