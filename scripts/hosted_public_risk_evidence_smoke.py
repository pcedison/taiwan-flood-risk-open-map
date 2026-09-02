from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://floodrisk.cc"
DEFAULT_LAT = 23.01929
DEFAULT_LNG = 120.18726
DEFAULT_RADIUS_M = 2000
DEFAULT_LOCATION_TEXT = "Tainan hosted public risk evidence smoke"
GEOCODE_ADMIN_CANARY_QUERY = "臺南市北區北安路一段"
GEOCODE_ADMIN_CANARY_CENTER = (23.0101, 120.205518)
GEOCODE_ADMIN_CANARY_MAX_DISTANCE_KM = 50.0
EVIDENCE_SCHEMA_VERSION = "hosted-public-risk-evidence-smoke/v1"
COMPLETION_EVIDENCE_SCHEMA_VERSION = "local-source-completion-evidence/v1"
PUBLIC_RISK_GATE_KEY = "public_risk_worker_evidence_path"
PUBLIC_RISK_REQUIREMENTS = [
    "hosted_risk_response_worker_evidence_smoke",
    "query_point_nearby_coverage_smoke",
]
PUBLIC_RISK_REQUIREMENT_EVIDENCE_PATHS = {
    "hosted_risk_response_worker_evidence_smoke": "/risk_assessment/worker_evidence",
    "query_point_nearby_coverage_smoke": "/risk_assessment/nearby_coverage",
}
OFFICIAL_REALTIME_EVENT_TYPES = {"rainfall", "water_level"}
OFFICIAL_REALTIME_FRESHNESS_SOURCE_IDS = {
    # Canonical source IDs returned by the production API.
    "official.cwa.rainfall",
    "official.wra.water_level",
    # Retain the pre-canonical contract IDs for older evidence artifacts.
    "cwa-rainfall",
    "wra-water-level",
}
OFFICIAL_REALTIME_SIGNAL_TYPES = {"rainfall", "water_level"}
ACCEPTABLE_WORKER_SOURCE_HEALTH_STATUSES = {"healthy", "degraded"}
HYDROLOGY_SIGNAL_TYPES = {"water_level", "flood_depth", "sewer_water_level"}
USABLE_NEARBY_AVAILABILITY_STATES = {"fresh_nearby", "degraded_nearby"}
# A deployment that has never enabled the official realtime adapters reports these
# causes for every official signal. That is a deployment configuration state, not a
# regression of the public contract, so scheduled monitoring reports it as degraded
# instead of failing on every run.
SOURCE_NOT_CONFIGURED_CAUSES = {
    "source_not_configured",
    "source_disabled",
    "source_not_enabled",
}
DATA_SOURCE_MODES = ("strict", "degraded-ok")
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
        "--data-source-mode",
        choices=DATA_SOURCE_MODES,
        default="degraded-ok",
        help=(
            "strict: official realtime data-source assertions always fail the run. "
            "degraded-ok (default): when the deployment has not enabled any official "
            "realtime source, report those assertions as degraded and exit 0. Public "
            "API contract assertions always fail the run in both modes."
        ),
    )
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
    contract_failures: list[str] = []
    data_source_failures: list[str] = []
    official_source_state = "unknown"

    health = request_json("GET", f"{base_url}/health", timeout_seconds=args.timeout_seconds)
    health_evidence = {
        "status_code": health.status_code,
        "service": health.payload.get("service"),
        "version": health.payload.get("version"),
        "deployment_sha": health.payload.get("deployment_sha"),
    }
    if health.status_code != 200:
        contract_failures.append(
            f"/health returned HTTP {health.status_code}: {health.error or health.payload}"
        )
    elif not health.payload.get("deployment_sha"):
        contract_failures.append("/health did not expose deployment_sha")
    else:
        print(
            "PASS health | "
            f"version={health.payload.get('version')} | "
            f"deployment_sha={health.payload.get('deployment_sha')}"
        )

    geocode = request_json(
        "POST",
        f"{base_url}/v1/geocode",
        {
            "query": GEOCODE_ADMIN_CANARY_QUERY,
            "input_type": "address",
            "limit": 1,
        },
        timeout_seconds=args.timeout_seconds,
    )
    geocode_failures, geocode_evidence = check_geocode_admin_canary(geocode)
    contract_failures.extend(geocode_failures)

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
        contract_failures.append(
            f"/v1/risk/assess returned HTTP {risk.status_code}: {risk.error or risk.payload}"
        )
    else:
        payload_contract, payload_data_source, official_source_state = check_risk_payload(
            risk.payload, radius_m=args.radius_m
        )
        contract_failures.extend(payload_contract)
        data_source_failures.extend(payload_data_source)

    degraded_notes: list[str] = []
    if (
        args.data_source_mode == "degraded-ok"
        and official_source_state == "not_configured"
        and data_source_failures
    ):
        degraded_notes = data_source_failures
        data_source_failures = []

    failures = contract_failures + data_source_failures
    if failures:
        status = "failed"
    elif degraded_notes:
        status = "degraded"
    else:
        status = "passed"
    completion_evidence_ref = args.evidence_output or _default_completion_evidence_ref(
        base_url,
        health_evidence,
    )
    artifact = build_evidence_artifact(
        base_url=base_url,
        captured_at=captured_at,
        completion_evidence_ref=completion_evidence_ref,
        status=status,
        data_source_mode=args.data_source_mode,
        official_source_state=official_source_state,
        contract_failures=contract_failures,
        data_source_failures=data_source_failures,
        degraded_notes=degraded_notes,
        health=health_evidence,
        geocode_admin_canary=geocode_evidence,
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

    if degraded_notes:
        print("HOSTED_PUBLIC_RISK_EVIDENCE_SMOKE degraded")
        print(
            "- the public API contract passed; official realtime sources are not "
            "enabled on this deployment (official_source_state=not_configured)"
        )
        for note in degraded_notes:
            print(f"- deferred: {note}")
        print(
            "- no completion evidence was emitted; run with --data-source-mode strict "
            "once the official realtime sources are enabled"
        )
        _append_step_summary(
            [
                "### Hosted public risk evidence degraded",
                "",
                "- Public API contract assertions passed.",
                "- Official realtime sources are not enabled on this deployment, so "
                "worker freshness and coverage evidence was deferred, not failed.",
                *(f"- deferred: {note}" for note in degraded_notes),
            ]
        )
        return 0

    if args.completion_evidence_output:
        _write_json(
            args.completion_evidence_output,
            build_completion_evidence_overlay(
                captured_at=captured_at,
                evidence_ref=completion_evidence_ref,
            ),
        )

    print(
        "HOSTED_PUBLIC_RISK_EVIDENCE_SMOKE passed | "
        f"assessment_id={risk.payload.get('assessment_id')} | "
        f"nearby={risk.payload.get('nearby_realtime_coverage', {}).get('overall_level')}"
    )
    return 0


def check_risk_payload(
    payload: Mapping[str, Any], *, radius_m: int
) -> tuple[list[str], list[str], str]:
    """Split risk payload assertions into contract and data-source classes.

    Returns ``(contract_failures, data_source_failures, official_source_state)``.

    Contract failures mean the public API shape or the hosted service itself
    regressed; they always fail the run. Data-source failures mean the response
    shape is fine but no official realtime observation reached it; whether they
    fail the run depends on ``--data-source-mode`` and on whether the deployment
    has any official realtime source enabled at all.
    """

    contract_failures: list[str] = []
    data_source_failures: list[str] = []
    if not payload.get("assessment_id"):
        contract_failures.append("risk response missing assessment_id")
    if not _non_empty_string(_nested_get(payload, "explanation", "summary")):
        contract_failures.append("risk response missing explanation summary")

    freshness_source_ids = _valid_worker_freshness_source_ids(payload.get("data_freshness"))
    if not freshness_source_ids:
        data_source_failures.append(
            "risk response did not include healthy official realtime freshness with observed_at and ingested_at"
        )

    official_events = _valid_official_evidence_event_types(payload.get("evidence"))
    if not official_events:
        data_source_failures.append(
            "risk response did not include official rainfall or water_level evidence "
            "with observed_at and ingested_at"
        )

    coverage = payload.get("nearby_realtime_coverage")
    worker_source_health_failures: list[str] = []
    if not isinstance(coverage, Mapping):
        contract_failures.append("risk response missing nearby_realtime_coverage")
    else:
        contract_failures.extend(_check_nearby_coverage(coverage, radius_m=radius_m))
        worker_source_health_failures = _check_worker_source_health(coverage)
        data_source_failures.extend(worker_source_health_failures)

    # The API intentionally fails closed from low to unknown when a required
    # worker source is unhealthy. Retained evidence can still be present for
    # traceability in that state, so report the source-health failure without
    # adding a contradictory "usable evidence but unknown" diagnostic.
    if (
        official_events
        and not worker_source_health_failures
        and _nested_get(payload, "realtime", "level") in {None, "unknown", "未知"}
    ):
        data_source_failures.append(
            "risk response had usable official realtime evidence but still returned an unknown "
            "realtime level"
        )
    return contract_failures, data_source_failures, resolve_official_source_state(payload)


def check_geocode_admin_canary(response: JsonResponse) -> tuple[list[str], dict[str, Any]]:
    evidence: dict[str, Any] = {
        "query": GEOCODE_ADMIN_CANARY_QUERY,
        "status_code": response.status_code,
    }
    if response.status_code != 200:
        return (
            [
                "geocode admin canary returned HTTP "
                f"{response.status_code}: {response.error or response.payload}"
            ],
            evidence,
        )

    candidates = response.payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], Mapping):
        return (["geocode admin canary returned no candidate"], evidence)

    candidate = candidates[0]
    point = candidate.get("point")
    evidence.update(
        {
            "candidate_name": candidate.get("name"),
            "source": candidate.get("source"),
            "precision": candidate.get("precision"),
            "point": point,
        }
    )
    if not isinstance(point, Mapping):
        return (["geocode admin canary candidate has no point"], evidence)
    lat = point.get("lat")
    lng = point.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return (["geocode admin canary candidate point is not numeric"], evidence)

    distance_km = _haversine_km(
        float(lat),
        float(lng),
        *GEOCODE_ADMIN_CANARY_CENTER,
    )
    evidence["distance_from_expected_admin_center_km"] = round(distance_km, 3)
    if distance_km > GEOCODE_ADMIN_CANARY_MAX_DISTANCE_KM:
        return (
            [
                "geocode admin canary escaped the requested Tainan admin area: "
                f"candidate={candidate.get('name')}, distance_km={distance_km:.1f}"
            ],
            evidence,
        )

    print(
        "PASS geocode admin canary | "
        f"source={candidate.get('source')} | distance_km={distance_km:.1f}"
    )
    return ([], evidence)


