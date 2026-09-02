from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from infra.scripts.apply_migrations import apply_migrations


QUARANTINED_ADAPTER_KEYS = (
    "official.civil_iot.flood_sensor",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
)


def _database_url() -> str:
    database_url = os.getenv("EVIDENCE_TEST_DATABASE_URL")
    required = os.getenv("OFFICIAL_DB_ACCEPTANCE_REQUIRED") == "1"
    if not database_url:
        if required:
            pytest.fail(
                "EVIDENCE_TEST_DATABASE_URL is required when "
                "OFFICIAL_DB_ACCEPTANCE_REQUIRED=1"
            )
        pytest.skip("EVIDENCE_TEST_DATABASE_URL is not configured")
    try:
        with psycopg.connect(database_url) as connection:
            connection.execute("SELECT PostGIS_Version()")
    except (OSError, psycopg.Error) as exc:
        if required:
            pytest.fail(f"required PostGIS is unreachable: {exc}")
        pytest.skip(f"PostGIS is unreachable: {exc}")
    return database_url


@contextmanager
def _isolated_schema(database_url: str) -> Iterator[str]:
    schema_name = f"civil_iot_quarantine_{uuid4().hex}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    connection_info = psycopg.conninfo.conninfo_to_dict(database_url)
    existing_options = connection_info.get("options", "")
    connection_info["options"] = (
        f"{existing_options} -c search_path={schema_name},public".strip()
    )
    try:
        yield psycopg.conninfo.make_conninfo(**connection_info)
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_quarantine_migration_matches_catalog_and_readiness_profile() -> None:
    with _isolated_schema(_database_url()) as isolated_url:
        first = apply_migrations(database_url=isolated_url)
        second = apply_migrations(database_url=isolated_url)

        with psycopg.connect(isolated_url) as connection:
            quarantined = connection.execute(
                """
                SELECT adapter_key,
                       is_enabled,
                       metadata->>'availability_status',
                       metadata->>'availability_incident_ref'
                FROM data_sources
                WHERE adapter_key = ANY(%s)
                ORDER BY adapter_key
                """,
                (list(QUARANTINED_ADAPTER_KEYS),),
            ).fetchall()
            sewer_enabled = connection.execute(
                """
                SELECT is_enabled
                FROM data_sources
                WHERE adapter_key = 'official.civil_iot.sewer_water_level'
                """
            ).fetchone()[0]
            readiness_keys = connection.execute(
                """
                SELECT adapter_key
                FROM ingestion_readiness_sources
                WHERE profile_key = 'production_backbone'
                ORDER BY adapter_key
                """
            ).fetchall()

        assert first.applied[-1] == "0062_quarantine_civil_iot_water_resource.sql"
        assert second.applied == ()
        assert len(second.skipped) == 62
        assert quarantined == [
            (
                adapter_key,
                False,
                "upstream_unavailable",
                "docs/reviews/civil-iot-source-recovery-2026-09-02.md",
            )
            for adapter_key in sorted(QUARANTINED_ADAPTER_KEYS)
        ]
        assert sewer_enabled is True
        assert len(readiness_keys) == 9
        assert {row[0] for row in readiness_keys}.isdisjoint(QUARANTINED_ADAPTER_KEYS)
        assert ("official.civil_iot.sewer_water_level",) in readiness_keys
