from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TARGET_COUNTIES = ("金門縣", "連江縣")
DATA_GOV_DATASET_EXPORT_URL = "https://data.gov.tw/api/front/dataset/export?format=json"
DISCOVERY_USER_AGENT = "FloodRiskTaiwan/0.1 local-source-discovery-monitor"

CandidateReadiness = Literal["candidate_live_read_api", "metadata_only"]

LIVE_KEYWORDS = ("即時", "監測", "水情", "觀測", "API", "水位", "雨水下水道")
WATER_KEYWORDS = ("水情", "水位", "淹水", "雨水下水道", "抽水", "水門", "閘門", "豪雨")
METADATA_KEYWORDS = ("易淹水", "清冊", "地區", "圖資", "位置")
NON_WATER_KEYWORDS = ("觀光", "旅遊", "景點", "停車", "餐飲", "枯旱", "補助款")


NON_SENSOR_INFRASTRUCTURE_KEYWORDS = (
    "\u6297\u65f1",
    "\u6c34\u4e95",
    "\u53c3\u8a2a",
    "\u806f\u7d61\u4eba",
    "\u96fb\u8a71",
    "\u7ba1\u7dda\u9577\u5ea6",
    "\u6c61\u6c34\u8655\u7406\u8a2d\u65bd",
)


@dataclass(frozen=True)
class DataGovDataset:
    title: str
    description: str | None = None
    identifier: str | None = None
    url: str | None = None
    field_description: str | None = None
    update_frequency: str | None = None
    data_provision_type: str | None = None
    resource_formats: tuple[str, ...] = ()
    resource_urls: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "DataGovDataset":
        distributions = _distributions(item)
        return cls(
            title=_first_text(item, "title", "資料集名稱", "name") or "",
            description=_first_text(item, "description", "資料集描述", "notes"),
            identifier=_first_text(item, "identifier", "資料集識別碼", "dataset_id", "id"),
            url=_first_text(item, "url", "資料集網址", "landingPage"),
            field_description=_first_text(
                item,
                "fieldDescription",
                "field_description",
                "\u4e3b\u8981\u6b04\u4f4d\u8aaa\u660e",
            ),
            update_frequency=_first_text(
                item,
                "accrualPeriodicity",
                "update_frequency",
                "\u66f4\u65b0\u983b\u7387",
            ),
            data_provision_type=_first_text(
                item,
                "data_provision_type",
                "\u8cc7\u6599\u63d0\u4f9b\u5c6c\u6027",
            ),
            resource_formats=_resource_formats(item, distributions),
            resource_urls=_resource_urls(item, distributions),
        )


@dataclass(frozen=True)
class LocalSourceCandidate:
    county: str
    title: str
    dataset_id: str | None
    dataset_url: str | None
    readiness: CandidateReadiness
    signal_types: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    resource_formats: tuple[str, ...]
    resource_urls: tuple[str, ...]
    field_description: str | None = None
    update_frequency: str | None = None
    data_provision_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "county": self.county,
            "title": self.title,
            "dataset_id": self.dataset_id,
            "dataset_url": self.dataset_url,
            "readiness": self.readiness,
            "signal_types": list(self.signal_types),
            "matched_keywords": list(self.matched_keywords),
            "resource_formats": list(self.resource_formats),
            "resource_urls": list(self.resource_urls),
            "field_description": self.field_description,
            "update_frequency": self.update_frequency,
            "data_provision_type": self.data_provision_type,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    target_counties: tuple[str, ...]
    candidates: tuple[LocalSourceCandidate, ...]
    required_signal_types: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_counties": list(self.target_counties),
            "required_signal_types": list(self.required_signal_types),
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "summary": _discovery_summary(self.target_counties, self.candidates),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def discover_local_source_candidates(
    payload: object,
    *,
    target_counties: Sequence[str] = DEFAULT_TARGET_COUNTIES,
    required_signal_types: Sequence[str] = (),
) -> DiscoveryResult:
    candidates: list[LocalSourceCandidate] = []
    required = tuple(
        dict.fromkeys(
            _normalized_signal_type(signal_type)
            for signal_type in required_signal_types
        )
    )
    for dataset in _datasets(payload):
        for county in target_counties:
            candidate = _candidate_for_county(dataset, county)
            if candidate is not None and _matches_required_signal_types(
                candidate,
                required_signal_types=required,
            ):
                candidates.append(candidate)
    return DiscoveryResult(
        target_counties=tuple(target_counties),
        candidates=tuple(candidates),
        required_signal_types=required,
    )