def resolve_official_source_state(payload: Mapping[str, Any]) -> str:
    """Report whether the deployment has any official realtime source enabled.

    ``not_configured`` means every official signal reports a "source is off"
    cause and no worker source health record exists, i.e. the deployment never
    tried to ingest official realtime data. ``configured`` means at least one
    official source is switched on, so an absent or stale observation is a real
    regression worth failing on. ``unknown`` is the conservative fallback and is
    treated like ``configured``.
    """

    if _valid_worker_freshness_source_ids(payload.get("data_freshness")):
        return "configured"

    coverage = payload.get("nearby_realtime_coverage")
    if not isinstance(coverage, Mapping):
        return "unknown"

    source_health = coverage.get("source_health")
    if isinstance(source_health, list) and source_health:
        return "configured"

    signals = coverage.get("signal_breakdown")
    if not isinstance(signals, list) or not signals:
        return "unknown"

    official_signals = [
        signal
        for signal in signals
        if isinstance(signal, Mapping)
        and signal.get("signal_type") in OFFICIAL_REALTIME_SIGNAL_TYPES
    ]
    if not official_signals:
        return "unknown"

    for signal in official_signals:
        source_count = signal.get("source_count")
        if isinstance(source_count, int) and source_count > 0:
            return "configured"
        if signal.get("missing_cause") not in SOURCE_NOT_CONFIGURED_CAUSES:
            return "configured"
    return "not_configured"


