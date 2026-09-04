from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, quote, urlparse

from app.domain.history.news_enrichment import (
    TAIWAN_OFFICIAL_HISTORY_ADAPTER_KEY,
    _google_news_decode_params,
    _google_news_decoded_url,
    _official_history_text_qualifies,
    _record_from_article,
    search_public_flood_news,
    search_taiwan_official_flood_citations,
    search_tainan_official_flood_news,
)


def test_tainan_official_news_recovers_recent_district_flood_without_claiming_point_depth() -> None:
    payload = """
    <html><body><table>
      <tr>
        <td data-title="刊登日期"><span>115-08-27</span></td>
        <td data-title="標題"><a href="News_Content.aspx?n=13370&amp;s=1"
          title="臺南豪雨農損救助">臺南豪雨農損救助</a></td>
      </tr>
      <tr>
        <td data-title="刊登日期"><span>115-08-24</span></td>
        <td data-title="標題"><a href="https://www.tainan.gov.tw/News_Content.aspx?n=13370&amp;s=8832256"
          title="黃偉哲視察安南、仁德淹水災情">黃偉哲視察安南、仁德淹水災情</a></td>
      </tr>
    </table></body></html>
    """

    result = search_tainan_official_flood_news(
        location_text="培安路305巷",
        lat=23.03882,
        lng=120.21349,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
    )

    assert result.attempted is True
    assert len(result.records) == 1
    record = result.records[0]
    assert record.title == "黃偉哲視察安南、仁德淹水災情"
    assert record.source_type == "official"
    assert record.adapter_key == "official.tainan.disaster_news"
    assert record.occurred_at == datetime(2026, 8, 24, tzinfo=timezone(timedelta(hours=8)))
    assert record.distance_to_query_m is None
    assert record.properties["evidence_scope"] == "historical"
    assert record.properties["location_precision"] == "admin_area"
    assert "未提供查詢門牌" in record.properties["limitations"][0]
    assert record.properties["full_text_stored"] is False


def test_tainan_reviewed_incident_bootstrap_survives_official_index_egress_failure() -> None:
    result = search_tainan_official_flood_news(
        location_text="培安路305巷",
        lat=23.03882,
        lng=120.21349,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: "",
    )

    assert result.attempted is True
    assert result.health_status == "degraded"
    assert len(result.records) == 1
    assert result.records[0].title.startswith("黃偉哲視察安南、仁德淹水災情")
    assert result.records[0].url == (
        "https://www.tainan.gov.tw/News_Content.aspx?n=13370&s=8832256"
    )
    assert "隨版本審核" in result.message


def test_nationwide_official_citations_accept_other_counties_and_recent_years_only() -> None:
    requested_urls: list[str] = []
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel>
      <item>
        <title>臺中市太平區樹孝路豪雨積淹水</title>
        <link>https://www.taichung.gov.tw/incident/2024-flood</link>
        <pubDate>Wed, 01 May 2024 04:30:00 GMT</pubDate>
      </item>
      <item>
        <title>臺中市太平區樹孝路豪雨積淹水</title>
        <link>https://news.example.test/incident/2024-flood</link>
        <pubDate>Wed, 01 May 2024 04:30:00 GMT</pubDate>
      </item>
      <item>
        <title>臺中市太平區樹孝路豪雨積淹水</title>
        <link>https://www.taichung.gov.tw/incident/2018-flood</link>
        <pubDate>Tue, 01 May 2018 04:30:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    def fetch_text(url: str, _timeout: float) -> str:
        requested_urls.append(url)
        return payload

    result = search_taiwan_official_flood_citations(
        location_text="臺中市太平區樹孝路",
        lat=24.154,
        lng=120.716,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        max_records=3,
        fetch_text=fetch_text,
    )

    assert result.attempted is True
    assert result.health_status == "healthy"
    assert len(result.records) == 1
    record = result.records[0]
    assert record.adapter_key == "official.gov_tw.flood_citation"
    assert record.source_type == "official"
    assert record.url == "https://www.taichung.gov.tw/incident/2024-flood"
    assert record.distance_to_query_m is None
    assert record.properties["coverage_start_year"] == 2020
    assert record.properties["coverage_end_year"] == 2026
    assert record.properties["coverage_is_complete"] is False
    assert record.properties["full_text_stored"] is False
    assert any("2026" in url and "2020" in url for url in requested_urls)


