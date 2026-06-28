from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import sys
from typing import Protocol

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> object: ...
    def fetchone(self) -> tuple[object, ...] | None: ...
    def __enter__(self) -> Cursor: ...
    def __exit__(self, *exc: object) -> object: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def __enter__(self) -> Connection: ...
    def __exit__(self, *exc: object) -> object: ...


ConnectionFactory = Callable[[str], Connection]


@dataclass(frozen=True)
class MigrationSummary:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


def apply_migrations(
    *,
    database_url: str,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    connection_factory: ConnectionFactory = psycopg.connect,
) -> MigrationSummary:
    migrations = _migration_files(migrations_dir)
    applied: list[str] = []
    skipped: list[str] = []

    with connection_factory(database_url) as connection:
        with connection.cursor() as cursor:
            _ensure_schema_migrations(cursor)
            for migration in migrations:
                version = _migration_version(migration)
                if _migration_is_recorded(cursor, version):
                    skipped.append(migration.name)
                    continue

                sql = migration.read_text(encoding="utf-8").strip()
                cursor.execute(sql)
                cursor.execute(
                    """
                    INSERT INTO schema_migrations (version, filename, checksum)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (version, migration.name, sha256(sql.encode("utf-8")).hexdigest()),
                )
                applied.append(migration.name)

    return MigrationSummary(applied=tuple(applied), skipped=tuple(skipped))


def _ensure_schema_migrations(cursor: Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version integer PRIMARY KEY,
            filename text NOT NULL,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def _migration_is_recorded(cursor: Cursor, version: int) -> bool:
    cursor.execute("SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = %s)", (version,))
    row = cursor.fetchone()
    return bool(row and row[0])


def _migration_files(migrations_dir: Path) -> tuple[Path, ...]:
    migrations = sorted(migrations_dir.glob("*.sql"))
    if not migrations:
        raise RuntimeError(f"No SQL migrations found in {migrations_dir}")
    for migration in migrations:
        _migration_version(migration)
    return tuple(migrations)


def _migration_version(migration: Path) -> int:
    match = MIGRATION_PATTERN.match(migration.name)
    if match is None:
        raise RuntimeError(f"{migration.name}: filename must match 0000_description.sql")
    return int(match.group("version"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply ordered PostGIS SQL migrations.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    args = parser.parse_args(argv)

    summary = apply_migrations(
        database_url=args.database_url,
        migrations_dir=args.migrations_dir,
    )
    print(
        "Migrations applied. "
        f"applied={len(summary.applied)} skipped={len(summary.skipped)}"
    )
    if summary.applied:
        print("Applied: " + ", ".join(summary.applied))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
