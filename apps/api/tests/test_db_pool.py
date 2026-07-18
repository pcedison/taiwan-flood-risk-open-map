from __future__ import annotations

from typing import Any

import psycopg
import psycopg_pool
import pytest

from app.core import db as db_module


@pytest.fixture(autouse=True)
def _reset_pools(monkeypatch) -> None:
    monkeypatch.setattr(db_module, "_POOLS", {})


class _FakePool:
    def __init__(self, conninfo: str, **kwargs: Any) -> None:
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.connection_calls: list[float | None] = []
        self.closed = False

    def connection(self, timeout: float | None = None) -> Any:
        self.connection_calls.append(timeout)
        return object()

    def close(self) -> None:
        self.closed = True


def test_same_database_url_reuses_one_pool(monkeypatch) -> None:
    created: list[_FakePool] = []

    def factory(conninfo: str, **kwargs: Any) -> _FakePool:
        pool = _FakePool(conninfo, **kwargs)
        created.append(pool)
        return pool

    monkeypatch.setattr(db_module, "ConnectionPool", factory)

    db_module.pooled_connection("postgresql://example.test/flood")
    db_module.pooled_connection("postgresql://example.test/flood")
    db_module.pooled_connection("postgresql://other.test/flood")

    assert len(created) == 2
    assert created[0].conninfo == "postgresql://example.test/flood"
    assert len(created[0].connection_calls) == 2
    assert len(created[1].connection_calls) == 1


def test_pool_connections_use_dict_row_and_short_connect_timeout(monkeypatch) -> None:
    created: list[_FakePool] = []

    def factory(conninfo: str, **kwargs: Any) -> _FakePool:
        pool = _FakePool(conninfo, **kwargs)
        created.append(pool)
        return pool

    monkeypatch.setattr(db_module, "ConnectionPool", factory)

    db_module.pooled_connection("postgresql://example.test/flood")

    kwargs = created[0].kwargs["kwargs"]
    assert kwargs["connect_timeout"] == 2
    assert kwargs["row_factory"] is not None
    assert created[0].kwargs["min_size"] == db_module.DEFAULT_POOL_MIN_SIZE
    assert created[0].kwargs["max_size"] == db_module.DEFAULT_POOL_MAX_SIZE


def test_pool_sizes_configurable_via_env(monkeypatch) -> None:
    created: list[_FakePool] = []

    def factory(conninfo: str, **kwargs: Any) -> _FakePool:
        pool = _FakePool(conninfo, **kwargs)
        created.append(pool)
        return pool

    monkeypatch.setattr(db_module, "ConnectionPool", factory)
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "4")

    db_module.pooled_connection("postgresql://example.test/flood")

    assert created[0].kwargs["min_size"] == 2
    assert created[0].kwargs["max_size"] == 4


def test_pool_timeout_maps_to_repository_unavailable_semantics() -> None:
    # Repositories catch psycopg.Error to raise *_Unavailable; pool exhaustion
    # must stay inside that contract.
    assert issubclass(psycopg_pool.PoolTimeout, psycopg.OperationalError)


def test_close_all_pools_closes_and_clears(monkeypatch) -> None:
    created: list[_FakePool] = []

    def factory(conninfo: str, **kwargs: Any) -> _FakePool:
        pool = _FakePool(conninfo, **kwargs)
        created.append(pool)
        return pool

    monkeypatch.setattr(db_module, "ConnectionPool", factory)
    db_module.pooled_connection("postgresql://example.test/flood")

    db_module.close_all_pools()

    assert created[0].closed is True
    db_module.pooled_connection("postgresql://example.test/flood")
    assert len(created) == 2
