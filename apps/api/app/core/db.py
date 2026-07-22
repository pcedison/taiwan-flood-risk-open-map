"""Shared psycopg connection pooling for request-path repositories.

Every repository used on the public request path previously opened a fresh
``psycopg.connect()`` per call, so a single ``/v1/risk/assess`` performed
6-8 TCP + auth handshakes and each one forked a new Postgres backend — real
latency per request and connection/memory pressure on a small shared node.

This module keeps one process-wide :class:`psycopg_pool.ConnectionPool` per
database URL. Pool exhaustion raises ``PoolTimeout`` (a subclass of
``psycopg.OperationalError``), so existing ``except psycopg.Error`` →
``*Unavailable`` handling in the repositories applies unchanged.

Deliberately NOT pooled: the ``/health`` database probe (its purpose is to
verify a fresh connection can be established) and low-traffic admin/bootstrap
paths whose tests patch ``psycopg.connect`` directly.
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 8
DEFAULT_POOL_TIMEOUT_SECONDS = 5.0

_POOLS: dict[str, ConnectionPool] = {}
_LOCK = Lock()


def pooled_connection(database_url: str) -> Any:
    """Return a context manager yielding a pooled ``dict_row`` connection.

    Usable exactly like ``with psycopg.connect(...) as conn:`` — commits on
    clean exit, rolls back on exception, then returns the connection to the
    pool instead of closing it.
    """
    return _get_pool(database_url).connection(
        timeout=_env_float("DB_POOL_TIMEOUT_SECONDS", DEFAULT_POOL_TIMEOUT_SECONDS)
    )


def _get_pool(database_url: str) -> ConnectionPool:
    pool = _POOLS.get(database_url)
    if pool is not None:
        return pool
    with _LOCK:
        pool = _POOLS.get(database_url)
        if pool is None:
            pool = ConnectionPool(
                database_url,
                min_size=_env_int("DB_POOL_MIN_SIZE", DEFAULT_POOL_MIN_SIZE),
                max_size=_env_int("DB_POOL_MAX_SIZE", DEFAULT_POOL_MAX_SIZE),
                kwargs={"row_factory": dict_row, "connect_timeout": 2},
                open=True,
            )
            _POOLS[database_url] = pool
    return pool


def close_all_pools() -> None:
    """Close every pool (test isolation and clean shutdown)."""
    with _LOCK:
        for pool in _POOLS.values():
            pool.close()
        _POOLS.clear()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default