def build_evidence_artifact(
    *,
    base_url: str,
    captured_at: str,
    completion_evidence_ref: str,
    status: str,
    data_source_mode: str,
    official_source_state: str,
    contract_failures: list[str],
    data_source_failures: list[str],
    degraded_notes: list[str],
    health: Mapping[str, Any],
    geocode_admin_canary: Mapping[str, Any],
    request: Mapping[str, Any],
    risk_payload: Mapping[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    gate_accepted = status == "passed"
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "base_url": base_url,
        "status": status,
        "data_source_mode": data_source_mode,
        "official_source_state": official_source_state,
        "health": dict(health),
        "geocode_admin_canary": dict(geocode_admin_canary),
        "request": dict(request),
        "risk_assessment": _risk_assessment_summary(risk_payload),
        "completion_evidence_targets": [
            {
                "gate_key": PUBLIC_RISK_GATE_KEY,
                "status": "accepted" if gate_accepted else "blocked",
                "satisfied_requirements": (
                    PUBLIC_RISK_REQUIREMENTS if gate_accepted else []
                ),
                "requirement_evidence": (
                    _requirement_evidence(
                        captured_at=captured_at,
                        evidence_ref=completion_evidence_ref,
                    )
                    if gate_accepted
                    else []
                ),
            }
        ],
        "contract_failures": list(contract_failures),
        "data_source_failures": list(data_source_failures),
        "degraded_notes": list(degraded_notes),
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
                "requirement_evidence": _requirement_evidence(
                    captured_at=captured_at,
                    evidence_ref=evidence_ref,
                ),
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


def _check_worker_source_health(coverage: Mapping[str, Any]) -> list[str]:
    if coverage.get("source_health_checked") is not True:
        return [
            "nearby_realtime_coverage did not verify worker source health; "
            "request-time official observations are not worker persistence evidence"
        ]

    source_health = coverage.get("source_health")
    if not isinstance(source_health, list) or not source_health:
        return ["nearby_realtime_coverage returned no worker source health records"]

    failures: list[str] = []
    for source in source_health:
        if not isinstance(source, Mapping) or source.get("required_for_absence") is False:
            continue
        status = source.get("health_status")
        reason = source.get("reason_code")
        if (
            status not in ACCEPTABLE_WORKER_SOURCE_HEALTH_STATUSES
            or reason == "pipeline_stalled"
        ):
            if reason == "upstream_unavailable" and _has_hydrology_redundancy(
                source,
                source_health,
                coverage,
            ):
                continue
            source_id = source.get("source_id") or source.get("name") or "unknown-source"
            failures.append(
                f"required worker source {source_id} health is {status} ({reason})"
            )
    return failures


def _has_hydrology_redundancy(
    failed_source: Mapping[str, Any],
    source_health: list[Any],
    coverage: Mapping[str, Any],
) -> bool:
    failed_signal_types = {
        str(signal_type)
        for signal_type in failed_source.get("signal_types", [])
        if str(signal_type) in HYDROLOGY_SIGNAL_TYPES
    }
    if not failed_signal_types:
        return False

    failed_source_id = failed_source.get("source_id")
    has_independent_healthy_source = any(
        isinstance(source, Mapping)
        and source.get("source_id") != failed_source_id
        and source.get("health_status") in ACCEPTABLE_WORKER_SOURCE_HEALTH_STATUSES
        and bool(
            {str(signal_type) for signal_type in source.get("signal_types", [])}
            & HYDROLOGY_SIGNAL_TYPES
        )
        for source in source_health
    )
    if not has_independent_healthy_source:
        return False

    signals = coverage.get("signal_breakdown")
    return isinstance(signals, list) and any(
        isinstance(signal, Mapping)
        and signal.get("signal_type") in HYDROLOGY_SIGNAL_TYPES
        and signal.get("availability_state") in USABLE_NEARBY_AVAILABILITY_STATES
        for signal in signals
    )


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
        "source_health_checked": coverage.get("source_health_checked"),
        "source_health_status": coverage.get("source_health_status"),
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
    return bool(counts) and all(type(value) is int and value >= 0 for value in counts.values())


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


def _haversine_km(lat_a: float, lng_a: float, lat_b: float, lng_b: float) -> float:
    earth_radius_km = 6371.0088
    lat_a_rad = radians(lat_a)
    lat_b_rad = radians(lat_b)
    d_lat = radians(lat_b - lat_a)
    d_lng = radians(lng_b - lng_a)
    haversine = sin(d_lat / 2) ** 2 + cos(lat_a_rad) * cos(lat_b_rad) * sin(d_lng / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(haversine))


def _default_completion_evidence_ref(base_url: str, health: Mapping[str, Any]) -> str:
    deployment_sha = health.get("deployment_sha") or "unknown-sha"
    return f"{base_url}/health#{deployment_sha}"


def _requirement_evidence(*, captured_at: str, evidence_ref: str) -> list[dict[str, str]]:
    return [
        {
            "requirement": requirement,
            "evidence_ref": f"{evidence_ref}#{path}",
            "observed_at": captured_at,
        }
        for requirement, path in PUBLIC_RISK_REQUIREMENT_EVIDENCE_PATHS.items()
    ]


def _append_step_summary(lines: list[str]) -> None:
    """Best-effort append to the GitHub step summary; a no-op outside Actions."""

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        return


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
    except (
        TimeoutError,
        URLError,
        OSError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        return JsonResponse(status_code=0, payload={}, error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
