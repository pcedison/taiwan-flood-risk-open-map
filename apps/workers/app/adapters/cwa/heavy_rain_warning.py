from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import (
    parse_qsl,
    quote,
    quote_plus,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)
from urllib.request import Request, urlopen

from app.adapters.cap_identity import cap_message_digest, cap_source_id
from app.adapters.cap_xml import (
    MAX_CAP_BYTES,
    CapDocumentError,
    ParseCapDocument,
    ParsedCapArea,
    ParsedCapMessage,
    parse_cap_document,
)
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    RawSourceItem,
    SourceFamily,
    SourceRejection,
)

CWA_HEAVY_RAIN_CAP_URL = (
    "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/"
    "W-C0033-003?format=CAP"
)
CWA_HEAVY_RAIN_DATASET_URL = (
    "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-003"
)
CWA_HEAVY_RAIN_LICENSE = "中央氣象署開放資料平臺使用規範"
CWA_HEAVY_RAIN_LICENSE_URL = "https://opendata.cwa.gov.tw/about/rules"
CWA_HEAVY_RAIN_USER_AGENT = "FloodRiskTaiwan/0.1 worker-cwa-heavy-rain-cap"
DEFAULT_CWA_HEAVY_RAIN_TIMEOUT_SECONDS = 8
MAX_AUDITED_ROWS = 256
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "token",
        "access_token",
        "password",
        "secret",
        "client_secret",
    }
)
CONFIGURATION_ERROR_MESSAGE = (
    "CWA heavy-rain CAP configuration is invalid: [REDACTED]"
)
FETCH_ERROR_MESSAGE = "CWA heavy-rain CAP request failed: [REDACTED]"
CAP_CREDENTIAL_ERROR_MESSAGE = (
    "CWA heavy-rain CAP contained [REDACTED] credential material"
)

CwaFetchCap = Callable[[str, str, int], str]

CWA_HEAVY_RAIN_WARNING_METADATA = AdapterMetadata(
    key="official.cwa.heavy_rain_warning",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=False,
    display_name="CWA heavy-rain CAP warning audit adapter",
    data_gov_dataset_id="W-C0033-003",
    data_gov_url=CWA_HEAVY_RAIN_DATASET_URL,
    resource_url=CWA_HEAVY_RAIN_CAP_URL,
    update_frequency="as issued by the Central Weather Administration",
    license=CWA_HEAVY_RAIN_LICENSE,
    limitations=(
        "Disabled by default and audit-only until exact administrative geometry is reviewed.",
        "Unreviewed CAP areas never become normalized, staging, latest, or scoring rows.",
    ),
)


class CwaHeavyRainWarningAdapterError(RuntimeError):
    """Base error for CWA heavy-rain CAP failures."""


class CwaHeavyRainWarningConfigurationError(CwaHeavyRainWarningAdapterError):
    """Raised when the credential required for an enabled adapter is absent."""


class CwaHeavyRainWarningFetchError(CwaHeavyRainWarningAdapterError):
    """Raised when the CWA CAP transport fails."""


