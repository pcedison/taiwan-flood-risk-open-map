from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


ConnectionFactory = Callable[[], Any]


class UserReportRepositoryUnavailable(RuntimeError):
    """Raised when user report storage cannot accept submissions."""


@dataclass(frozen=True)
class PendingUserReport:
    id: str
    status: str


def create_pending_user_report(
    *,
    database_url: str,
    lat: float,
    lng: float,
    summary: str,
    connection_factory: ConnectionFactory | None = None,
) -> PendingUserReport:
    sql = """
        WITH inserted_report AS (
            INSERT INTO user_reports (
                geom,
                summary,
                media_ref,
                status,
                privacy_level
            )
            VALUES (
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                %s,
                NULL,
                'pending',
                'redacted'
            )
            RETURNING id, status
        ),
        inserted_audit AS (
            INSERT INTO audit_logs (
                actor_ref,
                action,
                subject_type,
                subject_id,
                metadata
            )
            SELECT
                NULL,
                'user_report.submitted',
                'user_report',
                inserted_report.id::text,
                %s::jsonb
            FROM inserted_report
        )
        SELECT id::text AS id, status
        FROM inserted_report
    """
    params = (
        lng,
        lat,
        summary,
        Jsonb({"status": "pending", "privacy_level": "redacted", "media_ref": None}),
    )
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
    except (OSError, psycopg.Error) as exc:
        raise UserReportRepositoryUnavailable(str(exc)) from exc

    if row is None:
        raise UserReportRepositoryUnavailable("user report insert returned no row")
    return PendingUserReport(id=str(row["id"]), status=str(row["status"]))


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)