def fetch_data_gov_dataset_export(
    *,
    url: str = DATA_GOV_DATASET_EXPORT_URL,
    timeout_seconds: int = 20,
) -> object:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": DISCOVERY_USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to fetch data.gov.tw dataset export: {exc}") from exc


def _discovery_summary(
    target_counties: tuple[str, ...],
    candidates: tuple[LocalSourceCandidate, ...],
) -> dict[str, Any]:
    by_county: dict[str, dict[str, Any]] = {}
    live_counts: dict[str, int] = {}
    metadata_counts: dict[str, int] = {}
    for county in target_counties:
        county_candidates = tuple(candidate for candidate in candidates if candidate.county == county)
        live_count = sum(
            1
            for candidate in county_candidates
            if candidate.readiness == "candidate_live_read_api"
        )
        metadata_count = sum(
            1 for candidate in county_candidates if candidate.readiness == "metadata_only"
        )
        if live_count:
            readiness_state = "live_candidate_found"
            live_counts[county] = live_count
        elif metadata_count:
            readiness_state = "metadata_only"
            metadata_counts[county] = metadata_count
        else:
            readiness_state = "no_candidate"
        signal_types = tuple(
            dict.fromkeys(
                signal_type
                for candidate in county_candidates
                for signal_type in candidate.signal_types
            )
        )
        by_county[county] = {
            "candidate_count": len(county_candidates),
            "candidate_live_read_api_count": live_count,
            "metadata_only_count": metadata_count,
            "readiness_state": readiness_state,
            "signal_types": list(signal_types),
        }
    return {
        "by_county": by_county,
        "candidate_live_read_api_count_by_county": live_counts,
        "metadata_only_count_by_county": metadata_counts,
        "target_counties_without_candidates": [
            county for county, item in by_county.items() if item["candidate_count"] == 0
        ],
    }


def _candidate_for_county(
    dataset: DataGovDataset,
    county: str,
) -> LocalSourceCandidate | None:
    text = " ".join(
        part
        for part in (
            dataset.title,
            dataset.description or "",
            dataset.identifier or "",
            dataset.url or "",
            dataset.field_description or "",
            dataset.update_frequency or "",
            dataset.data_provision_type or "",
            " ".join(dataset.resource_formats),
            " ".join(dataset.resource_urls),
        )
        if part
    )
    if not _text_matches_county(text, county):
        return None
    if any(
        keyword in text
        for keyword in (*NON_WATER_KEYWORDS, *NON_SENSOR_INFRASTRUCTURE_KEYWORDS)
    ):
        return None
    matched = _matched_keywords(text, (*WATER_KEYWORDS, *LIVE_KEYWORDS, *METADATA_KEYWORDS))
    signal_types = _signal_types(text)
    if not matched or not signal_types:
        return None
    readiness = _readiness(dataset, text, dataset.resource_formats)
    return LocalSourceCandidate(
        county=county,
        title=dataset.title,
        dataset_id=dataset.identifier,
        dataset_url=dataset.url,
        readiness=readiness,
        signal_types=signal_types,
        matched_keywords=matched,
        resource_formats=dataset.resource_formats,
        resource_urls=dataset.resource_urls,
        field_description=dataset.field_description,
        update_frequency=dataset.update_frequency,
        data_provision_type=dataset.data_provision_type,
    )


def _readiness(
    dataset: DataGovDataset,
    text: str,
    resource_formats: tuple[str, ...],
) -> CandidateReadiness:
    upper_formats = {item.upper() for item in resource_formats}
    has_machine_readable = bool(upper_formats.intersection({"JSON", "XML", "CSV", "API"}))
    if (
        has_machine_readable
        and any(keyword in text for keyword in LIVE_KEYWORDS)
        and not _looks_like_static_inventory(dataset)
    ):
        return "candidate_live_read_api"
    return "metadata_only"


def _looks_like_static_inventory(dataset: DataGovDataset) -> bool:
    frequency = (dataset.update_frequency or "").lower()
    fields = (dataset.field_description or "").lower()
    provision_type = dataset.data_provision_type or ""
    has_annual_cadence = any(
        token in frequency for token in ("每1年", "每年", "yearly", "annual")
    )
    file_dataset = "檔案資料" in provision_type
    return (has_annual_cadence or file_dataset) and _fields_look_like_static_inventory(
        fields
    )


