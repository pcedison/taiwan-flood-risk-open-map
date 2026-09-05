"""Derive `runtime_state` in the official source catalog from the source registry.

`config/source-registry.yaml` is the canonical enablement decision. The official
source catalog keeps dataset identity plus a manually reviewed `status` field
that can lag those decisions, so the machine-readable runtime view is generated
here instead of being maintained by hand. CI runs `--check`, which fails when the
committed catalog no longer matches the registry.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "source-registry.yaml"
CATALOG_PATH = REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"

# Every enablement decision the registry may record maps to exactly one runtime
# state. A decision that is missing here is a hard error rather than a guess: a
# new decision needs a deliberate runtime meaning.
RUNTIME_STATE_BY_ENABLEMENT_DECISION: Mapping[str, str] = {
    "production_backbone": "live",
    "eligible_default_off": "available_off",
    "candidate": "available_off",
    "development_only": "available_off",
    "audit_only": "retired",
    "superseded": "retired",
    "blocked_pending_approval": "blocked",
    "authorization_pending": "blocked",
    "contract_review_pending": "blocked",
    "credential_and_contract_pending": "blocked",
    "context_only": "reference",
    "planning_reference": "reference",
    "request_time_fallback": "reference",
    "request_time_legacy": "reference",
}

# Catalog entries the registry does not decide on (currently the geocoder inputs).
UNREGISTERED_RUNTIME_STATE = "unregistered"

RUNTIME_STATE_FIELD = "runtime_state"
_ENTRY_PREFIX = "  - "
_FIELD_INDENT = "    "


class RuntimeStateRenderError(RuntimeError):
    """Raised when the registry or the catalog cannot be rendered."""


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RuntimeStateRenderError(f"cannot load {path}: {exc}") from exc


def load_runtime_states_by_adapter_key(
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, str]:
    """Map every registry adapter key to its derived runtime state."""
    payload = _load_yaml(registry_path)
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list) or not sources:
        raise RuntimeStateRenderError(f"{registry_path}: sources must be a non-empty list")

    runtime_states: dict[str, str] = {}
    unknown: dict[str, list[str]] = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise RuntimeStateRenderError(f"{registry_path}: sources[{index}] must be a mapping")
        adapter_key = source.get("adapter_key")
        decision = source.get("enablement_decision")
        if not isinstance(adapter_key, str) or not isinstance(decision, str):
            raise RuntimeStateRenderError(
                f"{registry_path}: sources[{index}] needs string "
                "adapter_key and enablement_decision"
            )
        runtime_state = RUNTIME_STATE_BY_ENABLEMENT_DECISION.get(decision)
        if runtime_state is None:
            unknown.setdefault(decision, []).append(adapter_key)
            continue
        runtime_states[adapter_key] = runtime_state

    if unknown:
        detail = "; ".join(
            f"{decision} ({', '.join(sorted(keys))})" for decision, keys in sorted(unknown.items())
        )
        raise RuntimeStateRenderError(
            "unmapped enablement_decision values; add them to "
            f"RUNTIME_STATE_BY_ENABLEMENT_DECISION: {detail}"
        )
    return runtime_states


def expected_runtime_states(
    catalog_path: Path = CATALOG_PATH,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, str]:
    """Map every catalog source key to the runtime state the registry implies."""
    registry_states = load_runtime_states_by_adapter_key(registry_path)
    payload = _load_yaml(catalog_path)
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list) or not sources:
        raise RuntimeStateRenderError(f"{catalog_path}: sources must be a non-empty list")

    expected: dict[str, str] = {}
    for index, source in enumerate(sources):
        key = source.get("key") if isinstance(source, dict) else None
        if not isinstance(key, str):
            raise RuntimeStateRenderError(f"{catalog_path}: sources[{index}] is missing key")
        expected[key] = registry_states.get(key, UNREGISTERED_RUNTIME_STATE)
    return expected


def check_catalog_runtime_state(
    catalog_path: Path = CATALOG_PATH,
    registry_path: Path = REGISTRY_PATH,
) -> list[str]:
    """Return one message per catalog source whose runtime state is stale."""
    expected = expected_runtime_states(catalog_path, registry_path)
    payload = _load_yaml(catalog_path)
    actual = {
        source["key"]: source.get(RUNTIME_STATE_FIELD)
        for source in payload["sources"]
        if isinstance(source, dict) and isinstance(source.get("key"), str)
    }

    differences: list[str] = []
    for key, wanted in expected.items():
        current = actual.get(key)
        if current is None:
            differences.append(f"{key}: missing runtime_state, expected {wanted!r}")
        elif current != wanted:
            differences.append(f"{key}: runtime_state {current!r}, expected {wanted!r}")
    return differences


def render_catalog_text(text: str, expected: Mapping[str, str]) -> str:
    """Rewrite the catalog text so each source carries its derived runtime state.

    Only `runtime_state` lines are added, replaced, or removed; every other line,
    including comments and quoting, is preserved byte for byte.
    """
    rendered: list[str] = []
    entry: list[str] | None = None
    entry_key: str | None = None
    in_sources = False
    seen: set[str] = set()

    def flush() -> None:
        nonlocal entry, entry_key
        if entry is not None:
            rendered.extend(_render_entry(entry, entry_key, expected))
        entry = None
        entry_key = None

    for line in text.split("\n"):
        if not in_sources:
            if line == "sources:":
                in_sources = True
            rendered.append(line)
            continue
        if line.startswith(_ENTRY_PREFIX):
            flush()
            entry_key = _entry_key(line)
            if entry_key is not None:
                seen.add(entry_key)
            entry = [line]
            continue
        if line and not line.startswith(" ") and not line.startswith("#"):
            flush()
            in_sources = False
            rendered.append(line)
            continue
        if entry is None:
            rendered.append(line)
            continue
        entry.append(line)
    flush()

    missing = sorted(set(expected) - seen)
    if missing:
        raise RuntimeStateRenderError(f"catalog text is missing source entries: {missing}")
    return "\n".join(rendered)


def _entry_key(line: str) -> str | None:
    field, separator, value = line[len(_ENTRY_PREFIX) :].partition(":")
    if not separator or field.strip() != "key":
        return None
    return value.strip().strip("\"'")


def _render_entry(
    entry: list[str],
    entry_key: str | None,
    expected: Mapping[str, str],
) -> list[str]:
    body = [line for line in entry if not _is_runtime_state_line(line)]
    runtime_state = expected.get(entry_key) if entry_key is not None else None
    if runtime_state is None:
        return body

    anchor = 0
    for index, line in enumerate(body):
        if line.startswith(f"{_FIELD_INDENT}status:"):
            anchor = index
            break
    field_line = f"{_FIELD_INDENT}{RUNTIME_STATE_FIELD}: {runtime_state}"
    return [*body[: anchor + 1], field_line, *body[anchor + 1 :]]


def _is_runtime_state_line(line: str) -> bool:
    return line.startswith(f"{_FIELD_INDENT}{RUNTIME_STATE_FIELD}:")


def render_catalog_file(
    catalog_path: Path = CATALOG_PATH,
    registry_path: Path = REGISTRY_PATH,
) -> bool:
    """Write the derived runtime states into the catalog; return True when changed."""
    expected = expected_runtime_states(catalog_path, registry_path)
    original = catalog_path.read_bytes()
    rendered = render_catalog_text(original.decode("utf-8"), expected).encode("utf-8")
    if rendered == original:
        return False
    catalog_path.write_bytes(rendered)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive the official source catalog runtime_state from the source registry."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift and exit non-zero instead of writing the catalog.",
    )
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)

    try:
        if args.check:
            differences = check_catalog_runtime_state(args.catalog, args.registry)
            if differences:
                detail = "\n".join(f"- {difference}" for difference in differences)
                print(
                    "Catalog runtime_state is stale; rerun "
                    "`python infra/scripts/render_source_catalog_runtime_state.py`:\n"
                    f"{detail}",
                    file=sys.stderr,
                )
                return 1
            print(f"Catalog runtime_state matches {args.registry}.")
            return 0
        changed = render_catalog_file(args.catalog, args.registry)
    except RuntimeStateRenderError as exc:
        print(f"Cannot render catalog runtime_state:\n{exc}", file=sys.stderr)
        return 1

    print(f"Catalog runtime_state {'updated' if changed else 'already up to date'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
