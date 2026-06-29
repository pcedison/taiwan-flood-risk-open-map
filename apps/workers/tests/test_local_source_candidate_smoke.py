from __future__ import annotations

from urllib.request import Request

from app.ops.local_source_candidate_smoke import (
    CANDIDATE_SOURCE_KEYS,
    CANDIDATE_SOURCE_DEFINITIONS,
    CandidateSourceDefinition,
    CandidateSourceFetchResult,
    CandidateSourceQualification,
    fetch_candidate_source,
    qualify_candidate_source_fetch,
    qualify_static_candidate_sources,
)


class FakeResponse:
    def __init__(self, *, url: str, body: str, content_type: str = "application/json") -> None:
        self._url = url
        self._body = body.encode("utf-8")
        self.headers = {"content-type": content_type}
        self.status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def test_static_candidate_source_catalog_tracks_priority_counties() -> None:
    result = qualify_static_candidate_sources(
        fetch_results={
            "taipei_evacuate_gate": CandidateSourceFetchResult.timeout(
                "https://example.test/taipei/evacuate",
                timeout_seconds=60,
            ),
        }
    )

    by_key = {item.key: item for item in result.sources}

    assert set(CANDIDATE_SOURCE_KEYS).issuperset(
        {
            "taipei_evacuate_gate",
            "miaoli_sewer_monitoring",
            "yunlin_flood_sensor_depth",
            "chiayi_county_management_api",
            "kaohsiung_rainfall",
            "pingtung_pteoc_rain_station",
            "taitung_flood_warning",
        }
    )
    assert by_key["taipei_evacuate_gate"].status == "blocked_timeout"
    assert by_key["taipei_evacuate_gate"].next_action == "retry_live_smoke"


def test_taipei_evacuate_gate_retries_public_mirror_and_stays_gate_status(
    monkeypatch,
) -> None:
    definition = next(
        item for item in CANDIDATE_SOURCE_DEFINITIONS if item.key == "taipei_evacuate_gate"
    )
    attempted_urls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: int):
        url = request.full_url
        attempted_urls.append(url)
        if "wic.heo.taipei" in url:
            raise TimeoutError("timed out")
        return FakeResponse(
            url=url,
            body=(
                '[{"stationNo":"A001","recTime":"202606291030",'
                '"name":"測試疏散門","fo":"0","fc":"1","flt":"0",'
                '"lng":121.5,"lat":25.0}]'
            ),
        )

    monkeypatch.setattr(
        "app.ops.local_source_candidate_smoke.urlopen",
        fake_urlopen,
    )

    fetch = fetch_candidate_source(definition, timeout_seconds=3)
    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert attempted_urls == [
        "https://wic.heo.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
        "https://wic.gov.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
    ]
    assert fetch.url.startswith("https://wic.gov.taipei/")
    assert fetch.attempted_urls == tuple(attempted_urls)
    assert definition.expected_signal_types == ("gate_status",)
    assert "water_level" not in definition.expected_signal_types
    assert "flood_depth" not in definition.expected_signal_types
    assert "status_only" in qualification.observed_capabilities
    assert qualification.status == "promotion_ready"


def test_json_source_with_observed_time_coordinates_and_measurement_is_promotion_ready() -> None:
    definition = CandidateSourceDefinition(
        key="chiayi_county_rfd_public",
        county="嘉義縣",
        name="嘉義縣智慧防汛公開 RFD API",
        url="https://api.floodsolution.aiot.ing/api/public/devices/RFD",
        expected_signal_types=("flood_depth",),
        existing_adapter_key="local.chiayi_county.flood_sensor",
    )
    fetch = CandidateSourceFetchResult.json_payload(
        definition.url,
        {
            "data": [
                {
                    "_id": "rfd-1",
                    "name": "測試路面淹水感測器",
                    "lon": 120.3,
                    "lat": 23.4,
                    "latest": {
                        "time": "2026-06-29T00:35:00+08:00",
                        "data": {"waterDepth": 12.5},
                    },
                }
            ]
        },
    )

    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status == "promotion_ready"
    assert qualification.missing_required_fields == ()
    assert qualification.next_action == "operate_existing_adapter"


def test_yunlin_flood_sensor_alarm_state_without_depth_stays_needs_measurement_value() -> None:
    definition = CandidateSourceDefinition(
        key="yunlin_flood_sensor_depth",
        county="雲林縣",
        name="雲林 iflood 淹水感測深度",
        url="https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5",
        expected_signal_types=("flood_depth",),
    )
    fetch = CandidateSourceFetchResult.json_payload(
        definition.url,
        {
            "result": {
                "items": [
                    {
                        "id": "flood-1",
                        "stationType": "淹水感測",
                        "displayName": "淹水感測_口湖鄉_港西村",
                        "latestUpdateTime": "2026-06-29T00:36:01.338+08:00",
                        "longitude": 120.147835,
                        "latitude": 23.575771,
                        "alarmState": "正常",
                    }
                ]
            }
        },
    )

    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status == "status_only_ready"
    assert qualification.missing_required_fields == ("measurement_value",)
    assert qualification.next_action == "present_as_status_only_and_find_depth_contract"
    assert "status_only" in qualification.observed_capabilities


