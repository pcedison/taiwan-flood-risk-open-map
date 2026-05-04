from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from infra.scripts.validate_source_allowlist import (  # noqa: E402
    ALLOWLIST,
    FORUM_APPROVAL_EXAMPLE,
    FORUM_MANIFEST,
    validate_all,
)


REQUIRED_EVIDENCE = (
    "terms",
    "privacy",
    "retention",
    "moderation",
    "opt_out",
    "rate_limit",
)


def test_checked_in_forum_manifest_and_rejected_example_are_valid() -> None:
    assert validate_all(approval_request_paths=[FORUM_APPROVAL_EXAMPLE]) == []


def test_ptt_and_dcard_remain_not_accepted_in_manifest() -> None:
    manifest = yaml.safe_load(FORUM_MANIFEST.read_text(encoding="utf-8"))
    sources = {source["key"]: source for source in manifest["sources"]}

    assert sources["ptt"]["accepted"] is False
    assert sources["ptt"]["acceptance_status"] == "blocked"
    assert sources["ptt"]["candidate_approval_ack_flag"] == (
        "SOURCE_PTT_CANDIDATE_APPROVAL_ACK"
    )
    assert sources["ptt"]["candidate_adapter_contract"]["runtime_mode"] == (
        "local_fixture_only"
    )
    assert sources["ptt"]["candidate_adapter_contract"]["http_fetch"] is False
    assert sources["dcard"]["accepted"] is False
    assert sources["dcard"]["acceptance_status"] == "blocked"
    assert sources["dcard"]["candidate_approval_ack_flag"] == (
        "SOURCE_DCARD_CANDIDATE_APPROVAL_ACK"
    )
    assert sources["dcard"]["candidate_adapter_contract"]["runtime_mode"] == (
        "local_fixture_only"
    )
    assert sources["dcard"]["candidate_adapter_contract"]["http_fetch"] is False


def test_forum_manifest_requires_candidate_approval_ack_flag(tmp_path: Path) -> None:
    manifest = yaml.safe_load(FORUM_MANIFEST.read_text(encoding="utf-8"))
    manifest["sources"][0].pop("candidate_approval_ack_flag")
    manifest_path = _write_yaml(tmp_path, manifest, name="forum-manifest.yaml")

    errors = validate_all(
        allowlist_path=ALLOWLIST,
        forum_manifest_path=manifest_path,
        approval_request_paths=[FORUM_APPROVAL_EXAMPLE],
    )

    assert any("missing fields ['candidate_approval_ack_flag']" in error for error in errors)


def test_forum_manifest_rejects_network_candidate_contract(tmp_path: Path) -> None:
    manifest = yaml.safe_load(FORUM_MANIFEST.read_text(encoding="utf-8"))
    manifest["sources"][0]["candidate_adapter_contract"]["http_fetch"] = True
    manifest_path = _write_yaml(tmp_path, manifest, name="forum-manifest.yaml")

    errors = validate_all(
        allowlist_path=ALLOWLIST,
        forum_manifest_path=manifest_path,
        approval_request_paths=[FORUM_APPROVAL_EXAMPLE],
    )

    assert any(
        "forum ptt: candidate_adapter_contract.http_fetch must be false" in error
        for error in errors
    )


@pytest.mark.parametrize("missing_category", REQUIRED_EVIDENCE)
def test_accepted_request_requires_each_evidence_category(
    tmp_path: Path,
    missing_category: str,
) -> None:
    request = _base_request(accepted=True)
    del request["request"]["evidence"][missing_category]
    request_path = _write_yaml(tmp_path, request)

    errors = validate_all(
        allowlist_path=ALLOWLIST,
        forum_manifest_path=FORUM_MANIFEST,
        approval_request_paths=[request_path],
    )

    assert any(f"evidence missing categories ['{missing_category}']" in error for error in errors)


