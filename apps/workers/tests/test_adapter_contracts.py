from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

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
