from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.adapters._helpers import optional_str, stable_evidence_id
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

POLICE_RADIO_TRAFFIC_URL = (
    "https://rtr.pbs.gov.tw/NMP103_PbsWS/resources/roadData/opendata"
)
POLICE_RADIO_DATA_GOV_URL = "https://data.gov.tw/dataset/15221"
POLICE_RADIO_LIMITATIONS = (
    "警廣即時路況通報，尚未由淹水感測器確認。",
    "路況通報可能由民眾或勤務單位提供，位置與狀態可能延遲更新。",
)
POLICE_RADIO_TRAFFIC_METADATA = AdapterMetadata(
    key="official.npa.police_radio_traffic",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="警廣即時路況積淹水通報",
    data_gov_dataset_id="15221",
    data_gov_url=POLICE_RADIO_DATA_GOV_URL,
    resource_url=POLICE_RADIO_TRAFFIC_URL,
    update_frequency="latest traffic records; source page may lag by up to one minute",
    license="Government Open Data License, version 1.0",
    limitations=(
        "Reported and unverified road-incident context; it is not a flood-sensor observation.",
        "Context-only rows never enter official realtime latest or scoring.",
    ),
)

PoliceRadioFetchJson = Callable[[str, int], object]

DEFAULT_POLICE_RADIO_TIMEOUT_SECONDS = 8
MAX_POLICE_RADIO_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_POLICE_RADIO_RECORDS = 1000
MAX_POLICE_RADIO_AUDITED_REJECTIONS = 256
POLICE_RADIO_USER_AGENT = "FloodRiskTaiwan/0.1 worker-police-radio-traffic"
_TAIPEI = ZoneInfo("Asia/Taipei")
_PUBLIC_FIELDS = (
    "region",
    "srcdetail",
    "areaNm",
    "UID",
    "direction",
    "y1",
    "happentime",
    "roadtype",
    "road",
    "modDttm",
    "comment",
    "happendate",
    "x1",
)
_TEXT_FIELDS = (
    "region",
    "srcdetail",
    "areaNm",
    "direction",
    "roadtype",
    "road",
    "comment",
)
_FLOOD_KEYWORDS = ("道路淹水", "淹水", "積水", "水淹")
_RAIN_KEYWORDS = ("大雨", "豪雨", "下雨")
_RESOLVED_KEYWORDS = ("恢復通行", "已排除", "解除", "排除")
_FETCH_ERROR_MESSAGE = "police-radio traffic request failed: [REDACTED]"
_PAYLOAD_ERROR_MESSAGE = "police-radio traffic payload was rejected: [REDACTED]"
_MISSING_PAYLOAD = object()


class PoliceRadioTrafficAdapterError(RuntimeError):
    """Base error for the police-radio traffic adapter."""


class PoliceRadioTrafficConfigurationError(PoliceRadioTrafficAdapterError):
    """Raised when the configured endpoint cannot be safely retained."""


class PoliceRadioTrafficFetchError(PoliceRadioTrafficAdapterError):
    """Raised when the bounded JSON transport fails."""


class PoliceRadioTrafficPayloadError(PoliceRadioTrafficAdapterError):
    """Raised when the fixture-pinned JSON contract is not satisfied."""


class PoliceRadioTrafficRateLimitError(PoliceRadioTrafficFetchError):
    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = _bounded_retry_after(retry_after_seconds)


