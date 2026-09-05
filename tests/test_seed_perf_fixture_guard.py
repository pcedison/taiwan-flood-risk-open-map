from __future__ import annotations

import pytest

from infra.scripts.seed_perf_fixture import (
    NonLocalDatabaseError,
    PRODUCTION_OVERRIDE_FLAG,
    _database_host,
    _require_local_database,
    main,
)


LOCAL_URLS = (
    "postgresql://flood_risk:change-me-local@127.0.0.1:5432/flood_risk",
    "postgresql://flood_risk:change-me-local@localhost:5432/flood_risk",
    "postgresql://flood_risk:change-me-local@LocalHost:5432/flood_risk",
    "postgresql://flood_risk:change-me-local@[::1]:5432/flood_risk",
    # No host at all, and an explicit Unix socket directory: both are local.
    "postgresql:///flood_risk",
    "host=/var/run/postgresql dbname=flood_risk",
)
REMOTE_URLS = (
    "postgresql://flood_risk:secret@db.zeabur.internal:5432/flood_risk",
    "postgresql://flood_risk:secret@10.0.0.5:5432/flood_risk",
    # A hostname that merely starts with "localhost" is still remote.
    "postgresql://flood_risk:secret@localhost.example.com:5432/flood_risk",
)


@pytest.mark.parametrize("database_url", LOCAL_URLS)
def test_local_database_urls_are_allowed(database_url: str) -> None:
    _require_local_database(database_url, override=False)


@pytest.mark.parametrize("database_url", REMOTE_URLS)
def test_non_loopback_database_urls_are_refused(database_url: str) -> None:
    with pytest.raises(NonLocalDatabaseError) as excinfo:
        _require_local_database(database_url, override=False)

    message = str(excinfo.value)
    assert PRODUCTION_OVERRIDE_FLAG in message
    # The refusal must not echo the password back into logs.
    assert "secret" not in message


@pytest.mark.parametrize("database_url", REMOTE_URLS)
def test_explicit_override_allows_non_loopback(database_url: str) -> None:
    _require_local_database(database_url, override=True)


def test_main_refuses_remote_host_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_on_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("seeding must not open a connection to a remote host")

    monkeypatch.setattr(
        "infra.scripts.seed_perf_fixture.psycopg.connect", fail_on_connect
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--database-url", "postgresql://flood_risk:secret@prod.example.com/db"])

    assert excinfo.value.code == 2


def test_unparsable_database_url_is_refused() -> None:
    with pytest.raises(NonLocalDatabaseError):
        _database_host("this is not a connection string")


def test_ipv6_loopback_brackets_are_stripped() -> None:
    assert _database_host("postgresql://user@[::1]:5432/db") == "::1"
