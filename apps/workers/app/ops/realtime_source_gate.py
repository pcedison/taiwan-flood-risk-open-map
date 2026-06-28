from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from app.ops.local_source_discovery_monitor import DiscoveryResult
from app.ops.official_realtime_live_smoke import OfficialRealtimeSmokeResult


DEFAULT_EXPECTED_COVERAGE_SUMMARY = {
    "local_direct_complete_count": 20,
    "local_direct_incomplete_count": 2,
    "central_backbone_minimum_complete_count": 21,
    "central_backbone_minimum_incomplete_count": 1,
    "local_direct_incomplete_counties": ["金門縣", "連江縣"],
    "counties_missing_hydrologic_backbone": ["連江縣"],
}


@dataclass(frozen=True)
class RealtimeSourceGateResult:
    passed: bool
    failures: tuple[str, ...]
    coverage_summary: Mapping[str, Any]
    smoke_result: OfficialRealtimeSmokeResult
    discovery_result: DiscoveryResult

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
    return RealtimeSourceGateResult(
        passed=not failures,
        failures=tuple(failures),
        coverage_summary=coverage_summary,
        smoke_result=smoke_result,
        discovery_result=discovery_result,
    )
