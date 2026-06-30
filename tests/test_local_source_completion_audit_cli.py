from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP = REPO_ROOT / "apps" / "api"
SCRIPT = REPO_ROOT / "scripts" / "local-source-completion-audit.py"
sys.path.insert(0, str(API_APP))

from app.domain.realtime.local_source_action_plan import (  # noqa: E402
    PRODUCTION_GATE_REQUIRED_REQUIREMENTS,
    build_local_source_action_plan,
)
from app.domain.realtime.local_source_coverage import (  # noqa: E402
    list_local_source_coverage,
)

FULL_HOSTED_SOURCE_ADAPTER_KEYS = [
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.wra.water_level",
    "official.ncdr.cap",
    "official.wra_iow.flood_depth",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
]


def test_local_source_completion_audit_cli_reports_incomplete_by_default() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "incomplete"
    assert payload["summary"]["signal_gap_county_item_count"] == 17


def test_local_source_completion_audit_cli_accepts_completion_evidence(
    tmp_path: Path,
) -> None:
    baseline = build_local_source_action_plan(list_local_source_coverage())
    evidence_path = tmp_path / "local-source-completion-evidence.json"
    evidence_path.write_text(
        json.dumps(_complete_evidence_overlay(baseline), ensure_ascii=False),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
            "--fail-on-incomplete",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    gates = {gate["gate_key"]: gate for gate in payload["gates"]}

    assert payload["overall_status"] == "satisfied"
    assert payload["next_priority_workstreams"] == []
    assert gates["required_signal_families"]["status"] == "satisfied"
    assert gates["official_authorization_and_contracts"]["status"] == "satisfied"
    assert gates["production_deployment_evidence"]["status"] == "satisfied"
    assert gates["hosted_worker_persisted_evidence"]["status"] == "satisfied"


def test_local_source_completion_audit_cli_merges_completion_evidence_files(
    tmp_path: Path,
) -> None:
    public_risk_evidence = tmp_path / "public-risk-evidence.json"
    hosted_worker_evidence = tmp_path / "hosted-worker-evidence.json"
    public_risk_artifact = tmp_path / "public-risk-smoke.json"
    public_risk_artifact.write_text(
        json.dumps(
            {
                "schema_version": "hosted-public-risk-evidence-smoke/v1",
                "status": "passed",
                "risk_assessment": {
                    "worker_evidence": {"freshness_source_ids": ["cwa-rainfall"]},
                    "nearby_coverage": {"query_radius_m": 500},
                },
            }
        ),
        encoding="utf-8",
    )
    public_risk_evidence.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T05:00:00+00:00",
                "signal_family_gap_evidence": [],
                "source_contract_evidence": [],
                "production_gate_evidence": [
                    {
                        "gate_key": "public_risk_worker_evidence_path",
                        "status": "accepted",
                        "evidence_ref": str(public_risk_artifact),
                        "satisfied_requirements": [
                            "hosted_risk_response_worker_evidence_smoke",
                            "query_point_nearby_coverage_smoke",
                        ],
                        "requirement_evidence": _local_public_risk_requirement_evidence(
                            public_risk_artifact
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    hosted_worker_evidence.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T05:10:00+00:00",
                "signal_family_gap_evidence": [],
                "source_contract_evidence": [],
                "production_gate_evidence": [
                    {
                        "gate_key": "hosted_worker_persisted_evidence",
                        "status": "accepted",
                        "evidence_ref": "private-ops://zeabur/worker",
                        "satisfied_requirements": list(
                            PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                                "hosted_worker_persisted_evidence"
                            ]
                        ),
                        "requirement_evidence": _requirement_evidence(
                            "hosted_worker_persisted_evidence",
                            PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                                "hosted_worker_persisted_evidence"
                            ],
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(public_risk_evidence),
            "--completion-evidence-json",
            str(hosted_worker_evidence),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    gates = {gate["gate_key"]: gate for gate in payload["gates"]}

    assert payload["evidence_overlay"]["production_gate_evidence_count"] == 2
    assert (
        payload["evidence_overlay"]["production_gate_requirement_evidence_count"]
        == 7
    )
    assert gates["public_risk_worker_evidence_path"]["status"] == "satisfied"
    assert gates["hosted_worker_persisted_evidence"]["status"] == "satisfied"
    assert gates["production_monitoring_and_alerting"]["status"] == "incomplete"
    assert payload["overall_status"] == "incomplete"


def test_local_source_completion_audit_cli_tracks_dispatched_signal_gap_without_accepting_it(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "dispatch-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T15:00:00+08:00",
                "signal_family_gap_evidence": [
                    {
                        "county": "\u9023\u6c5f\u7e23",
                        "signal_type": "flood_depth",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/dispatch/flood-depth"
                        ),
                    }
                ],
                "source_contract_evidence": [],
                "production_gate_evidence": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    gates = {gate["gate_key"]: gate for gate in payload["gates"]}

    assert payload["evidence_overlay"]["signal_family_gap_evidence_count"] == 0
    assert payload["evidence_overlay"]["signal_family_gap_dispatch_count"] == 1
    assert gates["required_signal_families"]["status"] == "incomplete"
    assert gates["required_signal_families"]["blocking_items"] == [
        "pump_or_gate_status:13",
        "flood_depth:3",
        "sewer_water_level:1",
    ]
    assert "Dispatch evidence supplied for 1/17" in gates[
        "required_signal_families"
    ]["evidence"]


def test_local_source_completion_audit_cli_reports_overdue_dispatch_followups(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "dispatch-evidence.json"
    markdown_output_path = tmp_path / "completion-audit.md"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T15:00:00+08:00",
                "signal_family_gap_evidence": [
                    {
                        "county": "\u9023\u6c5f\u7e23",
                        "signal_type": "flood_depth",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/dispatch/flood-depth"
                        ),
                        "follow_up_due_at": "2026-07-07T09:00:00+08:00",
                    }
                ],
                "source_contract_evidence": [
                    {
                        "county": "\u91d1\u9580\u7e23",
                        "gate": "authorization_request",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/source-contract/kinmen"
                        ),
                        "follow_up_due_at": "2026-07-07T09:00:00+08:00",
                    },
                    {
                        "county": "\u82b1\u84ee\u7e23",
                        "gate": "authorization_request",
                        "status": "request_dispatched",
                        "evidence_ref": (
                            "private-ops://local-source/source-contract/hualien"
                        ),
                        "follow_up_due_at": "2026-07-09T09:00:00+08:00",
                    },
                ],
                "production_gate_evidence": [],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
            "--as-of",
            "2026-07-08T00:00:00+08:00",
            "--markdown-output",
            str(markdown_output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    overlay = payload["evidence_overlay"]
    gates = {gate["gate_key"]: gate for gate in payload["gates"]}
    markdown = markdown_output_path.read_text(encoding="utf-8")

    assert overlay["follow_up_as_of"] == "2026-07-08T00:00:00+08:00"
    assert overlay["signal_family_gap_dispatch_overdue_count"] == 1
    assert overlay["source_contract_dispatch_overdue_count"] == 1
    assert overlay["source_contract_next_follow_up_due_at"] == (
        "2026-07-07T09:00:00+08:00"
    )
    assert "1 dispatch follow-up items are overdue" in gates[
        "required_signal_families"
    ]["evidence"]
    assert "1 dispatch follow-up items are overdue" in gates[
        "official_authorization_and_contracts"
    ]["evidence"]
    assert "`signal_family_gap_dispatch_overdue_count`: `1`" in markdown
    assert "`source_contract_dispatch_overdue_count`: `1`" in markdown
    assert "private-ops://" not in markdown


def test_local_source_completion_audit_cli_rejects_invalid_as_of() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--as-of",
            "not-a-date",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--as-of must be an ISO 8601 timestamp" in result.stderr


def test_local_source_completion_audit_cli_writes_output_artifact(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "completion-audit.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    output_payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_payload == stdout_payload
    assert output_payload["overall_status"] == "incomplete"
    assert output_payload["summary"]["signal_gap_county_item_count"] == 17


def test_local_source_completion_audit_cli_writes_markdown_report(
    tmp_path: Path,
) -> None:
    json_output_path = tmp_path / "completion-audit.json"
    markdown_output_path = tmp_path / "completion-audit.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(json_output_path),
            "--markdown-output",
            str(markdown_output_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(json_output_path.read_text(encoding="utf-8"))
    markdown = markdown_output_path.read_text(encoding="utf-8")

    assert payload["overall_status"] == "incomplete"
    assert "# Local Source Completion Audit" in markdown
    assert "- Overall status: `incomplete`" in markdown
    assert "| `required_signal_families` | `incomplete` |" in markdown
    assert "`pump_or_gate_status:13`, `flood_depth:3`, `sewer_water_level:1`" in markdown
    assert "`send_official_read_api_requests`" in markdown
    assert "`production_deployment_evidence` | `incomplete`" in markdown


def test_local_source_completion_audit_cli_rejects_failed_local_evidence_ref(
    tmp_path: Path,
) -> None:
    failed_artifact = tmp_path / "failed-public-risk-smoke.json"
    failed_artifact.write_text(
        json.dumps(
            {
                "schema_version": "hosted-public-risk-evidence-smoke/v1",
                "status": "failed",
                "risk_assessment": {
                    "worker_evidence": {},
                    "nearby_coverage": {},
                },
            }
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "local-source-completion-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T05:00:00+00:00",
                "signal_family_gap_evidence": [],
                "source_contract_evidence": [],
                "production_gate_evidence": [
                    {
                        "gate_key": "public_risk_worker_evidence_path",
                        "status": "accepted",
                        "evidence_ref": str(failed_artifact),
                        "satisfied_requirements": [
                            "hosted_risk_response_worker_evidence_smoke",
                            "query_point_nearby_coverage_smoke",
                        ],
                        "requirement_evidence": _local_public_risk_requirement_evidence(
                            failed_artifact
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert (
        "local evidence_ref status must be 'passed'"
        in result.stderr
    )
    assert str(failed_artifact) in result.stderr


def test_local_source_completion_audit_cli_rejects_narrow_hosted_source_freshness_evidence(
    tmp_path: Path,
) -> None:
    hosted_source_artifact = tmp_path / "hosted-source-freshness-smoke.json"
    hosted_source_artifact.write_text(
        json.dumps(
            {
                "schema_version": "hosted-source-freshness-smoke/v1",
                "status": "passed",
                "required_adapter_keys": [
                    "official.cwa.rainfall",
                    "official.wra.water_level",
                ],
                "checked_sources": [
                    {"adapter_key": "official.cwa.rainfall"},
                    {"adapter_key": "official.wra.water_level"},
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "local-source-completion-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T05:00:00+00:00",
                "signal_family_gap_evidence": [],
                "source_contract_evidence": [],
                "production_gate_evidence": [
                    {
                        "gate_key": "hosted_worker_persisted_evidence",
                        "status": "accepted",
                        "evidence_ref": str(hosted_source_artifact),
                        "satisfied_requirements": [
                            "freshness_policy",
                            "worker_persisted_evidence_path",
                        ],
                        "requirement_evidence": [
                            {
                                "requirement": "freshness_policy",
                                "evidence_ref": (
                                    f"{hosted_source_artifact}#/checked_sources"
                                ),
                                "observed_at": "2026-06-30T05:00:00+00:00",
                            },
                            {
                                "requirement": "worker_persisted_evidence_path",
                                "evidence_ref": (
                                    f"{hosted_source_artifact}#/checked_sources"
                                ),
                                "observed_at": "2026-06-30T05:00:00+00:00",
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "must cover the full hosted realtime backbone" in result.stderr
    assert "official.cwa.tide_level" in result.stderr


def test_local_source_completion_audit_cli_accepts_full_hosted_source_freshness_evidence(
    tmp_path: Path,
) -> None:
    hosted_source_artifact = tmp_path / "hosted-source-freshness-smoke.json"
    hosted_source_artifact.write_text(
        json.dumps(
            {
                "schema_version": "hosted-source-freshness-smoke/v1",
                "status": "passed",
                "required_adapter_keys": FULL_HOSTED_SOURCE_ADAPTER_KEYS,
                "checked_sources": [
                    {"adapter_key": adapter_key}
                    for adapter_key in FULL_HOSTED_SOURCE_ADAPTER_KEYS
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "local-source-completion-evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-06-30T05:00:00+00:00",
                "signal_family_gap_evidence": [],
                "source_contract_evidence": [],
                "production_gate_evidence": [
                    {
                        "gate_key": "hosted_worker_persisted_evidence",
                        "status": "accepted",
                        "evidence_ref": str(hosted_source_artifact),
                        "satisfied_requirements": [
                            "freshness_policy",
                            "worker_persisted_evidence_path",
                        ],
                        "requirement_evidence": [
                            {
                                "requirement": "freshness_policy",
                                "evidence_ref": (
                                    f"{hosted_source_artifact}#/checked_sources"
                                ),
                                "observed_at": "2026-06-30T05:00:00+00:00",
                            },
                            {
                                "requirement": "worker_persisted_evidence_path",
                                "evidence_ref": (
                                    f"{hosted_source_artifact}#/checked_sources"
                                ),
                                "observed_at": "2026-06-30T05:00:00+00:00",
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--completion-evidence-json",
            str(evidence_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    gates = {gate["gate_key"]: gate for gate in payload["gates"]}
    assert gates["hosted_worker_persisted_evidence"]["blocking_items"] == [
        "raw_snapshot_retention_policy",
        "monitored_scheduler_cadence",
        "hosted_egress_review",
    ]


def _complete_evidence_overlay(plan: dict) -> dict:
    return {
        "schema_version": "local-source-completion-evidence/v1",
        "captured_at": "2026-06-30T12:00:00+08:00",
        "signal_family_gap_evidence": [
            {
                "county": county,
                "signal_type": group["signal_type"],
                "status": "official_unavailable",
                "evidence_ref": (
                    f"private-ops://local-source/{county}/{group['signal_type']}"
                ),
            }
            for group in plan["signal_gap_priority_groups"]
            for county in group["counties"]
        ],
        "source_contract_evidence": [
            *_source_contract_evidence(
                plan["authorization_requests"],
                gate="authorization_request",
            ),
            *_source_contract_evidence(
                plan["metadata_release_monitors"],
                gate="metadata_release_monitor",
            ),
            *_source_contract_evidence(
                plan["public_api_contract_reviews"],
                gate="public_api_contract_review",
            ),
        ],
        "production_gate_evidence": [
            {
                "gate_key": "hosted_worker_persisted_evidence",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/worker-persisted-evidence",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "hosted_worker_persisted_evidence"
                    ]
                ),
                "requirement_evidence": _requirement_evidence(
                    "hosted_worker_persisted_evidence",
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "hosted_worker_persisted_evidence"
                    ],
                ),
            },
            {
                "gate_key": "production_deployment_evidence",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/main-deployment",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "production_deployment_evidence"
                    ]
                ),
                "requirement_evidence": _requirement_evidence(
                    "production_deployment_evidence",
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "production_deployment_evidence"
                    ],
                ),
            },
            {
                "gate_key": "production_monitoring_and_alerting",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/alert-routing",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "production_monitoring_and_alerting"
                    ]
                ),
                "requirement_evidence": _requirement_evidence(
                    "production_monitoring_and_alerting",
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "production_monitoring_and_alerting"
                    ],
                ),
            },
            {
                "gate_key": "public_risk_worker_evidence_path",
                "status": "accepted",
                "evidence_ref": "private-ops://zeabur/public-risk-smoke",
                "satisfied_requirements": list(
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "public_risk_worker_evidence_path"
                    ]
                ),
                "requirement_evidence": _requirement_evidence(
                    "public_risk_worker_evidence_path",
                    PRODUCTION_GATE_REQUIRED_REQUIREMENTS[
                        "public_risk_worker_evidence_path"
                    ],
                ),
            },
        ],
    }


def _requirement_evidence(gate_key: str, requirements: tuple[str, ...]) -> list[dict]:
    return [
        {
            "requirement": requirement,
            "evidence_ref": f"private-ops://local-source/{gate_key}/{requirement}",
            "observed_at": "2026-06-30T12:00:00+08:00",
        }
        for requirement in requirements
    ]


def _local_public_risk_requirement_evidence(artifact: Path) -> list[dict]:
    return [
        {
            "requirement": "hosted_risk_response_worker_evidence_smoke",
            "evidence_ref": f"{artifact}#/risk_assessment/worker_evidence",
            "observed_at": "2026-06-30T05:00:00+00:00",
        },
        {
            "requirement": "query_point_nearby_coverage_smoke",
            "evidence_ref": f"{artifact}#/risk_assessment/nearby_coverage",
            "observed_at": "2026-06-30T05:00:00+00:00",
        },
    ]


def _source_contract_evidence(items: list[dict], *, gate: str) -> list[dict]:
    return [
        {
            "county": item["county"],
            "gate": gate,
            "status": "accepted",
            "evidence_ref": f"private-ops://local-source/{gate}/{item['county']}",
        }
        for item in items
    ]
