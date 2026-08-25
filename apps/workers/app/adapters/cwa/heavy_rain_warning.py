from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
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
        self._cap_url = _source_url(cap_url or CWA_HEAVY_RAIN_CAP_URL)
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
        fetched_at = self._fetched_at or datetime.now(UTC)
        fetch_failure: CwaHeavyRainWarningFetchError | None = None
        try:
            if self._fetch_cap_override is None:
                xml_text = _fetch_cap(
                    self._cap_url,
                    authorization,
                    self._timeout_seconds,
                    now=fetched_at,
                )
            else:
                xml_text = self._fetch_cap_override(
                    self._cap_url,
                    authorization,
                    self._timeout_seconds,
                )
        except CwaHeavyRainWarningAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - redact arbitrary injected transport failures
            detail = _redact_detail(str(exc), authorization=authorization)
            fetch_failure = CwaHeavyRainWarningFetchError(
                f"CWA heavy-rain CAP fetcher failed at {_redacted_url(self._cap_url)}: {detail}"
            )
        if fetch_failure is not None:
            raise fetch_failure

        if authorization in xml_text:
            xml_text = ""
            raise CapDocumentError(
                "CWA heavy-rain CAP response contained the redacted authorization value"
            )

        parse_failure: CapDocumentError | None = None
        try:
            messages = self._parse_cap(xml_text)
        except CapDocumentError as exc:
            parse_failure = CapDocumentError(
                _redact_detail(str(exc), authorization=authorization)
            )
        except Exception as exc:  # noqa: BLE001 - contain arbitrary injected parser failures
            parse_failure = CapDocumentError(
                f"CWA heavy-rain CAP parser failed: {type(exc).__name__}"
            )
        if parse_failure is not None:
            xml_text = ""
            raise parse_failure

        prepared = [
            _prepare_row(message, area, fetched_at=fetched_at, source_url=self._cap_url)
            for message in messages
            for area in (message.areas or (None,))
        ]
        if len(prepared) > MAX_AUDITED_ROWS:
            raise CapDocumentError("CWA heavy-rain CAP exceeds the 256 audited-row limit")
        source_ids = [raw.source_id for raw, _reason in prepared]
        if len(source_ids) != len(set(source_ids)):
            raise CapDocumentError("CWA heavy-rain CAP contains duplicate deterministic row identities")

        fetched = tuple(
            RawSourceItem(
                source_id=raw.source_id,
                source_url=raw.source_url,
                fetched_at=raw.fetched_at,
                payload=raw.payload,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for raw, _reason in prepared
        )
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


def _fetch_cap(
    url: str,
    authorization: str,
    timeout_seconds: int,
    *,
    now: datetime | None = None,
) -> str:
    request_url = _request_url(url, authorization)
    body: bytes | None = None
    failure: CwaHeavyRainWarningFetchError | None = None
    try:
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
        redacted_url = _redacted_url(url)
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            cooldown = _retry_after_seconds(retry_after, now=now or datetime.now(UTC))
            failure = CwaHeavyRainWarningRateLimitError(
                f"CWA heavy-rain CAP returned HTTP 429 at {redacted_url}",
                retry_after_seconds=cooldown,
            )
        else:
            failure = CwaHeavyRainWarningFetchError(
                f"CWA heavy-rain CAP returned HTTP {exc.code} at {redacted_url}"
            )
    except (URLError, TimeoutError, OSError) as exc:
        detail = _redact_detail(str(exc), authorization=authorization)
        failure = CwaHeavyRainWarningFetchError(
            f"CWA heavy-rain CAP request failed at {_redacted_url(url)}: {detail}"
        )
    if failure is not None:
        raise failure
    if body is None:
        raise CwaHeavyRainWarningFetchError(
            f"CWA heavy-rain CAP request failed at {_redacted_url(url)}"
        )
    if len(body) > MAX_CAP_BYTES:
        raise CwaHeavyRainWarningFetchError(
            f"CWA heavy-rain CAP response exceeds the 2 MiB limit at {_redacted_url(url)}"
        )
    decoded: str | None = None
    decode_failure: CwaHeavyRainWarningFetchError | None = None
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        decode_failure = CwaHeavyRainWarningFetchError(
            f"CWA heavy-rain CAP response could not be decoded at {_redacted_url(url)}"
        )
    if decode_failure is not None:
        raise decode_failure
    if decoded is None:
        raise CwaHeavyRainWarningFetchError(
            f"CWA heavy-rain CAP response could not be decoded at {_redacted_url(url)}"
        )
    return decoded


def _source_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query: list[tuple[str, str]] = []
    found_format = False
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = name.lower()
        if lowered == "authorization":
            continue
        if lowered == "format":
            if not found_format:
                query.append((name, "CAP"))
                found_format = True
            continue
        query.append((name, value))
    if not found_format:
        query.append(("format", "CAP"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _request_url(url: str, authorization: str) -> str:
    parts = urlsplit(_source_url(url))
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("Authorization", authorization))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _redacted_url(url: str) -> str:
    return _request_url(url, "REDACTED")


def _redact_detail(detail: str, *, authorization: str) -> str:
    redacted = detail.replace(authorization, "REDACTED") if authorization else detail
    return re.sub(
        r"(?i)(Authorization(?:=|%3D))[^&\s]+",
        r"\1REDACTED",
        redacted,
    )


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
