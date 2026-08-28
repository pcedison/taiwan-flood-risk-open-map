from __future__ import annotations

from typing import Any, Self

import pytest

from app.jobs.source_catalog import (
    PostgresSourceCatalogReader,
    SourceCatalogUnavailable,
    filter_catalog_enabled_adapter_keys,
)


def test_postgres_source_catalog_reader_excludes_missing_and_disabled_keys() -> None:
    connection = _FakeConnection(
        fetch_rows=[
            ("official.cwa.heavy_rain_warning",),
            ("official.ncdr.cap",),
        ]
    )
    reader = PostgresSourceCatalogReader(connection_factory=lambda: connection)

    enabled = reader.enabled_keys(
        (
            "official.ncdr.cap",
            "official.cwa.heavy_rain_warning",
            "official.ncdr.cap",
            "official.wra.flood_warning",
            "official.npa.police_radio_traffic",
        )
    )

    assert enabled == frozenset({"official.cwa.heavy_rain_warning", "official.ncdr.cap"})
    assert "official.wra.flood_warning" not in enabled  # missing catalog row
    assert "official.npa.police_radio_traffic" not in enabled  # is_enabled = false
    assert connection.cursor_instance.executions is not None
    sql, params = connection.cursor_instance.executions
    assert "SELECT adapter_key" in sql
    assert "adapter_key = ANY(%s)" in sql
    assert "is_enabled IS TRUE" in sql
    assert "ORDER BY adapter_key ASC" in sql
    assert params == (
        [
            "official.cwa.heavy_rain_warning",
            "official.ncdr.cap",
            "official.npa.police_radio_traffic",
            "official.wra.flood_warning",
        ],
    )


def test_postgres_source_catalog_reader_avoids_connection_for_no_keys() -> None:
    calls = 0

    def connection_factory() -> _FakeConnection:
        nonlocal calls
        calls += 1
        return _FakeConnection(fetch_rows=[])

    reader = PostgresSourceCatalogReader(connection_factory=connection_factory)

    assert reader.enabled_keys(()) == frozenset()
    assert calls == 0


def test_filter_catalog_gates_every_requested_adapter_not_only_incident_sources() -> None:
    reader = type(
        "Reader",
        (),
        {
            "enabled_keys": lambda _self, keys: frozenset(
                key for key in keys if key != "official.wra.historical_flood"
            )
        },
    )()

    enabled = filter_catalog_enabled_adapter_keys(
        (
            "official.cwa.rainfall",
            "official.wra.historical_flood",
            "local.tainan.flood_sensor",
        ),
        source_catalog_reader=reader,
    )

    assert enabled == (
        "official.cwa.rainfall",
        "local.tainan.flood_sensor",
    )


def test_filter_catalog_fails_closed_without_reader_for_any_adapter() -> None:
    with pytest.raises(SourceCatalogUnavailable, match="reader is required"):
        filter_catalog_enabled_adapter_keys(
            ("official.cwa.rainfall",),
            source_catalog_reader=None,
        )


class _FakeConnection:
    def __init__(self, *, fetch_rows: list[tuple[Any, ...]]) -> None:
        self.cursor_instance = _FakeCursor(fetch_rows)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance


class _FakeCursor:
    def __init__(self, fetch_rows: list[tuple[Any, ...]]) -> None:
        self.fetch_rows = fetch_rows
        self.executions: tuple[str, tuple[object, ...]] | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions = (sql, params)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.fetch_rows
