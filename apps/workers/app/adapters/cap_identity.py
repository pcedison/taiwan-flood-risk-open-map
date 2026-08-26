from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime


def canonical_cap_message_json(*, sender: str, identifier: str, sent: datetime) -> str:
    if sent.tzinfo is None or sent.utcoffset() is None:
        raise ValueError("CAP sent must be timezone-aware")
    sent_utc = sent.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return json.dumps(
        [sender.strip(), identifier.strip(), sent_utc],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def cap_message_digest(*, sender: str, identifier: str, sent: datetime) -> str:
    canonical = canonical_cap_message_json(sender=sender, identifier=identifier, sent=sent)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cap_source_id(
    *,
    sender: str,
    identifier: str,
    sent: datetime,
    admin_code: str | None,
    message_level: bool = False,
) -> str:
    if not message_level and re.fullmatch(r"[0-9]{8}", admin_code or "") is None:
        raise ValueError("CAP area source id requires canonical admin code")
    digest = cap_message_digest(sender=sender, identifier=identifier, sent=sent)
    discriminator = "message" if message_level else f"area:{admin_code}"
    return f"cap:{digest}:{discriminator}"


def official_event_origin_key(
    *, sender: str, identifier: str, sent: datetime, admin_code: str
) -> str:
    if re.fullmatch(r"[0-9]{8}", admin_code) is None:
        raise ValueError("CAP area origin requires canonical admin code")
    if sent.tzinfo is None or sent.utcoffset() is None:
        raise ValueError("CAP sent must be timezone-aware")
    canonical = json.dumps(
        [
            sender.strip(),
            identifier.strip(),
            sent.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            admin_code,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
