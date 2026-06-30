from __future__ import annotations

import json
import re
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIRED_READ_API_FIELDS = (
    "observed_at",
    "station_or_device_id",
    "measurement_value",
    "longitude_latitude_or_joinable_station_metadata",
)

CandidateSourceStatus = Literal[
    "promotion_ready",
    "status_only_ready",
    "blocked_fetch_error",
    "blocked_timeout",
    "needs_authorization_or_session",
    "needs_api_contract",
    "needs_measurement_value",
    "needs_observed_time_and_metadata",
    "needs_observed_time",
    "needs_metadata",
    "not_checked",
]


@dataclass(frozen=True)
class CandidateSourceDefinition:
    key: str
    county: str
    name: str
    url: str
    expected_signal_types: tuple[str, ...]
    existing_adapter_key: str | None = None
    metadata_url: str | None = None
    fallback_urls: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "county": self.county,
            "name": self.name,
            "url": self.url,
            "expected_signal_types": list(self.expected_signal_types),
            "existing_adapter_key": self.existing_adapter_key,
            "metadata_url": self.metadata_url,
            "fallback_urls": list(self.fallback_urls),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CandidateSourceFetchResult:
    url: str
    status_code: int | None
    content_type: str | None
    body: str | None = None
    payload: object | None = None
    error: str | None = None
    timeout_seconds: int | None = None
    attempted_urls: tuple[str, ...] = ()

    @classmethod
    def json_payload(cls, url: str, payload: object, *, status_code: int = 200) -> "CandidateSourceFetchResult":
        return cls(
            url=url,
            status_code=status_code,
            content_type="application/json",
            payload=payload,
            body=json.dumps(payload, ensure_ascii=False),
        )

    @classmethod
    def html(cls, url: str, body: str, *, status_code: int = 200) -> "CandidateSourceFetchResult":
        return cls(url=url, status_code=status_code, content_type="text/html", body=body)

    @classmethod
    def timeout(cls, url: str, *, timeout_seconds: int) -> "CandidateSourceFetchResult":
        return cls(
            url=url,
            status_code=None,
            content_type=None,
            error=f"timeout after {timeout_seconds}s",
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def http_error(
        cls,
        url: str,
        *,
        status_code: int,
        content_type: str | None,
        body: str | None = None,
    ) -> "CandidateSourceFetchResult":
        return cls(url=url, status_code=status_code, content_type=content_type, body=body)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "error": self.error,
            "timeout_seconds": self.timeout_seconds,
            "attempted_urls": list(self.attempted_urls),
        }


@dataclass(frozen=True)
class CandidateSourceQualification:
    key: str
    county: str
    name: str
    url: str
    status: CandidateSourceStatus
    next_action: str
    missing_required_fields: tuple[str, ...]
    observed_capabilities: tuple[str, ...]
    existing_adapter_key: str | None
    fetch: CandidateSourceFetchResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "county": self.county,
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "next_action": self.next_action,
            "missing_required_fields": list(self.missing_required_fields),
            "observed_capabilities": list(self.observed_capabilities),
            "existing_adapter_key": self.existing_adapter_key,
            "fetch": self.fetch.to_dict() if self.fetch else None,
        }


