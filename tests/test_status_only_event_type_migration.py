from __future__ import annotations

from pathlib import Path


def test_status_only_event_type_migration_extends_staging_and_evidence_constraints() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "infra"
        / "migrations"
        / "0031_status_only_event_type.sql"
    ).read_text(encoding="utf-8")

    assert "staging_evidence_event_type_check" in migration
    assert "evidence_event_type_check" in migration
    assert "'status_only'" in migration
