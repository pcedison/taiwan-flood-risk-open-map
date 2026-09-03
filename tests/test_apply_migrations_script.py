from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from types import TracebackType

import pytest

import infra.scripts.apply_migrations as migration_runner
from infra.scripts.apply_migrations import (
    MIGRATION_ADVISORY_LOCK_KEY,
    MigrationDriftError,
    MigrationReleaseGateError,
    MigrationSummary,
    apply_migrations,
)


def _checksum(sql: str) -> str:
    return sha256(sql.strip().encode("utf-8")).hexdigest()


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self._rows: list[tuple[object, ...]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT to_regclass"):
            self._rows = [(self.connection.manifest_exists,)]
        elif normalized.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            self.connection.manifest_exists = True
        elif normalized.startswith("SELECT version, filename, checksum"):
            if not self.connection.manifest_exists:
                raise RuntimeError("schema_migrations does not exist")
            self._rows = [
                (version, filename, checksum)
                for version, (filename, checksum) in sorted(self.connection.records.items())
            ]
        elif "INSERT INTO schema_migrations" in sql:
            version = params[0]
            if not isinstance(version, int):
                raise AssertionError("migration version must be an integer")
            self.connection.records[version] = (str(params[1]), str(params[2]))
        elif self.connection.fail_on_sql and self.connection.fail_on_sql in sql:
            raise RuntimeError("simulated migration failure")

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.snapshot: dict[int, tuple[str, str]] = {}

    def __enter__(self) -> None:
        self.snapshot = dict(self.connection.records)
        self.connection.transaction_events.append("start")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.connection.transaction_events.append("commit")
        else:
            self.connection.records = self.snapshot
            self.connection.transaction_events.append("rollback")
        return None


class FakeConnection:
    def __init__(
        self,
        records: dict[int, tuple[str, str]] | None = None,
        *,
        fail_on_sql: str | None = None,
        manifest_exists: bool | None = None,
    ) -> None:
        self.records = dict(records or {})
        self.fail_on_sql = fail_on_sql
        self.manifest_exists = bool(records) if manifest_exists is None else manifest_exists
        self.autocommit = False
        self.transaction_events: list[str] = []
        self.cursor_obj = FakeCursor(self)

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


def _write_migrations(tmp_path: Path, migrations: dict[str, str]) -> Path:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    for filename, sql in migrations.items():
        (migrations_dir / filename).write_text(sql, encoding="utf-8")
    return migrations_dir


def test_applies_each_migration_atomically_under_one_session_lock(tmp_path: Path) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": "CREATE TABLE example(id int);",
            "0002_seed.sql": "INSERT INTO example(id) VALUES (1);",
        },
    )
    connection = FakeConnection()

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
        lock_timeout_ms=12_345,
        statement_timeout_ms=456_789,
    )

    assert summary.applied == ("0001_base.sql", "0002_seed.sql")
    assert summary.skipped == ()
    assert connection.autocommit is True
    # One transaction creates the manifest table; every migration then gets a
    # separate commit so locks from 0001 cannot leak into 0002.
    assert connection.transaction_events == [
        "start",
        "commit",
        "start",
        "commit",
        "start",
        "commit",
    ]
    executed = connection.cursor_obj.executed
    lock_index = next(i for i, (sql, _) in enumerate(executed) if "pg_advisory_lock" in sql)
    table_index = next(
        i for i, (sql, _) in enumerate(executed) if "CREATE TABLE IF NOT EXISTS" in sql
    )
    assert lock_index < table_index
    assert executed[lock_index][1] == (MIGRATION_ADVISORY_LOCK_KEY,)
    assert (
        "SELECT set_config('lock_timeout', %s, false)",
        ("12345ms",),
    ) in executed
    assert (
        "SELECT set_config('statement_timeout', %s, false)",
        ("456789ms",),
    ) in executed
    assert connection.records == {
        1: ("0001_base.sql", _checksum("CREATE TABLE example(id int);")),
        2: ("0002_seed.sql", _checksum("INSERT INTO example(id) VALUES (1);")),
    }


def test_failed_migration_rolls_back_without_undoing_prior_commit(tmp_path: Path) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": "CREATE TABLE example(id int);",
            "0002_fail.sql": "FAIL MIGRATION;",
        },
    )
    connection = FakeConnection(fail_on_sql="FAIL MIGRATION")

    with pytest.raises(RuntimeError, match="simulated migration failure"):
        apply_migrations(
            database_url="postgresql://example.test/db",
            migrations_dir=migrations,
            connection_factory=lambda _url: connection,
        )

    assert connection.records == {
        1: ("0001_base.sql", _checksum("CREATE TABLE example(id int);"))
    }
    assert connection.transaction_events == [
        "start",
        "commit",
        "start",
        "commit",
        "start",
        "rollback",
    ]


