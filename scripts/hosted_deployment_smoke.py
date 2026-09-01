from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from time import sleep
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://floodrisk.cc"
EVIDENCE_SCHEMA_VERSION = "hosted-deployment-smoke/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
DEPLOYMENT_GATE_KEY = "production_deployment_evidence"
DEPLOYMENT_REQUIREMENTS = [
    "main_branch_deployed_sha",
    "ready_dependency_smoke",
]
DEPLOYMENT_REQUIREMENT_EVIDENCE_PATHS = {
    "main_branch_deployed_sha": "/health/deployment_sha",
    "ready_dependency_smoke": "/ready/dependencies",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hosted deployment smoke: verify /health and /ready report the "
            "expected main deployment SHA, then require a healthy persisted "
            "scheduler heartbeat and complete readiness contract shape."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--expected-deployment-sha",
        required=True,
        help="Full main/merge commit SHA expected on the hosted service.",
    )
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--retry-count",
        type=int,
        default=1,
        help="Maximum deployment-smoke attempts before failing.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=0.0,
        help="Delay between failed deployment-smoke attempts.",
    )
    parser.add_argument(
        "--evidence-output",
        help="Optional JSON file capturing hosted deployment smoke evidence.",
    )
    parser.add_argument(
        "--completion-evidence-output",
        help=(
            "Optional local-source-completion-evidence/v1 JSON overlay proving "
            "the production_deployment_evidence gate only."
        ),
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    attempts = max(1, args.retry_count)
    attempt_count = 0
    failures: list[str] = []
    health = JsonResponse(status_code=0, payload={}, error="not requested")
    ready = JsonResponse(status_code=0, payload={}, error="not requested")
    ingestion_readiness = JsonResponse(status_code=0, payload={}, error="not requested")

    for attempt in range(1, attempts + 1):
        attempt_count = attempt
        failures = []
        health = request_json(f"{base_url}/health", timeout_seconds=args.timeout_seconds)
        ready = request_json(f"{base_url}/ready", timeout_seconds=args.timeout_seconds)
        ingestion_readiness = request_json(
            f"{base_url}/v1/ingestion-readiness",
            timeout_seconds=args.timeout_seconds,
        )

        failures.extend(_check_endpoint("health", health, args.expected_deployment_sha))
        failures.extend(_check_endpoint("ready", ready, args.expected_deployment_sha))
        failures.extend(_check_ready_dependencies(ready.payload))
        failures.extend(
            _check_ingestion_readiness(
                ingestion_readiness,
                expected_deployment_sha=args.expected_deployment_sha,
            )
        )
        if not failures:
            break
        if attempt < attempts and args.retry_delay_seconds > 0:
            sleep(args.retry_delay_seconds)

    status = "failed" if failures else "passed"
    completion_evidence_ref = args.evidence_output or _default_completion_evidence_ref(
        base_url,
        args.expected_deployment_sha,
    )
    artifact = build_evidence_artifact(
        base_url=base_url,
        captured_at=captured_at,
        completion_evidence_ref=completion_evidence_ref,
        expected_deployment_sha=args.expected_deployment_sha,
        status=status,
        health=health,
        ready=ready,
        ingestion_readiness=ingestion_readiness,
        attempt_count=attempt_count,
        failures=failures,
    )
    _write_json(args.evidence_output, artifact)

    if failures:
        print("HOSTED_DEPLOYMENT_SMOKE failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    if args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                evidence_ref=completion_evidence_ref,
            ),
        )

    print(
        "HOSTED_DEPLOYMENT_SMOKE passed | "
        f"deployment_sha={args.expected_deployment_sha}"
    )
    return 0


def build_evidence_artifact(
    *,
    base_url: str,
    captured_at: str,
    completion_evidence_ref: str,
    expected_deployment_sha: str,
    status: str,
    health: "JsonResponse",
    ready: "JsonResponse",
    ingestion_readiness: "JsonResponse",
    attempt_count: int,
    failures: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "base_url": base_url,
        "status": status,
        "expected_deployment_sha": expected_deployment_sha,
        "attempt_count": attempt_count,
        "health": _endpoint_summary(health),
        "ready": _endpoint_summary(ready),
        "ingestion_readiness": _ingestion_readiness_summary(ingestion_readiness),
        "completion_evidence_targets": (
            [
                {
                    "gate_key": DEPLOYMENT_GATE_KEY,
                    "status": "accepted",
                    "satisfied_requirements": DEPLOYMENT_REQUIREMENTS,
                    "requirement_evidence": _requirement_evidence(
                        captured_at=captured_at,
                        evidence_ref=completion_evidence_ref,
                    ),
                }
            ]
            if status == "passed"
            else []
        ),
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
                "gate_key": DEPLOYMENT_GATE_KEY,
                "status": "accepted",
                "evidence_ref": evidence_ref,
                "satisfied_requirements": DEPLOYMENT_REQUIREMENTS,
                "requirement_evidence": _requirement_evidence(
                    captured_at=captured_at,
                    evidence_ref=evidence_ref,
                ),
            }
        ],
    }


