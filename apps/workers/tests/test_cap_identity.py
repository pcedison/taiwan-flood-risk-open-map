from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

CAP_SENT = datetime(2026, 8, 24, 1, 2, 3, 456789, tzinfo=UTC)


def test_cap_message_identity_uses_canonical_utc_microseconds() -> None:
    try:
        cap_identity = import_module("app.adapters.cap_identity")
    except ModuleNotFoundError:
        cap_identity = None

    assert cap_identity is not None
    assert cap_identity.canonical_cap_message_json(
        sender=" sender@example.test ",
        identifier=" alert-1 ",
        sent=CAP_SENT,
    ) == '["sender@example.test","alert-1","2026-08-24T01:02:03.456789Z"]'


def test_cap_message_digest_is_collision_safe_at_field_boundaries() -> None:
    cap_identity = import_module("app.adapters.cap_identity")
    digest = getattr(cap_identity, "cap_message_digest", None)

    assert callable(digest)
    assert digest(sender="sender|a", identifier="b", sent=CAP_SENT) != digest(
        sender="sender", identifier="a|b", sent=CAP_SENT
    )


def test_cap_source_id_distinguishes_area_and_message_level_records() -> None:
    cap_identity = import_module("app.adapters.cap_identity")
    source_id = getattr(cap_identity, "cap_source_id", None)

    assert callable(source_id)
    area_id = source_id(
        sender="sender", identifier="alert", sent=CAP_SENT, admin_code="67000000"
    )
    message_id = source_id(
        sender="sender",
        identifier="alert",
        sent=CAP_SENT,
        admin_code=None,
        message_level=True,
    )
    assert area_id.endswith(":area:67000000")
    assert message_id.endswith(":message")
    with pytest.raises(ValueError, match="canonical admin code"):
        source_id(sender="sender", identifier="alert", sent=CAP_SENT, admin_code="67000")


def test_official_event_origin_key_includes_admin_area() -> None:
    cap_identity = import_module("app.adapters.cap_identity")
    origin_key = getattr(cap_identity, "official_event_origin_key", None)

    assert callable(origin_key)
    assert origin_key(
        sender="sender", identifier="alert", sent=CAP_SENT, admin_code="67000000"
    ) != origin_key(
        sender="sender", identifier="alert", sent=CAP_SENT, admin_code="64000000"
    )


def test_cap_source_id_distinguishes_each_admin_area_for_one_message() -> None:
    cap_identity = import_module("app.adapters.cap_identity")

    tainan = cap_identity.cap_source_id(
        sender="sender", identifier="alert", sent=CAP_SENT, admin_code="67000000"
    )
    kaohsiung = cap_identity.cap_source_id(
        sender="sender", identifier="alert", sent=CAP_SENT, admin_code="64000000"
    )

    assert tainan != kaohsiung


def test_cap_message_identity_changes_when_only_sender_changes() -> None:
    cap_identity = import_module("app.adapters.cap_identity")

    assert cap_identity.cap_source_id(
        sender="first@example.test",
        identifier="alert",
        sent=CAP_SENT,
        admin_code="67000000",
    ) != cap_identity.cap_source_id(
        sender="second@example.test",
        identifier="alert",
        sent=CAP_SENT,
        admin_code="67000000",
    )


def test_cap_message_identity_changes_when_only_sent_changes() -> None:
    cap_identity = import_module("app.adapters.cap_identity")

    assert cap_identity.cap_source_id(
        sender="sender",
        identifier="alert",
        sent=CAP_SENT,
        admin_code="67000000",
    ) != cap_identity.cap_source_id(
        sender="sender",
        identifier="alert",
        sent=CAP_SENT + timedelta(microseconds=1),
        admin_code="67000000",
    )


@pytest.mark.parametrize("admin_code", ["６７００００００", "67000", "6700000A"])
def test_cap_area_identity_rejects_non_ascii_or_malformed_admin_code(
    admin_code: str,
) -> None:
    cap_identity = import_module("app.adapters.cap_identity")

    with pytest.raises(ValueError, match="canonical admin code"):
        cap_identity.cap_source_id(
            sender="sender",
            identifier="alert",
            sent=CAP_SENT,
            admin_code=admin_code,
        )
    with pytest.raises(ValueError, match="canonical admin code"):
        cap_identity.official_event_origin_key(
            sender="sender",
            identifier="alert",
            sent=CAP_SENT,
            admin_code=admin_code,
        )
