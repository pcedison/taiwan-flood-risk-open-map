from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "infra" / "migrations" / "0056_historical_coverage_ledger.sql"
JURISDICTION_MIGRATION = (
    REPO_ROOT / "infra" / "migrations" / "0035_station_inventory_and_jurisdiction_proofs.sql"
)
EXPECTED_STATUSES = (
    "unassessed",
    "complete",
    "partial",
    "official_checked_empty",
    "not_published",
    "stale",
    "failed",
)


def test_historical_coverage_migration_seeds_the_fixed_22_by_9_matrix() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    jurisdiction_sql = JURISDICTION_MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS historical_coverage_cells" in sql
    assert "REFERENCES realtime_jurisdictions(jurisdiction_code)" in sql
    assert "generate_series(2018, 2026)" in sql
    assert "ON CONFLICT (jurisdiction_code, coverage_year) DO NOTHING" in sql
    jurisdiction_seed = jurisdiction_sql.split(
        "INSERT INTO realtime_jurisdictions (jurisdiction_code, jurisdiction_name)",
        1,
    )[1].split("ON CONFLICT (jurisdiction_code)", 1)[0]
    jurisdictions = re.findall(r"\('([0-9]{8})', '([^']+)'\)", jurisdiction_seed)
    assert len(jurisdictions) == 22
    assert len({code for code, _ in jurisdictions}) == 22
    assert len({name for _, name in jurisdictions}) == 22
    for status in EXPECTED_STATUSES:
        assert f"'{status}'" in sql


def test_historical_coverage_migration_keeps_absence_and_failures_distinct() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "status <> 'official_checked_empty' OR record_count = 0" in sql
    assert "status <> 'complete' OR record_count > 0" in sql
    assert "status <> 'not_published'" in sql
    assert "status NOT IN ('partial', 'stale', 'failed')" in sql
    assert "Coverage audit has not been run." in sql
    assert "a status never asserts that flooding did or did not occur" in sql
