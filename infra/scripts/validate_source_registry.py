from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import yaml

try:  # imported as `infra.scripts.validate_source_registry`
    from infra.scripts.render_source_catalog_runtime_state import (
        RuntimeStateRenderError,
        check_catalog_runtime_state,
    )
except ImportError:  # executed as `python infra/scripts/validate_source_registry.py`
    from render_source_catalog_runtime_state import (
        RuntimeStateRenderError,
        check_catalog_runtime_state,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "source-registry.yaml"
WORKER_DIR = REPO_ROOT / "apps" / "workers"
ENTRYPOINT_PATH = REPO_ROOT / "infra" / "docker" / "entrypoint.sh"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
API_HISTORY_SOURCE_PATH = (
    REPO_ROOT / "apps" / "api" / "app" / "domain" / "history" / "news_enrichment.py"
)
OFFICIAL_SOURCE_CATALOG_PATH = (
    REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"
)

REQUIRED_SOURCE_FIELDS = frozenset(
    {
        "adapter_key",
        "family",
        "contract",
        "implementation",
        "runtime_scope",
        "worker_default_enabled",
        "catalog_state",
        "deployment_default",
        "enablement_decision",
    }
)
# Optional annotations. They record operational facts about a source without
# changing any enablement decision, so they must never be required.
OPTIONAL_SOURCE_FIELDS = frozenset({"upstream_incident"})
ALLOWED_FAMILIES = frozenset({"official", "news", "forum"})
ALLOWED_IMPLEMENTATIONS = frozenset({"worker", "api", "catalog"})
ALLOWED_RUNTIME_SCOPES = frozenset(
    {"v1_baseline", "context_only", "candidate", "development_only", "blocked", "not_applicable"}
)
ALLOWED_CATALOG_STATES = frozenset({"enabled", "disabled", "absent"})
ALLOWED_ENABLEMENT_DECISIONS = frozenset(
    {
        "production_backbone",
        "eligible_default_off",
        "audit_only",
        "credential_and_contract_pending",
        "context_only",
        "planning_reference",
        "static_snapshot",
        "contract_review_pending",
        "authorization_pending",
        "development_only",
        "candidate",
        "blocked_pending_approval",
        "request_time_fallback",
        "request_time_legacy",
        "superseded",
    }
)
ADAPTER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)*$")


class SourceRegistryValidationError(RuntimeError):
    pass


def load_source_registry(path: Path = REGISTRY_PATH) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceRegistryValidationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != "source-registry/v1":
        raise SourceRegistryValidationError("source registry version must be source-registry/v1")

    raw_contracts = payload.get("contracts")
    raw_sources = payload.get("sources")
    if not isinstance(raw_contracts, dict) or not raw_contracts:
        raise SourceRegistryValidationError("source registry contracts must be a non-empty mapping")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise SourceRegistryValidationError("source registry sources must be a non-empty list")

    contracts: dict[str, Path] = {}
    for key, value in raw_contracts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SourceRegistryValidationError("contract names and paths must be strings")
        contracts[key] = REPO_ROOT / value

    sources: list[dict[str, Any]] = []
    for index, source in enumerate(raw_sources):
        if not isinstance(source, dict):
            raise SourceRegistryValidationError(f"sources[{index}] must be a mapping")
        sources.append(source)
    return contracts, sources


