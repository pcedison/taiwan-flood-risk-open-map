from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from infra.scripts.apply_migrations import apply_migrations

RESTORED_KEYS = (
    "official.ncdr.cap",
    "official.wra_iow.flood_depth",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
    "local.tainan.flood_sensor",
)
MUST_STAY_DISABLED = (
    "official.cwa.heavy_rain_warning",
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
)


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail(
                "EVIDENCE_TEST_DATABASE_URL is required when OFFICIAL_DB_ACCEPTANCE_REQUIRED=1"
            )
        pytest.skip("EVIDENCE_TEST_DATABASE_URL is not configured")
    return database_url


@contextmanager
def _isolated_schema(database_url: str) -> Iterator[str]:
    schema_name = f"migration0039_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    info = psycopg.conninfo.conninfo_to_dict(database_url)
    info["options"] = f"{info.get('options', '')} -c search_path={schema_name},public".strip()
    try:
        yield psycopg.conninfo.make_conninfo(**info)
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def _enabled_by_key(database_url: str, keys: tuple[str, ...]) -> dict[str, bool]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            "SELECT adapter_key, is_enabled FROM data_sources WHERE adapter_key = ANY(%s)",
            (list(keys),),
        ).fetchall()
    return {str(row["adapter_key"]): bool(row["is_enabled"]) for row in rows}


def test_backbone_sources_are_catalog_enabled_and_new_sources_stay_off() -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        apply_migrations(database_url=isolated_url)

        restored = _enabled_by_key(isolated_url, RESTORED_KEYS)
        assert set(restored) == set(RESTORED_KEYS)
        for key, enabled in restored.items():
            assert enabled is True, key

        held_off = _enabled_by_key(isolated_url, MUST_STAY_DISABLED)
        for key, enabled in held_off.items():
            assert enabled is False, key


def test_migration_0039_is_idempotent_and_never_disables_an_enabled_row() -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        apply_migrations(database_url=isolated_url)
        control_key = "official.cwa.rainfall"
        assert _enabled_by_key(isolated_url, (control_key,))[control_key] is True

        migration = (
            "UPDATE data_sources SET is_enabled = true, updated_at = now() "
            "WHERE adapter_key = ANY(%s) AND is_enabled = false"
        )
        with psycopg.connect(isolated_url) as connection:
            connection.execute(migration, (list(RESTORED_KEYS),))
            connection.commit()

        restored = _enabled_by_key(isolated_url, RESTORED_KEYS)
        assert all(restored.values())
        assert _enabled_by_key(isolated_url, (control_key,))[control_key] is True
        held_off = _enabled_by_key(isolated_url, MUST_STAY_DISABLED)
        assert not any(held_off.values())