class PoliceRadioTrafficAdapter:
    metadata = POLICE_RADIO_TRAFFIC_METADATA

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        timeout_seconds: int = DEFAULT_POLICE_RADIO_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        payload: object = _MISSING_PAYLOAD,
        fetch_json: PoliceRadioFetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._endpoint_url = _configured_url(endpoint_url or POLICE_RADIO_TRAFFIC_URL)
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._payload = payload
        self._fetch_json_override = fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        result = self._build_result()
        return result.fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        if raw_item.payload.get("accepted_context") is not True:
            return None
        source_timestamp = _parse_aware_utc(raw_item.payload.get("source_timestamp"))
        if source_timestamp is None:
            return None
        road = optional_str(raw_item.payload.get("road"))
        area = optional_str(raw_item.payload.get("areaNm"))
        location_text = " ".join(value for value in (area, road) if value) or None
        state = str(raw_item.payload["incident_state"])
        summary = f"警廣積淹水路況通報（{state}）"
        if location_text:
            summary = f"{summary}：{location_text}"
        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw_item.source_id),
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.STATUS_ONLY,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=self.metadata.display_name,
            source_timestamp=source_timestamp,
            fetched_at=raw_item.fetched_at,
            summary=summary,
            location_text=location_text,
            confidence=0.62,
            status=IngestionStatus.NORMALIZED,
            attribution="Police Broadcasting Service",
            tags=(
                "official",
                "police_radio",
                "reported_flood_road_incident",
                "reported_unverified",
                "status_only",
                state,
            ),
        )

    def run(self) -> AdapterRunResult:
        return self._build_result()

    def _build_result(self) -> AdapterRunResult:
        fetched_at = self._fetched_at or datetime.now(UTC)
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE)
        fetched_at = fetched_at.astimezone(UTC)
        payload = self._load_payload(fetched_at=fetched_at)
        selection_failure: PoliceRadioTrafficPayloadError | None = None
        selected: tuple[tuple[str, Mapping[str, object], datetime | None], ...] = ()
        try:
            selected = _select_latest_records(payload)
        except PoliceRadioTrafficPayloadError:
            raise
        except Exception:  # noqa: BLE001 - sanitize the injected JSON-like boundary
            selection_failure = PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE)
        if selection_failure is not None:
            raise selection_failure

        fetched: list[RawSourceItem] = []
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []
        rejection_candidates: list[SourceRejection] = []
        preparation_failure: PoliceRadioTrafficPayloadError | None = None
        try:
            for uid, record, update_time in selected:
                raw, reason_code, detailed = _prepare_raw_item(
                    uid,
                    record,
                    update_time=update_time,
                    endpoint_url=self._endpoint_url,
                    fetched_at=fetched_at,
                    raw_snapshot_key=self._raw_snapshot_key,
                )
                fetched.append(raw)
                evidence = self.normalize(raw)
                if evidence is not None:
                    normalized.append(evidence)
                    continue
                rejected.append(uid)
                if detailed and reason_code is not None:
                    rejection_candidates.append(SourceRejection(uid, reason_code))
        except PoliceRadioTrafficPayloadError:
            raise
        except Exception:  # noqa: BLE001 - sanitize record preparation state
            preparation_failure = PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE)
        if preparation_failure is not None:
            raise preparation_failure

        source_rejections = tuple(
            sorted(rejection_candidates, key=lambda item: item.source_id)[
                :MAX_POLICE_RADIO_AUDITED_REJECTIONS
            ]
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=tuple(fetched),
            normalized=tuple(normalized),
            rejected=tuple(rejected),
            source_rejections=source_rejections,
            no_active_event=not payload,
        )

    def _load_payload(self, *, fetched_at: datetime) -> object:
        if self._payload is not _MISSING_PAYLOAD:
            return self._payload
        fetcher = self._fetch_json_override
        if fetcher is None:
            return _fetch_json(
                self._endpoint_url,
                self._timeout_seconds,
                now=fetched_at,
            )

        failure: PoliceRadioTrafficFetchError | None = None
        fetched: object = None
        try:
            fetched = fetcher(self._endpoint_url, self._timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - sanitize the injected transport boundary
            if isinstance(exc, PoliceRadioTrafficRateLimitError):
                failure = PoliceRadioTrafficRateLimitError(
                    "police-radio traffic returned HTTP 429: [REDACTED]",
                    retry_after_seconds=exc.retry_after_seconds,
                )
            else:
                failure = PoliceRadioTrafficFetchError(_FETCH_ERROR_MESSAGE)
        if failure is not None:
            raise failure
        return fetched


def _select_latest_records(
    payload: object,
) -> tuple[tuple[str, Mapping[str, object], datetime | None], ...]:
    if not isinstance(payload, list):
        raise PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE)
    if len(payload) > MAX_POLICE_RADIO_RECORDS:
        raise PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE)

    grouped: dict[str, list[tuple[datetime | None, str, Mapping[str, object]]]] = {}
    for item in payload:
        if not isinstance(item, Mapping):
            raise PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE)
        uid_value = item.get("UID")
        if not isinstance(uid_value, str):
            raise PoliceRadioTrafficPayloadError("police-radio traffic UID was rejected")
        uid = uid_value.strip()
        if not uid or uid != uid_value or len(uid) > 512:
            raise PoliceRadioTrafficPayloadError("police-radio traffic UID was rejected")
        canonical = _canonical_record(item)
        update_time = _parse_local_datetime(item.get("modDttm"))
        grouped.setdefault(uid, []).append((update_time, canonical, item))

    selected: list[tuple[str, Mapping[str, object], datetime | None]] = []
    for uid in sorted(grouped):
        versions = grouped[uid]
        invalid_candidates = [
            version
            for version in versions
            if version[0] is None and _candidate_kind(version[2]) != "ordinary"
        ]
        if invalid_candidates:
            update_time, _canonical, record = max(
                invalid_candidates,
                key=lambda version: version[1],
            )
        else:
            update_time, _canonical, record = max(
                versions,
                key=lambda version: (
                    version[0] is not None,
                    version[0] or datetime.min.replace(tzinfo=UTC),
                    version[1],
                ),
            )
        selected.append((uid, record, update_time))
    return tuple(selected)


