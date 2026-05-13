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
    assert params["maxrecords"] == ["20"]
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


def test_search_public_flood_news_trims_village_prefix_for_numbered_road() -> None:
    requested_queries: list[str] = []

    def fetch_json(url: str, _timeout_seconds: float) -> dict[str, object]:
        query = parse_qs(urlparse(url).query)["query"][0]
        requested_queries.append(query)
        if '"大豐一路"' not in query:
            return {"articles": []}
        return {
            "articles": [
                {
                    "url": "https://example.test/news/sanmin-flood",
                    "title": "高雄三民區大豐一路淹水 地下室災情嚴重",
                    "seendate": "20240727090100",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "language": "Chinese",
                }
            ]
        }

    result = search_public_flood_news(
        location_text="三民區本和里大豐一路",
        lat=22.65646,
        lng=120.32574,
        radius_m=500,
        now=datetime(2026, 5, 7, 3, 0, tzinfo=timezone.utc),
        max_records=5,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
    )

    assert any('"大豐一路"' in query for query in requested_queries)
    assert len(result.records) == 1
    assert result.records[0].properties["location_match_scope"] == "road"


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


def test_search_public_flood_news_checks_previous_year_when_recent_window_misses() -> None:
    requested_windows: list[tuple[str, str]] = []

    def fetch_json(url: str, _timeout_seconds: float) -> dict[str, object]:
        params = parse_qs(urlparse(url).query)
        window = (params["startdatetime"][0], params["enddatetime"][0])
        requested_windows.append(window)
        if window != ("20250101000000", "20251231235959"):
            return {"articles": []}
        return {
            "articles": [
                {
                    "url": "https://example.test/news/tainan-july-flood",
                    "title": "台南安南區培安路水淹 民眾清理家園",
                    "seendate": "20250728103000",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "language": "Chinese",
                }
            ]
        }

    result = search_public_flood_news(
        location_text="台南安南區培安路",
        lat=23.03844,
        lng=120.21315,
        radius_m=500,
        now=datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
    )

    assert ("20250101000000", "20251231235959") in requested_windows
    assert len(result.records) == 1
    assert result.records[0].properties["search_window"] == "2025"


