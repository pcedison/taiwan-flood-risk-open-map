from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app.domain.history.news_enrichment import search_public_flood_news


def test_search_public_flood_news_builds_bounded_gdelt_metadata_query() -> None:
    requested_urls: list[str] = []

    def fetch_json(url: str, timeout_seconds: float) -> dict[str, object]:
        requested_urls.append(url)
        assert 0.5 <= timeout_seconds <= 2.5
        return {
            "articles": [
                {
                    "url": "https://example.test/news/taichung-flood",
                    "title": "台中太平樹孝路豪雨淹水 多處交通受阻",
                    "seendate": "20240501123000",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "language": "Chinese",
                },
                {
                    "url": "https://example.test/news/other-place",
                    "title": "台南豪雨淹水 多處交通受阻",
                    "seendate": "20240501123000",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "language": "Chinese",
                },
            ]
        }

    result = search_public_flood_news(
        location_text="2024 台中太平樹孝路 淹水",
        lat=24.153,
        lng=120.719,
        radius_m=500,
        now=datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc),
        max_records=5,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
    )

    parsed = urlparse(requested_urls[0])
    params = parse_qs(parsed.query)
    assert params["mode"] == ["ArtList"]
    assert params["format"] == ["json"]
    assert params["maxrecords"] == ["5"]
    assert "sourcecountry:TW" in params["query"][0]
    assert result.attempted is True
    assert len(result.records) == 1
    record = result.records[0]
    assert record.title == "台中太平樹孝路豪雨淹水 多處交通受阻"
    assert record.lat == 24.153
    assert record.lng == 120.719
    assert record.properties["location_match_scope"] == "exact"
    assert record.properties["full_text_stored"] is False
    assert record.properties["citation_only"] is True


def test_search_public_flood_news_falls_back_to_admin_road_terms() -> None:
    requested_queries: list[str] = []

    def fetch_json(url: str, _timeout_seconds: float) -> dict[str, object]:
        query = parse_qs(urlparse(url).query)["query"][0]
        requested_queries.append(query)
        if '"岡山區嘉新東路"' not in query:
            return {"articles": []}
        return {
            "articles": [
                {
                    "url": "https://example.test/news/okshan-flood",
                    "title": "岡山區嘉新東路豪雨淹水 地下道一度封閉",
                    "seendate": "20240725103000",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "language": "Chinese",
                }
            ]
        }

    result = search_public_flood_news(
        location_text="2024 高雄岡山嘉新東路 淹水｜嘉新東路（由查詢文字萃取地名）",
        lat=22.8073,
        lng=120.298,
        radius_m=500,
        now=datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc),
        max_records=5,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
    )

    assert any('"岡山區嘉新東路"' in query for query in requested_queries)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.title == "岡山區嘉新東路豪雨淹水 地下道一度封閉"
    assert record.properties["location_match_scope"] == "road"
    assert record.source_weight < 0.86


def test_search_public_flood_news_returns_not_attempted_without_location() -> None:
    result = search_public_flood_news(
        location_text=None,
        lat=24.153,
        lng=120.719,
        radius_m=500,
        now=datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc),
        max_records=5,
        timeout_seconds=2.5,
        fetch_json=lambda *_args: {"articles": []},
    )

    assert result.attempted is False
    assert result.records == ()
