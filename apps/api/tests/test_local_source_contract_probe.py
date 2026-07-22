from __future__ import annotations

from app.ops.local_source.local_source_action_plan import build_local_source_action_plan
from app.ops.local_source.local_source_contract_probe import (
    ProbeHttpResponse,
    build_public_api_contract_probe,
    classify_contract_probe_response,
)
from app.ops.local_source.local_source_coverage import list_local_source_coverage


def test_classifies_machine_readable_response_with_required_fields_as_live_candidate() -> None:
    response = ProbeHttpResponse(
        url="https://example.test/water/realtime.json",
        status_code=200,
        content_type="application/json",
        text=(
            '{"station_id":"P001","observed_at":"2026-06-30T18:00:00+08:00",'
            '"measurement_value":12.3,"measurement_unit":"cm",'
            '"longitude":120.5,"latitude":22.6,'
            '"license":"Open Government Data License"}'
        ),
        error=None,
    )

    result = classify_contract_probe_response(response)

    assert result["readiness"] == "candidate_live_read_api"
    assert result["missing_required_fields"] == []
    assert "observed_at" in result["detected_required_fields"]
    assert "longitude_latitude_or_joinable_station_metadata" in result[
        "detected_required_fields"
    ]


def test_keeps_public_html_table_as_contract_blocker_when_timestamp_and_metadata_missing() -> None:
    response = ProbeHttpResponse(
        url="https://pteoc.pthg.gov.tw/RainStation/Details/C0R190",
        status_code=200,
        content_type="text/html; charset=utf-8",
        text="""
        <table>
          <tr><th>10分鐘雨量</th><td>0</td></tr>
          <tr><th>1小時雨量</th><td>0</td></tr>
          <tr><th>24小時雨量</th><td>0</td></tr>
        </table>
        """,
        error=None,
    )

    result = classify_contract_probe_response(response)

    assert result["readiness"] == "public_html_missing_read_api_contract"
    assert "measurement_value" in result["detected_required_fields"]
    assert "measurement_unit_or_type" in result["detected_required_fields"]
    assert result["missing_required_fields"] == [
        "observed_at",
        "station_or_device_id",
        "longitude_latitude_or_joinable_station_metadata",
        "official_source_url_and_license",
    ]


def test_marks_cctv_or_warning_only_pages_as_non_measurement_context() -> None:
    response = ProbeHttpResponse(
        url="https://pteoc.pthg.gov.tw/Crawler/Details/1",
        status_code=200,
        content_type="text/html",
        text='<img src="/camera/latest.jpg" alt="CCTV 即時影像">',
        error=None,
    )

    result = classify_contract_probe_response(response)

    assert result["readiness"] == "non_measurement_context"
    assert "image_only_cctv" in result["non_measurement_notes"]


def test_navigation_image_word_does_not_make_rain_station_page_non_measurement() -> None:
    response = ProbeHttpResponse(
        url="https://pteoc.pthg.gov.tw/RainStation",
        status_code=200,
        content_type="text/html",
        text="""
        <nav>即時影像</nav>
        <table><tr><th>雨量(mm)</th><td>0</td></tr></table>
        """,
        error=None,
    )

    result = classify_contract_probe_response(response)

    assert result["readiness"] == "public_html_missing_read_api_contract"
    assert "image_only_cctv" not in result["non_measurement_notes"]


def test_html_article_with_generic_hydrology_words_does_not_satisfy_contract_fields() -> None:
    response = ProbeHttpResponse(
        url="https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx",
        status_code=200,
        content_type="text/html",
        text="""
        <html><body>
          <img src="/logo.png" alt="縣府標誌">
          成果頁說明雨水下水道即時水情監測系統建置計畫，
          設置水位監測站並每月維護，但沒有資料時間、站號或 API response。
        </body></html>
        """,
        error=None,
    )

    result = classify_contract_probe_response(response)

    assert result["readiness"] == "public_html_missing_read_api_contract"
    assert "image_only_cctv" not in result["non_measurement_notes"]
    assert "observed_at" in result["missing_required_fields"]
    assert "station_or_device_id" in result["missing_required_fields"]
    assert "longitude_latitude_or_joinable_station_metadata" in result[
        "missing_required_fields"
    ]


def test_probe_plan_tracks_current_public_api_contract_review_count() -> None:
    plan = build_local_source_action_plan(list_local_source_coverage())

    def fake_fetch(url: str, timeout_seconds: float) -> ProbeHttpResponse:
        assert timeout_seconds == 3.0
        return ProbeHttpResponse(
            url=url,
            status_code=200,
            content_type="text/html",
            text="<html><body>成果頁，含雨量與水位文字，但未提供觀測時間或座標。</body></html>",
            error=None,
        )

    artifact = build_public_api_contract_probe(
        plan,
        captured_at="2026-06-30T18:40:00+08:00",
        timeout_seconds=3.0,
        fetcher=fake_fetch,
    )

    assert artifact["schema_version"] == "public-api-contract-probe/v1"
    assert artifact["captured_at"] == "2026-06-30T18:40:00+08:00"
    assert artifact["summary"]["public_api_contract_review_count"] == 3
    assert artifact["summary"]["candidate_live_read_api_count"] == 0
    assert artifact["conclusion"] == "no_candidate_live_read_api_found"
    assert {county["county"] for county in artifact["counties"]} == {
        "苗栗縣",
        "屏東縣",
        "臺東縣",
    }
