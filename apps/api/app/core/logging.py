"""Structured operational logging for the API.

One JSON object per line so hosted log search can filter by ``event`` and read
numeric fields without parsing prose.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

_LOGGER = logging.getLogger("app.events")


def log_event(event: str, **fields: Any) -> None:
    _LOGGER.info(
        json.dumps(
            {"event": event, "timestamp": datetime.now(UTC).isoformat(), **fields},
            default=str,
            ensure_ascii=False,
        )
    )


__all__ = ["log_event"]