def test_nationwide_official_citations_search_admin_area_before_exact_road() -> None:
    requested_queries: list[str] = []
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel>
    <item>
      <title>安南區排水改善降低淹水風險</title>
      <link>https://wrb1.tainan.gov.tw/archive/2021-drainage</link>
      <pubDate>Mon, 24 Aug 2021 12:38:00 GMT</pubDate>
    </item>
    <item>
      <title>黃偉哲視察安南、仁德淹水災情</title>
      <link>https://www.tainan.gov.tw/News_Content.aspx?n=13370&amp;s=8832256</link>
      <pubDate>Mon, 24 Aug 2026 12:38:00 GMT</pubDate>
    </item>
    </channel></rss>"""

    def fetch_text(url: str, _timeout: float) -> str:
        query = parse_qs(urlparse(url).query)["q"][0]
        requested_queries.append(query)
        return payload

    result = search_taiwan_official_flood_citations(
        location_text="台南市安南區培安路",
        lat=23.04477,
        lng=120.21154,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        max_records=1,
        fetch_text=fetch_text,
    )

    assert requested_queries
    assert "安南區" in requested_queries[0]
    assert "培安路" not in requested_queries[0]
    assert len(result.records) == 1
    assert result.records[0].occurred_at == datetime(
        2026,
        8,
        24,
        12,
        38,
        tzinfo=timezone.utc,
    )
    assert result.records[0].properties["location_precision"] == "admin_area"


def test_nationwide_official_citations_rejects_preparedness_and_planning_pages() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel>
    <item>
      <title>巴威颱風逼近 安南區全面強化防災整備</title>
      <link>https://www.tainan.gov.tw/preparation/2026-typhoon</link>
      <pubDate>Thu, 09 Jul 2026 04:48:17 GMT</pubDate>
    </item>
    <item>
      <title>新建雨水下水道降低安南區淹水潛勢</title>
      <link>https://wrb1.tainan.gov.tw/planning/2026-drainage</link>
      <pubDate>Thu, 09 Jul 2026 03:48:17 GMT</pubDate>
    </item>
    </channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="台南市安南區培安路",
        lat=23.04477,
        lng=120.21154,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        max_records=3,
        fetch_text=lambda _url, _timeout: payload,
    )

    assert result.records == ()


def test_nationwide_official_citations_keeps_incident_that_mentions_follow_up_work() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>豪雨造成安南區淹水，市府加速改善淹水工程</title>
      <link>https://www.tainan.gov.tw/incident-and-recovery/2026-flood</link>
      <pubDate>Mon, 24 Aug 2026 12:38:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="台南市安南區培安路",
        lat=23.04477,
        lng=120.21154,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
    )

    assert len(result.records) == 1
    assert result.records[0].occurred_at == datetime(
        2026,
        8,
        24,
        12,
        38,
        tzinfo=timezone.utc,
    )


def test_nationwide_official_citations_accepts_official_gov_taipei_domain() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>臺北市文山區木柵路道路積水</title>
      <link>https://water.gov.taipei/News_Content.aspx?n=1&amp;s=2</link>
      <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="臺北市文山區木柵路",
        lat=24.988,
        lng=121.566,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
    )

    assert len(result.records) == 1
    assert result.records[0].url.startswith("https://water.gov.taipei/")


def test_nationwide_official_citations_rejects_aggregator_link_with_official_publisher() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>高雄市仁武區道路積淹水</title>
      <link>https://news.google.com/rss/articles/example</link>
      <source url="https://rwdo.kcg.gov.tw/">高雄市政府水利局</source>
      <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="高雄市仁武區",
        lat=22.701,
        lng=120.36,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
        resolve_url=lambda _url, _timeout: None,
    )

    assert result.records == ()
    assert result.health_status == "unknown"


def test_nationwide_official_citations_retains_decoded_direct_government_url() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>高雄市仁武區道路積淹水</title>
      <link>https://news.google.com/rss/articles/example</link>
      <source url="https://rwdo.kcg.gov.tw/">高雄市政府水利局</source>
      <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
    </item></channel></rss>"""
    direct_url = "https://rwdo.kcg.gov.tw/News_Content.aspx?n=1&amp;s=2"

    result = search_taiwan_official_flood_citations(
        location_text="高雄市仁武區",
        lat=22.701,
        lng=120.36,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
        resolve_url=lambda _url, _timeout: direct_url.replace("&amp;", "&"),
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.url == "https://rwdo.kcg.gov.tw/News_Content.aspx?n=1&s=2"
    assert record.properties["source_domain"] == "rwdo.kcg.gov.tw"
    assert record.properties["official_publisher_url"] == "https://rwdo.kcg.gov.tw/"
    assert record.properties["publisher_name"] == "高雄市政府水利局"


def test_nationwide_official_citations_verifies_location_on_generic_official_page() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>災情詳情－積淹水災情</title>
      <link>https://news.google.com/rss/articles/example</link>
      <source url="https://ktc.kcg.gov.tw/">高雄數位市民</source>
      <pubDate>Tue, 25 Aug 2026 05:48:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="高雄市仁武區",
        lat=22.701,
        lng=120.36,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
        resolve_url=lambda _url, _timeout: (
            "https://ktc.kcg.gov.tw/disaster/detail?id=102026064754139"
        ),
        fetch_citation_text=lambda _url, _timeout: (
            "<html><head><title>積淹水災情：仁武區高楠公路路面積水</title></head>"
            "<body><p>詳細內容說明。</p></body></html>"
        ),
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.url == "https://ktc.kcg.gov.tw/disaster/detail?id=102026064754139"
    assert record.properties["location_precision"] == "admin_area"
    assert record.properties["location_verification"] == "direct_official_page"
    assert record.properties["full_text_stored"] is False


def test_google_news_signed_redirect_metadata_is_parsed_without_article_content() -> None:
    html = (
        '<c-wiz data-n-a-id="example" data-n-a-sg="signed-value" '
        'data-n-a-ts="1788134400"></c-wiz>'
    )
    assert _google_news_decode_params(html, article_id="example") == (
        "signed-value",
        "1788134400",
    )

    direct_url = "https://www.tainan.gov.tw/News_Content.aspx?n=13370&s=8832256"
    rpc_payload = json.dumps(
        [["wrb.fr", "Fbv4je", json.dumps([None, direct_url]), None]],
        separators=(",", ":"),
    )
    assert _google_news_decoded_url(")]}'\n" + rpc_payload) == direct_url


def test_nationwide_official_citations_keep_village_context_at_admin_precision() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>臺北市文山區萬興里豪雨積淹水</title>
      <link>https://water.gov.taipei/flood/wanxing</link>
      <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text=None,
        lat=25.006,
        lng=121.573,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.properties["location_precision"] == "admin_area"
    assert record.properties["location_match_scope"] == "admin_area"
    assert record.distance_to_query_m is None


def test_nationwide_official_citations_rejects_wrong_district_in_same_city() -> None:
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>新北市瑞芳區豪雨積淹水</title>
      <link>https://www.ntpc.gov.tw/flood/ruifang</link>
      <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="新北市板橋區文化路",
        lat=25.011,
        lng=121.461,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
    )

    assert result.records == ()