def validate_registry_schema(
    contracts: dict[str, Path],
    sources: list[dict[str, Any]],
) -> None:
    errors: list[str] = []
    for contract_key, contract_path in contracts.items():
        if not contract_path.is_file():
            errors.append(f"contract {contract_key!r} does not exist: {contract_path}")

    seen: set[str] = set()
    for index, source in enumerate(sources):
        fields = frozenset(source)
        if not fields >= REQUIRED_SOURCE_FIELDS or not (
            fields - REQUIRED_SOURCE_FIELDS
        ) <= OPTIONAL_SOURCE_FIELDS:
            errors.append(
                f"sources[{index}] fields differ: missing={sorted(REQUIRED_SOURCE_FIELDS - fields)} "
                f"extra={sorted(fields - REQUIRED_SOURCE_FIELDS - OPTIONAL_SOURCE_FIELDS)}"
            )
            continue
        upstream_incident = source.get("upstream_incident")
        if upstream_incident is not None and (
            not isinstance(upstream_incident, str) or not upstream_incident.strip()
        ):
            errors.append(f"sources[{index}] upstream_incident must be a non-empty string")
            continue
        adapter_key = source["adapter_key"]
        if not isinstance(adapter_key, str) or ADAPTER_KEY_PATTERN.fullmatch(adapter_key) is None:
            errors.append(f"sources[{index}] has invalid adapter_key {adapter_key!r}")
            continue
        if adapter_key in seen:
            errors.append(f"duplicate adapter_key: {adapter_key}")
        seen.add(adapter_key)

        _validate_enum(errors, adapter_key, source, "family", ALLOWED_FAMILIES)
        _validate_enum(errors, adapter_key, source, "implementation", ALLOWED_IMPLEMENTATIONS)
        _validate_enum(errors, adapter_key, source, "runtime_scope", ALLOWED_RUNTIME_SCOPES)
        _validate_enum(errors, adapter_key, source, "catalog_state", ALLOWED_CATALOG_STATES)
        _validate_enum(
            errors,
            adapter_key,
            source,
            "enablement_decision",
            ALLOWED_ENABLEMENT_DECISIONS,
        )

        contract_key = source["contract"]
        if not isinstance(contract_key, str) or contract_key not in contracts:
            errors.append(f"{adapter_key}: unknown contract {contract_key!r}")
        if not isinstance(source["deployment_default"], bool):
            errors.append(f"{adapter_key}: deployment_default must be boolean")

        is_worker = source["implementation"] == "worker"
        worker_default = source["worker_default_enabled"]
        if is_worker and not isinstance(worker_default, bool):
            errors.append(f"{adapter_key}: worker source requires boolean worker_default_enabled")
        if not is_worker and worker_default is not None:
            errors.append(f"{adapter_key}: non-worker source must use null worker_default_enabled")
        if is_worker and source["runtime_scope"] == "not_applicable":
            errors.append(f"{adapter_key}: worker source requires an explicit runtime scope")
        if not is_worker and source["runtime_scope"] != "not_applicable":
            errors.append(f"{adapter_key}: non-worker source must use runtime_scope=not_applicable")
        if source["deployment_default"] and (
            source["runtime_scope"] != "v1_baseline" or source["catalog_state"] != "enabled"
        ):
            errors.append(
                f"{adapter_key}: deployment default must be v1_baseline and catalog enabled"
            )

    _raise_errors(errors)


