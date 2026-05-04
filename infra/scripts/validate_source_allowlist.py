from __future__ import annotations

from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "docs" / "data-sources" / "news" / "l2-source-allowlist.yaml"
FORUM_MANIFEST = (
    REPO_ROOT / "docs" / "data-sources" / "forum" / "source-approval-manifest.yaml"
)
FORUM_APPROVAL_EXAMPLE = (
    REPO_ROOT / "docs" / "data-sources" / "forum" / "source-approval-request.example.yaml"
)
REQUIRED_SOURCE_FIELDS = {
    "key",
    "adapter_key",
    "display_name",
    "source_family",
    "legal_basis",
    "status",
    "enabled_by_default",
    "homepage_url",
    "robots_reviewed",
    "terms_reviewed",
    "full_text_redistribution",
    "citation_required",
    "ingestion_frequency",
    "review_note",
}
REQUIRED_FORUM_FIELDS = {
    "key",
    "platform",
    "family",
    "registry_key",
    "source_specific_flag",
    "candidate_approval_ack_flag",
    "acceptance_status",
    "accepted",
    "disabled_reason",
    "missing_acceptance_fields",
    "prohibited_until_accepted",
    "candidate_adapter_contract",
}
REQUIRED_FORUM_PROHIBITIONS = {
    "real_crawling",
    "scraping",
    "http_fetch",
}
REQUIRED_FORUM_CANDIDATE_CONTRACT_FIELDS = {
    "runtime_mode",
    "fixture_records",
    "network_access",
    "real_source_records",
    "http_fetch",
    "crawl",
    "scrape",
    "login_bypass",
    "anti_bot_circumvention",
    "raw_content_storage",
    "identity_storage",
}
REQUIRED_FORUM_CANDIDATE_FALSE_FIELDS = {
    "real_source_records",
    "http_fetch",
    "crawl",
    "scrape",
    "login_bypass",
    "anti_bot_circumvention",
    "raw_content_storage",
    "identity_storage",
}
REQUIRED_APPROVAL_DISALLOWED_OPERATIONS = {
    "real_crawling",
    "scraping",
    "http_fetch",
    "login_bypass",
    "anti_bot_circumvention",
    "private_content_access",
    "raw_content_storage",
    "identity_storage",
}
REQUIRED_APPROVAL_SCHEMA_FIELDS = {
    "required_request_fields",
    "required_evidence_categories",
    "disallowed_requested_operations",
    "required_boundary_attestations",
}
REQUIRED_APPROVAL_REQUEST_FIELDS = {
    "source_key",
    "platform",
    "requested_acceptance",
    "proposed_collection",
    "evidence",
    "governance",
    "boundary",
}
REQUIRED_APPROVAL_EVIDENCE = {
    "terms",
    "privacy",
    "retention",
    "moderation",
    "opt_out",
    "rate_limit",
}
REQUIRED_BOUNDARY_ATTESTATIONS = {
    "implementation_included",
    "fetcher_included",
    "crawler_included",
    "scraper_included",
    "http_fetch_included",
}
ALLOWED_APPROVAL_DECISIONS = {"blocked", "rejected", "pending_review", "accepted"}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    approval_request_paths = [Path(arg) for arg in argv] if argv else None
    errors = validate_all(approval_request_paths=approval_request_paths)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    payload = _load_yaml(ALLOWLIST)
    forum_payload = _load_yaml(FORUM_MANIFEST)
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    forum_sources = forum_payload.get("sources", []) if isinstance(forum_payload, dict) else []
    print(f"Source allowlist valid. news_sources={len(sources)} forum_sources={len(forum_sources)}")
    return 0