def test_official_history_text_qualifies_rejects_dengue_prevention_notice() -> None:
    assert (
        _official_history_text_qualifies(
            "大雨過後記得整理戶內外環境，確實清除積水容器，提醒民眾做好防蚊措施"
        )
        is False
    )


def test_official_history_text_qualifies_rejects_faq_page() -> None:
    assert (
        _official_history_text_qualifies("豪大雨造成一般道路積淹水時，應向哪個單位通報?")
        is False
    )


def test_official_history_text_qualifies_rejects_typhoon_preparedness_notice() -> None:
    assert _official_history_text_qualifies("迎戰巴威颱風！楊文科坐鎮防颱整備") is False


def test_official_history_text_qualifies_rejects_completed_drainage_project_notice() -> None:
    assert (
        _official_history_text_qualifies("改善板本排水及護岸橋梁 解決大村、秀水淹水問題")
        is False
    )


def test_official_history_text_qualifies_accepts_genuine_incident_report() -> None:
    assert (
        _official_history_text_qualifies("卓揆赴宜蘭蘇澳關心淹水災情 指示地方政府加速清淤復原")
        is True
    )


def test_official_history_text_qualifies_accepts_incident_with_followup_sanitation() -> None:
    # "消毒" is a soft-exclude phrase, but this text also carries genuine
    # incident markers ("災情"/"災後") and must not be rejected for that.
    assert (
        _official_history_text_qualifies(
            "台南市多處淹水災情嚴重，衛生局派員進行災後消毒作業"
        )
        is True
    )


