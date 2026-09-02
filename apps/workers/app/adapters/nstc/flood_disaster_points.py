from __future__ import annotations

import csv
import hashlib
import math
import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from http.client import HTTPMessage
from io import StringIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from app.adapters._helpers import stable_evidence_id
from app.adapters._taiwan_gov_tls import taiwan_gov_open_data_ssl_context
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
    SourceRejection,
)

FetchText = Callable[[str, int], str]

NSTC_FLOOD_DISASTER_POINTS_DATASET_ID = "130016"
NSTC_FLOOD_DISASTER_POINTS_DATA_GOV_URL = "https://data.gov.tw/dataset/130016"
NSTC_FLOOD_DISASTER_POINTS_RESOURCE_URL = (
    "https://mas.nstc.gov.tw/OPENDATA/GetFile?fileodr=1&format=csv&serialno=455"
)
NSTC_FLOOD_DISASTER_POINTS_USER_AGENT = (
    "FloodRiskTaiwan/0.1 worker-nstc-flood-disaster-points"
)
DEFAULT_NSTC_FLOOD_DISASTER_POINTS_TIMEOUT_SECONDS = 12
MAX_NSTC_FLOOD_DISASTER_POINTS_BYTES = 2 * 1024 * 1024
MAX_NSTC_FLOOD_DISASTER_POINTS_ROWS = 50_000
_TAIWAN_LONGITUDE_BOUNDS = (117.0, 123.5)
_TAIWAN_LATITUDE_BOUNDS = (20.0, 27.5)
_REQUIRED_FIELDS = frozenset({"FID", "year", "X_97", "Y_97", "source"})
_LIMITATIONS = (
    "The snapshot contains annual flood-disaster information points, not exact event times.",
    "The rolling year range is derived from each fetched snapshot and is not assumed in code.",
    "A missing point is not evidence that a location did not flood.",
)

NSTC_FLOOD_DISASTER_POINTS_METADATA = AdapterMetadata(
    key="official.nstc.flood_disaster_points",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="NSTC nationwide flood-disaster points adapter",
    data_gov_dataset_id=NSTC_FLOOD_DISASTER_POINTS_DATASET_ID,
    data_gov_url=NSTC_FLOOD_DISASTER_POINTS_DATA_GOV_URL,
    resource_url=NSTC_FLOOD_DISASTER_POINTS_RESOURCE_URL,
    update_frequency="irregular rolling recent-years snapshot; worker checks daily",
    license="Government Open Data License, version 1.0",
    limitations=_LIMITATIONS,
)


class NstcFloodDisasterPointsError(RuntimeError):
    pass


class NstcFloodDisasterPointsFetchError(NstcFloodDisasterPointsError):
    pass


class NstcFloodDisasterPointsPayloadError(NstcFloodDisasterPointsError):
    pass


class _NstcRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        approved_url = _approved_resource_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, approved_url)