def validate_all(
    allowlist_path: Path = ALLOWLIST,
    forum_manifest_path: Path = FORUM_MANIFEST,
    approval_request_paths: list[Path] | None = None,
) -> list[str]:
    payload = _load_yaml(allowlist_path)
    forum_payload = _load_yaml(forum_manifest_path)
    errors: list[str] = []

    if not isinstance(payload, dict):
        return ["Allowlist must be a YAML object."]
    if not isinstance(forum_payload, dict):
        return ["Forum source approval manifest must be a YAML object."]

    policy = payload.get("policy", {})
    allowed_legal_basis = set(policy.get("allowed_legal_basis", ()))
    disallowed_families = set(policy.get("disallowed_source_families", ()))
    full_text_allowed = bool(policy.get("full_text_redistribution_allowed", False))
    sources = payload.get("sources", [])

    if allowed_legal_basis != {"L2"}:
        errors.append("Phase 2 news allowlist must allow only L2 sources")
    if not isinstance(sources, list) or not sources:
        errors.append("Allowlist must contain at least one source")

    seen_keys: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be an object")
            continue

        missing = REQUIRED_SOURCE_FIELDS - set(source)
        if missing:
            errors.append(f"{source.get('key', f'sources[{index}]')}: missing fields {sorted(missing)}")
            continue

        key = str(source["key"])
        if key in seen_keys:
            errors.append(f"{key}: duplicate source key")
        seen_keys.add(key)

        legal_basis = str(source["legal_basis"])
        source_family = str(source["source_family"])
        if legal_basis not in allowed_legal_basis:
            errors.append(f"{key}: legal_basis {legal_basis} is not allowed in Phase 2")
        if source_family in disallowed_families:
            errors.append(f"{key}: source_family {source_family} is disallowed in Phase 2")
        if source.get("full_text_redistribution") and not full_text_allowed:
            errors.append(f"{key}: full text redistribution is not allowed by policy")
        if source.get("enabled_by_default"):
            if not source.get("robots_reviewed"):
                errors.append(f"{key}: enabled sources must have robots_reviewed=true")
            if not source.get("terms_reviewed"):
                errors.append(f"{key}: enabled sources must have terms_reviewed=true")
            if source.get("status") not in {"fixture_only", "approved"}:
                errors.append(f"{key}: enabled sources must be fixture_only or approved")

    forum_sources = forum_payload.get("sources", [])
    if forum_payload.get("default") != "disabled":
        errors.append("forum manifest: default must be disabled")
    if forum_payload.get("global_enable_flag") != "SOURCE_FORUM_ENABLED":
        errors.append("forum manifest: global_enable_flag must be SOURCE_FORUM_ENABLED")
    if forum_payload.get("terms_ack_flag") != "SOURCE_TERMS_REVIEW_ACK":
        errors.append("forum manifest: terms_ack_flag must be SOURCE_TERMS_REVIEW_ACK")
    if not isinstance(forum_sources, list) or not forum_sources:
        errors.append("forum manifest must contain at least one source")
    else:
        _validate_forum_sources(forum_sources, errors)

    _validate_approval_schema(forum_payload, errors)

    if approval_request_paths is None:
        approval_request_paths = [FORUM_APPROVAL_EXAMPLE] if FORUM_APPROVAL_EXAMPLE.exists() else []
    for request_path in approval_request_paths:
        request_payload = _load_yaml(request_path)
        validate_forum_approval_request(
            request_payload,
            forum_payload,
            errors,
            label=_display_path(request_path),
        )

    return errors


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validate_forum_sources(sources: list[object], errors: list[str]) -> None:
    seen_keys: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"forum sources[{index}] must be an object")
            continue

        missing = REQUIRED_FORUM_FIELDS - set(source)
        key = str(source.get("key", f"sources[{index}]"))
        if missing:
            errors.append(f"forum {key}: missing fields {sorted(missing)}")
            continue

        if key in seen_keys:
            errors.append(f"forum {key}: duplicate source key")
        seen_keys.add(key)

        if source.get("family") != "forum":
            errors.append(f"forum {key}: family must be forum")
        expected_ack_flag = f"SOURCE_{key.upper()}_CANDIDATE_APPROVAL_ACK"
        if source.get("candidate_approval_ack_flag") != expected_ack_flag:
            errors.append(
                f"forum {key}: candidate_approval_ack_flag must be {expected_ack_flag}"
            )
        if source.get("accepted") is not False:
            errors.append(f"forum {key}: accepted must remain false until governance approval")
        if source.get("acceptance_status") not in {"blocked", "non_accepted"}:
            errors.append(f"forum {key}: acceptance_status must be blocked or non_accepted")
        if not str(source.get("disabled_reason", "")).strip():
            errors.append(f"forum {key}: disabled_reason is required")

        missing_acceptance_fields = source.get("missing_acceptance_fields")
        if not isinstance(missing_acceptance_fields, list) or len(missing_acceptance_fields) < 8:
            errors.append(f"forum {key}: missing_acceptance_fields must list launch blockers")

        prohibitions = source.get("prohibited_until_accepted")
        if not isinstance(prohibitions, list):
            errors.append(f"forum {key}: prohibited_until_accepted must be a list")
            continue
        missing_prohibitions = REQUIRED_FORUM_PROHIBITIONS - {str(item) for item in prohibitions}
        if missing_prohibitions:
            errors.append(
                f"forum {key}: prohibited_until_accepted missing {sorted(missing_prohibitions)}"
            )

        candidate_contract = source.get("candidate_adapter_contract")
        if not isinstance(candidate_contract, dict):
            errors.append(f"forum {key}: candidate_adapter_contract must be an object")
            continue
        _validate_forum_candidate_contract(key, candidate_contract, errors)


