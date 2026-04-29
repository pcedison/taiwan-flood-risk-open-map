from __future__ import annotations

from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "docs" / "data-sources" / "news" / "l2-source-allowlist.yaml"
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


def main() -> int:
    payload = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8"))
    errors: list[str] = []

    if not isinstance(payload, dict):
        print("Allowlist must be a YAML object.", file=sys.stderr)
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

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"Source allowlist valid. sources={len(sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