def test_search_public_flood_news_uses_public_metadata_beyond_title_for_location_match() -> None:
    def fetch_json(url: str, _timeout_seconds: float) -> dict[str, object]:
        query = parse_qs(urlparse(url).query)["query"][0]
        if '"汐止區康寧街"' not in query:
            return {"articles": []}
        return {
            "articles": [
                {
                    "url": "https://example.test/news/xizhi-flood",
                    "title": "豪雨造成道路積水 多處交通受阻",
                    "description": "新北市汐止區康寧街一帶水淹，住戶上午清理積水。",
                    "seendate": "20250710120000",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "language": "Chinese",
                }
            ]
        }

    result = search_public_flood_news(
        location_text="新北汐止康寧街",
        lat=25.068,
        lng=121.628,
        radius_m=500,
        now=datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.title == "豪雨造成道路積水 多處交通受阻"
    assert record.properties["location_match_scope"] == "road"
    assert record.properties["full_text_stored"] is False


def test_search_public_flood_news_expands_representative_taiwan_regions() -> None:
    cases = (
        ("台北文山木柵路", "文山區木柵路", "台北文山區木柵路豪雨淹水"),
        ("台中太平樹孝路", "太平區樹孝路", "台中太平區樹孝路道路積水"),
        ("高雄三民大豐一路", "三民區大豐一路", "高雄三民區大豐一路水淹"),
        ("宜蘭羅東中正路", "羅東中正路", "宜蘭羅東中正路颱風積水"),
        ("花蓮市中山路", "花蓮市中山路", "花蓮市中山路豪雨淹水"),
    )

    for location_text, expected_query_term, title in cases:

        def fetch_json(url: str, _timeout_seconds: float) -> dict[str, object]:
            query = parse_qs(urlparse(url).query)["query"][0]
            if f'"{expected_query_term}"' not in query:
                return {"articles": []}
            return {
                "articles": [
                    {
                        "url": f"https://example.test/news/{expected_query_term}",
                        "title": title,
                        "seendate": "20250710120000",
                        "domain": "example.test",
                        "sourcecountry": "TW",
                        "language": "Chinese",
                    }
                ]
            }

        result = search_public_flood_news(
            location_text=location_text,
            lat=24.0,
            lng=121.0,
            radius_m=500,
            now=datetime(2026, 5, 4, 3, 0, tzinfo=timezone.utc),
            max_records=1,
            timeout_seconds=2.5,
            fetch_json=fetch_json,
        )

        assert len(result.records) == 1, location_text


def test_search_public_flood_news_uses_rss_backup_when_gdelt_is_unavailable() -> None:
    requested_feed_urls: list[str] = []

    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {}

    def fetch_text(url: str, _timeout_seconds: float) -> str:
        requested_feed_urls.append(url)
        return """<?xml version="1.0" encoding="utf-8" ?>
        <rss version="2.0">
          <channel>
            <item>
              <title>彰化員林中山路水淹 店家清理積水</title>
              <link>https://example.test/news/yuanlin-flood</link>
              <pubDate>Thu, 10 Jul 2025 04:00:00 GMT</pubDate>
              <description>彰化員林中山路豪雨後道路積水。</description>
            </item>
          </channel>
        </rss>
        """

    result = search_public_flood_news(
        location_text="彰化員林中山路",
        lat=23.956,
        lng=120.57,
        radius_m=500,
        now=datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )

    assert requested_feed_urls
    assert len(result.records) == 1
    record = result.records[0]
    assert record.adapter_key == "news.public_web.on_demand_search"
    assert record.source_id.startswith("public-news-rss:")
    assert record.title == "彰化員林中山路水淹 店家清理積水"
    assert record.url == "https://example.test/news/yuanlin-flood"
    assert record.properties["ingestion_mode"] == "on_demand_public_news_rss"
    assert record.properties["location_match_scope"] == "road"
    assert record.properties["location_match_basis"] == "exact"
    assert record.properties["full_text_stored"] is False


def test_search_public_flood_news_rejects_same_road_in_wrong_admin_area() -> None:
    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {}

    def fetch_text(_url: str, _timeout_seconds: float) -> str:
        return """<?xml version="1.0" encoding="utf-8" ?>
        <rss version="2.0">
          <channel>
            <item>
              <title>神岡中山路長期積淹水 居民陳情改善</title>
              <link>https://example.test/news/shengang-flood</link>
              <pubDate>Mon, 28 Jul 2025 07:00:00 GMT</pubDate>
              <description>台中神岡中山路豪雨後道路積水。</description>
            </item>
          </channel>
        </rss>
        """

    result = search_public_flood_news(
        location_text="彰化員林中山路",
        lat=23.956,
        lng=120.57,
        radius_m=500,
        now=datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )

    assert result.records == ()


def test_search_public_flood_news_accepts_rss_admin_context_when_road_title_is_broader() -> None:
    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {}

    def fetch_text(_url: str, _timeout_seconds: float) -> str:
        return """<?xml version="1.0" encoding="utf-8" ?>
        <rss version="2.0">
          <channel>
            <item>
              <title>員林市區大淹水 救護車寸步難行</title>
              <link>https://example.test/news/yuanlin-city-flood</link>
              <pubDate>Tue, 08 Jul 2025 07:00:00 GMT</pubDate>
              <description>彰化員林豪雨造成市區水淹。</description>
            </item>
          </channel>
        </rss>
        """

    result = search_public_flood_news(
        location_text="彰化員林中山路",
        lat=23.956,
        lng=120.57,
        radius_m=500,
        now=datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.title == "員林市區大淹水 救護車寸步難行"
    assert record.properties["location_match_scope"] == "admin_area"
    assert record.properties["location_match_basis"] == "relaxed_admin_context"
    assert record.distance_to_query_m is None
    assert record.source_weight == 0.58


def test_search_public_flood_news_rss_reaches_2023_queries() -> None:
    requested_queries: list[str] = []

    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {"articles": []}

    def fetch_text(url: str, _timeout_seconds: float) -> str:
        requested_queries.append(parse_qs(urlparse(url).query)["q"][0])
        return """<?xml version="1.0" encoding="utf-8" ?>
        <rss version="2.0"><channel></channel></rss>
        """

    search_public_flood_news(
        location_text="嘉義市",
        lat=23.48,
        lng=120.45,
        radius_m=500,
        now=datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc),
        max_records=1,
        timeout_seconds=5.0,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )

    assert any("2023" in query for query in requested_queries)


def test_search_public_flood_news_uses_wiki_public_metadata_fallback() -> None:
    requested_wiki_queries: list[str] = []

    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {"articles": []}

    def fetch_wiki_json(url: str, _timeout_seconds: float) -> dict[str, object]:
        params = parse_qs(urlparse(url).query)
        query = (params.get("q") or params.get("srsearch") or [""])[0]
        requested_wiki_queries.append(query)
        if "2023" not in query:
            return {"pages": []} if "api.wikimedia.org" in url else {"query": {"search": []}}
        if "api.wikimedia.org" in url:
            return {
                "pages": [
                    {
                        "key": "2023年9月嘉義暴雨",
                        "title": "2023年9月嘉義暴雨",
                        "excerpt": (
                            '<span class="searchmatch">2023</span>年9月'
                            '<span class="searchmatch">嘉義</span>縣與'
                            '<span class="searchmatch">嘉義市</span>持續暴雨，'
                            "造成道路淹水與災情。"
                        ),
                        "description": "指嘉義縣與嘉義市於2023年9月發生的天災事件",
                    }
                ]
            }
        return {
            "query": {
                "search": [
                    {
                        "title": "2023年9月嘉義暴雨",
                        "snippet": (
                            '<span class="searchmatch">2023</span>年9月'
                            '<span class="searchmatch">嘉義</span>縣與'
                            '<span class="searchmatch">嘉義市</span>持續暴雨，'
                            "造成道路淹水與災情。"
                        ),
                        "timestamp": "2025-11-01T00:00:00Z",
                    }
                ]
            }
        }

    result = search_public_flood_news(
        location_text="嘉義市",
        lat=23.48,
        lng=120.45,
        radius_m=500,
        now=datetime(2026, 5, 13, 3, 0, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=fetch_json,
        fetch_wiki_json=fetch_wiki_json,
    )

    assert any("2023" in query for query in requested_wiki_queries)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.adapter_key == "news.public_web.wiki_search"
    assert record.source_id.startswith("public-wiki:")
    assert record.title == "2023年9月嘉義暴雨"
    assert record.url == "https://zh.wikipedia.org/wiki/2023%E5%B9%B49%E6%9C%88%E5%98%89%E7%BE%A9%E6%9A%B4%E9%9B%A8"
    assert record.occurred_at == datetime(2023, 9, 1, tzinfo=timezone.utc)
    assert record.properties["ingestion_mode"] == "on_demand_public_wiki"
    assert record.properties["location_match_scope"] == "exact"
    assert record.properties["full_text_stored"] is False
