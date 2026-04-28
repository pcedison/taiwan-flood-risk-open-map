from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        **fields,
    }
    print(json.dumps(payload, default=str), file=sys.stdout, flush=True)