@dataclass(frozen=True)
class CandidateSourceSmokeResult:
    sources: tuple[CandidateSourceQualification, ...]

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for source in self.sources:
            counts[source.status] = counts.get(source.status, 0) + 1
        return {
            "source_count": len(self.sources),
            "status_counts": counts,
            "sources": [source.to_dict() for source in self.sources],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


CANDIDATE_SOURCE_DEFINITIONS: tuple[CandidateSourceDefinition, ...] = (
    CandidateSourceDefinition(
        key="taipei_evacuate_gate",
        county="臺北市",
        name="臺北市疏散門即時監測",
        url="https://wic.heo.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
        expected_signal_types=("gate_status",),
        fallback_urls=(
            "https://wic.gov.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
        ),
    ),
    CandidateSourceDefinition(
        key="taipei_flood_depth_simulation_metadata",
        county="臺北市",
        name="臺北市降雨積水模擬圖",
        url="https://data.taipei/dataset/detail?id=fa1e8012-ebb4-473b-888e-97f9a9ce365e",
        expected_signal_types=("flood_depth",),
        notes=("Flood-depth context only; 5-year simulation metadata is not a realtime sensor feed.",),
    ),
    CandidateSourceDefinition(
        key="new_taipei_pump_station_metadata",
        county="新北市",
        name="新北市各抽水站資訊",
        url="https://data.ntpc.gov.tw/datasets/3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296",
        expected_signal_types=("pump_status",),
        notes=("Annual static inventory; use for metadata only until an observed status API is found.",),
    ),
    CandidateSourceDefinition(
        key="new_taipei_water_gate_metadata",
        county="新北市",
        name="新北市水門資料",
        url="https://data.ntpc.gov.tw/datasets/bf784279-31aa-44bc-a210-33151d03e7ab",
        expected_signal_types=("gate_status",),
        notes=("Annual static inventory; use for metadata only until an observed status API is found.",),
    ),
    CandidateSourceDefinition(
        key="taoyuan_water_gate_metadata",
        county="桃園市",
        name="桃園市政府水務局管理水門資訊",
        url="https://opendata.tycg.gov.tw/api/dataset/1232b08a-121f-4505-ab39-14f40b12aa19/resource/8fe03219-d637-47d2-a771-0ce8635e55fa/download",
        expected_signal_types=("gate_status",),
        notes=("Static water-gate inventory; not a current gate-open/gate-closed observation.",),
    ),
    CandidateSourceDefinition(
        key="taoyuan_pump_inventory",
        county="桃園市",
        name="桃園市政府水務局抽水機",
        url="https://opendata.tycg.gov.tw/api/dataset/328dc013-6d8a-41be-bacf-706d6c61a9de/resource/260e3099-8e5f-47e0-ace6-f7653d9ea0de/download",
        expected_signal_types=("pump_status",),
        notes=("Annual static pump inventory; not a pump runtime/status observation.",),
    ),
    CandidateSourceDefinition(
        key="taichung_pump_station_metadata",
        county="臺中市",
        name="臺中市各抽水站資訊",
        url="https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=87e89521-27f4-4beb-8aea-fa07be55e609",
        expected_signal_types=("pump_status",),
        notes=("Static/open-data metadata; not a realtime pump status feed.",),
    ),
    CandidateSourceDefinition(
        key="taichung_gate_metadata",
        county="臺中市",
        name="臺中市市管水門",
        url="https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=7c597e67-ae3d-419f-bf93-d27fd5238d82",
        expected_signal_types=("gate_status",),
        notes=("Static/open-data metadata; not a realtime gate status feed.",),
    ),
    CandidateSourceDefinition(
        key="miaoli_sewer_monitoring",
        county="苗栗縣",
        name="苗栗縣雨水下水道即時水情監測",
        url="https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx?n=563&s=922337&sms=9560",
        expected_signal_types=("sewer_water_level",),
    ),
    CandidateSourceDefinition(
        key="yunlin_flood_sensor_depth",
        county="雲林縣",
        name="雲林 iflood 淹水感測深度",
        url="https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5",
        expected_signal_types=("flood_depth",),
        existing_adapter_key="local.yunlin.water_level",
    ),
    CandidateSourceDefinition(
        key="chiayi_county_management_api",
        county="嘉義縣",
        name="嘉義縣智慧防汛管理型 API",
        url="https://www.cyhg.gov.tw/News_Content.aspx?n=16&s=249470",
        expected_signal_types=("flood_depth", "pump_status"),
        existing_adapter_key="local.chiayi_county.flood_sensor",
    ),
    CandidateSourceDefinition(
        key="kaohsiung_rainfall",
        county="高雄市",
        name="高雄智慧水利雨量候選",
        url="https://wrbswi.kcg.gov.tw/SFC/api/rain/rt",
        expected_signal_types=("rainfall",),
        existing_adapter_key="local.kaohsiung.rainfall",
        metadata_url="https://wrbswi.kcg.gov.tw/SFC/api/rain/base",
    ),
    CandidateSourceDefinition(
        key="tainan_pump_station_metadata",
        county="臺南市",
        name="臺南市抽水站基本資料",
        url="https://soa.tainan.gov.tw/Api/Service/Get/d9311994-b4c3-4952-8493-b7e49d17fbd3",
        expected_signal_types=("pump_status",),
        notes=("Static station metadata; do not treat as pump operation/status evidence.",),
    ),
    CandidateSourceDefinition(
        key="tainan_water_gate_metadata",
        county="臺南市",
        name="臺南市水門基本資料",
        url="https://soa.tainan.gov.tw/Api/Service/Get/3be620b5-4381-4195-bc2f-2eff62a46291",
        expected_signal_types=("gate_status",),
        notes=("Static gate metadata; do not treat as gate operation/status evidence.",),
    ),
    CandidateSourceDefinition(
        key="pingtung_pteoc_rain_station",
        county="屏東縣",
        name="屏東防災資訊整合平台雨量站",
        url="https://pteoc.pthg.gov.tw/RainStation",
        expected_signal_types=("rainfall",),
        existing_adapter_key="local.pingtung.flood_sensor",
    ),
    CandidateSourceDefinition(
        key="taitung_flood_warning",
        county="臺東縣",
        name="臺東洪水與淹水預警系統",
        url="https://www.taitung.gov.tw/News_Content.aspx?n=13370&s=131527&sms=12652",
        expected_signal_types=("flood_warning", "flood_depth"),
        existing_adapter_key="local.taitung.flood_sensor",
    ),
    CandidateSourceDefinition(
        key="penghu_drainage_metadata",
        county="澎湖縣",
        name="澎湖縣區域排水疏濬工程",
        url="https://data.gov.tw/dataset/156926",
        expected_signal_types=("flood_depth", "pump_status"),
        notes=("Static drainage-work context; not a flood-depth or pump/gate observation.",),
    ),
    CandidateSourceDefinition(
        key="hualien_senslink_login",
        county="花蓮縣",
        name="花蓮行動水情登入型儀表板",
        url="https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index",
        expected_signal_types=("flood_depth", "pump_status"),
        existing_adapter_key="local.hualien.flood_sensor",
        notes=("Login-gated dashboard; requires official authorization before API contract review.",),
    ),
    CandidateSourceDefinition(
        key="kinmen_kwis_token_gated_api",
        county="金門縣",
        name="金門水情系統 KWIS SOAP/ASMX",
        url="https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx?WSDL",
        expected_signal_types=("flood_depth", "water_level", "pump_status"),
        notes=("WSDL is visible, but read methods require a county-issued token.",),
    ),
    CandidateSourceDefinition(
        key="lienchiang_flood_prone_metadata",
        county="連江縣",
        name="連江縣大潮、豪雨易淹水地區",
        url="https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5",
        expected_signal_types=("flood_depth",),
        notes=("Static flood-prone-area metadata; not a realtime flood-depth feed.",),
    ),
    CandidateSourceDefinition(
        key="lienchiang_erbwater_non_qualifying",
        county="連江縣",
        name="連江縣資訊公開查詢系統即時監測值",
        url="http://erbwater.matsu.gov.tw/PUBLIC/RealTime/Get_AVGR.aspx",
        expected_signal_types=("water_quality",),
        notes=("Environmental discharge/CEMS context; not a flood-risk water sensor.",),
    ),
)
CANDIDATE_SOURCE_KEYS = tuple(definition.key for definition in CANDIDATE_SOURCE_DEFINITIONS)


def qualify_static_candidate_sources(
    *,
    fetch_results: Mapping[str, CandidateSourceFetchResult] | None = None,
    definitions: Sequence[CandidateSourceDefinition] = CANDIDATE_SOURCE_DEFINITIONS,
) -> CandidateSourceSmokeResult:
    results = fetch_results or {}
    return CandidateSourceSmokeResult(
        sources=tuple(
            qualify_candidate_source_fetch(definition, results.get(definition.key))
            for definition in definitions
        )
    )


def fetch_candidate_source(
    definition: CandidateSourceDefinition,
    *,
    timeout_seconds: int = 20,
    verify_tls: bool = True,
) -> CandidateSourceFetchResult:
    attempted_urls: list[str] = []
    last_fetch: CandidateSourceFetchResult | None = None
    for url in (definition.url, *definition.fallback_urls):
        attempted_urls.append(url)
        fetch = _fetch_candidate_url(
            url,
            timeout_seconds=timeout_seconds,
            verify_tls=verify_tls,
        )
        last_fetch = fetch
        if not _should_try_fallback(fetch):
            return replace(fetch, attempted_urls=tuple(attempted_urls))
    if last_fetch is None:
        return CandidateSourceFetchResult.timeout(
            definition.url, timeout_seconds=max(1, timeout_seconds)
        )
    return replace(last_fetch, attempted_urls=tuple(attempted_urls))


def _fetch_candidate_url(
    url: str,
    *,
    timeout_seconds: int,
    verify_tls: bool,
) -> CandidateSourceFetchResult:
    request = Request(
        url,
        headers={"Accept": "*/*", "User-Agent": "FloodRiskTaiwan/0.1 local-source-candidate-smoke"},
    )
    context = None if verify_tls else ssl._create_unverified_context()
    try:
        with urlopen(request, timeout=max(1, timeout_seconds), context=context) as response:
            body_bytes = response.read()
            body = body_bytes.decode("utf-8-sig", errors="replace")
            content_type = response.headers.get("content-type")
            payload = _json_payload(body, content_type)
            return CandidateSourceFetchResult(
                url=response.geturl(),
                status_code=response.status,
                content_type=content_type,
                body=body,
                payload=payload,
            )
    except TimeoutError:
        return CandidateSourceFetchResult.timeout(
            url, timeout_seconds=max(1, timeout_seconds)
        )
    except HTTPError as exc:
        body = exc.read().decode("utf-8-sig", errors="replace") if exc.fp else None
        return CandidateSourceFetchResult.http_error(
            url,
            status_code=exc.code,
            content_type=exc.headers.get("content-type"),
            body=body,
        )
    except URLError as exc:
        reason = str(exc.reason)
        if "timed out" in reason.lower():
            return CandidateSourceFetchResult.timeout(
                url, timeout_seconds=max(1, timeout_seconds)
            )
        return CandidateSourceFetchResult(
            url=url,
            status_code=None,
            content_type=None,
            error=reason,
        )


def _should_try_fallback(fetch: CandidateSourceFetchResult) -> bool:
    if fetch.error and "timeout" in fetch.error.lower():
        return True
    return fetch.status_code is None and fetch.error is not None


def qualify_candidate_source_fetch(
    definition: CandidateSourceDefinition,
    fetch: CandidateSourceFetchResult | None,
) -> CandidateSourceQualification:
    if fetch is None:
        return _qualification(
            definition,
            fetch,
            status="not_checked",
            next_action="run_live_smoke",
            missing_required_fields=REQUIRED_READ_API_FIELDS,
            observed_capabilities=(),
        )
    if fetch.error and "timeout" in fetch.error.lower():
        return _qualification(
            definition,
            fetch,
            status="blocked_timeout",
            next_action="retry_live_smoke",
            missing_required_fields=REQUIRED_READ_API_FIELDS,
            observed_capabilities=(),
        )
    if fetch.error or fetch.status_code is None:
        return _qualification(
            definition,
            fetch,
            status="blocked_fetch_error",
            next_action="retry_live_smoke_or_manual_review",
            missing_required_fields=REQUIRED_READ_API_FIELDS,
            observed_capabilities=(),
        )
    if _looks_like_authorization_or_session_block(fetch):
        return _qualification(
            definition,
            fetch,
            status="needs_authorization_or_session",
            next_action="request_official_read_api_access",
            missing_required_fields=REQUIRED_READ_API_FIELDS,
            observed_capabilities=(),
        )

    capabilities = _observed_capabilities(definition, fetch)
    missing = tuple(field for field in REQUIRED_READ_API_FIELDS if field not in capabilities)
    if not missing:
        return _qualification(
            definition,
            fetch,
            status="promotion_ready",
            next_action=(
                "operate_existing_adapter"
                if definition.existing_adapter_key
                else "start_adapter_tdd"
            ),
            missing_required_fields=(),
            observed_capabilities=tuple(sorted(capabilities)),
        )

    if missing == ("measurement_value",) and "status_only" in capabilities:
        return _qualification(
            definition,
            fetch,
            status="status_only_ready",
            next_action="present_as_status_only_and_find_depth_contract",
            missing_required_fields=missing,
            observed_capabilities=tuple(sorted(capabilities)),
        )
    if missing == ("measurement_value",):
        return _qualification(
            definition,
            fetch,
            status="needs_measurement_value",
            next_action="find_depth_api_or_official_field_contract",
            missing_required_fields=missing,
            observed_capabilities=tuple(sorted(capabilities)),
        )
    if missing == (
        "observed_at",
        "longitude_latitude_or_joinable_station_metadata",
    ):
        return _qualification(
            definition,
            fetch,
            status="needs_observed_time_and_metadata",
            next_action="find_machine_readable_api_or_metadata_join",
            missing_required_fields=missing,
            observed_capabilities=tuple(sorted(capabilities)),
        )
    if "observed_at" in missing:
        return _qualification(
            definition,
            fetch,
            status="needs_observed_time",
            next_action="find_observed_time_field_or_contract",
            missing_required_fields=missing,
            observed_capabilities=tuple(sorted(capabilities)),
        )
    if "longitude_latitude_or_joinable_station_metadata" in missing:
        return _qualification(
            definition,
            fetch,
            status="needs_metadata",
            next_action="find_station_metadata_join",
            missing_required_fields=missing,
            observed_capabilities=tuple(sorted(capabilities)),
        )
    return _qualification(
        definition,
        fetch,
        status="needs_api_contract",
        next_action="find_public_read_api_contract",
        missing_required_fields=missing,
        observed_capabilities=tuple(sorted(capabilities)),
    )


def _qualification(
    definition: CandidateSourceDefinition,
    fetch: CandidateSourceFetchResult | None,
    *,
    status: CandidateSourceStatus,
    next_action: str,
    missing_required_fields: tuple[str, ...],
    observed_capabilities: tuple[str, ...],
) -> CandidateSourceQualification:
    return CandidateSourceQualification(
        key=definition.key,
        county=definition.county,
        name=definition.name,
        url=definition.url,
        status=status,
        next_action=next_action,
        missing_required_fields=missing_required_fields,
        observed_capabilities=observed_capabilities,
        existing_adapter_key=definition.existing_adapter_key,
        fetch=fetch,
    )


def _observed_capabilities(
    definition: CandidateSourceDefinition,
    fetch: CandidateSourceFetchResult,
) -> set[str]:
    values = tuple(_walk_values(fetch.payload if fetch.payload is not None else fetch.body))
    keys = {key.lower() for key, _value in values}
    text_values = tuple(str(value) for _key, value in values if value is not None)
    body = fetch.body or ""
    capabilities: set[str] = set()
    if _has_any_key(
        keys,
        ("time", "date", "latestupdatetime", "rectime", "observed_at", "timestamp"),
    ):
        capabilities.add("observed_at")
    if _has_station_or_device_id(keys) or any(token in body for token in ("站名", "地點")):
        capabilities.add("station_or_device_id")
    if _has_coordinates(keys):
        capabilities.add("longitude_latitude_or_joinable_station_metadata")
    if definition.metadata_url and (
        "station_or_device_id" in capabilities or _has_station_or_device_id(keys)
    ):
        capabilities.add("longitude_latitude_or_joinable_station_metadata")
    if _has_joinable_station_metadata(keys, body):
        capabilities.add("longitude_latitude_or_joinable_station_metadata")
    if _has_measurement_value(definition, keys, text_values, body):
        capabilities.add("measurement_value")
    if (
        _has_status_only_value(keys)
        or ("gate_status" in definition.expected_signal_types and _has_gate_status_value(keys))
    ) and {
        "observed_at",
        "station_or_device_id",
        "longitude_latitude_or_joinable_station_metadata",
    }.issubset(capabilities):
        capabilities.add("status_only")
    return capabilities


def _looks_like_authorization_or_session_block(fetch: CandidateSourceFetchResult) -> bool:
    if fetch.status_code in {401, 403}:
        return True
    if fetch.status_code in {301, 302, 303, 307, 308}:
        return True
    body = (fetch.body or "").lower()
    form_texts = _extract_html_form_texts(body)
    return any(_form_looks_like_authorization(form_text) for form_text in form_texts)


def _form_looks_like_authorization(form_text: str) -> bool:
    if "captcha" in form_text or "驗證碼" in form_text:
        return True
    if "type password" in form_text or 'type="password"' in form_text:
        return True
    return any(token in form_text for token in ("login", "登入", "sign in"))


class _FormTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[str] = []
        self._current_form_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "form":
            self._current_form_parts = [self._attrs_text(attrs)]
            return
        if self._current_form_parts is not None:
            self._current_form_parts.append(tag)
            self._current_form_parts.append(self._attrs_text(attrs))

    def handle_data(self, data: str) -> None:
        if self._current_form_parts is not None:
            self._current_form_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._current_form_parts is not None:
            self.forms.append(" ".join(self._current_form_parts).lower())
            self._current_form_parts = None

    @staticmethod
    def _attrs_text(attrs: list[tuple[str, str | None]]) -> str:
        return " ".join(f"{name} {value or ''}" for name, value in attrs)


def _extract_html_form_texts(body: str) -> tuple[str, ...]:
    parser = _FormTextParser()
    try:
        parser.feed(body)
    except Exception:
        return ()
    return tuple(parser.forms)


def _json_payload(body: str, content_type: str | None) -> object | None:
    if "json" not in (content_type or "").lower() and not body.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _walk_values(value: object, parent_key: str | None = None) -> tuple[tuple[str, object], ...]:
    values: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            text_key = str(key)
            values.append((text_key, child))
            values.extend(_walk_values(child, text_key))
    elif isinstance(value, list | tuple):
        for child in value:
            values.extend(_walk_values(child, parent_key))
    elif parent_key is not None:
        values.append((parent_key, value))
    return tuple(values)


def _has_any_key(keys: set[str], wanted: tuple[str, ...]) -> bool:
    return any(key in keys for key in wanted)


def _has_station_or_device_id(keys: set[str]) -> bool:
    return bool(
        keys.intersection(
            {
                "_id",
                "id",
                "stationid",
                "station_id",
                "stationno",
                "st_no",
                "dev_uuid",
                "sensorid",
            }
        )
    )


def _has_coordinates(keys: set[str]) -> bool:
    has_lng = bool(keys.intersection({"lon", "lng", "longitude", "x"}))
    has_lat = bool(keys.intersection({"lat", "latitude", "y"}))
    return has_lng and has_lat


def _has_joinable_station_metadata(keys: set[str], body: str) -> bool:
    if _has_station_or_device_id(keys) and any(token in body for token in ("座標", "經度", "緯度")):
        return True
    return bool(re.search(r"\b(station|sensor|device)[ _-]?(name|no|id)\b", body, re.I))


def _has_measurement_value(
    definition: CandidateSourceDefinition,
    keys: set[str],
    text_values: tuple[str, ...],
    body: str,
) -> bool:
    if "flood_depth" in definition.expected_signal_types:
        return bool(
            keys.intersection(
                {
                    "waterdepth",
                    "flooddepth",
                    "flood_depth_cm",
                    "depth",
                    "water_inner",
                    "obs_value",
                }
            )
        )
    if "rainfall" in definition.expected_signal_types:
        return bool(
            keys.intersection(
                {
                    "rain",
                    "rainfall",
                    "rainfall_mm",
                    "rainfall_mm_10m",
                    "rainfall_mm_1h",
                    "h1",
                    "m10",
                }
            )
        ) or any("雨量" in value for value in text_values) or "雨量" in body
    if any(signal in definition.expected_signal_types for signal in ("water_level", "sewer_water_level")):
        return bool(
            keys.intersection(
                {
                    "waterlevel",
                    "water_level_m",
                    "levelheight",
                    "waterdepth",
                    "stage",
                    "water_inner",
                }
            )
        )
    return False


def _has_status_only_value(keys: set[str]) -> bool:
    return bool(
        keys.intersection(
            {
                "alarmstate",
                "status",
                "state",
                "warningstate",
                "device_status",
                "sensor_status",
            }
        )
    )


def _has_gate_status_value(keys: set[str]) -> bool:
    return bool(keys.intersection({"fo", "fc", "flt", "gate_status"}))