def test_official_history_text_qualifies_accepts_incident_with_completed_repair() -> None:
    # "完工"/"通車" are soft-exclude phrases, but "封閉" is a genuine incident
    # marker describing the road closure that preceded the repair.
    assert (
        _official_history_text_qualifies(
            "因豪雨淹水封閉的中山路已搶修完工，今起恢復通車"
        )
        is True
    )


def test_official_history_text_qualifies_accepts_incident_with_pump_deployment() -> None:
    # "整備" is a soft-exclude phrase, but "多處" plus the flood term marks
    # this as a live incident report, not a preparedness notice.
    assert (
        _official_history_text_qualifies("嘉義縣多處淹水 縣府緊急整備抽水機馳援")
        is True
    )


def test_official_history_text_qualifies_rejects_sanitation_supply_press_release() -> None:
    # No incident marker present alongside the soft-exclude phrases, so this
    # generic preparedness press release must still be rejected.
    assert (
        _official_history_text_qualifies(
            "衛福部提醒：汛期水患將至，消毒劑儲備量充足因應"
        )
        is False
    )


def test_nationwide_official_citations_rejects_admin_area_match_found_only_in_body() -> None:
    # The title never names the district; only the RSS description does. A
    # bounded direct-page fetch is the only path that may confirm an
    # admin-area match, and here it fails to mention the district too, so
    # this must not be silently accepted from body text alone.
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>災情詳情</title>
      <description>高雄市仁武區近期發生嚴重積淹水，請留意。</description>
      <link>https://ktc.kcg.gov.tw/disaster/detail?id=999</link>
      <pubDate>Tue, 25 Aug 2026 05:48:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="高雄市仁武區",
        lat=22.701,
        lng=120.36,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
        fetch_citation_text=lambda _url, _timeout: (
            "本頁為全國性防汛宣導頁面，適用於所有縣市。"
        ),
    )

    assert result.records == ()


def test_nationwide_official_citations_rejects_page_listing_multiple_counties_in_body() -> None:
    # The direct-page body lists several counties, including the queried
    # district, but the page's own <title> is a generic nationwide roundup.
    # Body text is untrusted for admin-area verification: only the title/h1
    # may confirm the match, so this must still be rejected.
    payload = """<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel><item>
      <title>災情詳情</title>
      <link>https://ktc.kcg.gov.tw/disaster/detail?id=888</link>
      <pubDate>Tue, 25 Aug 2026 05:48:00 GMT</pubDate>
    </item></channel></rss>"""

    result = search_taiwan_official_flood_citations(
        location_text="高雄市仁武區",
        lat=22.701,
        lng=120.36,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        fetch_text=lambda _url, _timeout: payload,
        fetch_citation_text=lambda _url, _timeout: (
            "<html><head><title>全國積淹水災情彙整專區</title></head>"
            "<body><p>本頁彙整近期積淹水縣市，包括台北市、高雄市仁武區、"
            "南投縣、澎湖縣等地災情。</p></body></html>"
        ),
    )

    assert result.records == ()


