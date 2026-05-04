from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from app.api.schemas import GeocodePrecision, GeocodeRequest, LatLng, PlaceCandidate
from app.domain.geocoding.taiwan import build_taiwan_geocode_queries

InputType = Literal["address", "landmark", "parcel"]
PlaceType = Literal["address", "parcel", "landmark", "admin_area", "poi"]
NominatimLookup = Callable[[str, InputType, int], tuple[PlaceCandidate, ...]]
WikimediaLookup = Callable[[str, int], tuple[PlaceCandidate, ...]]
GEOCODE_PRECISION_VALUES: set[str] = {
    "exact_address",
    "road_or_lane",
    "poi",
    "admin_area",
    "map_click",
    "unknown",
}
PLACE_TYPE_VALUES: set[str] = {"address", "parcel", "landmark", "admin_area", "poi"}


@dataclass(frozen=True)
class LocalFixturePoint:
    aliases: tuple[str, ...]
    name: str
    lat: float
    lng: float
    admin_code: str
    precision: GeocodePrecision
    place_type: PlaceType


@dataclass(frozen=True)
class LocalOpenDataPoint:
    aliases: tuple[str, ...]
    name: str
    lat: float
    lng: float
    admin_code: str | None
    precision: GeocodePrecision
    place_type: PlaceType
    source: str


LOCAL_TAIWAN_OPEN_DATA_FIXTURES: tuple[LocalFixturePoint, ...] = (
    LocalFixturePoint(
        aliases=("台南市安南區長溪路二段410巷16弄1號",),
        name="台南市安南區長溪路二段410巷16弄1號",
        lat=23.05753,
        lng=120.20144,
        admin_code="67000000",
        precision="exact_address",
        place_type="address",
    ),
    LocalFixturePoint(
        aliases=("高雄市鼓山區蓮海路70號",),
        name="高雄市鼓山區蓮海路70號",
        lat=22.62676,
        lng=120.26575,
        admin_code="64000000",
        precision="exact_address",
        place_type="address",
    ),
    LocalFixturePoint(
        aliases=("嘉義市東區林森東路", "林森東路151號"),
        name="嘉義市東區林森東路",
        lat=23.4889,
        lng=120.4555,
        admin_code="10020000",
        precision="road_or_lane",
        place_type="address",
    ),
)


KNOWN_GEOCODE_POINTS: tuple[tuple[tuple[str, ...], float, float, str], ...] = (
    (
        ("台北火車站", "台北車站", "臺北車站", "taipei main station", "taipei station"),
        25.04776,
        121.51706,
        "63000000",
    ),
    (("台北101", "台北 101", "臺北101", "taipei 101"), 25.03396, 121.56447, "63000000"),
    (("台北市政府", "臺北市政府", "taipei city hall"), 25.03752, 121.56368, "63000000"),
    (("西門町", "ximending"), 25.04208, 121.50777, "63000000"),
    (("板橋車站", "banqiao station"), 25.01433, 121.46386, "65000000"),
    (("桃園機場", "桃園國際機場", "taoyuan airport"), 25.07965, 121.23422, "68000000"),
    (("新竹車站", "hsinchu station"), 24.80158, 120.9717, "10018000"),
    (("台中車站", "臺中車站", "taichung station"), 24.13716, 120.68686, "66000000"),
    (("台南車站", "臺南車站", "tainan station"), 22.99713, 120.21295, "67000000"),
    (("高雄車站", "kaohsiung station"), 22.63937, 120.30203, "64000000"),
    (("花蓮車站", "hualien station"), 23.9928, 121.60195, "10015000"),
    (("國立臺灣大學", "國立台灣大學", "台灣大學", "臺灣大學", "ntu"), 25.01682, 121.53846, "63000000"),
    (("國立成功大學", "成功大學", "成大", "ncku"), 22.9997, 120.21972, "67000000"),
    (("奇美博物館", "chimei museum"), 22.93486, 120.22688, "67000000"),
    (("台南七股鹽山", "臺南七股鹽山", "七股鹽山", "七股鹽場", "cigu salt mountain"), 23.152758, 120.102489, "67000000"),
    (("四草綠色隧道", "台南四草綠色隧道", "臺南四草綠色隧道"), 23.01916, 120.13554, "67000000"),
    (("安平古堡", "台南安平古堡", "臺南安平古堡"), 23.00155, 120.16056, "67000000"),
    (("赤崁樓", "台南赤崁樓", "臺南赤崁樓"), 22.99743, 120.20256, "67000000"),
    (("億載金城", "台南億載金城", "臺南億載金城"), 22.98718, 120.15981, "67000000"),
    (("台南孔廟", "臺南孔廟", "全臺首學"), 22.99032, 120.20401, "67000000"),
    (("神農街", "台南神農街", "臺南神農街"), 22.99753, 120.19625, "67000000"),
    (("國立故宮博物院", "故宮", "台北故宮", "taipei palace museum"), 25.10236, 121.54849, "63000000"),
    (("士林夜市", "shilin night market"), 25.08808, 121.52418, "63000000"),
    (("國立自然科學博物館", "科博館", "台中科博館"), 24.15752, 120.66602, "66000000"),
    (("逢甲夜市", "fengjia night market"), 24.17509, 120.64554, "66000000"),
    (("高鐵台南站", "高鐵臺南站", "台南高鐵站", "tainan hsr"), 22.92508, 120.28572, "67000000"),
    (("高鐵左營站", "左營高鐵站", "zuoying hsr"), 22.68739, 120.30748, "64000000"),
    (
        (
            "高雄市左營區桃子園路",
            "左營區桃子園路",
            "桃子園路",
            "桃子園路61號",
            "翡翠流域",
            "先鋒路桃子園路",
            "taoziyuan road",
            "zuoying taoziyuan road",
        ),
        22.6731,
        120.2862,
        "64000000",
    ),
    (("松山機場", "台北松山機場", "taipei songshan airport"), 25.06972, 121.5525, "63000000"),
)

