from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    REPO_ROOT / "infra" / "migrations" / "0060_retire_request_time_flood_citation.sql"
)
REGISTRY_PATH = REPO_ROOT / "config" / "source-registry.yaml"
CATALOG_PATH = (
    REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"
)
ADAPTER_KEY = "official.gov_tw.flood_citation"


def _registry_entry() -> dict[str, object]:
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    return next(
        source for source in payload["sources"] if source["adapter_key"] == ADAPTER_KEY
    )


def test_registry_marks_the_request_time_citation_source_as_audit_only() -> None:
    entry = _registry_entry()

    assert entry["catalog_state"] == "disabled"
    assert entry["enablement_decision"] == "audit_only"
    assert entry["deployment_default"] is False


def test_catalog_records_the_retirement_instead_of_claiming_gap_recovery() -> None:
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    entry = next(
        source for source in payload["sources"] if source["key"] == ADAPTER_KEY
    )

    assert entry["status"] == "retired_request_time"
    assert "2026-09-04" in entry["integration_decision"]


def test_retirement_migration_flips_the_catalog_row_without_rewriting_evidence() -> None:
    # The 2026-09-03 audit's rule: a data rewrite belongs in a batched backfill
    # job, never in a migration. Retiring a source only needs the catalog row.
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    statements = [
        line.strip().lower()
        for line in sql.splitlines()
        if not line.strip().startswith("--")
    ]
    body = "\n".join(statements)

    assert f"where adapter_key = '{ADAPTER_KEY}'" in body
    assert "is_enabled = false" in body
    assert "update evidence" not in body
    assert "delete from" not in body
