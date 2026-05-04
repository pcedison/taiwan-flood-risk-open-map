from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import DataSourceAdapter
from app.adapters.dcard import DcardCandidateFixtureAdapter
from app.adapters.ptt import PttCandidateFixtureAdapter
from app.adapters.registry import enabled_adapter_keys
from app.config import WorkerSettings


def build_forum_candidate_fixture_adapters(
    settings: WorkerSettings,
    *,
    fetched_at: datetime | None = None,
) -> Mapping[str, DataSourceAdapter]:
    resolved_fetched_at = fetched_at or datetime.now(UTC)
    published_at = resolved_fetched_at.isoformat()
    selected_keys = set(enabled_adapter_keys(settings))
    adapters: list[DataSourceAdapter] = []

    if "ptt" in selected_keys:
        adapters.append(
            PttCandidateFixtureAdapter(
                _ptt_fixture_records(published_at),
                fetched_at=resolved_fetched_at,
                raw_snapshot_key="raw/forum-candidate/ptt.json",
            )
        )
    if "dcard" in selected_keys:
        adapters.append(
            DcardCandidateFixtureAdapter(
                _dcard_fixture_records(published_at),
                fetched_at=resolved_fetched_at,
                raw_snapshot_key="raw/forum-candidate/dcard.json",
            )
        )

    return {adapter.metadata.key: adapter for adapter in adapters}


def _ptt_fixture_records(published_at: str) -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "id": "ptt-synthetic-flood-001",
            "url": "https://example.test/forum/ptt/flood-risk-fixture-001",
            "title": "Synthetic PTT fixture: street flooding discussion",
            "summary": (
                "Synthetic local fixture notes street flooding near a low-lying "
                "intersection. No PTT content, usernames, or raw posts are stored."
            ),
            "published_at": published_at,
            "location_text": "Synthetic Low-Lying Intersection",
            "confidence": 0.52,
            "attribution": "Synthetic PTT candidate fixture",
            "tags": ("forum", "ptt", "candidate-contract"),
        },
    )


def _dcard_fixture_records(published_at: str) -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "id": "dcard-synthetic-flood-001",
            "url": "https://example.test/forum/dcard/flood-risk-fixture-001",
            "title": "Synthetic Dcard fixture: ponding discussion",
            "summary": (
                "Synthetic local fixture describes ponding around a campus road. "
                "No Dcard content, user identity, or raw bodies are stored."
            ),
            "published_at": published_at,
            "location_text": "Synthetic Campus Road",
            "confidence": 0.5,
            "attribution": "Synthetic Dcard candidate fixture",
            "tags": ("forum", "dcard", "candidate-contract"),
        },
    )
