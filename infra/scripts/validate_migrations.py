from __future__ import annotations

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
REQUIRED_MARKERS = ("CREATE ", "ALTER ", "INSERT ", "UPDATE ", "DELETE ", "DROP ")


def main() -> int:
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        print("No SQL migrations found.", file=sys.stderr)
        return 1

    versions: list[int] = []
    errors: list[str] = []
    for migration in migrations:
        match = MIGRATION_PATTERN.match(migration.name)
        if not match:
            errors.append(f"{migration.name}: filename must match 0000_description.sql")
            continue

        version = int(match.group("version"))
        versions.append(version)
        sql = migration.read_text(encoding="utf-8").strip()
        if not sql:
            errors.append(f"{migration.name}: migration is empty")
        if not any(marker in sql.upper() for marker in REQUIRED_MARKERS):
            errors.append(f"{migration.name}: no recognized SQL operation marker found")
        if "ON_ERROR_STOP" in sql.upper():
            errors.append(f"{migration.name}: keep psql execution flags outside SQL files")

    if len(versions) != len(set(versions)):
        errors.append("Migration versions must be unique")
    if versions != sorted(versions):
        errors.append("Migration versions must be sortable in apply order")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"Migration files valid. count={len(migrations)} latest={migrations[-1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