def _prepare_raw_item(
    uid: str,
    record: Mapping[str, object],
    *,
    update_time: datetime | None,
    endpoint_url: str,
    fetched_at: datetime,
    raw_snapshot_key: str | None,
) -> tuple[RawSourceItem, str | None, bool]:
    payload = {key: record.get(key) for key in _PUBLIC_FIELDS}
    kind = _candidate_kind(record)
    reason_code: str | None = None
    detailed = kind in {"flood", "rain"}
    if kind == "ordinary":
        reason_code = "police_radio_unrelated_traffic"
    elif kind == "rain":
        reason_code = "police_radio_rain_only"
    elif update_time is None:
        reason_code = "police_radio_invalid_update_time"
    else:
        source_timestamp = _parse_source_timestamp(record)
        if source_timestamp is None:
            reason_code = "police_radio_invalid_source_time"
        elif source_timestamp > fetched_at + timedelta(minutes=5):
            reason_code = "police_radio_future_source_time"
        elif source_timestamp < fetched_at - timedelta(hours=6):
            reason_code = "police_radio_stale_source_time"
        else:
            coordinates = _coordinates(record)
            if coordinates is None:
                reason_code = "police_radio_invalid_coordinates"
            elif not (117.0 <= coordinates[0] <= 123.5 and 20.0 <= coordinates[1] <= 27.5):
                reason_code = "police_radio_coordinates_outside_taiwan"
            else:
                incident_state = (
                    "resolved"
                    if any(keyword in _candidate_text(record) for keyword in _RESOLVED_KEYWORDS)
                    else "active"
                )
                payload.update(
                    {
                        "accepted_context": True,
                        "source_timestamp": source_timestamp.isoformat(),
                        "upstream_updated_at": update_time.isoformat(),
                        "evidence_scope": "context",
                        "location_precision": "road_or_lane",
                        "context_kind": "reported_flood_road_incident",
                        "verification_status": "reported_unverified",
                        "incident_state": incident_state,
                        "geometry": {
                            "type": "Point",
                            "coordinates": [coordinates[0], coordinates[1]],
                        },
                        "limitations": list(POLICE_RADIO_LIMITATIONS),
                    }
                )

    raw = RawSourceItem(
        source_id=uid,
        source_url=endpoint_url,
        fetched_at=fetched_at,
        payload=payload,
        raw_snapshot_key=raw_snapshot_key,
    )
    return raw, reason_code, detailed


def _candidate_kind(record: Mapping[str, object]) -> str:
    text = _candidate_text(record)
    if any(keyword in text for keyword in _FLOOD_KEYWORDS):
        return "flood"
    if any(keyword in text for keyword in _RAIN_KEYWORDS):
        return "rain"
    return "ordinary"


def _candidate_text(record: Mapping[str, object]) -> str:
    values: list[str] = []
    for key in _TEXT_FIELDS:
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
    return "\n".join(values)