def _validate_forum_candidate_contract(
    key: str,
    contract: dict[object, object],
    errors: list[str],
) -> None:
    missing = REQUIRED_FORUM_CANDIDATE_CONTRACT_FIELDS - set(contract)
    if missing:
        errors.append(
            f"forum {key}: candidate_adapter_contract missing {sorted(missing)}"
        )

    if contract.get("runtime_mode") != "local_fixture_only":
        errors.append(
            f"forum {key}: candidate_adapter_contract.runtime_mode must be local_fixture_only"
        )
    if contract.get("fixture_records") != "synthetic_only":
        errors.append(
            f"forum {key}: candidate_adapter_contract.fixture_records must be synthetic_only"
        )
    if contract.get("network_access") != "disabled":
        errors.append(
            f"forum {key}: candidate_adapter_contract.network_access must be disabled"
        )

    for field in sorted(REQUIRED_FORUM_CANDIDATE_FALSE_FIELDS):
        if contract.get(field) is not False:
            errors.append(
                f"forum {key}: candidate_adapter_contract.{field} must be false"
            )


def _validate_approval_schema(forum_payload: dict[object, object], errors: list[str]) -> None:
    schema = forum_payload.get("approval_request_schema")
    if not isinstance(schema, dict):
        errors.append("forum manifest: approval_request_schema is required")
        return

    missing = REQUIRED_APPROVAL_SCHEMA_FIELDS - set(schema)
    if missing:
        errors.append(f"forum manifest: approval_request_schema missing {sorted(missing)}")

    request_fields = _string_set(schema.get("required_request_fields"))
    missing_request_fields = REQUIRED_APPROVAL_REQUEST_FIELDS - request_fields
    if missing_request_fields:
        errors.append(
            "forum manifest: approval_request_schema.required_request_fields missing "
            f"{sorted(missing_request_fields)}"
        )

    evidence_categories = _string_set(schema.get("required_evidence_categories"))
    missing_evidence = REQUIRED_APPROVAL_EVIDENCE - evidence_categories
    if missing_evidence:
        errors.append(
            "forum manifest: approval_request_schema.required_evidence_categories missing "
            f"{sorted(missing_evidence)}"
        )

    disallowed_operations = _string_set(schema.get("disallowed_requested_operations"))
    missing_disallowed = REQUIRED_APPROVAL_DISALLOWED_OPERATIONS - disallowed_operations
    if missing_disallowed:
        errors.append(
            "forum manifest: approval_request_schema.disallowed_requested_operations missing "
            f"{sorted(missing_disallowed)}"
        )

    boundary_attestations = _string_set(schema.get("required_boundary_attestations"))
    missing_attestations = REQUIRED_BOUNDARY_ATTESTATIONS - boundary_attestations
    if missing_attestations:
        errors.append(
            "forum manifest: approval_request_schema.required_boundary_attestations missing "
            f"{sorted(missing_attestations)}"
        )


def validate_forum_approval_request(
    payload: object,
    forum_payload: dict[object, object],
    errors: list[str],
    label: str = "forum approval request",
) -> None:
    if not isinstance(payload, dict):
        errors.append(f"{label}: request must be a YAML object")
        return

    request = payload.get("request", payload)
    if not isinstance(request, dict):
        errors.append(f"{label}: request must be an object")
        return

    missing = REQUIRED_APPROVAL_REQUEST_FIELDS - set(request)
    if missing:
        errors.append(f"{label}: missing request fields {sorted(missing)}")
        return

    source_key = str(request.get("source_key", ""))
    source = _forum_source_by_key(forum_payload, source_key)
    if source is None:
        errors.append(f"{label}: source_key {source_key!r} is not listed in forum manifest")
    elif source.get("accepted") is not False:
        errors.append(f"{label}: manifest source {source_key} must remain accepted=false")

    requested_acceptance = request.get("requested_acceptance")
    if not isinstance(requested_acceptance, dict):
        errors.append(f"{label}: requested_acceptance must be an object")
        return

    accepted = requested_acceptance.get("accepted")
    decision = requested_acceptance.get("decision")
    if not isinstance(accepted, bool):
        errors.append(f"{label}: requested_acceptance.accepted must be boolean")
    if decision not in ALLOWED_APPROVAL_DECISIONS:
        errors.append(
            f"{label}: requested_acceptance.decision must be one of {sorted(ALLOWED_APPROVAL_DECISIONS)}"
        )
    if accepted and decision != "accepted":
        errors.append(f"{label}: accepted=true requires requested_acceptance.decision=accepted")
    if not accepted and decision == "accepted":
        errors.append(f"{label}: decision=accepted requires requested_acceptance.accepted=true")

    _validate_collection_boundary(request, errors, label)
    _validate_disallowed_flag_fields(request, errors, label, path="request")

    evidence = request.get("evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{label}: evidence must be an object")
        return

    missing_evidence = REQUIRED_APPROVAL_EVIDENCE - set(evidence)
    if missing_evidence:
        errors.append(f"{label}: evidence missing categories {sorted(missing_evidence)}")

    if accepted is True:
        for category in sorted(REQUIRED_APPROVAL_EVIDENCE):
            _validate_complete_evidence(evidence.get(category), errors, label, category)