def test_candidate_with_station_id_and_known_metadata_url_is_joinable() -> None:
    definition = CandidateSourceDefinition(
        key="kaohsiung_rainfall",
        county="高雄市",
        name="高雄智慧水利雨量",
        url="https://wrbswi.kcg.gov.tw/SFC/api/rain/rt",
        expected_signal_types=("rainfall",),
        existing_adapter_key="local.kaohsiung.rainfall",
        metadata_url="https://wrbswi.kcg.gov.tw/SFC/api/rain/base",
    )
    fetch = CandidateSourceFetchResult.json_payload(
        definition.url,
        [
            {
                "DATE": "2026-06-29T00:40:00",
                "H1": 2.5,
                "M10": 0.5,
                "ST_NO": "KHRF001",
            }
        ],
    )

    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status == "promotion_ready"
    assert qualification.next_action == "operate_existing_adapter"
    assert qualification.missing_required_fields == ()


def test_pingtung_html_table_without_observed_time_or_coordinates_stays_needs_review() -> None:
    definition = CandidateSourceDefinition(
        key="pingtung_pteoc_rain_station",
        county="屏東縣",
        name="屏東防災資訊整合平台雨量站",
        url="https://pteoc.pthg.gov.tw/RainStation",
        expected_signal_types=("rainfall",),
    )
    fetch = CandidateSourceFetchResult.html(
        definition.url,
        "<table><tr><th>站名</th><th>10分鐘雨量</th></tr>"
        "<tr><td>屏東</td><td>0</td></tr></table>",
    )

    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status == "needs_observed_time_and_metadata"
    assert qualification.missing_required_fields == (
        "observed_at",
        "longitude_latitude_or_joinable_station_metadata",
    )
    assert qualification.next_action == "find_machine_readable_api_or_metadata_join"


def test_timeout_and_login_responses_are_not_promotion_ready() -> None:
    definition = CandidateSourceDefinition(
        key="taipei_evacuate_gate",
        county="臺北市",
        name="臺北市疏散門即時監測",
        url="https://wic.heo.taipei/OpenData/API/Evacuate/Get",
        expected_signal_types=("gate_status",),
    )

    timeout = qualify_candidate_source_fetch(
        definition,
        CandidateSourceFetchResult.timeout(definition.url, timeout_seconds=60),
    )
    login = qualify_candidate_source_fetch(
        definition,
        CandidateSourceFetchResult.http_error(
            definition.url,
            status_code=302,
            content_type="text/html",
            body="login",
        ),
    )

    assert timeout.status == "blocked_timeout"
    assert timeout.next_action == "retry_live_smoke"
    assert login.status == "needs_authorization_or_session"
    assert login.next_action == "request_official_read_api_access"
    assert isinstance(timeout, CandidateSourceQualification)


def test_public_html_with_login_word_but_no_login_form_is_not_authorization_block() -> None:
    definition = CandidateSourceDefinition(
        key="pingtung_pteoc_rain_station",
        county="屏東縣",
        name="屏東防災資訊整合平台雨量站",
        url="https://pteoc.pthg.gov.tw/RainStation",
        expected_signal_types=("rainfall",),
    )
    fetch = CandidateSourceFetchResult.html(
        definition.url,
        "<html><body>防救災人員入口 login captcha 雨量站資訊"
        "<table><tr><th>站名</th><th>10分鐘雨量</th></tr></table></body></html>",
    )

    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status != "needs_authorization_or_session"
    assert qualification.next_action != "request_official_read_api_access"


def test_public_html_with_login_link_and_non_login_filter_form_is_not_authorization_block() -> None:
    definition = CandidateSourceDefinition(
        key="pingtung_pteoc_rain_station",
        county="屏東縣",
        name="屏東防災資訊整合平台雨量站",
        url="https://pteoc.pthg.gov.tw/RainStation",
        expected_signal_types=("rainfall",),
    )
    fetch = CandidateSourceFetchResult.html(
        definition.url,
        "<html><body>"
        "<nav><a href='/Admin/Account/Login'>防救災人員入口</a></nav>"
        "<main>"
        "<form action='/RainStation' method='post'>"
        "<select name='other'><option>1小時雨量</option></select>"
        "<button type='submit'>搜尋</button>"
        "</form>"
        "<table><tr><th>雨量站</th><th>雨量(mm)</th></tr></table>"
        "</main>"
        "</body></html>",
    )

    qualification = qualify_candidate_source_fetch(definition, fetch)

    assert qualification.status != "needs_authorization_or_session"
    assert qualification.next_action != "request_official_read_api_access"
