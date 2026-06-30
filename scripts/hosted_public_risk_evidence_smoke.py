from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://floodrisk.cc"
DEFAULT_LAT = 23.01929
DEFAULT_LNG = 120.18726
DEFAULT_RADIUS_M = 500
DEFAULT_LOCATION_TEXT = "Tainan hosted public risk evidence smoke"
EVIDENCE_SCHEMA_VERSION = "hosted-public-risk-evidence-smoke/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
PUBLIC_RISK_GATE_KEY = "public_risk_worker_evidence_path"
PUBLIC_RISK_REQUIREMENTS = [
    "hosted_risk_response_worker_evidence_smoke",
    "query_point_nearby_coverage_smoke",
]
OFFICIAL_REALTIME_EVENT_TYPES = {"rainfall", "water_level"}
OFFICIAL_REALTIME_FRESHNESS_SOURCE_IDS = {"cwa-rainfall", "wra-water-level"}
REQUIRED_NEARBY_SIGNALS = {
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
    "pump_or_gate_status",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hosted public risk evidence smoke: verify worker-style official "
            "evidence and query-point nearby coverage in a public risk response."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lng", type=float, default=DEFAULT_LNG)
    parser.add_argument("--radius-m", type=int, default=DEFAULT_RADIUS_M)
    parser.add_argument("--location-text", default=DEFAULT_LOCATION_TEXT)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--captured-at",
        help="Optional ISO 8601 timestamp for reproducible evidence artifacts.",
    )
    parser.add_argument(
        "--evidence-output",
        help="Optional JSON file capturing the hosted public risk evidence smoke result.",
    )
    parser.add_argument(
        "--completion-evidence-output",
        help=(
            "Optional local-source-completion-evidence/v1 JSON overlay containing "
            "only the public_risk_worker_evidence_path production gate evidence."
        ),
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    captured_at = args.captured_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    failures: list[str] = []

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

    risk_request = {
        "point": {"lat": args.lat, "lng": args.lng},
        "radius_m": args.radius_m,
        "time_context": "now",
        "location_text": args.location_text,
    }
    risk = request_json(
        "POST",
        f"{base_url}/v1/risk/assess",
        risk_request,
        timeout_seconds=args.timeout_seconds,
    )
    if risk.status_code != 200:
        failures.append(f"/v1/risk/assess returned HTTP {risk.status_code}: {risk.error or risk.payload}")
    else:
        failures.extend(check_risk_payload(risk.payload, radius_m=args.radius_m))

    status = "failed" if failures else "passed"
    artifact = build_evidence_artifact(
        base_url=base_url,
        captured_at=captured_at,
        status=status,
        health=health_evidence,
        request={
            "lat": args.lat,
            "lng": args.lng,
            "radius_m": args.radius_m,
            "location_text": args.location_text,
        },
        risk_payload=risk.payload if risk.status_code == 200 else {},
        failures=failures,
    )
    _write_json(args.evidence_output, artifact)

    if failures:
        print("HOSTED_PUBLIC_RISK_EVIDENCE_SMOKE failed")
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
        "HOSTED_PUBLIC_RISK_EVIDENCE_SMOKE passed | "
        f"assessment_id={risk.payload.get('assessment_id')} | "
        f"nearby={risk.payload.get('nearby_realtime_coverage', {}).get('overall_level')}"
    )
    return 0


def check_risk_payload(payload: Mapping[str, Any], *, radius_m: int) -> list[str]:
    failures: list[str] = []
    if not payload.get("assessment_id"):
        failures.append("risk response missing assessment_id")
    if not _non_empty_string(_nested_get(payload, "explanation", "summary")):
        failures.append("risk response missing explanation summary")

    freshness_source_ids = _valid_worker_freshness_source_ids(payload.get("data_freshness"))
    if not freshness_source_ids:
        failures.append(
            "risk response did not include healthy official realtime freshness with observed_at and ingested_at"
        )

    official_events = _valid_official_evidence_event_types(payload.get("evidence"))
    if not official_events:
        failures.append(
            "risk response did not include official rainfall or water_level evidence "
            "with observed_at and ingested_at"
        )

    coverage = payload.get("nearby_realtime_coverage")
    if not isinstance(coverage, Mapping):
        failures.append("risk response missing nearby_realtime_coverage")
    else:
        failures.extend(_check_nearby_coverage(coverage, radius_m=radius_m))
    return failures