@pytest.mark.parametrize(
    "operation",
    (
        "real_crawling",
        "scraping",
        "http_fetch",
        "login_bypass",
        "anti_bot_circumvention",
        "private_content_access",
        "raw_content_storage",
        "identity_storage",
    ),
)
def test_approval_request_cannot_ask_for_real_collection_boundary(
    tmp_path: Path,
    operation: str,
) -> None:
    request = _base_request(accepted=False)
    request["request"]["proposed_collection"]["allowed_operations"] = [operation]
    request_path = _write_yaml(tmp_path, request)

    errors = validate_all(
        allowlist_path=ALLOWLIST,
        forum_manifest_path=FORUM_MANIFEST,
        approval_request_paths=[request_path],
    )

    assert any(f"allowed_operations must not include ['{operation}']" in error for error in errors)


def test_approval_request_cannot_include_http_fetcher_implementation(
    tmp_path: Path,
) -> None:
    request = _base_request(accepted=False)
    request["request"]["boundary"]["http_fetch_included"] = True
    request_path = _write_yaml(tmp_path, request)

    errors = validate_all(
        allowlist_path=ALLOWLIST,
        forum_manifest_path=FORUM_MANIFEST,
        approval_request_paths=[request_path],
    )

    assert any(
        "boundary.http_fetch_included must be false for approval-only requests" in error
        for error in errors
    )


@pytest.mark.parametrize(
    ("field", "path"),
    (
        ("raw_content_storage", "request.proposed_collection.raw_content_storage"),
        ("identity_storage", "request.governance.identity_storage"),
        ("login_bypass", "request.boundary.login_bypass"),
        ("anti_bot_circumvention", "request.proposed_collection.review.anti_bot_circumvention"),
    ),
)
def test_approval_request_cannot_enable_disallowed_flags_in_extra_fields(
    tmp_path: Path,
    field: str,
    path: str,
) -> None:
    request = _base_request(accepted=False)
    _set_nested(request["request"], path.removeprefix("request.").split("."), True)
    request_path = _write_yaml(tmp_path, request)

    errors = validate_all(
        allowlist_path=ALLOWLIST,
        forum_manifest_path=FORUM_MANIFEST,
        approval_request_paths=[request_path],
    )

    assert any(f"{path} must not enable {field}" in error for error in errors)


def _base_request(accepted: bool) -> dict[str, object]:
    decision = "accepted" if accepted else "rejected"
    evidence = {category: _approved_evidence(category) for category in REQUIRED_EVIDENCE}
    return {
        "version": 1,
        "request": {
            "source_key": "ptt",
            "platform": "PTT",
            "requested_acceptance": {
                "accepted": accepted,
                "decision": decision,
                "reason": "test request",
            },
            "proposed_collection": {
                "access_method": "reviewed-public-api-or-manual-import-only",
                "allowed_operations": [],
                "requested_operations": [],
                "prohibited_operations_ack": [
                    "real_crawling",
                    "scraping",
                    "http_fetch",
                    "login_bypass",
                    "anti_bot_circumvention",
                    "private_content_access",
                    "raw_content_storage",
                    "identity_storage",
                ],
            },
            "evidence": evidence,
            "governance": {
                "requested_by": "test",
                "reviewed_by": ["legal", "privacy"],
                "review_date": "2026-05-03",
                "public_contact_or_opt_out": "privacy-review-ref",
                "emergency_disable_owner": "source-owner",
            },
            "boundary": {
                "implementation_included": False,
                "fetcher_included": False,
                "crawler_included": False,
                "scraper_included": False,
                "http_fetch_included": False,
            },
        },
    }


def _approved_evidence(category: str) -> dict[str, object]:
    return {
        "status": "approved",
        "reviewed": True,
        "reviewed_by": "reviewer",
        "reviewed_on": "2026-05-03",
        "summary": f"{category} evidence approved for validator coverage.",
        "references": [f"docs/reviews/{category}-approval.md"],
    }


def _write_yaml(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    name: str = "source-approval-request.yaml",
) -> Path:
    request_path = tmp_path / name
    request_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return request_path


def _set_nested(payload: object, keys: list[str], value: object) -> None:
    assert isinstance(payload, dict)
    current = payload
    for key in keys[:-1]:
        next_value = current.setdefault(key, {})
        assert isinstance(next_value, dict)
        current = next_value
    current[keys[-1]] = value