def _parse_source_timestamp(record: Mapping[str, object]) -> datetime | None:
    date_text = _strict_text(record.get("happendate"))
    time_text = _strict_text(record.get("happentime"))
    if date_text is None or time_text is None:
        return None
    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        for time_format in ("%H:%M:%S", "%H:%M", "%H%M%S"):
            try:
                parsed = datetime.strptime(
                    f"{date_text} {time_text}",
                    f"{date_format} {time_format}",
                ).replace(tzinfo=_TAIPEI)
            except ValueError:
                continue
            return parsed.astimezone(UTC)
    return None


def _parse_local_datetime(value: object) -> datetime | None:
    text = _strict_text(value)
    if text is None:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for date_format in ("%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S"):
            try:
                parsed = datetime.strptime(
                    text,
                    date_format,
                ).replace(tzinfo=_TAIPEI)
            except ValueError:
                continue
            break
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_TAIPEI)
    return parsed.astimezone(UTC)


def _parse_aware_utc(value: object) -> datetime | None:
    text = _strict_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _coordinates(record: Mapping[str, object]) -> tuple[float, float] | None:
    longitude = _finite_float(record.get("x1"))
    latitude = _finite_float(record.get("y1"))
    if longitude is None or latitude is None:
        return None
    return longitude, latitude


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _canonical_record(record: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            {key: record.get(key) for key in _PUBLIC_FIELDS},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE) from None


def _configured_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            raise ValueError
        _ = parts.port
        if parts.query or parts.fragment:
            raise ValueError
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:  # noqa: BLE001 - sanitize configured endpoint parsing
        raise PoliceRadioTrafficConfigurationError(
            "police-radio traffic configuration is invalid: [REDACTED]"
        ) from None


def _fetch_json(url: str, timeout_seconds: int, *, now: datetime) -> object:
    body: bytes | None = None
    failure: PoliceRadioTrafficFetchError | None = None
    try:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": POLICE_RADIO_USER_AGENT,
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_POLICE_RADIO_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        try:
            if type(exc.code) is int and exc.code == 429:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                failure = PoliceRadioTrafficRateLimitError(
                    "police-radio traffic returned HTTP 429: [REDACTED]",
                    retry_after_seconds=_retry_after_seconds(retry_after, now=now),
                )
            else:
                failure = PoliceRadioTrafficFetchError(_FETCH_ERROR_MESSAGE)
        except Exception:  # noqa: BLE001 - contain hostile HTTP error metadata
            failure = PoliceRadioTrafficFetchError(_FETCH_ERROR_MESSAGE)
    except Exception:  # noqa: BLE001 - complete untrusted transport boundary
        failure = PoliceRadioTrafficFetchError(_FETCH_ERROR_MESSAGE)
    if failure is not None:
        raise failure
    if type(body) is not bytes:
        raise PoliceRadioTrafficFetchError(_FETCH_ERROR_MESSAGE)
    if len(body) > MAX_POLICE_RADIO_RESPONSE_BYTES:
        body = None
        raise PoliceRadioTrafficFetchError(
            "police-radio traffic response exceeds the 2 MiB limit: [REDACTED]"
        )
    decoded: str | None = None
    decode_failed = False
    try:
        decoded = body.decode("utf-8")
    except Exception:  # noqa: BLE001 - contain response decode state
        decode_failed = True
    body = None
    if decode_failed or decoded is None:
        raise PoliceRadioTrafficFetchError(_FETCH_ERROR_MESSAGE)
    try:
        return json.loads(decoded)
    except Exception:  # noqa: BLE001 - sanitize JSON parser state
        raise PoliceRadioTrafficPayloadError(_PAYLOAD_ERROR_MESSAGE) from None


def _retry_after_seconds(value: str | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    try:
        seconds = int(stripped)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(stripped)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None or retry_at.utcoffset() is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = math.ceil((retry_at.astimezone(UTC) - now).total_seconds())
    return min(3600, max(0, seconds))


def _bounded_retry_after(value: int | None) -> int | None:
    if type(value) is not int:
        return None
    return min(3600, max(0, value))