def build_evidence_artifact(
    *,
    base_url: str,
    captured_at: str,
    status: str,
    health: Mapping[str, Any],
    request: Mapping[str, Any],
    risk_payload: Mapping[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "base_url": base_url,
        "status": status,
        "health": dict(health),
        "request": dict(request),
        "risk_assessment": _risk_assessment_summary(risk_payload),
        "completion_evidence_targets": [
            {
                "gate_key": PUBLIC_RISK_GATE_KEY,
                "status": "accepted",
                "satisfied_requirements": PUBLIC_RISK_REQUIREMENTS,
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
                "gate_key": PUBLIC_RISK_GATE_KEY,
                "status": "accepted",
                "evidence_ref": evidence_ref,
                "satisfied_requirements": PUBLIC_RISK_REQUIREMENTS,
            }
        ],
    }


def _check_nearby_coverage(coverage: Mapping[str, Any], *, radius_m: int) -> list[str]:
    failures: list[str] = []
    if coverage.get("query_radius_m") != radius_m:
        failures.append(
            f"nearby_realtime_coverage query_radius_m should be {radius_m}, got {coverage.get('query_radius_m')}"
        )
    if not _non_empty_string(coverage.get("summary")):
        failures.append("nearby_realtime_coverage missing summary")
    if not coverage.get("radius_buckets_m"):
        failures.append("nearby_realtime_coverage missing radius_buckets_m")

    signals = coverage.get("signal_breakdown")
    if not isinstance(signals, list) or not signals:
        failures.append("nearby_realtime_coverage missing signal_breakdown")
        return failures

    signal_types = {str(item.get("signal_type")) for item in signals if isinstance(item, Mapping)}
    missing = sorted(REQUIRED_NEARBY_SIGNALS - signal_types)
    if missing:
        failures.append(f"nearby_realtime_coverage missing signal types: {missing}")

    if not any(_signal_has_query_point_context(item) for item in signals if isinstance(item, Mapping)):
        failures.append(
            "nearby_realtime_coverage did not include nearest sensor context or radius counts"
        )
    return failures


def _risk_assessment_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    coverage = payload.get("nearby_realtime_coverage")
    return {
        "assessment_id": payload.get("assessment_id"),
        "levels": {
            "realtime": _nested_get(payload, "realtime", "level"),
            "historical": _nested_get(payload, "historical", "level"),
            "confidence": _nested_get(payload, "confidence", "level"),
        },
        "worker_evidence": {
            "freshness_source_ids": _valid_worker_freshness_source_ids(
                payload.get("data_freshness")
            ),
            "official_evidence_event_types": _valid_official_evidence_event_types(
                payload.get("evidence")
            ),
        },
        "nearby_coverage": _nearby_coverage_summary(coverage if isinstance(coverage, Mapping) else {}),
    }


def _nearby_coverage_summary(coverage: Mapping[str, Any]) -> dict[str, Any]:
    signals = coverage.get("signal_breakdown")
    signal_types = []
    if isinstance(signals, list):
        signal_types = [
            str(item.get("signal_type"))
            for item in signals
            if isinstance(item, Mapping) and item.get("signal_type")
        ]
    return {
        "overall_level": coverage.get("overall_level"),
        "query_radius_m": coverage.get("query_radius_m"),
        "radius_buckets_m": coverage.get("radius_buckets_m") or [],
        "signal_types": signal_types,
        "missing_signal_types": coverage.get("missing_signal_types") or [],
    }


def _valid_worker_freshness_source_ids(value: Any) -> list[str]:
    source_ids: list[str] = []
    if not isinstance(value, list):
        return source_ids
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source_id = item.get("source_id")
        if source_id not in OFFICIAL_REALTIME_FRESHNESS_SOURCE_IDS:
            continue
        if not _non_empty_string(item.get("observed_at")):
            continue
        if not _non_empty_string(item.get("ingested_at")):
            continue
        source_ids.append(str(source_id))
    return _unique(source_ids)


def _valid_official_evidence_event_types(value: Any) -> list[str]:
    event_types: list[str] = []
    if not isinstance(value, list):
        return event_types
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if item.get("source_type") != "official":
            continue
        event_type = item.get("event_type")
        if event_type not in OFFICIAL_REALTIME_EVENT_TYPES:
            continue
        if not _non_empty_string(item.get("observed_at")):
            continue
        if not _non_empty_string(item.get("ingested_at")):
            continue
        event_types.append(str(event_type))
    return _unique(event_types)


def _signal_has_query_point_context(signal: Mapping[str, Any]) -> bool:
    if _non_empty_string(signal.get("nearest_source_id")) and signal.get("nearest_distance_m") is not None:
        return True
    counts = signal.get("counts_by_radius_m")
    if not isinstance(counts, Mapping):
        return False
    return any(isinstance(value, int) and value > 0 for value in counts.values())


def _nested_get(value: Mapping[str, Any], key: str, nested_key: str) -> Any:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        return None
    return nested.get(nested_key)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _default_completion_evidence_ref(base_url: str, health: Mapping[str, Any]) -> str:
    deployment_sha = health.get("deployment_sha") or "unknown-sha"
    return f"{base_url}/health#{deployment_sha}"


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
    timeout_seconds: float,
) -> JsonResponse:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
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