def test_skips_only_an_exact_recorded_manifest_match(tmp_path: Path) -> None:
    base_sql = "CREATE TABLE example(id int);"
    seed_sql = "INSERT INTO example(id) VALUES (1);"
    migrations = _write_migrations(
        tmp_path,
        {"0001_base.sql": base_sql, "0002_seed.sql": seed_sql},
    )
    connection = FakeConnection({1: ("0001_base.sql", _checksum(base_sql))})

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
    )

    assert summary.applied == ("0002_seed.sql",)
    assert summary.skipped == ("0001_base.sql",)
    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.executed)
    assert "CREATE TABLE example(id int);" not in executed_sql
    assert seed_sql in executed_sql


def test_plan_lists_bounded_pending_migrations_without_writes(tmp_path: Path) -> None:
    base_sql = "CREATE TABLE example(id int);"
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": base_sql,
            "0002_seed.sql": "INSERT INTO example(id) VALUES (1);",
            "0003_later.sql": "SELECT 3;",
        },
    )
    connection = FakeConnection({1: ("0001_base.sql", _checksum(base_sql))})

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
        expected_current_version=1,
        target_version=2,
        dry_run=True,
    )

    assert summary.applied == ()
    assert summary.skipped == ("0001_base.sql",)
    assert summary.pending == ("0002_seed.sql",)
    assert summary.current_version_before == 1
    assert summary.current_version_after == 1
    assert summary.target_version == 2
    assert connection.transaction_events == []
    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.executed)
    assert "CREATE TABLE IF NOT EXISTS" not in executed_sql
    assert "INSERT INTO example" not in executed_sql


def test_plan_treats_missing_manifest_as_empty_without_writes(tmp_path: Path) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": "CREATE TABLE example(id int);",
            "0002_seed.sql": "INSERT INTO example(id) VALUES (1);",
        },
    )
    connection = FakeConnection(manifest_exists=False)

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
        expected_current_version=0,
        target_version=2,
        dry_run=True,
    )

    assert summary.current_version_before == 0
    assert summary.current_version_after == 0
    assert summary.pending == ("0001_base.sql", "0002_seed.sql")
    assert connection.manifest_exists is False
    assert connection.transaction_events == []
    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.executed)
    assert "to_regclass('schema_migrations')" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" not in executed_sql
    assert "SELECT version, filename, checksum" not in executed_sql


def test_release_applies_only_through_explicit_target(tmp_path: Path) -> None:
    base_sql = "CREATE TABLE example(id int);"
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": base_sql,
            "0002_seed.sql": "INSERT INTO example(id) VALUES (1);",
            "0003_later.sql": "SELECT 3;",
        },
    )
    connection = FakeConnection({1: ("0001_base.sql", _checksum(base_sql))})

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
        expected_current_version=1,
        target_version=2,
    )

    assert summary.applied == ("0002_seed.sql",)
    assert summary.current_version_before == 1
    assert summary.current_version_after == 2
    assert summary.target_version == 2
    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.executed)
    assert "INSERT INTO example(id) VALUES (1);" in executed_sql
    assert "SELECT 3;" not in executed_sql


def test_release_rejects_unexpected_current_version_before_new_migration(
    tmp_path: Path,
) -> None:
    base_sql = "CREATE TABLE example(id int);"
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": base_sql,
            "0002_seed.sql": "INSERT INTO example(id) VALUES (1);",
        },
    )
    connection = FakeConnection({1: ("0001_base.sql", _checksum(base_sql))})

    with pytest.raises(MigrationReleaseGateError, match="expected=0000 actual=0001"):
        apply_migrations(
            database_url="postgresql://example.test/db",
            migrations_dir=migrations,
            connection_factory=lambda _url: connection,
            expected_current_version=0,
            target_version=2,
        )

    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.executed)
    assert "INSERT INTO example" not in executed_sql


def test_release_gate_requires_exact_environment_version_sha_ack() -> None:
    sha = "a" * 40

    with pytest.raises(RuntimeError, match="acknowledgement"):
        migration_runner._validate_release_gate(
            dry_run=False,
            release_environment="staging",
            release_sha=sha,
            release_ack="apply:staging:0059->0061:" + sha,
            expected_current_version=59,
            target_version=62,
        )

    migration_runner._validate_release_gate(
        dry_run=False,
        release_environment="staging",
        release_sha=sha,
        release_ack="apply:staging:0059->0062:" + sha,
        expected_current_version=59,
        target_version=62,
    )