def test_record_from_article_id_is_stable_across_different_query_counties() -> None:
    # SDD 9.3 fix: the same URL must resolve to the same evidence id
    # regardless of which county's query produced it, so the same
    # nationwide citation cannot be duplicated once per county.
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    article = {
        "title": "台北市南投縣豪雨淹水共同報導",
        "url": "https://www.cdc.gov.tw/News/generic-flood-notice",
        "published_at": now,
        "domain": "www.cdc.gov.tw",
    }

    record_taipei = _record_from_article(
        article,
        location="台北市",
        match_scope="admin_area",
        target_source_weight=0.74,
        lat=25.03,
        lng=121.56,
        radius_m=500,
        now=now,
        query_url="https://example.test/feed-taipei",
        search_window_label="test-window",
        adapter_key=TAIWAN_OFFICIAL_HISTORY_ADAPTER_KEY,
        source_prefix="official-gov-tw-citation",
        raw_ref_prefix="official-gov-tw-citation",
        source_type="official",
    )
    record_nantou = _record_from_article(
        article,
        location="南投縣",
        match_scope="admin_area",
        target_source_weight=0.74,
        lat=23.9,
        lng=120.68,
        radius_m=500,
        now=now,
        query_url="https://example.test/feed-nantou",
        search_window_label="test-window",
        adapter_key=TAIWAN_OFFICIAL_HISTORY_ADAPTER_KEY,
        source_prefix="official-gov-tw-citation",
        raw_ref_prefix="official-gov-tw-citation",
        source_type="official",
    )

    assert record_taipei is not None
    assert record_nantou is not None
    assert record_taipei.id == record_nantou.id
    assert record_taipei.source_id == record_nantou.source_id


def test_bing_rss_redirects_are_canonicalized_before_deduplication() -> None:
    direct_url = "https://news.example.test/flood/peian"
    encoded = quote(direct_url, safe="")
    payload = f"""<?xml version="1.0" encoding="utf-8" ?>
    <rss version="2.0"><channel>
      <item>
        <title>安南區培安路豪雨淹水</title>
        <link>https://www.bing.com/news/apiclick.aspx?url={encoded}&amp;tid=one</link>
        <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
      </item>
      <item>
        <title>安南區培安路豪雨淹水</title>
        <link>https://www.bing.com/news/apiclick.aspx?url={encoded}&amp;tid=two</link>
        <pubDate>Mon, 24 Aug 2026 04:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    result = search_public_flood_news(
        location_text="臺南市安南區培安路",
        lat=23.03882,
        lng=120.21349,
        radius_m=500,
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
        max_records=3,
        timeout_seconds=2.5,
        fetch_json=lambda _url, _timeout: {},
        fetch_text=lambda _url, _timeout: payload,
    )

    assert len(result.records) == 1
    assert result.records[0].url == direct_url


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
    requested_feed_urls: list[str] = []

    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {"articles": []}

    def fetch_text(url: str, _timeout_seconds: float) -> str:
        requested_feed_urls.append(url)
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

    assert any(urlparse(url).hostname == "www.bing.com" for url in requested_feed_urls)
    assert any("2024" in query for query in requested_queries)
    assert any("2023" in query for query in requested_queries)


def test_search_public_flood_news_uses_wiki_public_metadata_fallback() -> None:
    requested_wiki_queries: list[str] = []

    def fetch_json(_url: str, _timeout_seconds: float) -> dict[str, object]:
        return {"articles": []}

    def fetch_wiki_json(url: str, _timeout_seconds: float) -> dict[str, object]:
        params = parse_qs(urlparse(url).query)
        query = (params.get("q") or params.get("srsearch") or [""])[0]
        requested_wiki_queries.append(query)
        is_wikimedia_api = urlparse(url).hostname == "api.wikimedia.org"
        if "2023" not in query:
            return {"pages": []} if is_wikimedia_api else {"query": {"search": []}}
        if is_wikimedia_api:
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
    assert (
        record.url
        == "https://zh.wikipedia.org/wiki/2023%E5%B9%B49%E6%9C%88%E5%98%89%E7%BE%A9%E6%9A%B4%E9%9B%A8"
    )
    assert record.occurred_at == datetime(2023, 9, 1, tzinfo=timezone.utc)
    assert record.properties["ingestion_mode"] == "on_demand_public_wiki"
    assert record.properties["location_match_scope"] == "exact"
    assert record.properties["full_text_stored"] is False
