from __future__ import annotations

import json
from pathlib import Path

from app.jobs.gdelt_live_acceptance import validate_gdelt_live_acceptance_file
from app.main import main


def test_gdelt_live_acceptance_happy_path(tmp_path: Path) -> None:
    evidence_path = _write_evidence(tmp_path, _production_complete_evidence())

    result = validate_gdelt_live_acceptance_file(evidence_path)

    assert result.status == "succeeded"
    assert result.production_complete is True
    assert result.errors == ()


def test_gdelt_live_acceptance_missing_legal_approval(tmp_path: Path) -> None:
    evidence = _production_complete_evidence()
    evidence = evidence.replace(
        "legal_source_approval_ref: ops://legal/gdelt-live/source-approval-2026-05-04\n",
        "",
    )
    evidence_path = _write_evidence(tmp_path, evidence)

    result = validate_gdelt_live_acceptance_file(evidence_path)

    assert result.status == "failed"
    assert any("legal_source_approval_ref" in error for error in result.errors)


def test_gdelt_live_acceptance_rejects_cadence_below_configured_minimum(
    tmp_path: Path,
) -> None:
    evidence = _production_complete_evidence().replace(
        "cadence_seconds: 120",
        "cadence_seconds: 30",
    )
    evidence_path = _write_evidence(tmp_path, evidence)

    result = validate_gdelt_live_acceptance_file(evidence_path)

    assert result.status == "failed"
    assert result.errors == (
        "cadence_seconds must be greater than or equal to "
        "configured_minimum_cadence_seconds",
    )


def test_gdelt_live_acceptance_rejects_placeholder_owner_for_production_complete(
    tmp_path: Path,
) -> None:
    evidence = _production_complete_evidence().replace(
        "source_owner: Jamie Lin",
        "source_owner: source-owner",
    )
    evidence_path = _write_evidence(tmp_path, evidence)

    result = validate_gdelt_live_acceptance_file(evidence_path)

    assert result.status == "failed"
    assert result.errors == (
        "source_owner must name a real owner, not a template placeholder",
    )


def test_gdelt_live_acceptance_rejects_runbook_only_production_ref(
    tmp_path: Path,
) -> None:
    evidence = _production_complete_evidence().replace(
        "rollback_kill_switch_ref: ops://runbooks/source-kill-switch/gdelt-live-2026-05-04",
        "rollback_kill_switch_ref: docs/runbooks/production-readiness.md#source-kill-switch",
    )
    evidence_path = _write_evidence(tmp_path, evidence)

    result = validate_gdelt_live_acceptance_file(evidence_path)

    assert result.status == "failed"
    assert result.errors == (
        "rollback_kill_switch_ref must reference production evidence, "
        "not only runbook instructions",
    )


def test_gdelt_live_acceptance_cli_outputs_no_network_json(
    tmp_path: Path,
    capsys,
) -> None:
    evidence_path = _write_evidence(tmp_path, _production_complete_evidence())

    exit_code = main(["--validate-gdelt-live-acceptance", str(evidence_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["network_allowed"] is False
    assert payload["mode"] == "gdelt-live-acceptance"
    assert payload["production_complete"] is True


def test_gdelt_live_acceptance_checked_in_example_is_not_production_complete() -> None:
    result = validate_gdelt_live_acceptance_file(
        Path(__file__).resolve().parents[3]
        / "docs"
        / "data-sources"
        / "news"
        / "gdelt-live-acceptance.example.yaml"
    )

    assert result.status == "skipped"
    assert result.reason == "not-production-complete"
    assert result.production_complete is False


def _write_evidence(tmp_path: Path, content: str) -> Path:
    evidence_path = tmp_path / "gdelt-live-acceptance.yaml"
    evidence_path.write_text(content, encoding="utf-8")
    return evidence_path


def _production_complete_evidence() -> str:
    return """\
schema_version: gdelt-live-acceptance/v1
production_complete: true
readiness_state: production-complete
legal_source_approval_ref: ops://legal/gdelt-live/source-approval-2026-05-04
source_owner: Jamie Lin
egress_owner: Morgan Chen
rate_limit_policy: ops://source/gdelt-live/rate-limit-policy-2026-05-04
cadence_seconds: 120
configured_minimum_cadence_seconds: 60
alert_owner: Priya Shah
alert_route: pagerduty://flood-risk/source-freshness
production_persistence_evidence_ref: ops://runs/gdelt-live/promotion-evidence-2026-05-04
rollback_kill_switch_ref: ops://runbooks/source-kill-switch/gdelt-live-2026-05-04
last_dry_run_or_prod_candidate_evidence_ref: ops://runs/gdelt-production-candidate/2026-05-04
"""