class NstcFloodDisasterPointsAdapter:
    metadata = NSTC_FLOOD_DISASTER_POINTS_METADATA

    def __init__(
        self,
        *,
        resource_url: str | None = None,
        timeout_seconds: int = DEFAULT_NSTC_FLOOD_DISASTER_POINTS_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_text: FetchText | None = None,
        raw_snapshot_key: str | None = None,
        dataset_revision_sha256: str | None = None,
    ) -> None:
        self._resource_url = (resource_url or self.metadata.resource_url or "").strip()
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_text = fetch_text or fetch_nstc_flood_disaster_csv
        self._raw_snapshot_key = raw_snapshot_key
        self._dataset_revision_sha256 = _normalized_sha256(dataset_revision_sha256)

    def fetch(self) -> tuple[RawSourceItem, ...]:
        fetched_at = self._fetched_at or datetime.now(UTC)
        try:
            text = self._fetch_text(self._resource_url, self._timeout_seconds)
            parsed = parse_nstc_flood_disaster_csv(text)
        except NstcFloodDisasterPointsError:
            raise
        except Exception as exc:
            raise NstcFloodDisasterPointsFetchError(
                f"NSTC flood-disaster point fetcher failed: {exc}"
            ) from exc
        revision = self._dataset_revision_sha256 or hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
        return tuple(
            RawSourceItem(
                source_id=str(record["source_id"]),
                source_url=NSTC_FLOOD_DISASTER_POINTS_DATA_GOV_URL,
                fetched_at=fetched_at,
                raw_snapshot_key=self._raw_snapshot_key,
                payload={
                    **record,
                    "evidence_scope": "historical",
                    "event_year": record.get("year"),
                    "temporal_precision": (
                        "year" if record.get("year") is not None else None
                    ),
                    "source_record_key": record.get("source_record_key"),
                    "location_precision": "point",
                    "dataset_revision": revision,
                    "resource_url": self._resource_url,
                    "limitations": list(_LIMITATIONS),
                    "attribution": "NSTC nationwide flood-disaster information points",
                },
            )
            for record in parsed
        )

    def normalize(self, raw: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw.payload
        geometry = payload.get("geometry")
        year = payload.get("year")
        source = payload.get("source")
        fid = payload.get("fid")
        if (
            not isinstance(geometry, Mapping)
            or geometry.get("type") != "Point"
            or not isinstance(year, int)
            or not isinstance(source, str)
            or not isinstance(fid, str)
        ):
            return None
        title = f"{year} 官方淹水災害情資點位（{source} #{fid}）"
        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw.source_id),
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=EventType.FLOOD_REPORT,
            source_id=raw.source_id,
            source_url=raw.source_url,
            source_title=title,
            source_timestamp=None,
            fetched_at=raw.fetched_at,
            summary=(
                "data.gov.tw dataset 130016 彙整防救災部會署淹水災害情資點位；"
                "此筆只提供年度與座標，未提供精確事件時間、淹水深度或地址。"
            ),
            location_text=title,
            confidence=0.82,
            status=IngestionStatus.NORMALIZED,
            attribution="NSTC nationwide flood-disaster information points",
            tags=("official", "nstc", "historical", "flood_report"),
        )

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []
        source_rejections: list[SourceRejection] = []
        for raw in fetched:
            evidence = self.normalize(raw)
            if evidence is None:
                rejected.append(raw.source_id)
                reason_code = raw.payload.get("rejection_reason_code")
                if not isinstance(reason_code, str):
                    reason_code = "nstc_normalization_rejected"
                if len(source_rejections) < 256:
                    source_rejections.append(
                        SourceRejection(
                            source_id=raw.source_id,
                            reason_code=reason_code,
                        )
                    )
            else:
                normalized.append(evidence)
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
            source_rejections=tuple(source_rejections),
        )