ADMIN_AREA_POINTS: tuple[tuple[tuple[str, ...], str, float, float, str], ...] = (
    (("台北市", "臺北市"), "台北市", 25.0375, 121.5637, "63000000"),
    (("新北市",), "新北市", 25.012, 121.4657, "65000000"),
    (("桃園市",), "桃園市", 24.9936, 121.301, "68000000"),
    (("台中市", "臺中市"), "台中市", 24.1477, 120.6736, "66000000"),
    (("台南市", "臺南市"), "台南市", 22.9997, 120.227, "67000000"),
    (("高雄市",), "高雄市", 22.6273, 120.3014, "64000000"),
    (("高雄市鼓山區", "鼓山區"), "高雄市鼓山區", 22.6502, 120.2742, "64000000"),
    (("嘉義市",), "嘉義市", 23.4801, 120.4491, "10020000"),
    (("嘉義市東區", "東區嘉義市"), "嘉義市東區", 23.4838, 120.459, "10020000"),
    (("宜蘭縣",), "宜蘭縣", 24.7021, 121.7378, "10002000"),
    (("宜蘭縣礁溪鄉", "礁溪鄉"), "宜蘭縣礁溪鄉", 24.827, 121.7706, "10002000"),
)


class GeocodeProvider(Protocol):
    provider_key: str

    def search(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        """Return candidates for the request, ordered by provider confidence."""


class GeocoderChain:
    def __init__(self, providers: tuple[GeocodeProvider, ...]) -> None:
        self.providers = providers

    def geocode(self, request: GeocodeRequest) -> list[PlaceCandidate]:
        for provider in self.providers:
            candidates = provider.search(request)
            if candidates:
                return list(candidates[: request.limit])
        return []


class FileBackedTaiwanOpenDataProvider:
    provider_key = "file-backed-taiwan-open-data"

    def __init__(self, paths: tuple[str, ...] = ()) -> None:
        self.paths = tuple(path for path in paths if path.strip())

    def search(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        if not self.paths:
            return ()
        normalized_query = normalize_query(request.query)
        matches: list[tuple[int, int, str, str, LocalOpenDataPoint, str]] = []
        for point in load_open_data_points(self.paths):
            matching_alias = next(
                (alias for alias in point.aliases if normalize_query(alias) in normalized_query),
                None,
            )
            if matching_alias is None:
                continue
            matches.append(
                (
                    precision_sort_order(point.precision),
                    -len(normalize_query(matching_alias)),
                    point.name,
                    point.source,
                    point,
                    matching_alias,
                )
            )
        matches.sort()
        return tuple(
            local_open_data_candidate(point, matched_query=matched_query)
            for _, _, _, _, point, matched_query in matches[: request.limit]
        )


class LocalTaiwanAddressProvider:
    provider_key = "local-taiwan-address"

    def search(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        fixture = self._open_data_fixture_candidates(request)
        if fixture:
            return fixture
        known = self._known_point_candidates(request)
        if known:
            return known
        return self._admin_area_candidates(request)

    def _open_data_fixture_candidates(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        normalized_query = normalize_query(request.query)
        for fixture in LOCAL_TAIWAN_OPEN_DATA_FIXTURES:
            matching_alias = next(
                (alias for alias in fixture.aliases if normalize_query(alias) in normalized_query),
                None,
            )
            if matching_alias is None:
                continue
            return (
                PlaceCandidate(
                    place_id=stable_uuid("local-open-data-fixture", fixture.name),
                    name=fixture.name,
                    type=fixture.place_type,
                    point=LatLng(lat=fixture.lat, lng=fixture.lng),
                    admin_code=fixture.admin_code,
                    source="local-open-data-address-fixture",
                    confidence=0.9 if fixture.precision == "exact_address" else 0.78,
                    precision=fixture.precision,
                    matched_query=matching_alias,
                    requires_confirmation=requires_geocode_confirmation(
                        fixture.precision,
                        0.9 if fixture.precision == "exact_address" else 0.78,
                    ),
                    limitations=geocode_limitations(fixture.precision),
                ),
            )
        return ()

    def _known_point_candidates(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        normalized_query = normalize_query(request.query)
        for aliases, lat, lng, admin_code in KNOWN_GEOCODE_POINTS:
            matching_alias = next(
                (alias for alias in aliases if normalize_query(alias) in normalized_query),
                None,
            )
            if matching_alias is None:
                continue
            precision = local_geocode_precision(request.query, request.input_type)
            return tuple(
                PlaceCandidate(
                    place_id=stable_uuid("place", request.query, request.input_type, index),
                    name=request.query if index == 0 else f"{request.query}候選地點 {index + 1}",
                    type=candidate_type_for_precision(request.input_type, precision),
                    point=LatLng(lat=lat + (index * 0.001), lng=lng + (index * 0.001)),
                    admin_code=admin_code,
                    source="local-taiwan-gazetteer",
                    confidence=max(0.5, 0.96 - (index * 0.08)),
                    precision=precision,
                    matched_query=matching_alias,
                    requires_confirmation=requires_geocode_confirmation(
                        precision,
                        max(0.5, 0.96 - (index * 0.08)),
                    ),
                    limitations=geocode_limitations(precision),
                )
                for index in range(request.limit)
            )
        return ()

    def _admin_area_candidates(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        normalized_query = normalize_query(request.query)
        for aliases, name, lat, lng, admin_code in ADMIN_AREA_POINTS:
            if any(normalize_query(alias) == normalized_query for alias in aliases):
                return (
                    PlaceCandidate(
                        place_id=stable_uuid("admin-area", name),
                        name=name,
                        type="admin_area",
                        point=LatLng(lat=lat, lng=lng),
                        admin_code=admin_code,
                        source="local-taiwan-admin-centroid",
                        confidence=0.72,
                        precision="admin_area",
                        matched_query=request.query.strip(),
                        requires_confirmation=True,
                        limitations=geocode_limitations("admin_area"),
                    ),
                )
        return ()


class OpenStreetMapProvider:
    provider_key = "openstreetmap-project-controlled"

    def __init__(self, lookup: NominatimLookup | None = None) -> None:
        self.lookup = lookup

    def search(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        if self.lookup is None:
            return ()
        candidates = self.lookup(request.query.strip(), request.input_type, request.limit)
        return tuple(
            candidate_with_fallback_metadata(
                candidate,
                fallback_kind="direct",
                matched_query=request.query.strip(),
            )
            for candidate in candidates
        )


class NominatimDevelopmentFallbackProvider:
    provider_key = "openstreetmap-nominatim-development"

    def __init__(self, lookup: NominatimLookup) -> None:
        self.lookup = lookup

    def search(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        for geocode_query in geocode_candidate_queries(request.query):
            candidates = self.lookup(geocode_query, request.input_type, request.limit)
            if candidates:
                fallback_kind = geocode_fallback_kind(geocode_query, request.query)
                return tuple(
                    candidate_with_fallback_metadata(
                        candidate,
                        fallback_kind=fallback_kind,
                        matched_query=geocode_query,
                    )
                    for candidate in candidates
                )
        return ()


class WikimediaPoiFallbackProvider:
    provider_key = "wikimedia-poi"

    def __init__(self, lookup: WikimediaLookup) -> None:
        self.lookup = lookup

    def search(self, request: GeocodeRequest) -> tuple[PlaceCandidate, ...]:
        return self.lookup(request.query, request.limit)


def build_open_data_geocoder(
    *,
    nominatim_lookup: NominatimLookup,
    wikimedia_lookup: WikimediaLookup,
    project_osm_lookup: NominatimLookup | None = None,
    open_data_paths: tuple[str, ...] = (),
) -> GeocoderChain:
    return GeocoderChain(
        providers=(
            FileBackedTaiwanOpenDataProvider(open_data_paths),
            LocalTaiwanAddressProvider(),
            OpenStreetMapProvider(project_osm_lookup),
            NominatimDevelopmentFallbackProvider(nominatim_lookup),
            WikimediaPoiFallbackProvider(wikimedia_lookup),
        )
    )


@lru_cache(maxsize=8)
def load_open_data_points(paths: tuple[str, ...]) -> tuple[LocalOpenDataPoint, ...]:
    points: list[LocalOpenDataPoint] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.casefold() == ".jsonl":
            points.extend(read_open_data_jsonl(path))
        else:
            points.extend(read_open_data_csv(path))
    return tuple(points)


def read_open_data_csv(path: Path) -> tuple[LocalOpenDataPoint, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return tuple(
                point
                for row in csv.DictReader(handle)
                for point in (open_data_point_from_row(cast(dict[str, Any], row), path),)
                if point is not None
            )
    except (OSError, csv.Error, UnicodeError):
        return ()


def read_open_data_jsonl(path: Path) -> tuple[LocalOpenDataPoint, ...]:
    points: list[LocalOpenDataPoint] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                point = open_data_point_from_row(payload, path)
                if point is not None:
                    points.append(point)
    except (OSError, UnicodeError):
        return ()
    return tuple(points)


def open_data_point_from_row(row: dict[str, Any], path: Path) -> LocalOpenDataPoint | None:
    name = row_text(row, "name", "address", "road_name", "poi_name")
    lat = row_float(row, "lat", "latitude", "y")
    lng = row_float(row, "lng", "lon", "longitude", "x")
    if not name or lat is None or lng is None or not within_taiwan_bounds(lat, lng):
        return None
    place_type = parse_place_type(row_text(row, "type", "place_type"), default="address")
    precision = parse_precision(
        row_text(row, "precision", "geocode_precision"),
        default=default_precision_for_place_type(place_type),
    )
    return LocalOpenDataPoint(
        aliases=open_data_aliases(row, name),
        name=name,
        lat=lat,
        lng=lng,
        admin_code=row_text(row, "admin_code", "county_code", "city_code"),
        precision=precision,
        place_type=place_type,
        source=row_text(row, "source") or f"local-open-data-import:{path.name}",
    )


def open_data_aliases(row: dict[str, Any], name: str) -> tuple[str, ...]:
    values = [name]
    raw_aliases = row_text(row, "aliases", "alias", "matched_query")
    if raw_aliases:
        values.extend(re.split(r"[|;,]", raw_aliases))
    return dedupe_texts(tuple(values), limit=16)


def row_text(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def row_float(row: dict[str, Any], *keys: str) -> float | None:
    text = row_text(row, *keys)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_place_type(value: str | None, *, default: PlaceType) -> PlaceType:
    normalized = (value or default).strip().casefold()
    if normalized in PLACE_TYPE_VALUES:
        return cast(PlaceType, normalized)
    return default


def parse_precision(value: str | None, *, default: GeocodePrecision) -> GeocodePrecision:
    normalized = (value or default).strip().casefold()
    if normalized in GEOCODE_PRECISION_VALUES:
        return cast(GeocodePrecision, normalized)
    return default


def default_precision_for_place_type(place_type: PlaceType) -> GeocodePrecision:
    if place_type in {"landmark", "poi"}:
        return "poi"
    if place_type == "admin_area":
        return "admin_area"
    return "exact_address"


def precision_sort_order(precision: GeocodePrecision) -> int:
    order = {
        "exact_address": 0,
        "road_or_lane": 1,
        "poi": 2,
        "map_click": 3,
        "admin_area": 4,
        "unknown": 5,
    }
    return order[precision]


def local_open_data_candidate(
    point: LocalOpenDataPoint,
    *,
    matched_query: str,
) -> PlaceCandidate:
    confidence = local_open_data_confidence(point.precision)
    return PlaceCandidate(
        place_id=stable_uuid("local-open-data-import", point.source, point.name, point.lat, point.lng),
        name=point.name,
        type=point.place_type,
        point=LatLng(lat=point.lat, lng=point.lng),
        admin_code=point.admin_code,
        source=point.source,
        confidence=confidence,
        precision=point.precision,
        matched_query=matched_query,
        requires_confirmation=requires_geocode_confirmation(point.precision, confidence),
        limitations=geocode_limitations(point.precision),
    )


def local_open_data_confidence(precision: GeocodePrecision) -> float:
    if precision == "exact_address":
        return 0.91
    if precision == "road_or_lane":
        return 0.78
    if precision == "poi":
        return 0.84
    if precision == "admin_area":
        return 0.72
    return 0.64


def normalize_query(query: str) -> str:
    return query.casefold().replace(" ", "").replace("臺", "台")


def stable_uuid(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(str(part) for part in parts)))


def geocode_candidate_queries(query: str) -> tuple[str, ...]:
    return dedupe_texts(
        (
            *build_taiwan_geocode_queries(query),
            *address_fallback_queries(query),
            *taiwan_context_fallback_queries(query.strip()),
        ),
        limit=12,
    )


def geocode_fallback_queries(query: str) -> tuple[str, ...]:
    normalized = query.strip()
    if not normalized:
        return ()
    return tuple(candidate for candidate in geocode_candidate_queries(normalized) if candidate != normalized)[:8]


def address_fallback_queries(query: str) -> tuple[str, ...]:
    normalized = query.strip()
    if not normalized:
        return ()

    candidates: list[str] = []
    lane_match = re.search(r"(.+?\d+巷)(?:\d+(?:之\d+)?號?)?$", normalized)
    if lane_match:
        candidates.append(lane_match.group(1))

    road_match = re.search(r"(.+?(?:路|街|大道|巷))\d+(?:之\d+)?號?$", normalized)
    if road_match:
        candidates.append(road_match.group(1))

    deduplicated: list[str] = []
    for candidate in candidates:
        if candidate != normalized and candidate not in deduplicated:
            deduplicated.append(candidate)
    return tuple(deduplicated[:4])


def taiwan_context_fallback_queries(query: str) -> tuple[str, ...]:
    if any(token in query.casefold() for token in ("taiwan", "臺灣", "台灣")):
        return ()
    return (f"{query} 台灣", f"臺灣 {query}")


def geocode_fallback_kind(geocode_query: str, original_query: str) -> str:
    if geocode_query == original_query.strip():
        return "direct"
    if geocode_query in address_fallback_queries(original_query.strip()):
        return "address-fallback"
    return "taiwan-normalized"


def geocode_confidence_cap(fallback_kind: str) -> float:
    if fallback_kind == "direct":
        return 0.9
    if fallback_kind == "address-fallback":
        return 0.78
    return 0.82


def candidate_with_fallback_metadata(
    candidate: PlaceCandidate,
    *,
    fallback_kind: str,
    matched_query: str,
) -> PlaceCandidate:
    precision = precision_for_fallback(candidate.precision, fallback_kind)
    confidence = min(candidate.confidence, geocode_confidence_cap(fallback_kind))
    source = candidate.source if fallback_kind == "direct" else f"{candidate.source}-{fallback_kind}"
    return candidate.model_copy(
        update={
            "name": fallback_candidate_name(candidate.name, fallback_kind),
            "source": source,
            "confidence": confidence,
            "precision": precision,
            "matched_query": matched_query,
            "requires_confirmation": requires_geocode_confirmation(precision, confidence),
            "limitations": merge_limitations(
                candidate.limitations,
                geocode_limitations(precision),
                fallback_limitations(fallback_kind),
            ),
        }
    )


def precision_for_fallback(
    original_precision: GeocodePrecision,
    fallback_kind: str,
) -> GeocodePrecision:
    if fallback_kind == "address-fallback":
        return "road_or_lane"
    if fallback_kind == "taiwan-normalized" and original_precision == "unknown":
        return "road_or_lane"
    return original_precision


def requires_geocode_confirmation(precision: GeocodePrecision, confidence: float) -> bool:
    return precision in {"admin_area", "unknown"} or confidence < 0.65


def local_geocode_precision(query: str, input_type: InputType) -> GeocodePrecision:
    if input_type == "landmark":
        return "poi"
    if input_type == "parcel":
        return "exact_address"
    if re.search(r"\d+(?:之\d+)?號", query):
        return "exact_address"
    if re.search(r"(?:路|街|大道|巷)", query):
        return "road_or_lane"
    return "poi"


def candidate_type_for_precision(input_type: InputType, precision: GeocodePrecision) -> PlaceType:
    if precision == "admin_area":
        return "admin_area"
    if precision == "poi":
        return "landmark" if input_type == "landmark" else "poi"
    if input_type == "parcel":
        return "parcel"
    return "address"


def geocode_limitations(precision: GeocodePrecision) -> list[str]:
    if precision == "exact_address":
        return []
    if precision == "road_or_lane":
        return ["定位精度為道路或巷道，門牌位置可能有偏移。"]
    if precision == "poi":
        return ["定位結果是地標或 POI 座標，不代表門牌精準位置。"]
    if precision == "admin_area":
        return ["定位只到行政區代表點，不能直接解讀為該行政區內任一地址風險。"]
    if precision == "map_click":
        return ["使用者點選地圖座標，未經門牌地址校正。"]
    return ["定位來源未提供可判讀精度，需人工確認後再解讀風險。"]


def fallback_limitations(fallback_kind: str) -> list[str]:
    if fallback_kind == "address-fallback":
        return ["原始門牌未能精準定位，已改以較粗的道路或巷道定位。"]
    if fallback_kind == "taiwan-normalized":
        return ["查詢文字已先清理為台灣地名或道路後再定位。"]
    return []


def merge_limitations(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item and item not in merged:
                merged.append(item)
    return merged


def fallback_candidate_name(name: str, fallback_kind: str) -> str:
    if fallback_kind == "address-fallback":
        return f"{name}（由門牌定位到巷道）"
    if fallback_kind == "taiwan-normalized":
        return f"{name}（由查詢文字萃取地名）"
    return name


def dedupe_texts(values: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    deduped: list[str] = []
    for value in values:
        candidate = value.strip()
        if candidate and candidate not in deduped:
            deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return tuple(deduped)


def nominatim_precision(item: dict[str, object], input_type: InputType) -> GeocodePrecision:
    addresstype = str(item.get("addresstype") or "").casefold()
    osm_class = str(item.get("class") or "").casefold()
    osm_type = str(item.get("type") or "").casefold()
    if input_type == "landmark" or osm_class in {"amenity", "tourism", "shop", "railway"}:
        return "poi"
    if addresstype in {"house", "building"} or osm_type in {"house", "building"}:
        return "exact_address"
    if addresstype in {"road", "street"} or osm_class == "highway":
        return "road_or_lane"
    if addresstype in {
        "city",
        "county",
        "municipality",
        "state",
        "town",
        "village",
        "suburb",
        "quarter",
        "neighbourhood",
    }:
        return "admin_area"
    if input_type == "parcel":
        return "exact_address"
    return "unknown"


def within_taiwan_bounds(lat: float, lng: float) -> bool:
    return 21.7 <= lat <= 25.5 and 119.2 <= lng <= 122.3
