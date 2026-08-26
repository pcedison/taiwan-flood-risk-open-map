from __future__ import annotations

import ast
import json
import socket
from pathlib import Path

import pytest

from app.ops.official_incident_request_packets import (
    EXPECTED_PACKET_IDS,
    build_official_incident_request_packets,
    render_official_incident_request_packets_markdown,
)

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "ops"
    / "official_incident_request_packets.py"
)
FORBIDDEN_SUBSTRINGS = (
    "token",
    "password",
    "cookie",
    "authorization",
    "private-ops://",
)
NETWORK_MODULES = (
    "requests",
    "httpx",
    "urllib.request",
    "urllib3",
    "smtplib",
    "selenium",
    "playwright",
    "socket",
    "aiohttp",
)


def test_exactly_nine_packets_in_the_fixed_order() -> None:
    packets = build_official_incident_request_packets()

    assert EXPECTED_PACKET_IDS == (
        "ncdr-citizen-disaster-report",
        "ncdr-edxl-sitrep",
        "kinmen-kwis-read-api",
        "hualien-senslink-read-api",
        "miaoli-drainage-read-api",
        "pingtung-pteoc-read-api",
        "taitung-water-read-api",
        "lienchiang-live-water-feed",
        "waze-for-cities-flood-incidents",
    )
    assert tuple(packet["packet_id"] for packet in packets) == EXPECTED_PACKET_IDS


def test_every_packet_is_manual_only_with_an_empty_contact() -> None:
    for packet in build_official_incident_request_packets():
        assert packet["requires_human_intervention"] is True
        assert packet["submission_mode"] == "manual_only"
        assert packet["contact_name"] is None
        assert packet["contact_email"] is None


def test_every_packet_declares_purpose_fields_cadence_retention_and_source() -> None:
    for packet in build_official_incident_request_packets():
        packet_id = packet["packet_id"]
        assert packet["purpose_zh"], packet_id
        assert isinstance(packet["requested_fields"], tuple)
        assert packet["requested_fields"], packet_id
        assert packet["expected_cadence"], packet_id
        assert packet["retention_policy_zh"], packet_id
        assert packet["deletion_policy_zh"], packet_id
        assert str(packet["public_source_url"]).startswith("https://"), packet_id
        assert packet["source_url_verification"] in {
            "repo_reviewed_local_source_evidence",
            "unverified_pending_operator_confirmation",
        }, packet_id


def test_serialized_output_contains_no_secret_or_private_reference() -> None:
    packets = build_official_incident_request_packets()
    serialized = json.dumps(_jsonable(packets), ensure_ascii=False).lower()
    markdown = render_official_incident_request_packets_markdown(packets).lower()

    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in serialized, forbidden
        assert forbidden not in markdown, forbidden


def test_markdown_render_lists_every_packet_and_never_sends() -> None:
    packets = build_official_incident_request_packets()
    markdown = render_official_incident_request_packets_markdown(packets)

    for packet_id in EXPECTED_PACKET_IDS:
        assert packet_id in markdown
    assert markdown.count("manual_only") == len(EXPECTED_PACKET_IDS)
    for verb in ("send(", "dispatch(", "smtp", "webhook"):
        assert verb not in markdown.lower()


def test_module_imports_no_network_or_mail_client() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for module in NETWORK_MODULES:
        assert not any(name == module or name.startswith(f"{module}.") for name in imported), module


def test_building_packets_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("packet generation must not touch the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)

    packets = build_official_incident_request_packets()
    render_official_incident_request_packets_markdown(packets)

    assert len(packets) == len(EXPECTED_PACKET_IDS)


def test_packets_are_immutable_and_deterministic() -> None:
    first = build_official_incident_request_packets()
    second = build_official_incident_request_packets()

    assert _jsonable(first) == _jsonable(second)
    first[0]["purpose_zh"] = "mutated"
    assert build_official_incident_request_packets()[0]["purpose_zh"] != "mutated"


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
