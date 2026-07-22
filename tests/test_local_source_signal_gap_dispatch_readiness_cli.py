from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "local-source-signal-gap-dispatch-readiness.py"


def test_signal_gap_dispatch_readiness_cli_merges_discovery_with_batches(
    tmp_path: Path,
) -> None:
    discovery_summary = tmp_path / "signal-gap-discovery-refresh-summary.json"
    discovery_summary.write_text(
        json.dumps(
            {
                "schema_version": "local-source-signal-gap-discovery-refresh/v1",
                "captured_at": "2026-07-01T03:03:06Z",
                "source_catalog_url": "https://data.gov.tw/api/front/dataset/export?format=json",
                "signal_gap_group_count": 3,
                "total_candidate_count": 11,
                "total_metadata_only_count": 11,
                "total_candidate_live_read_api_count": 0,
                "live_candidate_signal_types": [],
                "groups": [
                    {
                        "artifact_name": "signal-gap-discovery-refresh-pump-or-gate-status.json",
                        "signal_type": "pump_or_gate_status",
                        "county_count": 13,
                        "candidate_count": 9,
                        "metadata_only_count": 9,
                        "candidate_live_read_api_count": 0,
                        "target_counties": ["連江縣", "金門縣"],
                        "target_counties_without_candidates": ["連江縣"],
                        "readiness_by_county": {
                            "連江縣": {
                                "candidate_count": 0,
                                "metadata_only_count": 0,
                                "candidate_live_read_api_count": 0,
                                "readiness_state": "no_candidate",
                                "signal_types": [],
                            },
                            "金門縣": {
                                "candidate_count": 2,
                                "metadata_only_count": 2,
                                "candidate_live_read_api_count": 0,
                                "readiness_state": "metadata_only",
                                "signal_types": ["pump_or_gate_status"],
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "dispatch-readiness.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--discovery-summary-json",
            str(discovery_summary),
            "--captured-at",
            "2026-07-01T11:20:00+08:00",
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
    assert result.stdout == ""
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "local-source-signal-gap-dispatch-readiness/v1"
    assert payload["captured_at"] == "2026-07-01T11:20:00+08:00"
    assert payload["discovery_summary"]["captured_at"] == "2026-07-01T03:03:06Z"
    assert payload["summary"] == {
        "signal_gap_group_count": 3,
        "dispatch_recommended_group_count": 3,
        "total_candidate_count": 11,
        "total_metadata_only_count": 11,
        "total_candidate_live_read_api_count": 0,
    }

    pump_group = payload["groups"][0]
    assert pump_group["target_signal_type"] == "pump_or_gate_status"
    assert pump_group["dispatch_recommended"] is True
    assert pump_group["dispatch_reasons"] == [
        "no_live_read_api_candidate",
        "metadata_only_candidates_require_contract_followup",
    ]
    assert pump_group["county_count"] == 13
    assert pump_group["discovery"]["candidate_count"] == 9
    assert pump_group["discovery"]["metadata_only_count"] == 9
    assert pump_group["discovery"]["candidate_live_read_api_count"] == 0
    assert pump_group["discovery"]["counties_without_candidates"] == ["連江縣"]
    assert pump_group["discovery"]["metadata_only_counties"] == ["金門縣"]
    assert "--format signal-gap-dispatch-evidence" in pump_group["dispatch_command"]
    assert "REPLACE_WITH_PRIVATE_DISPATCH_EVIDENCE_REF" in pump_group[
        "dispatch_command"
    ]
    assert "private-ops://" not in json.dumps(payload, ensure_ascii=False)


def test_signal_gap_dispatch_readiness_cli_rejects_wrong_discovery_schema(
    tmp_path: Path,
) -> None:
    discovery_summary = tmp_path / "wrong-summary.json"
    discovery_summary.write_text(
        json.dumps({"schema_version": "wrong/v1"}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--discovery-summary-json",
            str(discovery_summary),
            "--captured-at",
            "2026-07-01T11:20:00+08:00",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "schema_version" in result.stderr


def test_signal_gap_dispatch_readiness_cli_omits_accepted_target(
    tmp_path: Path,
) -> None:
    discovery_summary = tmp_path / "signal-gap-discovery-refresh-summary.json"
    discovery_summary.write_text(
        json.dumps(
            {
                "schema_version": "local-source-signal-gap-discovery-refresh/v1",
                "captured_at": "2026-07-22T03:00:00Z",
                "groups": [],
            }
        ),
        encoding="utf-8",
    )
    completion_evidence = tmp_path / "completion-evidence.json"
    private_ref = "private-ops://local-source/review/secret-ticket"
    completion_evidence.write_text(
        json.dumps(
            {
                "schema_version": "local-source-completion-evidence/v1",
                "captured_at": "2026-07-22T03:01:00Z",
                "signal_family_gap_evidence": [
                    {
                        "county": "連江縣",
                        "signal_type": "pump_or_gate_status",
                        "status": "official_unavailable",
                        "evidence_ref": private_ref,
                        "reviewed_at": "2026-07-22T03:01:00Z",
                    }
                ],
                "source_contract_evidence": [],
                "production_gate_evidence": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--discovery-summary-json",
            str(discovery_summary),
            "--completion-evidence-json",
            str(completion_evidence),
            "--captured-at",
            "2026-07-22T03:02:00Z",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert private_ref not in result.stdout
    payload = json.loads(result.stdout)
    pump_group = next(
        group
        for group in payload["groups"]
        if group["target_signal_type"] == "pump_or_gate_status"
    )
    assert pump_group["county_count"] == 12
    assert pump_group["completion_evidence_target_count"] == 12
