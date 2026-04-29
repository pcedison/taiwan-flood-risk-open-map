from __future__ import annotations

from datetime import datetime
from hashlib import sha256


def parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def stable_evidence_id(adapter_key: str, source_id: str) -> str:
    digest = sha256(f"{adapter_key}:{source_id}".encode("utf-8")).hexdigest()[:16]
    return f"ev_{digest}"
