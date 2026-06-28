from __future__ import annotations

from pathlib import Path

from infra.scripts.apply_migrations import apply_migrations


class FakeCursor:
    def __init__(self, existing_versions: set[int]) -> None:
        self.existing_versions = existing_versions
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self._last_fetchone: tuple[bool] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, params))
        if "SELECT EXISTS" in sql:
            version = int(params[0])
            self._last_fetchone = (version in self.existing_versions,)
        if "INSERT INTO schema_migrations" in sql:
            self.existing_versions.add(int(params[0]))

    def fetchone(self) -> tuple[bool] | None:
        return self._last_fetchone


class FakeConnection:
    def __init__(self, existing_versions: set[int]) -> None:
        self.cursor_obj = FakeCursor(existing_versions)

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_obj


def test_apply_migrations_skips_recorded_versions(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_base.sql").write_text("CREATE TABLE example(id int);", encoding="utf-8")
    (migrations / "0002_seed.sql").write_text("INSERT INTO example(id) VALUES (1);", encoding="utf-8")
    connection = FakeConnection({1})

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
    )

    assert summary.applied == ("0002_seed.sql",)
    assert summary.skipped == ("0001_base.sql",)
    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.executed)
    assert "CREATE TABLE example" not in executed_sql
    assert "INSERT INTO example(id) VALUES (1);" in executed_sql


def test_apply_migrations_records_checksum(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_base.sql").write_text("CREATE TABLE example(id int);", encoding="utf-8")
    connection = FakeConnection(set())

    summary = apply_migrations(
        database_url="postgresql://example.test/db",
        migrations_dir=migrations,
        connection_factory=lambda _url: connection,
    )

    assert summary.applied == ("0001_base.sql",)
    insert_params = [
        params
        for sql, params in connection.cursor_obj.executed
        if "INSERT INTO schema_migrations" in sql
    ][0]
    assert insert_params[0] == 1
    assert insert_params[1] == "0001_base.sql"
    assert isinstance(insert_params[2], str)
    assert len(insert_params[2]) == 64
