"""Operational database failure metadata without DSNs, SQL, or exception text."""

from __future__ import annotations

import re
from time import monotonic

from app.core.logging import log_event


def log_database_failure(
    *, operation: str, stage: str, started_at: float, error: Exception
) -> None:
    sqlstate = getattr(error, "sqlstate", None)
    log_event(
        "database.operation.failed",
        operation=operation,
        stage=stage,
        error_type=type(error).__name__,
        sqlstate=(
            sqlstate
            if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate)
            else None
        ),
        elapsed_ms=round(max(0.0, monotonic() - started_at) * 1000, 1),
    )