def test_release_plan_does_not_require_apply_ack() -> None:
    migration_runner._validate_release_gate(
        dry_run=True,
        release_environment="staging",
        release_sha="b" * 40,
        release_ack=None,
        expected_current_version=59,
        target_version=62,
    )


def test_release_progress_reports_lock_and_per_migration_duration(tmp_path: Path) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "0001_base.sql": "CREATE TABLE example(id int);",
            "0002_seed.sql": "INSERT INTO example(id) VALUES (1);",
        },
    )
    connection = FakeConnection()
    events: list[tuple[str, str | None, int]] = []

    apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
        target_version=2,
        progress_callback=lambda event, filename, elapsed_ms: events.append(
            (event, filename, elapsed_ms)
        ),
    )

    assert [event for event, _filename, _elapsed_ms in events] == [
        "lock_acquired",
        "migration_started",
        "migration_applied",
        "migration_started",
        "migration_applied",
    ]
    assert [filename for _event, filename, _elapsed_ms in events] == [
        None,
        "0001_base.sql",
        "0001_base.sql",
        "0002_seed.sql",
        "0002_seed.sql",
    ]
    assert all(elapsed_ms >= 0 for _event, _filename, elapsed_ms in events)


@pytest.mark.parametrize(
    ("recorded_filename", "recorded_checksum", "message"),
    [
        ("0001_renamed.sql", _checksum("SELECT 1;"), "filename drift"),
        ("0001_base.sql", "0" * 64, "checksum drift"),
    ],
)
def test_recorded_filename_or_checksum_drift_fails_before_new_migrations(
    tmp_path: Path,
    recorded_filename: str,
    recorded_checksum: str,
    message: str,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {"0001_base.sql": "SELECT 1;", "0002_new.sql": "SELECT 2;"},
    )
    connection = FakeConnection({1: (recorded_filename, recorded_checksum)})

    with pytest.raises(MigrationDriftError, match=message):
        apply_migrations(
            database_url="postgresql://example.test/db",
            migrations_dir=migrations,
            connection_factory=lambda _url: connection,
        )

    assert not any("SELECT 2;" in sql for sql, _ in connection.cursor_obj.executed)
    assert connection.transaction_events == ["start", "commit"]


def test_recorded_version_missing_from_local_manifest_fails_closed(tmp_path: Path) -> None:
    migrations = _write_migrations(tmp_path, {"0001_base.sql": "SELECT 1;"})
    connection = FakeConnection(
        {
            1: ("0001_base.sql", _checksum("SELECT 1;")),
            2: ("0002_missing.sql", _checksum("SELECT 2;")),
        }
    )

    with pytest.raises(MigrationDriftError, match="missing from the local manifest: 0002"):
        apply_migrations(
            database_url="postgresql://example.test/db",
            migrations_dir=migrations,
            connection_factory=lambda _url: connection,
        )


def test_duplicate_local_versions_are_rejected_before_connecting(tmp_path: Path) -> None:
    migrations = _write_migrations(
        tmp_path,
        {"0001_base.sql": "SELECT 1;", "0001_duplicate.sql": "SELECT 2;"},
    )
    connection_attempted = False

    def connect(_url: str) -> FakeConnection:
        nonlocal connection_attempted
        connection_attempted = True
        return FakeConnection()

    with pytest.raises(RuntimeError, match="Duplicate migration version 0001"):
        apply_migrations(
            database_url="postgresql://example.test/db",
            migrations_dir=migrations,
            connection_factory=connect,
        )

    assert connection_attempted is False


@pytest.mark.parametrize(("name", "value"), [("lock_timeout_ms", 0), ("statement_timeout_ms", -1)])
def test_non_positive_timeouts_are_rejected_before_connecting(
    tmp_path: Path, name: str, value: int
) -> None:
    migrations = _write_migrations(tmp_path, {"0001_base.sql": "SELECT 1;"})

    with pytest.raises(ValueError, match=f"{name} must be a positive integer"):
        if name == "lock_timeout_ms":
            apply_migrations(
                database_url="postgresql://example.test/db",
                migrations_dir=migrations,
                connection_factory=lambda _url: pytest.fail("must not connect"),
                lock_timeout_ms=value,
            )
        else:
            apply_migrations(
                database_url="postgresql://example.test/db",
                migrations_dir=migrations,
                connection_factory=lambda _url: pytest.fail("must not connect"),
                statement_timeout_ms=value,
            )


