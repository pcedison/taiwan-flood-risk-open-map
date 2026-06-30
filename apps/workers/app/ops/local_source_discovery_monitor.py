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


@dataclass(frozen=True)
class DataGovDataset:
    title: str
    description: str | None = None
    identifier: str | None = None
    url: str | None = None
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
            " ".join(dataset.resource_formats),
            " ".join(dataset.resource_urls),
        )
        if part
    )
    if county not in text and _short_county_name(county) not in text:
        return None
    if any(keyword in text for keyword in NON_WATER_KEYWORDS):
        return None
    matched = _matched_keywords(text, (*WATER_KEYWORDS, *LIVE_KEYWORDS, *METADATA_KEYWORDS))
    signal_types = _signal_types(text)
    if not matched or not signal_types:
        return None
    readiness = _readiness(text, dataset.resource_formats)
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
    )


def _readiness(text: str, resource_formats: tuple[str, ...]) -> CandidateReadiness:
    upper_formats = {item.upper() for item in resource_formats}
    has_machine_readable = bool(upper_formats.intersection({"JSON", "XML", "CSV", "API"}))
    if has_machine_readable and any(keyword in text for keyword in LIVE_KEYWORDS):
        return "candidate_live_read_api"
    return "metadata_only"


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


def _first_text(item: Mapping[str, Any], *keys: str) -> str | None:
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        value = item.get(key)
        if value is None:
            value = lowered.get(key.lower())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
