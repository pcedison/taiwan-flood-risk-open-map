"""Structured operational logging for the API.

One JSON object per line so hosted log search can filter by ``event`` and read
numeric fields without parsing prose.

Nothing in this service configures the root logger, and uvicorn's default
logging config leaves the root logger without a handler, so an event logger
that only calls ``logger.info`` is silently dropped in production. This module
therefore owns its own stdout handler instead of inheriting one.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_EVENT_LOGGER_NAME = "app.events"
_HANDLER_NAME = "app.events.stdout"


def _event_logger() -> logging.Logger:
    """Return the event logger, attaching its stdout handler exactly once."""

    logger = logging.getLogger(_EVENT_LOGGER_NAME)
    if not any(handler.get_name() == _HANDLER_NAME for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        # The record message is already a complete JSON object; adding a prefix
        # would stop hosted log search from parsing the line.
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Own handler only: never duplicate the line into uvicorn's root handlers.
    logger.propagate = False
    return logger


_LOGGER = _event_logger()


def log_event(event: str, **fields: Any) -> None:
    _LOGGER.info(
        json.dumps(
            {"event": event, "timestamp": datetime.now(UTC).isoformat(), **fields},
            default=str,
            ensure_ascii=False,
        )
    )


__all__ = ["log_event"]
