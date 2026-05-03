from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.jobs.historical_news_backfill import (
    HistoricalNewsBackfillConfig,
    build_historical_news_backfill_batch,
)


def test_historical_news_backfill_is_disabled_before_explicit_gates() -> None:
    calls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"articles": []}

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台灣豪雨",),
        fetch_json=fetch_json,
    )

    with pytest.raises(RuntimeError, match="disabled by default"):
        build_historical_news_backfill_batch(config)

    assert calls == []


@pytest.mark.parametrize(
    ("news_enabled", "terms_ack", "message"),
    [
        (False, True, "SOURCE_NEWS_ENABLED=true"),
        (True, False, "SOURCE_TERMS_REVIEW_ACK=true"),
    ],
)
def test_historical_news_backfill_requires_news_and_terms_gates(
    news_enabled: bool,
    terms_ack: bool,
    message: str,
) -> None:
    calls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"articles": []}

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台灣豪雨",),
        gdelt_backfill_enabled=True,
        source_news_enabled=news_enabled,
        source_terms_review_ack=terms_ack,
        fetch_json=fetch_json,
    )

    with pytest.raises(RuntimeError, match=message):
        build_historical_news_backfill_batch(config)

    assert calls == []


def test_historical_news_backfill_uses_injected_fetcher_when_all_gates_pass() -> None:
    calls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "articles": [
                {
                    "url": "https://example.test/news/annnan-flood",
                    "title": "台南市安南區積淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                }
            ]
        }

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台南市安南區積淹水",),
        gdelt_backfill_enabled=True,
        source_news_enabled=True,
        source_terms_review_ack=True,
        fetch_json=fetch_json,
    )

    batch = build_historical_news_backfill_batch(config)

    assert len(calls) == 1
    assert batch.adapter_key == "news.public_web.gdelt_backfill"
    assert len(batch.accepted) == 1
    assert batch.rejected == ()