def validate_static_surfaces(sources: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    source_by_key = {str(source["adapter_key"]): source for source in sources}
    worker_contract = _load_worker_contract()
    registered = worker_contract["adapters"]
    registered_keys = set(registered)
    expected_worker_keys = {
        key for key, source in source_by_key.items() if source["implementation"] == "worker"
    }
    _compare_key_sets(errors, "worker registry", registered_keys, expected_worker_keys)
    api_history_keys = _api_history_adapter_keys()
    missing_api_decisions = sorted(api_history_keys - set(source_by_key))
    if missing_api_decisions:
        errors.append(f"API history sources lack registry decisions: {missing_api_decisions}")

    for adapter_key in sorted(registered_keys & expected_worker_keys):
        actual = registered[adapter_key]
        expected = source_by_key[adapter_key]
        if actual["family"] != expected["family"]:
            errors.append(
                f"{adapter_key}: worker family={actual['family']!r}, "
                f"registry family={expected['family']!r}"
            )
        if actual["enabled_by_default"] is not expected["worker_default_enabled"]:
            errors.append(
                f"{adapter_key}: worker default={actual['enabled_by_default']!r}, "
                f"registry default={expected['worker_default_enabled']!r}"
            )

    expected_v1 = {
        key for key, source in source_by_key.items() if source["runtime_scope"] == "v1_baseline"
    }
    _compare_key_sets(errors, "V1 runtime scope", set(worker_contract["v1_baseline"]), expected_v1)

    expected_official_catalog = {
        key
        for key, source in source_by_key.items()
        if source["contract"] in {"central_official", "incident_activation", "nationwide_history"}
    }
    _compare_key_sets(
        errors,
        "official source catalog",
        _official_flood_source_catalog_keys(),
        expected_official_catalog,
    )

    expected_deployment = {
        key for key, source in source_by_key.items() if source["deployment_default"]
    }
    entrypoint_keys = set(_entrypoint_backbone_keys())
    _compare_key_sets(errors, "entrypoint deployment defaults", entrypoint_keys, expected_deployment)
    for variable in ("REALTIME_BACKBONE_ADAPTER_KEYS", "WORKER_ENABLED_ADAPTER_KEYS"):
        assignments = _non_empty_env_assignments(variable)
        if len(assignments) != 1:
            errors.append(
                f".env.example: expected one non-empty {variable} assignment, got {len(assignments)}"
            )
            continue
        _compare_key_sets(
            errors,
            f".env.example {variable}",
            set(assignments[0]),
            expected_deployment,
        )

    _raise_errors(errors)


def validate_catalog(
    sources: list[dict[str, Any]],
    *,
    database_url: str,
) -> None:
    expected = {
        str(source["adapter_key"]): source["catalog_state"] == "enabled"
        for source in sources
        if source["catalog_state"] != "absent"
    }
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            rows = connection.execute(
                "SELECT adapter_key, is_enabled FROM data_sources ORDER BY adapter_key"
            ).fetchall()
            readiness_rows = connection.execute(
                """
                SELECT adapter_key
                FROM ingestion_readiness_sources
                WHERE profile_key = 'production_backbone'
                ORDER BY adapter_key
                """
            ).fetchall()
    except (OSError, psycopg.Error) as exc:
        raise SourceRegistryValidationError(
            f"cannot validate migrated data_sources catalog: {exc}"
        ) from exc

    actual = {str(row[0]): bool(row[1]) for row in rows}
    actual_readiness = {str(row[0]) for row in readiness_rows}
    expected_readiness = {
        str(source["adapter_key"]) for source in sources if source["deployment_default"]
    }
    errors: list[str] = []
    _compare_key_sets(errors, "migrated data_sources catalog", set(actual), set(expected))
    _compare_key_sets(
        errors,
        "migrated production readiness profile",
        actual_readiness,
        expected_readiness,
    )
    for adapter_key in sorted(set(actual) & set(expected)):
        if actual[adapter_key] != expected[adapter_key]:
            errors.append(
                f"{adapter_key}: migrated catalog enabled={actual[adapter_key]}, "
                f"registry enabled={expected[adapter_key]}"
            )
    _raise_errors(errors)


def validate_catalog_runtime_state() -> None:
    """Fail when the catalog runtime_state no longer matches the registry decisions."""
    try:
        differences = check_catalog_runtime_state(
            OFFICIAL_SOURCE_CATALOG_PATH,
            REGISTRY_PATH,
        )
    except RuntimeStateRenderError as exc:
        raise SourceRegistryValidationError(str(exc)) from exc
    if differences:
        _raise_errors(
            [
                *differences,
                "rerun `python infra/scripts/render_source_catalog_runtime_state.py`",
            ]
        )


def _validate_enum(
    errors: list[str],
    adapter_key: str,
    source: dict[str, Any],
    field: str,
    allowed: frozenset[str],
) -> None:
    if not isinstance(source[field], str) or source[field] not in allowed:
        errors.append(f"{adapter_key}: invalid {field} {source[field]!r}")


def _load_worker_contract() -> dict[str, Any]:
    code = """
import json
from app.adapters.registry import ADAPTER_REGISTRY
from app.jobs.runtime_managed import V1_BASELINE_ADAPTER_KEYS

print(json.dumps({
    "adapters": {
        key: {
            "family": metadata.family.value,
            "enabled_by_default": metadata.enabled_by_default,
        }
        for key, metadata in ADAPTER_REGISTRY.items()
    },
    "v1_baseline": list(V1_BASELINE_ADAPTER_KEYS),
}, sort_keys=True))
"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=WORKER_DIR,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise SourceRegistryValidationError(f"cannot inspect worker registry: {detail}") from exc
    return json.loads(completed.stdout)


def _entrypoint_backbone_keys() -> tuple[str, ...]:
    text = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^realtime_backbone_adapter_keys="([^"]*)"$', text, flags=re.MULTILINE)
    if match is None:
        raise SourceRegistryValidationError("entrypoint deployment backbone assignment is missing")
    return _split_adapter_keys(match.group(1), label="entrypoint deployment defaults")


def _official_flood_source_catalog_keys() -> set[str]:
    payload = yaml.safe_load(OFFICIAL_SOURCE_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise SourceRegistryValidationError("official source catalog sources must be a list")
    keys: set[str] = set()
    for source in payload["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("key"), str):
            raise SourceRegistryValidationError("official source catalog entry is missing key")
        key = source["key"]
        if not key.startswith("geocoder."):
            keys.add(key)
    return keys


def _api_history_adapter_keys() -> set[str]:
    tree = ast.parse(API_HISTORY_SOURCE_PATH.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("_ADAPTER_KEY"):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            keys.add(node.value.value)
    return keys


def _non_empty_env_assignments(variable: str) -> list[tuple[str, ...]]:
    prefix = f"{variable}="
    assignments: list[tuple[str, ...]] = []
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if value:
            assignments.append(_split_adapter_keys(value, label=f".env.example {variable}"))
    return assignments


def _split_adapter_keys(value: str, *, label: str) -> tuple[str, ...]:
    keys = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(keys) != len(set(keys)):
        raise SourceRegistryValidationError(f"{label} contains duplicate adapter keys")
    return keys


def _compare_key_sets(
    errors: list[str],
    label: str,
    actual: set[str],
    expected: set[str],
) -> None:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        errors.append(f"{label} drift: missing={missing} unexpected={unexpected}")


def _raise_errors(errors: list[str]) -> None:
    if errors:
        raise SourceRegistryValidationError("\n".join(f"- {error}" for error in errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the canonical source registry against code, deployment, and catalog."
    )
    parser.add_argument("--database-url", help="Optional migrated Postgres URL; never printed.")
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Validate schema/contracts and the migrated data_sources catalog only.",
    )
    args = parser.parse_args(argv)

    try:
        contracts, sources = load_source_registry()
        validate_registry_schema(contracts, sources)
        if not args.catalog_only:
            validate_static_surfaces(sources)
        if args.database_url:
            validate_catalog(sources, database_url=args.database_url)
        elif args.catalog_only:
            parser.error("--catalog-only requires --database-url")
        validate_catalog_runtime_state()
    except SourceRegistryValidationError as exc:
        print(f"Source registry invalid:\n{exc}", file=sys.stderr)
        return 1

    worker_count = sum(source["implementation"] == "worker" for source in sources)
    v1_count = sum(source["runtime_scope"] == "v1_baseline" for source in sources)
    deployment_count = sum(bool(source["deployment_default"]) for source in sources)
    catalog_count = sum(source["catalog_state"] != "absent" for source in sources)
    print(
        "Source registry valid. "
        f"sources={len(sources)} worker={worker_count} v1={v1_count} "
        f"deployment_default={deployment_count} catalog={catalog_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
