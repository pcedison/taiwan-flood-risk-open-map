from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import sys
from types import TracebackType
from typing import Protocol, Self, cast

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
DEFAULT_LOCK_TIMEOUT_MS = 10_000
DEFAULT_STATEMENT_TIMEOUT_MS = 300_000
# A stable, repository-specific signed bigint. Session-level advisory locks are
# released by PostgreSQL when the runner connection closes, including failures.
MIGRATION_ADVISORY_LOCK_KEY = int.from_bytes(
    sha256(b"taiwan-flood-risk-open-map:schema-migrations:v1").digest()[:8],
    byteorder="big",
    signed=True,
)


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> object: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class Transaction(Protocol):
    def __enter__(self) -> None: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class Connection(Protocol):
    autocommit: bool

    def cursor(self) -> Cursor: ...
    def transaction(self) -> Transaction: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


ConnectionFactory = Callable[[str], Connection]


def _connect(database_url: str) -> Connection:
    return cast(Connection, psycopg.connect(database_url))


class MigrationDriftError(RuntimeError):
    """The database migration manifest differs from the checked-in files."""


@dataclass(frozen=True)
class MigrationFile:
    version: int
    filename: str
    sql: str
    checksum: str


@dataclass(frozen=True)
class RecordedMigration:
    version: int
    filename: str
    checksum: str


@dataclass(frozen=True)
class MigrationSummary:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]


def apply_migrations(
    *,
    database_url: str,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    connection_factory: ConnectionFactory = _connect,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> MigrationSummary:
    _validate_timeout("lock_timeout_ms", lock_timeout_ms)
    _validate_timeout("statement_timeout_ms", statement_timeout_ms)
    migrations = _migration_files(migrations_dir)
    applied: list[str] = []
    skipped: list[str] = []

    with connection_factory(database_url) as connection:
        # Explicit transaction blocks below are required to make every migration
        # independently durable. Without autocommit, psycopg would keep an outer
        # transaction open around the advisory lock and every migration.
        connection.autocommit = True
        with connection.cursor() as cursor:
            _configure_session_timeouts(
                cursor,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
            )
            _acquire_migration_lock(cursor)

            with connection.transaction():
                _ensure_schema_migrations(cursor)

            recorded = _recorded_migrations(cursor)
            _validate_recorded_migrations(migrations, recorded)

            for migration in migrations:
                if migration.version in recorded:
                    skipped.append(migration.filename)
                    continue

                # The SQL and its manifest row succeed or roll back together.
                # Exiting this block commits before the next migration starts,
                # so table locks cannot accidentally span multiple files.
                with connection.transaction():
                    cursor.execute(migration.sql)
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (version, filename, checksum)
                        VALUES (%s, %s, %s)
                        """,
                        (migration.version, migration.filename, migration.checksum),
                    )
                applied.append(migration.filename)

    return MigrationSummary(applied=tuple(applied), skipped=tuple(skipped))


def _configure_session_timeouts(
    cursor: Cursor,
    *,
    lock_timeout_ms: int,
    statement_timeout_ms: int,
) -> None:
    cursor.execute(
        "SELECT set_config('lock_timeout', %s, false)",
        (f"{lock_timeout_ms}ms",),
    )
    cursor.execute(
        "SELECT set_config('statement_timeout', %s, false)",
        (f"{statement_timeout_ms}ms",),
    )


def _acquire_migration_lock(cursor: Cursor) -> None:
    cursor.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_ADVISORY_LOCK_KEY,))


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


def _recorded_migrations(cursor: Cursor) -> dict[int, RecordedMigration]:
    cursor.execute(
        "SELECT version, filename, checksum FROM schema_migrations ORDER BY version"
    )
    records: dict[int, RecordedMigration] = {}
    for row in cursor.fetchall():
        if len(row) != 3:
            raise MigrationDriftError("schema_migrations returned an invalid manifest row")
        version = row[0]
        if not isinstance(version, int):
            raise MigrationDriftError("schema_migrations returned an invalid version")
        record = RecordedMigration(
            version=version,
            filename=str(row[1]),
            checksum=str(row[2]),
        )
        records[record.version] = record
    return records


def _validate_recorded_migrations(
    migrations: tuple[MigrationFile, ...],
    recorded: dict[int, RecordedMigration],
) -> None:
    local_by_version = {migration.version: migration for migration in migrations}
    missing_versions = sorted(set(recorded) - set(local_by_version))
    if missing_versions:
        versions = ", ".join(f"{version:04d}" for version in missing_versions)
        raise MigrationDriftError(
            f"Recorded migration versions are missing from the local manifest: {versions}"
        )

    for version, record in recorded.items():
        migration = local_by_version[version]
        if record.filename != migration.filename:
            raise MigrationDriftError(
                f"Migration {version:04d} filename drift: "
                f"recorded={record.filename!r} local={migration.filename!r}"
            )
        if record.checksum != migration.checksum:
            raise MigrationDriftError(
                f"Migration {version:04d} checksum drift for {migration.filename}"
            )


def _migration_files(migrations_dir: Path) -> tuple[MigrationFile, ...]:
    paths = sorted(migrations_dir.glob("*.sql"))
    if not paths:
        raise RuntimeError(f"No SQL migrations found in {migrations_dir}")

    migrations: list[MigrationFile] = []
    seen_versions: set[int] = set()
    for path in paths:
        version = _migration_version(path)
        if version in seen_versions:
            raise RuntimeError(f"Duplicate migration version {version:04d}")
        seen_versions.add(version)
        sql = path.read_text(encoding="utf-8").strip()
        migrations.append(
            MigrationFile(
                version=version,
                filename=path.name,
                sql=sql,
                checksum=sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(migrations)


def _migration_version(migration: Path) -> int:
    match = MIGRATION_PATTERN.match(migration.name)
    if match is None:
        raise RuntimeError(f"{migration.name}: filename must match 0000_description.sql")
    return int(match.group("version"))


def _validate_timeout(name: str, value: int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _environment_timeout(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    _validate_timeout(name, value)
    return value


def _safe_failure_message(exc: Exception) -> str:
    if isinstance(exc, MigrationDriftError):
        return "Migration failed: migration manifest validation failed."
    if isinstance(exc, psycopg.Error):
        return "Migration failed: database operation failed."
    if isinstance(exc, OSError):
        return "Migration failed: local migration files could not be read."
    if isinstance(exc, (ValueError, RuntimeError)):
        return "Migration failed: migration configuration or manifest is invalid."
    return "Migration failed: unexpected error."


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply ordered PostGIS SQL migrations.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument(
        "--lock-timeout-ms",
        type=int,
        default=_environment_timeout("MIGRATION_LOCK_TIMEOUT_MS", DEFAULT_LOCK_TIMEOUT_MS),
    )
    parser.add_argument(
        "--statement-timeout-ms",
        type=int,
        default=_environment_timeout(
            "MIGRATION_STATEMENT_TIMEOUT_MS", DEFAULT_STATEMENT_TIMEOUT_MS
        ),
    )
    args = parser.parse_args(argv)

    summary = apply_migrations(
        database_url=args.database_url,
        migrations_dir=args.migrations_dir,
        lock_timeout_ms=args.lock_timeout_ms,
        statement_timeout_ms=args.statement_timeout_ms,
    )
    print(
        "Migrations applied. "
        f"applied={len(summary.applied)} skipped={len(summary.skipped)}"
    )
    if summary.applied:
        print("Applied: " + ", ".join(summary.applied))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except Exception as exc:
        print(_safe_failure_message(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
