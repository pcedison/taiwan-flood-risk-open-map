from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "infra"
    / "migrations"
    / "0063_autovacuum_tuning_for_evidence_tables.sql"
)


def test_autovacuum_tuning_sets_bounded_thresholds_for_both_evidence_tables() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE staging_evidence SET (" in migration
    assert "ALTER TABLE evidence SET (" in migration

    # staging_evidence is the table the retention pass churns, so it gets the
    # tighter threshold and the larger IO budget.
    staging, _, evidence = migration.partition("ALTER TABLE evidence SET (")
    assert "autovacuum_vacuum_scale_factor = 0.02" in staging
    assert "autovacuum_analyze_scale_factor = 0.02" in staging
    assert "autovacuum_vacuum_cost_limit = 1000" in staging
    assert "autovacuum_vacuum_scale_factor = 0.05" in evidence
    assert "autovacuum_analyze_scale_factor = 0.05" in evidence
    assert "autovacuum_vacuum_cost_limit" not in evidence


def test_autovacuum_tuning_is_pure_ddl_and_rewrites_no_rows() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    statements = " ".join(
        line for line in migration.splitlines() if not line.strip().startswith("--")
    ).upper()

    # "VACUUM" is deliberately absent from this list: it is a substring of every
    # autovacuum_* storage parameter name being set here.
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE INDEX"):
        assert forbidden not in statements
    assert statements.count("ALTER TABLE") == 2