class CwaHeavyRainWarningRateLimitError(CwaHeavyRainWarningFetchError):
    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class CwaHeavyRainWarningAdapter:
    metadata = CWA_HEAVY_RAIN_WARNING_METADATA

    def __init__(
        self,
        *,
        authorization: str | None,
        cap_url: str | None = None,
        timeout_seconds: int = DEFAULT_CWA_HEAVY_RAIN_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_cap: CwaFetchCap | None = None,
        parse_cap: ParseCapDocument = parse_cap_document,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._authorization = authorization
        self._cap_url = _configured_source_url(
            cap_url or CWA_HEAVY_RAIN_CAP_URL,
            authorization=(authorization or "").strip(),
        )
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_cap_override = fetch_cap
        self._parse_cap = parse_cap
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        rows, _rejections = self._fetch_audited_rows()
        return rows

    def normalize(self, raw_item: RawSourceItem) -> None:
        del raw_item

    def run(self) -> AdapterRunResult:
        fetched, source_rejections = self._fetch_audited_rows()
        rejected = tuple(rejection.source_id for rejection in source_rejections)
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=(),
            rejected=rejected,
            source_rejections=source_rejections,
            no_active_event=not fetched,
        )

    def _fetch_audited_rows(
        self,
    ) -> tuple[tuple[RawSourceItem, ...], tuple[SourceRejection, ...]]:
        authorization = (self._authorization or "").strip()
        if not authorization:
            raise CwaHeavyRainWarningConfigurationError(
                "CWA_API_AUTHORIZATION is required when the CWA heavy-rain warning adapter is enabled"
            )
        if _value_contains_credential(
            self._raw_snapshot_key,
            authorization=authorization,
        ):
            raise CwaHeavyRainWarningConfigurationError(
                CONFIGURATION_ERROR_MESSAGE
            )
        fetched_at = self._fetched_at or datetime.now(UTC)
        xml_text: str | None = None
        if self._fetch_cap_override is None:
            xml_text = _fetch_cap(
                self._cap_url,
                authorization,
                self._timeout_seconds,
                now=fetched_at,
            )
        else:
            fetch_failure: CwaHeavyRainWarningFetchError | None = None
            try:
                xml_text = self._fetch_cap_override(
                    self._cap_url,
                    authorization,
                    self._timeout_seconds,
                )
            except Exception:  # noqa: BLE001 - sanitize the untrusted override boundary
                fetch_failure = CwaHeavyRainWarningFetchError(
                    "CWA heavy-rain CAP fetcher failed: [REDACTED]"
                )
            if fetch_failure is not None:
                raise fetch_failure
        if type(xml_text) is not str:
            raise CwaHeavyRainWarningFetchError(
                "CWA heavy-rain CAP fetcher returned invalid data: [REDACTED]"
            )

        if _string_contains_credential(xml_text, authorization=authorization):
            xml_text = ""
            raise CapDocumentError(
                CAP_CREDENTIAL_ERROR_MESSAGE
            )

        parse_failure: CapDocumentError | None = None
        messages: tuple[ParsedCapMessage, ...] = ()
        try:
            messages = self._parse_cap(xml_text)
        except CapDocumentError as exc:
            if self._parse_cap is parse_cap_document:
                trusted_detail = str(exc)
                parse_failure = CapDocumentError(
                    trusted_detail
                # The shared parser emits only fixed text and field names, never
                    # decoded source values.
                    if not _string_contains_credential(
                        trusted_detail,
                        authorization=authorization,
                    )
                    else "CWA heavy-rain CAP document was rejected: [REDACTED]"
                )
            else:
                # Do not call even __str__ on an injected parser's exception.
                parse_failure = CapDocumentError(
                    "CWA heavy-rain CAP document was rejected: [REDACTED]"
                )
        except Exception:  # noqa: BLE001 - contain arbitrary injected parser failures
            parse_failure = CapDocumentError(
                "CWA heavy-rain CAP parser failed: [REDACTED]"
            )
        xml_text = ""
        if parse_failure is not None:
            raise parse_failure

        scan_failed = False
        contains_credential = False
        try:
            contains_credential = _value_contains_credential(
                messages,
                authorization=authorization,
            )
        except Exception:  # noqa: BLE001 - fail closed on an untrusted parsed structure
            scan_failed = True
        if scan_failed or contains_credential:
            messages = ()
            raise CapDocumentError(CAP_CREDENTIAL_ERROR_MESSAGE)

        preparation_failure: CapDocumentError | None = None
        prepared: list[tuple[RawSourceItem, str]] = []
        try:
            prepared = [
                _prepare_row(
                    message,
                    area,
                    fetched_at=fetched_at,
                    source_url=self._cap_url,
                )
                for message in messages
                for area in (message.areas or (None,))
            ]
        except Exception:  # noqa: BLE001 - contain an untrusted parsed structure
            preparation_failure = CapDocumentError(
                "CWA heavy-rain CAP audit preparation failed: [REDACTED]"
            )
        if preparation_failure is not None:
            prepared = []
            raise preparation_failure
        if len(prepared) > MAX_AUDITED_ROWS:
            raise CapDocumentError("CWA heavy-rain CAP exceeds the 256 audited-row limit")
        source_ids = [raw.source_id for raw, _reason in prepared]
        if len(source_ids) != len(set(source_ids)):
            raise CapDocumentError("CWA heavy-rain CAP contains duplicate deterministic row identities")

        fetched_rows: list[RawSourceItem] = []
        for raw, reason in prepared:
            prepared_raw = RawSourceItem(
                source_id=raw.source_id,
                source_url=raw.source_url,
                fetched_at=raw.fetched_at,
                payload=raw.payload,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            _reject_credential_bearing_raw(
                prepared_raw,
                reason=reason,
                authorization=authorization,
            )
            fetched_rows.append(prepared_raw)
        fetched = tuple(fetched_rows)
        rejections = tuple(
            SourceRejection(raw.source_id, reason) for raw, reason in prepared
        )
        return fetched, rejections


def unresolved_cap_area_source_id(message: ParsedCapMessage, area: ParsedCapArea) -> str:
    message_id = cap_message_digest(
        sender=message.sender,
        identifier=message.identifier,
        sent=message.sent,
    )
    area_json = json.dumps(
        [
            area.area_desc,
            sorted(area.geocodes),
            area.polygon,
            area.circle,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    area_id = hashlib.sha256(area_json.encode("utf-8")).hexdigest()[:24]
    return f"cap:{message_id}:unresolved-area:{area_id}"


def _prepare_row(
    message: ParsedCapMessage,
    area: ParsedCapArea | None,
    *,
    fetched_at: datetime,
    source_url: str,
) -> tuple[RawSourceItem, str]:
    if message.message_type not in {"Alert", "Update", "Cancel"}:
        raise CapDocumentError("CWA CAP msgType must be Alert, Update, or Cancel")
    if message.message_type in {"Update", "Cancel"} and not message.references:
        raise CapDocumentError("CWA CAP Update and Cancel messages require references")
    active_from = message.onset or message.effective
    if active_from is None or message.expires is None:
        raise CapDocumentError("CWA CAP lifecycle requires effective or onset and expires")
    if message.expires <= active_from:
        raise CapDocumentError("CWA CAP expires must be later than active_from")

    if area is None:
        source_id = cap_source_id(
            sender=message.sender,
            identifier=message.identifier,
            sent=message.sent,
            admin_code=None,
            message_level=True,
        )
    else:
        source_id = unresolved_cap_area_source_id(message, area)

    payload: dict[str, object] = {
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "cap_sender": message.sender,
        "cap_identifier": message.identifier,
        "cap_sent": message.sent.isoformat(),
        "cap_references": [
            {
                "sender": reference.sender,
                "identifier": reference.identifier,
                "sent": reference.sent.isoformat(),
            }
            for reference in message.references
        ],
        "cap_status": message.status,
        "cap_message_type": message.message_type,
        "active_from": active_from.isoformat(),
        "active_until": message.expires.isoformat(),
        "areaDesc": area.area_desc if area is not None else None,
        "source_geocodes": (
            [
                {"valueName": name, "value": value}
                for name, value in area.geocodes
            ]
            if area is not None
            else []
        ),
    }
    reason = _rejection_reason(
        message,
        active_from=active_from,
        fetched_at=fetched_at,
        has_area=area is not None,
    )
    return (
        RawSourceItem(
            source_id=source_id,
            source_url=source_url,
            fetched_at=fetched_at,
            payload=payload,
        ),
        reason,
    )


def _rejection_reason(
    message: ParsedCapMessage,
    *,
    active_from: datetime,
    fetched_at: datetime,
    has_area: bool,
) -> str:
    if message.status != "Actual":
        return "cwa_inactive_status"
    if message.scope != "Public":
        return "cwa_inactive_scope"
    if message.message_type == "Cancel":
        return "cwa_inactive_cancel"
    if active_from > fetched_at:
        return "cwa_inactive_future"
    if message.expires is not None and message.expires <= fetched_at:
        return "cwa_inactive_expired"
    return "cwa_unreviewed_admin_geometry" if has_area else "cwa_unreviewed_message_geometry"


def _credential_reflections(authorization: str) -> tuple[str, ...]:
    if not authorization:
        return ()
    return tuple(
        dict.fromkeys(
            (
                authorization,
                quote(authorization, safe=""),
                quote_plus(authorization),
            )
        )
    )


def _string_contains_credential(value: str, *, authorization: str) -> bool:
    return any(
        reflection in value
        for reflection in _credential_reflections(authorization)
    )


def _value_contains_credential(
    value: object,
    *,
    authorization: str,
    _seen: set[int] | None = None,
) -> bool:
    if isinstance(value, str):
        return _string_contains_credential(value, authorization=authorization)
    if value is None:
        return False

    seen = _seen if _seen is not None else set()
    marker = id(value)
    if marker in seen:
        return False

    if is_dataclass(value) and not isinstance(value, type):
        seen.add(marker)
        return any(
            _value_contains_credential(
                getattr(value, field.name),
                authorization=authorization,
                _seen=seen,
            )
            for field in fields(value)
        )
    if isinstance(value, Mapping):
        seen.add(marker)
        return any(
            _value_contains_credential(
                key,
                authorization=authorization,
                _seen=seen,
            )
            or _value_contains_credential(
                item,
                authorization=authorization,
                _seen=seen,
            )
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        seen.add(marker)
        return any(
            _value_contains_credential(
                item,
                authorization=authorization,
                _seen=seen,
            )
            for item in value
        )
    if isinstance(value, (set, frozenset)):
        seen.add(marker)
        return any(
            _value_contains_credential(
                item,
                authorization=authorization,
                _seen=seen,
            )
            for item in value
        )
    return False


def _reject_credential_bearing_raw(
    raw: RawSourceItem,
    *,
    reason: str,
    authorization: str,
) -> None:
    scan_failed = False
    contains_credential = False
    try:
        contains_credential = _value_contains_credential(
            (
                raw.source_id,
                raw.source_url,
                raw.raw_snapshot_key,
                raw.payload,
                reason,
            ),
            authorization=authorization,
        )
    except Exception:  # noqa: BLE001 - fail closed before persistence
        scan_failed = True
    if scan_failed or contains_credential:
        raise CapDocumentError(CAP_CREDENTIAL_ERROR_MESSAGE)


def _fetch_cap(
    url: str,
    authorization: str,
    timeout_seconds: int,
    *,
    now: datetime | None = None,
) -> str:
    body: bytes | None = None
    failure: CwaHeavyRainWarningFetchError | None = None
    try:
        request_url = _request_url(url, authorization)
        request = Request(
            request_url,
            headers={
                "Accept": "application/xml, text/xml",
                "User-Agent": CWA_HEAVY_RAIN_USER_AGENT,
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_CAP_BYTES + 1)
    except HTTPError as exc:
        metadata_failed = False
        is_rate_limited = False
        cooldown: int | None = None
        try:
            is_rate_limited = type(exc.code) is int and exc.code == 429
            if is_rate_limited:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                cooldown = _retry_after_seconds(
                    retry_after,
                    now=now or datetime.now(UTC),
                )
        except Exception:  # noqa: BLE001 - contain hostile HTTP error metadata
            metadata_failed = True
        if is_rate_limited and not metadata_failed:
            failure = CwaHeavyRainWarningRateLimitError(
                "CWA heavy-rain CAP returned HTTP 429: [REDACTED]",
                retry_after_seconds=cooldown,
            )
        else:
            failure = CwaHeavyRainWarningFetchError(FETCH_ERROR_MESSAGE)
    except Exception:  # noqa: BLE001 - complete untrusted transport boundary
        failure = CwaHeavyRainWarningFetchError(FETCH_ERROR_MESSAGE)
    if failure is not None:
        raise failure
    if type(body) is not bytes:
        raise CwaHeavyRainWarningFetchError(FETCH_ERROR_MESSAGE)
    if len(body) > MAX_CAP_BYTES:
        body = None
        raise CwaHeavyRainWarningFetchError(
            "CWA heavy-rain CAP response exceeds the 2 MiB limit: [REDACTED]"
        )
    decoded: str | None = None
    decode_failed = False
    try:
        decoded = body.decode("utf-8")
    except Exception:  # noqa: BLE001 - contain response decode state
        decode_failed = True
    body = None
    if decode_failed:
        raise CwaHeavyRainWarningFetchError(
            "CWA heavy-rain CAP response could not be decoded: [REDACTED]"
        )
    if decoded is None:
        raise CwaHeavyRainWarningFetchError(
            "CWA heavy-rain CAP response could not be decoded: [REDACTED]"
        )
    return decoded


def _source_url(url: str, *, authorization: str = "") -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("CWA CAP URL must be an HTTP endpoint")
    if parts.username is not None or parts.password is not None:
        raise ValueError("CWA CAP URL must not contain userinfo")
    _ = parts.port
    for component in (parts.netloc, parts.path):
        if _string_contains_credential(
            component,
            authorization=authorization,
        ) or _string_contains_credential(
            unquote(component),
            authorization=authorization,
        ):
            raise ValueError("CWA CAP URL must not contain authorization material")

    query: list[tuple[str, str]] = []
    found_format = False
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = name.lower()
        if lowered == "authorization":
            continue
        if lowered in SENSITIVE_QUERY_KEYS:
            raise ValueError("CWA CAP URL must not contain credential query keys")
        if _string_contains_credential(
            name,
            authorization=authorization,
        ) or _string_contains_credential(
            value,
            authorization=authorization,
        ):
            raise ValueError("CWA CAP URL must not contain authorization material")
        if lowered == "format":
            if not found_format:
                query.append(("format", "CAP"))
                found_format = True
            continue
        query.append((name, value))
    if not found_format:
        query.append(("format", "CAP"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _configured_source_url(url: str, *, authorization: str) -> str:
    source_url: str | None = None
    failed = False
    try:
        source_url = _source_url(url, authorization=authorization)
    except Exception:  # noqa: BLE001 - sanitize configured URL parsing failures
        failed = True
    if failed or source_url is None:
        raise CwaHeavyRainWarningConfigurationError(CONFIGURATION_ERROR_MESSAGE)
    return source_url


def _request_url(url: str, authorization: str) -> str:
    parts = urlsplit(_source_url(url, authorization=authorization))
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("Authorization", authorization))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


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
        seconds = math.ceil((retry_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds())
    return min(3600, max(0, seconds))
