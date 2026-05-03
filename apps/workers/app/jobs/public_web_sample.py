from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import DataSourceAdapter
from app.adapters.news import SamplePublicWebNewsAdapter


def build_public_web_sample_adapters(
    *,
    fetched_at: datetime | None = None,
) -> Mapping[str, DataSourceAdapter]:
    resolved_fetched_at = fetched_at or datetime.now(UTC)
    adapter = SamplePublicWebNewsAdapter(
        _sample_public_web_records(resolved_fetched_at.isoformat()),
        fetched_at=resolved_fetched_at,
        raw_snapshot_key="raw/news-public-web/sample.json",
    )
    return {adapter.metadata.key: adapter}


def _sample_public_web_records(published_at: str) -> tuple[Mapping[str, Any], ...]:
    return (
        {
            "id": "sample-news-001",
            "url": "https://example.test/news/flood-001",
            "title": "Heavy rain reported near riverside district",
            "summary": "Public report describes street flooding near the riverside district.",
            "published_at": published_at,
            "location_text": "Riverside District",
            "confidence": 0.72,
            "attribution": "Example Public News",
            "tags": ("rain", "street-flooding"),
        },
        {
            "id": "sample-news-002",
            "url": "https://example.test/news/flood-002",
            "title": "Road underpass temporarily closed after rainfall",
            "summary": "A public web update notes ponding around a low-lying underpass.",
            "published_at": published_at,
            "location_text": "Lowland Underpass",
            "confidence": 0.65,
            "attribution": "Example Public News",
            "tags": ("road", "underpass"),
        },
    )
