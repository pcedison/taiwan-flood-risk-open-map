from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from infra.scripts.apply_migrations import apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "infra" / "migrations"
TARGET_MIGRATION = "0038_official_incident_context_sources.sql"
EXPECTED_KEYS = (
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
)
CONTEXT_ONLY_KEYS = (
    "official.npa.police_radio_traffic",
    "official.wra.flood_warning",
)
SPATIAL_REVIEW_KEYS = (
    "official.cwa.heavy_rain_warning",
    "official.ncdr.cap",
)
FORBIDDEN_METADATA_SUBSTRINGS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "bearer",
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
    schema_name = f"migration0038_{uuid4().hex}"
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


def _migrations_before_target(tmp_path: Path) -> Path:
    staged = tmp_path / "migrations_0001_0037"
    staged.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if migration.name >= TARGET_MIGRATION:
            continue
        shutil.copy2(migration, staged / migration.name)
    return staged


def _source_rows(database_url: str) -> dict[str, dict[str, object]]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT adapter_key, source_type, health_status, is_enabled,
                   metadata::text AS metadata_text, metadata
            FROM data_sources
            WHERE adapter_key = ANY(%s)
            """,
            (list(EXPECTED_KEYS),),
        ).fetchall()
    return {str(row["adapter_key"]): row for row in rows}


def _assert_disabled_and_credential_free(rows: dict[str, dict[str, object]]) -> None:
    assert set(rows) == set(EXPECTED_KEYS)
    for key, row in rows.items():
        assert row["is_enabled"] is False, key
        assert row["source_type"] == "official", key
        assert row["health_status"] == "unknown", key
        metadata_text = str(row["metadata_text"]).lower()
        for forbidden in FORBIDDEN_METADATA_SUBSTRINGS:
            assert forbidden not in metadata_text, (key, forbidden)
    for key in CONTEXT_ONLY_KEYS:
        metadata = rows[key]["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["evidence_scope"] == "context", key
        assert metadata["scoring_use"] == "never", key
    for key in SPATIAL_REVIEW_KEYS:
        metadata = rows[key]["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["spatial_review"] == "unapproved", key


def test_empty_schema_upgrade_registers_four_disabled_context_sources() -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        summary = apply_migrations(database_url=isolated_url)

        assert TARGET_MIGRATION in summary.applied
        _assert_disabled_and_credential_free(_source_rows(isolated_url))

        repeated = apply_migrations(database_url=isolated_url)
        assert TARGET_MIGRATION in repeated.skipped
        _assert_disabled_and_credential_free(_source_rows(isolated_url))


def test_existing_0037_database_is_forced_back_to_disabled(tmp_path: Path) -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        before = apply_migrations(
            database_url=isolated_url,
            migrations_dir=_migrations_before_target(tmp_path),
        )
        assert TARGET_MIGRATION not in before.applied

        with psycopg.connect(isolated_url) as connection:
            connection.execute(
                """
                UPDATE data_sources
                SET is_enabled = true, health_status = 'healthy'
                WHERE adapter_key = ANY(%s)
                """,
                (list(EXPECTED_KEYS),),
            )
            connection.commit()

        summary = apply_migrations(database_url=isolated_url)

        assert TARGET_MIGRATION in summary.applied
        _assert_disabled_and_credential_free(_source_rows(isolated_url))


def test_migration_never_creates_a_required_realtime_coverage_mapping() -> None:
    database_url = _database_url()

    with _isolated_schema(database_url) as isolated_url:
        apply_migrations(database_url=isolated_url)

        with psycopg.connect(isolated_url) as connection:
            mapped = connection.execute(
                """
                SELECT count(*)
                FROM realtime_source_jurisdictions
                WHERE adapter_key = ANY(%s)
                """,
                (list(CONTEXT_ONLY_KEYS),),
            ).fetchone()

        assert mapped is not None
        assert mapped[0] == 0