def _validate_collection_boundary(
    request: dict[object, object],
    errors: list[str],
    label: str,
) -> None:
    proposed_collection = request.get("proposed_collection")
    if not isinstance(proposed_collection, dict):
        errors.append(f"{label}: proposed_collection must be an object")
        return

    for field in ("allowed_operations", "requested_operations"):
        operations = _string_set(proposed_collection.get(field, []))
        prohibited = operations & REQUIRED_APPROVAL_DISALLOWED_OPERATIONS
        if prohibited:
            errors.append(f"{label}: {field} must not include {sorted(prohibited)}")

    acknowledged = _string_set(proposed_collection.get("prohibited_operations_ack"))
    missing_ack = REQUIRED_APPROVAL_DISALLOWED_OPERATIONS - acknowledged
    if missing_ack:
        errors.append(f"{label}: prohibited_operations_ack missing {sorted(missing_ack)}")

    boundary = request.get("boundary")
    if not isinstance(boundary, dict):
        errors.append(f"{label}: boundary must be an object")
        return

    missing_attestations = REQUIRED_BOUNDARY_ATTESTATIONS - set(boundary)
    if missing_attestations:
        errors.append(f"{label}: boundary missing {sorted(missing_attestations)}")

    for field in sorted(REQUIRED_BOUNDARY_ATTESTATIONS):
        if boundary.get(field) is not False:
            errors.append(f"{label}: boundary.{field} must be false for approval-only requests")


def _validate_disallowed_flag_fields(
    value: object,
    errors: list[str],
    label: str,
    *,
    path: str,
) -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key)
            item_path = f"{path}.{key}"
            if key in REQUIRED_APPROVAL_DISALLOWED_OPERATIONS and item not in (False, None, "", ()):
                errors.append(f"{label}: {item_path} must not enable {key}")
            _validate_disallowed_flag_fields(item, errors, label, path=item_path)
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_disallowed_flag_fields(item, errors, label, path=f"{path}[{index}]")


def _validate_complete_evidence(
    evidence: object,
    errors: list[str],
    label: str,
    category: str,
) -> None:
    if not isinstance(evidence, dict):
        errors.append(f"{label}: accepted=true requires {category} evidence object")
        return

    if evidence.get("status") != "approved":
        errors.append(f"{label}: accepted=true requires evidence.{category}.status=approved")
    if evidence.get("reviewed") is not True:
        errors.append(f"{label}: accepted=true requires evidence.{category}.reviewed=true")
    if not _nonempty_string(evidence.get("reviewed_by")):
        errors.append(f"{label}: accepted=true requires evidence.{category}.reviewed_by")
    if not _nonempty_string(evidence.get("reviewed_on")):
        errors.append(f"{label}: accepted=true requires evidence.{category}.reviewed_on")
    if not _nonempty_string(evidence.get("summary")):
        errors.append(f"{label}: accepted=true requires evidence.{category}.summary")
    references = evidence.get("references")
    if not isinstance(references, list) or not references:
        errors.append(f"{label}: accepted=true requires evidence.{category}.references")


def _forum_source_by_key(
    forum_payload: dict[object, object],
    source_key: str,
) -> dict[object, object] | None:
    sources = forum_payload.get("sources", [])
    if not isinstance(sources, list):
        return None
    for source in sources:
        if isinstance(source, dict) and source.get("key") == source_key:
            return source
    return None


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