def fetch_nstc_flood_disaster_csv(url: str, timeout_seconds: int) -> str:
    approved_url = _approved_resource_url(url)
    request = Request(
        approved_url,
        headers={
            "Accept": "text/csv,application/csv,text/plain;q=0.8",
            "User-Agent": NSTC_FLOOD_DISASTER_POINTS_USER_AGENT,
        },
    )
    try:
        opener = build_opener(
            _NstcRedirectHandler(),
            HTTPSHandler(context=_nstc_ssl_context()),
        )
        with opener.open(request, timeout=max(1, timeout_seconds)) as response:
            _approved_resource_url(response.geturl())
            payload = response.read(MAX_NSTC_FLOOD_DISASTER_POINTS_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise NstcFloodDisasterPointsFetchError(
            f"NSTC flood-disaster CSV request failed: {exc}"
        ) from exc
    if len(payload) > MAX_NSTC_FLOOD_DISASTER_POINTS_BYTES:
        raise NstcFloodDisasterPointsPayloadError(
            "NSTC flood-disaster CSV exceeds the reviewed byte limit"
        )
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise NstcFloodDisasterPointsPayloadError(
        "NSTC flood-disaster CSV is neither UTF-8 nor CP950"
    )


def _nstc_ssl_context() -> ssl.SSLContext:
    context = taiwan_gov_open_data_ssl_context()
    # The current mas.nstc.gov.tw endpoint requires a legacy-compatible cipher
    # security level. CA and hostname verification remain enabled; this change
    # is scoped to this reviewed host rather than weakening the shared context.
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    return context


def parse_nstc_flood_disaster_csv(text: str) -> tuple[dict[str, object], ...]:
    reader = csv.DictReader(StringIO(text))
    missing = _REQUIRED_FIELDS.difference(reader.fieldnames or ())
    if missing:
        raise NstcFloodDisasterPointsPayloadError(
            "NSTC flood-disaster CSV is missing required fields: "
            + ", ".join(sorted(missing))
        )
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    valid_count = 0
    for row_number, row in enumerate(reader, start=2):
        if row_number > MAX_NSTC_FLOOD_DISASTER_POINTS_ROWS + 1:
            raise NstcFloodDisasterPointsPayloadError(
                "NSTC flood-disaster CSV exceeds the reviewed row limit"
            )
        fid = _clean_text(row.get("FID"))
        source = _clean_text(row.get("source")) or "unknown"
        year = _int_value(row.get("year"))
        x = _float_value(row.get("X_97"))
        y = _float_value(row.get("Y_97"))
        if not fid or year is None or x is None or y is None or not 1900 <= year <= 2100:
            records.append(
                _rejected_record(row_number, "nstc_invalid_required_value")
            )
            continue
        coordinate = _twd97_tm2_121_to_wgs84(x, y)
        if coordinate is None:
            records.append(
                _rejected_record(row_number, "nstc_invalid_twd97_coordinate")
            )
            continue
        lat, lng = coordinate
        if not (
            _TAIWAN_LATITUDE_BOUNDS[0] <= lat <= _TAIWAN_LATITUDE_BOUNDS[1]
            and _TAIWAN_LONGITUDE_BOUNDS[0] <= lng <= _TAIWAN_LONGITUDE_BOUNDS[1]
        ):
            records.append(
                _rejected_record(row_number, "nstc_outside_taiwan_bounds")
            )
            continue
        stable_location_key = _stable_location_key(
            year=year,
            source=source,
            lng=lng,
            lat=lat,
        )
        source_id = f"data-gov-130016:{year}:{source}:{fid}"
        if source_id in seen:
            records.append(
                _rejected_record(row_number, "nstc_duplicate_source_id")
            )
            continue
        seen.add(source_id)
        valid_count += 1
        records.append(
            {
                "source_id": source_id,
                "source_record_key": stable_location_key,
                "fid": fid,
                "year": year,
                "source": source,
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
            }
        )
    if valid_count == 0:
        raise NstcFloodDisasterPointsPayloadError(
            "NSTC flood-disaster CSV contains no valid Taiwan point rows"
        )
    return tuple(records)


def _rejected_record(row_number: int, reason_code: str) -> dict[str, object]:
    return {
        "source_id": f"data-gov-130016:rejected:row-{row_number}",
        "rejection_reason_code": reason_code,
    }


def _stable_location_key(*, year: int, source: str, lng: float, lat: float) -> str:
    normalized_source = " ".join(source.casefold().split()) or "unknown"
    identity = f"{year}|{normalized_source}|{lng:.6f}|{lat:.6f}"
    return f"{year}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _approved_resource_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NstcFloodDisasterPointsPayloadError("NSTC resource URL is missing")
    parsed = urlsplit(value.strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "mas.nstc.gov.tw"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/OPENDATA/GetFile"
        or parsed.fragment
        or query != {"fileodr": ["1"], "format": ["csv"], "serialno": ["455"]}
    ):
        raise NstcFloodDisasterPointsPayloadError(
            "NSTC resource URL is outside the reviewed endpoint"
        )
    return value.strip()


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("dataset_revision_sha256 must be a 64-character SHA-256 digest")
    return normalized


def _int_value(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float_value(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _twd97_tm2_121_to_wgs84(x: float, y: float) -> tuple[float, float] | None:
    a = 6378137.0
    b = 6356752.314245
    lng0 = math.radians(121)
    k0 = 0.9999
    eccentricity = math.sqrt(1 - (b * b) / (a * a))
    x -= 250000.0
    meridian = y / k0
    mu = meridian / (
        a
        * (
            1
            - eccentricity**2 / 4
            - 3 * eccentricity**4 / 64
            - 5 * eccentricity**6 / 256
        )
    )
    e1 = (1 - math.sqrt(1 - eccentricity**2)) / (
        1 + math.sqrt(1 - eccentricity**2)
    )
    fp = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    e2 = eccentricity**2 / (1 - eccentricity**2)
    c1 = e2 * math.cos(fp) ** 2
    t1 = math.tan(fp) ** 2
    r1 = a * (1 - eccentricity**2) / (
        (1 - eccentricity**2 * math.sin(fp) ** 2) ** 1.5
    )
    n1 = a / math.sqrt(1 - eccentricity**2 * math.sin(fp) ** 2)
    d = x / (n1 * k0)
    lat = fp - (n1 * math.tan(fp) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * e2) * d**4 / 24
        + (
            61
            + 90 * t1
            + 298 * c1
            + 45 * t1**2
            - 252 * e2
            - 3 * c1**2
        )
        * d**6
        / 720
    )
    lng = lng0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * e2 + 24 * t1**2)
        * d**5
        / 120
    ) / math.cos(fp)
    latitude = math.degrees(lat)
    longitude = math.degrees(lng)
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    return latitude, longitude
