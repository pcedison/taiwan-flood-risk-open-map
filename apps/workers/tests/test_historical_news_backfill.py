from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.jobs.historical_news_backfill import (
    HistoricalNewsBackfillConfig,
    build_historical_news_backfill_batch,
    run_historical_news_backfill_rehearsal,
)


@pytest.mark.parametrize(
    (
        "gdelt_source_enabled",
        "gdelt_backfill_enabled",
        "source_news_enabled",
        "terms_ack",
        "message",
    ),
    [
        (False, False, False, False, "GDELT_SOURCE_ENABLED=true"),
        (True, False, False, False, "disabled by default"),
        (True, True, False, False, "SOURCE_NEWS_ENABLED=true"),
        (True, True, True, False, "SOURCE_TERMS_REVIEW_ACK=true"),
    ],
)
def test_historical_news_backfill_is_no_network_until_all_gates_pass(
    gdelt_source_enabled: bool,
    gdelt_backfill_enabled: bool,
    source_news_enabled: bool,
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
        gdelt_source_enabled=gdelt_source_enabled,
        gdelt_backfill_enabled=gdelt_backfill_enabled,
        source_news_enabled=source_news_enabled,
        source_terms_review_ack=terms_ack,
        fetch_json=fetch_json,
    )

    with pytest.raises(RuntimeError, match=message):
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
        gdelt_source_enabled=True,
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
        gdelt_source_enabled=True,
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


def test_gdelt_rehearsal_staging_batch_contract_is_bounded_and_metadata_only() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "articles": [
                {
                    "url": f"https://example.test/news/{len(calls)}",
                    "title": "台南安南區長溪路二段淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "body": "must not be staged",
                }
            ]
        }

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台南淹水", "安南區豪雨"),
        max_records_per_query=7,
        request_cadence_seconds=30,
        gdelt_source_enabled=True,
        gdelt_backfill_enabled=True,
        source_news_enabled=True,
        source_terms_review_ack=True,
        fetch_json=fetch_json,
        sleep=sleeps.append,
    )

    result = run_historical_news_backfill_rehearsal(config, mode="staging-batch")

    assert len(calls) == 2
    assert "maxrecords=7" in calls[0]
    assert sleeps == [30.0]
    assert result.batch is not None
    assert result.batch.adapter_key == "news.public_web.gdelt_backfill"
    assert len(result.batch.accepted) == 2
    assert result.metadata["metadata_only"] is True
    assert result.metadata["rate_limit_contract"] == "one bounded GDELT DOC request per query"
    assert result.metadata["cadence_seconds"] == 30
    assert result.metadata["max_records_per_query"] == 7
    assert result.batch.raw_snapshot.metadata["items_fetched"] == 2