def _check_endpoint(
    name: str,
    response: "JsonResponse",
    expected_deployment_sha: str,
) -> list[str]:
    failures: list[str] = []
    if response.status_code != 200:
        failures.append(
            f"{name} returned HTTP {response.status_code}: {response.error or response.payload}"
        )
        return failures
    actual = response.payload.get("deployment_sha")
    if actual != expected_deployment_sha:
        failures.append(
            f"{name} deployment_sha {actual} did not match expected {expected_deployment_sha}"
        )
    return failures


def _check_ready_dependencies(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, Mapping):
        return ["ready response missing dependencies"]
    for name in ("database", "redis"):
        dependency = dependencies.get(name)
        status = dependency.get("status") if isinstance(dependency, Mapping) else None
        if status != "healthy":
            failures.append(f"ready dependency {name} status is {status}")
    return failures


def _check_ingestion_readiness(
    response: "JsonResponse",
    *,
    expected_deployment_sha: str,
) -> list[str]:
    if response.status_code != 200:
        return [
            "ingestion-readiness returned HTTP "
            f"{response.status_code}: {response.error or response.payload}"
        ]
    payload = response.payload
    failures: list[str] = []
    if payload.get("deployment_sha") != expected_deployment_sha:
        failures.append(
            "ingestion-readiness deployment_sha "
            f"{payload.get('deployment_sha')} did not match expected {expected_deployment_sha}"
        )
    scheduler = payload.get("scheduler")
    scheduler_status = scheduler.get("status") if isinstance(scheduler, Mapping) else None
    if scheduler_status != "healthy":
        failures.append(f"ingestion scheduler status is {scheduler_status}")

    source_summary = payload.get("source_summary")
    expected_sources = (
        source_summary.get("expected_source_count")
        if isinstance(source_summary, Mapping)
        else None
    )
    sources = payload.get("sources")
    if expected_sources != 11 or not isinstance(sources, list) or len(sources) != 11:
        failures.append(
            "ingestion readiness did not return the complete 11-source production profile"
        )

    jurisdiction_summary = payload.get("jurisdiction_summary")
    expected_counties = (
        jurisdiction_summary.get("expected_county_count")
        if isinstance(jurisdiction_summary, Mapping)
        else None
    )
    returned_counties = (
        jurisdiction_summary.get("returned_county_count")
        if isinstance(jurisdiction_summary, Mapping)
        else None
    )
    jurisdictions = payload.get("jurisdictions")
    if (
        expected_counties != 22
        or returned_counties != 22
        or not isinstance(jurisdictions, list)
        or len(jurisdictions) != 22
    ):
        failures.append("ingestion readiness did not return all 22 county contracts")
    if payload.get("absence_is_safety_evidence") is not False:
        failures.append("ingestion readiness must reject absence as safety evidence")

    forbidden_keys = {
        "adapter_key",
        "holder_id",
        "database_url",
        "error_message",
        "source_url",
        "credential",
        "secret",
    }
    exposed_keys = _nested_keys(payload).intersection(forbidden_keys)
    if exposed_keys:
        failures.append(
            f"ingestion readiness exposed forbidden fields: {sorted(exposed_keys)}"
        )
    return failures


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {
            *(str(key) for key in value),
            *(key for child in value.values() for key in _nested_keys(child)),
        }
    if isinstance(value, list):
        return {key for child in value for key in _nested_keys(child)}
    return set()


def _endpoint_summary(response: "JsonResponse") -> dict[str, Any]:
    return {
        "status_code": response.status_code,
        "status": response.payload.get("status"),
        "service": response.payload.get("service"),
        "version": response.payload.get("version"),
        "deployment_sha": response.payload.get("deployment_sha"),
        "dependencies": _dependency_summary(response.payload),
        "error": response.error,
    }


def _ingestion_readiness_summary(response: "JsonResponse") -> dict[str, Any]:
    scheduler = response.payload.get("scheduler")
    return {
        "status_code": response.status_code,
        "status": response.payload.get("status"),
        "deployment_sha": response.payload.get("deployment_sha"),
        "scheduler_status": (
            scheduler.get("status") if isinstance(scheduler, Mapping) else None
        ),
        "source_summary": response.payload.get("source_summary"),
        "jurisdiction_summary": response.payload.get("jurisdiction_summary"),
        "absence_is_safety_evidence": response.payload.get("absence_is_safety_evidence"),
        "error": response.error,
    }


def _dependency_summary(payload: Mapping[str, Any]) -> dict[str, str]:
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, Mapping):
        return {}
    summary: dict[str, str] = {}
    for name, value in dependencies.items():
        if isinstance(value, Mapping):
            status = value.get("status")
            if isinstance(status, str):
                summary[str(name)] = status
    return summary


def _default_completion_evidence_ref(base_url: str, deployment_sha: str) -> str:
    return f"{base_url}/health#{deployment_sha}"


def _requirement_evidence(*, captured_at: str, evidence_ref: str) -> list[dict[str, str]]:
    return [
        {
            "requirement": requirement,
            "evidence_ref": f"{evidence_ref}#{path}",
            "observed_at": captured_at,
        }
        for requirement, path in DEPLOYMENT_REQUIREMENT_EVIDENCE_PATHS.items()
    ]


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


def request_json(url: str, *, timeout_seconds: float) -> JsonResponse:
    request = Request(url, headers={"Accept": "application/json"})
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
