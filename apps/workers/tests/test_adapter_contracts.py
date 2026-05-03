from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.adapters.contracts import DataSourceAdapter, EventType, IngestionStatus, SourceFamily
from app.adapters.news import GdeltPublicNewsBackfillAdapter, SamplePublicWebNewsAdapter
from app.adapters.registry import ADAPTER_REGISTRY, enabled_adapter_keys
from app.config import load_worker_settings
from app.pipelines.validation import validate_evidence_for_promotion


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_sample_public_web_news_adapter_normalizes_fixture_records() -> None:
    adapter: DataSourceAdapter = SamplePublicWebNewsAdapter(
        _load_fixture("news_public_web_sample.json"),
        fetched_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
        raw_snapshot_key="raw/news-public-web/sample.json",
    )

    result = adapter.run()

    assert result.adapter_key == "news.public_web.sample"
    assert len(result.fetched) == 2
    assert len(result.normalized) == 2
    assert result.rejected == ()

    first = result.normalized[0]
    assert first.evidence_id.startswith("ev_")
    assert first.source_family is SourceFamily.NEWS
    assert first.event_type is EventType.FLOOD_REPORT
    assert first.source_url == "https://example.test/news/flood-001"
    assert first.location_text == "Riverside District"
    assert first.confidence == 0.72
    assert first.status is IngestionStatus.NORMALIZED


def test_pipeline_validation_accepts_normalized_evidence() -> None:
    adapter = SamplePublicWebNewsAdapter(
        _load_fixture("news_public_web_sample.json"),
        fetched_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )

    validation = validate_evidence_for_promotion(adapter.run().normalized)

    assert len(validation.accepted) == 2
    assert validation.rejected == ()


def test_gdelt_backfill_adapter_normalizes_public_news_articles() -> None:
    fetched_at = datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc)
    adapter = GdeltPublicNewsBackfillAdapter(
        ("台南 長溪路二段 淹水",),
        fetched_at=fetched_at,
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetch_json=lambda _url: {
            "articles": [
                {
                    "url": "https://example.test/news/changxi-flood",
                    "title": "台南安南區長溪路二段多處淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                }
            ]
        },
    )

    result = adapter.run()

    assert result.adapter_key == "news.public_web.gdelt_backfill"
    assert len(result.fetched) == 1
    assert len(result.normalized) == 1
    evidence = result.normalized[0]
    assert evidence.source_family is SourceFamily.NEWS
    assert evidence.event_type is EventType.FLOOD_REPORT
    assert evidence.location_text is not None
    assert "長溪路二段" in evidence.location_text
    assert evidence.confidence >= 0.8
    assert evidence.attribution == "example.test"


def test_gdelt_backfill_url_construction_and_max_records_clamp() -> None:
    captured_urls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        captured_urls.append(url)
        return {"articles": []}

    adapter = GdeltPublicNewsBackfillAdapter(
        ("積淹水 sourcecountry:TW",),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        start_datetime=datetime(2025, 8, 1, 1, 2, 3, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, 4, 5, 6, tzinfo=timezone.utc),
        max_records_per_query=999,
        fetch_json=fetch_json,
    )

    assert adapter.fetch() == ()

    parsed = urlparse(captured_urls[0])
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "api.gdeltproject.org"
    assert params["query"] == ["積淹水 sourcecountry:TW"]
    assert params["mode"] == ["ArtList"]
    assert params["format"] == ["json"]
    assert params["maxrecords"] == ["250"]
    assert params["startdatetime"] == ["20250801010203"]
    assert params["enddatetime"] == ["20250805040506"]


def test_gdelt_backfill_dedupes_by_url_and_keeps_metadata_only() -> None:
    adapter = GdeltPublicNewsBackfillAdapter(
        ("台南市安南區積淹水", "台南市安南區豪雨"),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetch_json=lambda _url: {
            "articles": [
                {
                    "url": "https://example.test/news/duplicate",
                    "title": "台南市安南區積淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "body": "full article text must not be redistributed",
                    "content": "full article text must not be redistributed",
                    "description": "long article excerpt must not be redistributed",
                }
            ]
        },
    )

    result = adapter.run()

    assert len(result.fetched) == 1
    assert result.rejected == ()
    raw_payload = result.fetched[0].payload
    assert raw_payload["url"] == "https://example.test/news/duplicate"
    assert raw_payload["domain"] == "example.test"
    assert raw_payload["sourcecountry"] == "TW"
    assert "body" not in raw_payload
    assert "content" not in raw_payload
    assert "description" not in raw_payload
    evidence = result.normalized[0]
    assert "full article text" not in evidence.summary
    assert evidence.location_text is not None
    assert "安南區" in evidence.location_text


def test_gdelt_backfill_rejects_invalid_title_and_date() -> None:
    adapter = GdeltPublicNewsBackfillAdapter(
        ("台灣豪雨",),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetch_json=lambda _url: {
            "articles": [
                {
                    "url": "https://example.test/news/no-title",
                    "title": " ",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                },
                {
                    "url": "https://example.test/news/no-date",
                    "title": "台北市豪雨積水",
                    "seendate": "not-a-date",
                    "domain": "example.test",
                },
            ]
        },
    )

    result = adapter.run()

    assert len(result.fetched) == 2
    assert result.normalized == ()
    assert result.rejected == tuple(item.source_id for item in result.fetched)


def test_pipeline_validation_rejects_out_of_range_confidence() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "bad-confidence",
                "url": "https://example.test/news/bad-confidence",
                "title": "Bad confidence fixture",
                "summary": "Fixture keeps required fields but has invalid confidence.",
                "published_at": "2026-04-28T09:10:00+00:00",
                "confidence": 1.5,
            }
        ],
        fetched_at=datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc),
    )

    validation = validate_evidence_for_promotion(adapter.run().normalized)

    assert validation.accepted == ()
    assert validation.rejected[0][1] == ("confidence must be between 0.0 and 1.0",)


def test_forum_adapters_remain_disabled_by_default() -> None:
    settings = load_worker_settings({})

    assert "news.public_web.sample" not in enabled_adapter_keys(settings)
    assert "news.public_web.gdelt_backfill" not in enabled_adapter_keys(settings)
    assert "official.cwa.rainfall" in enabled_adapter_keys(settings)
    assert "official.wra.water_level" in enabled_adapter_keys(settings)
    assert "official.flood_potential.geojson" in enabled_adapter_keys(settings)
    assert ADAPTER_REGISTRY["ptt"].enabled_by_default is False
    assert ADAPTER_REGISTRY["ptt"].terms_review_required is True
    assert ADAPTER_REGISTRY["dcard"].enabled_by_default is False
    assert ADAPTER_REGISTRY["dcard"].terms_review_required is True
    assert ADAPTER_REGISTRY["news.public_web.gdelt_backfill"].terms_review_required is True


def _load_fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
