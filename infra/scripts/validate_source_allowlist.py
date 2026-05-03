from __future__ import annotations

from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "docs" / "data-sources" / "news" / "l2-source-allowlist.yaml"
FORUM_MANIFEST = (
    REPO_ROOT / "docs" / "data-sources" / "forum" / "source-approval-manifest.yaml"
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
    "acceptance_status",
    "accepted",
    "disabled_reason",
    "missing_acceptance_fields",
    "prohibited_until_accepted",
}
REQUIRED_FORUM_PROHIBITIONS = {
    "real_crawling",
    "scraping",
    "http_fetch",
}


def main() -> int:
    payload = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8"))
    forum_payload = yaml.safe_load(FORUM_MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []

    if not isinstance(payload, dict):
        print("Allowlist must be a YAML object.", file=sys.stderr)
        return 1
    if not isinstance(forum_payload, dict):
        print("Forum source approval manifest must be a YAML object.", file=sys.stderr)
        return 1

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

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"Source allowlist valid. news_sources={len(sources)} forum_sources={len(forum_sources)}")
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
