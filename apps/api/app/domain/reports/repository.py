from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


ConnectionFactory = Callable[[], Any]
UserReportStatus = Literal["pending", "approved", "rejected", "spam"]
UserReportModerationStatus = Literal["approved", "rejected", "spam"]
UserReportModerationReason = Literal[
    "verified_flood_signal",
    "duplicate",
    "not_flood_related",
    "insufficient_detail",
    "abuse_or_spam",
    "out_of_scope",
]
VALID_MODERATION_STATUSES: set[str] = {"approved", "rejected", "spam"}
VALID_MODERATION_REASONS: set[str] = {
    "verified_flood_signal",
    "duplicate",
    "not_flood_related",
    "insufficient_detail",
    "abuse_or_spam",
    "out_of_scope",
}
MODERATION_REASONS_BY_STATUS: dict[UserReportModerationStatus, set[str]] = {
    "approved": {"verified_flood_signal"},
    "rejected": {
        "duplicate",
        "not_flood_related",
        "insufficient_detail",
        "out_of_scope",
    },
    "spam": {"abuse_or_spam"},
}


class UserReportRepositoryUnavailable(RuntimeError):
    """Raised when user report storage cannot accept submissions."""


@dataclass(frozen=True)
class PendingUserReport:
    id: str
    status: Literal["pending"]


@dataclass(frozen=True)
class UserReportModerationRecord:
    id: str
    status: UserReportStatus
    summary: str
    lat: float
    lng: float
    created_at: datetime
    reviewed_at: datetime | None


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
    return PendingUserReport(id=str(row["id"]), status="pending")


def list_pending_user_reports(
    *,
    database_url: str,
    limit: int = 100,
    connection_factory: ConnectionFactory | None = None,
) -> list[UserReportModerationRecord]:
    sql = """
        SELECT
            id::text AS id,
            status,
            summary,
            ST_Y(geom::geometry) AS lat,
            ST_X(geom::geometry) AS lng,
            created_at,
            reviewed_at
        FROM user_reports
        WHERE status = 'pending'
        ORDER BY created_at ASC, id ASC
        LIMIT %s
    """
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (limit,))
                rows = cursor.fetchall()
    except (OSError, psycopg.Error) as exc:
        raise UserReportRepositoryUnavailable(str(exc)) from exc

    return [_moderation_record_from_row(row) for row in rows]


def moderate_user_report(
    *,
    database_url: str,
    report_id: str,
    status: UserReportModerationStatus,
    reason_code: UserReportModerationReason,
    actor_ref: str,
    connection_factory: ConnectionFactory | None = None,
) -> UserReportModerationRecord | None:
    if status not in VALID_MODERATION_STATUSES:
        raise ValueError(f"invalid moderation status: {status}")
    if reason_code not in VALID_MODERATION_REASONS:
        raise ValueError(f"invalid moderation reason_code: {reason_code}")
    if reason_code not in MODERATION_REASONS_BY_STATUS[status]:
        raise ValueError(f"moderation reason_code {reason_code} is not allowed for status {status}")

    sql = """
        WITH target_report AS (
            SELECT id, status AS previous_status
            FROM user_reports
            WHERE id = %s::uuid
            FOR UPDATE
        ),
        updated_report AS (
            UPDATE user_reports
            SET
                status = %s,
                reviewed_at = now()
            FROM target_report
            WHERE user_reports.id = target_report.id
            RETURNING
                user_reports.id::text AS id,
                user_reports.status,
                target_report.previous_status,
                user_reports.summary,
                ST_Y(user_reports.geom::geometry) AS lat,
                ST_X(user_reports.geom::geometry) AS lng,
                user_reports.created_at,
                user_reports.reviewed_at
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
                %s,
                'user_report.moderated',
                'user_report',
                updated_report.id,
                jsonb_build_object(
                    'previous_status', updated_report.previous_status,
                    'status', updated_report.status,
                    'reason_code', %s,
                    'reviewed_by', %s
                )
            FROM updated_report
        )
        SELECT id, status, summary, lat, lng, created_at, reviewed_at
        FROM updated_report
    """
    params = (report_id, status, actor_ref, reason_code, actor_ref)
    try:
        with _connect(database_url, connection_factory) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
    except (OSError, psycopg.Error) as exc:
        raise UserReportRepositoryUnavailable(str(exc)) from exc

    if row is None:
        return None
    return _moderation_record_from_row(row)


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


def _moderation_record_from_row(row: dict[str, Any]) -> UserReportModerationRecord:
    return UserReportModerationRecord(
        id=str(row["id"]),
        status=cast(UserReportStatus, row["status"]),
        summary=str(row["summary"]),
        lat=float(row["lat"]),
        lng=float(row["lng"]),
        created_at=cast(datetime, row["created_at"]),
        reviewed_at=cast(datetime | None, row["reviewed_at"]),
    )
