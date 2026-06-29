from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from app.ops.local_source_discovery_monitor import DiscoveryResult
from app.ops.official_realtime_live_smoke import OfficialRealtimeSmokeResult

PRODUCTION_READINESS_GATES = [
    "credential_review",
    "source_license_review",
    "raw_snapshot_retention_policy",
    "hosted_scheduler_cadence",
    "hosted_egress_review",
    "alert_routing_ownership",
    "worker_persisted_evidence_smoke",
]


DEFAULT_EXPECTED_COVERAGE_SUMMARY = {
    "local_direct_complete_count": 20,
    "local_direct_incomplete_count": 2,
    "central_backbone_minimum_complete_count": 22,
    "central_backbone_minimum_incomplete_count": 0,
    "local_direct_incomplete_counties": ["金門縣", "連江縣"],
    "counties_missing_hydrologic_backbone": [],
}


@dataclass(frozen=True)
class RealtimeSourceGateResult:
    passed: bool
    failures: tuple[str, ...]
    coverage_summary: Mapping[str, Any]
    smoke_result: OfficialRealtimeSmokeResult
    discovery_result: DiscoveryResult
    production_readiness: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failures": list(self.failures),
            "coverage": {
                "local_direct_complete_count": int(
                    self.coverage_summary.get("local_direct_complete_count", 0)
                ),
                "local_direct_remaining_count": int(
                    self.coverage_summary.get("local_direct_incomplete_count", 0)
                ),
                "central_backbone_minimum_complete_count": int(
                    self.coverage_summary.get(
                        "central_backbone_minimum_complete_count",
                        0,
                    )
                ),
                "central_backbone_remaining_count": int(
                    self.coverage_summary.get(
                        "central_backbone_minimum_incomplete_count",
                        0,
                    )
                ),
                "local_direct_incomplete_counties": list(
                    self.coverage_summary.get("local_direct_incomplete_counties", [])
                ),
                "counties_missing_hydrologic_backbone": list(
                    self.coverage_summary.get("counties_missing_hydrologic_backbone", [])
                ),
            },
            "official_live_smoke": self.smoke_result.to_dict(),
            "discovery": {
                **self.discovery_result.to_dict(),
                "candidate_live_read_api_count": sum(
                    1
                    for candidate in self.discovery_result.candidates
                    if candidate.readiness == "candidate_live_read_api"
                ),
            },
            "production_readiness": dict(self.production_readiness),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def evaluate_realtime_source_gate(
    *,
    coverage_summary: Mapping[str, Any],
    smoke_result: OfficialRealtimeSmokeResult,
    discovery_result: DiscoveryResult,
    fail_on_live_candidate: bool = False,
    fail_on_skipped_smoke: bool = False,
    production_gate_evidence: Mapping[str, Any] | None = None,
    fail_on_missing_production_gates: bool = False,
) -> RealtimeSourceGateResult:
    failures: list[str] = []
    for item in smoke_result.results:
        if item.status == "failed":
            failures.append(f"{item.adapter_key}: {item.message or 'live smoke failed'}")
        elif fail_on_skipped_smoke and item.status == "skipped":
            failures.append(f"{item.adapter_key}: live smoke skipped")
    live_candidates = [
        candidate
        for candidate in discovery_result.candidates
        if candidate.readiness == "candidate_live_read_api"
    ]
    if fail_on_live_candidate and live_candidates:
        failures.append(
            "candidate_live_read_api found: "
            + ", ".join(
                f"{candidate.county}/{candidate.dataset_id or candidate.title}"
                for candidate in live_candidates
            )
        )
    production_readiness = _production_readiness(production_gate_evidence)
    if fail_on_missing_production_gates and production_readiness["missing_gates"]:
        failures.append(
            "missing production readiness gates: "
            + ", ".join(production_readiness["missing_gates"])
        )
    return RealtimeSourceGateResult(
        passed=not failures,
        failures=tuple(failures),
        coverage_summary=coverage_summary,
        smoke_result=smoke_result,
        discovery_result=discovery_result,
        production_readiness=production_readiness,
    )


def _production_readiness(
    production_gate_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    evidence = production_gate_evidence or {}
    satisfied = [
        gate for gate in PRODUCTION_READINESS_GATES if bool(evidence.get(gate))
    ]
    missing = [gate for gate in PRODUCTION_READINESS_GATES if gate not in satisfied]
    readiness_state = (
        "production_evidence_complete" if not missing else "not_production_complete"
    )
    return {
        "readiness_state": readiness_state,
        "required_gates": list(PRODUCTION_READINESS_GATES),
        "satisfied_gates": satisfied,
        "missing_gates": missing,
    }