def _fields_look_like_static_inventory(fields: str) -> bool:
    if not fields:
        return False
    observation_tokens = (
        "observed_at",
        "datatime",
        "rectime",
        "timestamp",
        "sourcetime",
        "infotime",
        "data_time",
        "資料時間",
        "觀測時間",
        "監測時間",
        "更新時間",
    )
    if any(token in fields for token in observation_tokens):
        return False
    static_tokens = ("year(", "竣工", "地址", "address", "型式", "清冊")
    return any(token in fields for token in static_tokens)


def _signal_types(text: str) -> tuple[str, ...]:
    if "易淹水" in text and not any(keyword in text for keyword in LIVE_KEYWORDS):
        return ("flood_prone_area",)
    signal_types: list[str] = []
    checks = (
        ("sewer_water_level", ("雨水下水道", "下水道")),
        ("flood_depth", ("淹水", "積淹水")),
        ("water_level", ("水位", "水情")),
        ("pump_or_gate_status", ("抽水", "水門", "閘門")),
        ("rainfall", ("雨量", "豪雨")),
        ("flood_prone_area", ("易淹水",)),
    )
    for signal_type, tokens in checks:
        if any(token in text for token in tokens) and signal_type not in signal_types:
            signal_types.append(signal_type)
    return tuple(signal_types)


def _matches_required_signal_types(
    candidate: LocalSourceCandidate,
    *,
    required_signal_types: tuple[str, ...],
) -> bool:
    if not required_signal_types:
        return True
    candidate_signal_types = {
        _normalized_signal_type(signal_type) for signal_type in candidate.signal_types
    }
    return bool(candidate_signal_types.intersection(required_signal_types))


def _normalized_signal_type(signal_type: str) -> str:
    if signal_type == "pump_or_gate":
        return "pump_or_gate_status"
    return signal_type


def _datasets(payload: object) -> tuple[DataGovDataset, ...]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, Mapping):
        maybe_items = (
            payload.get("result")
            or payload.get("records")
            or payload.get("data")
            or payload.get("datasets")
        )
        items = maybe_items if isinstance(maybe_items, list) else []
    else:
        items = []
    return tuple(
        DataGovDataset.from_mapping(item) for item in items if isinstance(item, Mapping)
    )


def _distributions(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = item.get("distribution") or item.get("resources") or item.get("檔案")
    if isinstance(raw, list):
        return tuple(entry for entry in raw if isinstance(entry, Mapping))
    return ()


def _resource_formats(
    item: Mapping[str, Any],
    distributions: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...]:
    values = [
        _first_text(item, "format", "檔案格式", "resource_format"),
        *(_first_text(entry, "format", "檔案格式", "resource_format") for entry in distributions),
    ]
    return tuple(dict.fromkeys(value.upper() for value in values if value))


def _resource_urls(
    item: Mapping[str, Any],
    distributions: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...]:
    values = [
        _first_text(item, "downloadURL", "下載網址", "resource_url"),
        *(
            _first_text(entry, "downloadURL", "下載網址", "accessURL", "resource_url")
            for entry in distributions
        ),
    ]
    return tuple(dict.fromkeys(value for value in values if value))


def _matched_keywords(text: str, keywords: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(keyword for keyword in keywords if keyword in text))


def _short_county_name(county: str) -> str:
    return county.removesuffix("縣").removesuffix("市")


def _text_matches_county(text: str, county: str) -> bool:
    if county in text:
        return True
    short_name = _short_county_name(county)
    if not short_name or short_name not in text:
        return False
    other_suffixes = ("市", "縣") if county.endswith("縣") else ("縣", "市")
    for suffix in other_suffixes:
        other_name = f"{short_name}{suffix}"
        if other_name != county and other_name in text:
            return False
    return True


DATA_GOV_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("\u8cc7\u6599\u96c6\u540d\u7a31",),
    "description": ("\u8cc7\u6599\u96c6\u63cf\u8ff0",),
    "identifier": ("\u8cc7\u6599\u96c6\u8b58\u5225\u78bc",),
    "format": ("\u6a94\u6848\u683c\u5f0f",),
    "downloadurl": ("\u8cc7\u6599\u4e0b\u8f09\u7db2\u5740",),
}


def _first_text(item: Mapping[str, Any], *keys: str) -> str | None:
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        for candidate_key in (key, *DATA_GOV_KEY_ALIASES.get(key.lower(), ())):
            value = item.get(candidate_key)
            if value is None:
                value = lowered.get(candidate_key.lower())
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return None