def test_drift_error_and_output_do_not_expose_database_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    migrations = _write_migrations(tmp_path, {"0001_base.sql": "SELECT 1;"})
    connection = FakeConnection({1: ("0001_base.sql", "0" * 64)})
    database_url = "postgresql://private-user:private-password@example.test/production"

    with pytest.raises(MigrationDriftError) as error:
        apply_migrations(
            database_url=database_url,
            migrations_dir=migrations,
            connection_factory=lambda _url: connection,
        )

    captured = capsys.readouterr()
    assert database_url not in str(error.value)
    assert database_url not in captured.out
    assert database_url not in captured.err


def test_main_reads_timeout_overrides_without_printing_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = "postgresql://private-user:private-password@example.test/production"
    captured_args: dict[str, object] = {}
    monkeypatch.setenv("MIGRATION_LOCK_TIMEOUT_MS", "2345")
    monkeypatch.setenv("MIGRATION_STATEMENT_TIMEOUT_MS", "67890")

    def fake_apply_migrations(**kwargs: object) -> MigrationSummary:
        captured_args.update(kwargs)
        return MigrationSummary(applied=(), skipped=())

    monkeypatch.setattr(migration_runner, "apply_migrations", fake_apply_migrations)

    result = migration_runner.main(
        [
            "--database-url",
            database_url,
            "--migrations-dir",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert captured_args["lock_timeout_ms"] == 2345
    assert captured_args["statement_timeout_ms"] == 67890
    assert database_url not in output


def test_main_redacts_malformed_percent_encoded_dsn_from_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = "postgresql://private-user:pa%ZZword@example.test/production"

    def reject_dsn(**_kwargs: object) -> MigrationSummary:
        raise RuntimeError(f"invalid percent-encoded DSN: {database_url}")

    monkeypatch.setattr(migration_runner, "apply_migrations", reject_dsn)

    result = migration_runner.main(
        [
            "--database-url",
            database_url,
            "--migrations-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == (
        "Migration failed: migration configuration or manifest is invalid.\n"
    )
    assert database_url not in captured.err
    assert "pa%ZZword" not in captured.err


def test_main_redacts_password_from_unexpected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = "postgresql://private-user:private-password@example.test/production"

    class UnexpectedMigrationFailure(Exception):
        pass

    def reject_connection(**_kwargs: object) -> MigrationSummary:
        raise UnexpectedMigrationFailure(f"could not connect with {database_url}")

    monkeypatch.setattr(migration_runner, "apply_migrations", reject_connection)

    result = migration_runner.main(
        [
            "--database-url",
            database_url,
            "--migrations-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "Migration failed: unexpected error.\n"
    assert database_url not in captured.err
    assert "private-password" not in captured.err


def test_main_reports_public_safe_release_version_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = "postgresql://private-user:private-password@example.test/staging"

    def reject_release(**_kwargs: object) -> MigrationSummary:
        raise MigrationReleaseGateError(
            "Current migration version does not match the explicit release gate: "
            "expected=0059 actual=0060"
        )

    monkeypatch.setattr(migration_runner, "apply_migrations", reject_release)

    result = migration_runner.main(
        [
            "--database-url",
            database_url,
            "--migrations-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == (
        "Migration release gate failed: Current migration version does not match "
        "the explicit release gate: expected=0059 actual=0060\n"
    )
    assert database_url not in captured.err
    assert "private-password" not in captured.err


def test_real_migration_manifest_matches_the_api_schema_sentinel() -> None:
    """The newest migration must stay in lockstep with the API readiness gate.

    The sentinel is read as text rather than imported so this root-level suite
    never has to put ``apps/api`` on ``sys.path``.
    """

    repository_root = Path(__file__).resolve().parents[1]
    migrations = sorted(
        (repository_root / "infra" / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")
    )
    latest = migrations[-1]
    health_source = (
        repository_root / "apps" / "api" / "app" / "api" / "routes" / "health.py"
    ).read_text(encoding="utf-8")

    def _constant(name: str) -> str:
        match = re.search(rf'^{name} = "?([^"\n]+)"?$', health_source, re.MULTILINE)
        assert match is not None, name
        return match.group(1)

    assert latest.name == _constant("REQUIRED_SCHEMA_FILENAME")
    assert int(latest.name[:4]) == int(_constant("REQUIRED_SCHEMA_VERSION"))
    assert _checksum(latest.read_text(encoding="utf-8")) == _constant(
        "REQUIRED_SCHEMA_CHECKSUM"
    )
