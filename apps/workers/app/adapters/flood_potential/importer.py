from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.adapters._helpers import optional_str, parse_datetime, stable_evidence_id
from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)


FetchJson = Callable[[str, int], Mapping[str, Any]]

FLOOD_POTENTIAL_GEOJSON_ATTRIBUTION = "Official flood potential dataset"
FLOOD_POTENTIAL_GEOJSON_USER_AGENT = "FloodRiskTaiwan/0.1 worker-flood-potential"
DEFAULT_FLOOD_POTENTIAL_GEOJSON_TIMEOUT_SECONDS = 8

FLOOD_POTENTIAL_GEOJSON_METADATA = AdapterMetadata(
    key="official.flood_potential.geojson",
    family=SourceFamily.OFFICIAL,
    enabled_by_default=True,
    display_name="Flood potential GeoJSON import adapter",
)


class FloodPotentialGeoJsonAdapterError(RuntimeError):
    """Base error for flood potential GeoJSON adapter failures."""


class FloodPotentialGeoJsonConfigurationError(FloodPotentialGeoJsonAdapterError):
    """Raised when the live GeoJSON client is enabled without required config."""


class FloodPotentialGeoJsonFetchError(FloodPotentialGeoJsonAdapterError):
    """Raised when fetching flood potential GeoJSON payloads fails."""


class FloodPotentialGeoJsonPayloadError(FloodPotentialGeoJsonAdapterError):
    """Raised when the flood potential GeoJSON payload shape is not parseable."""


class FloodPotentialGeoJsonApiAdapter:
    metadata = FLOOD_POTENTIAL_GEOJSON_METADATA

    def __init__(
        self,
        *,
        geojson_url: str | None,
        timeout_seconds: int = DEFAULT_FLOOD_POTENTIAL_GEOJSON_TIMEOUT_SECONDS,
        fetched_at: datetime | None = None,
        fetch_json: FetchJson | None = None,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._geojson_url = geojson_url
        self._timeout_seconds = max(1, timeout_seconds)
        self._fetched_at = fetched_at
        self._fetch_json = fetch_json or _fetch_json
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        request_url = optional_str(self._geojson_url)
        if request_url is None:
            raise FloodPotentialGeoJsonConfigurationError(
                "FLOOD_POTENTIAL_GEOJSON_URL is required when "
                "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED=true"
            )

        source_url = _flood_potential_source_url(request_url)
        try:
            payload = self._fetch_json(request_url, self._timeout_seconds)
        except FloodPotentialGeoJsonAdapterError:
            raise
        except Exception as exc:
            raise FloodPotentialGeoJsonFetchError(
                f"Flood potential GeoJSON fetcher failed: {exc}"
            ) from exc

        feature_collection = parse_flood_potential_geojson_payload(
            payload,
            source_url=source_url,
        )
        fetched_at = self._fetched_at or datetime.now(UTC)
        return _feature_collection_raw_items(
            feature_collection,
            fetched_at=fetched_at,
            raw_snapshot_key=self._raw_snapshot_key,
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_feature(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []

        for raw_item in fetched:
            evidence = self.normalize(raw_item)
            if evidence is None:
                rejected.append(raw_item.source_id)
            else:
                normalized.append(evidence)

        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
        )


class FloodPotentialGeoJsonAdapter:
    metadata = FLOOD_POTENTIAL_GEOJSON_METADATA

    def __init__(
        self,
        feature_collection: Mapping[str, Any],
        *,
        fetched_at: datetime,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._feature_collection = feature_collection
        self._fetched_at = fetched_at
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return _feature_collection_raw_items(
            self._feature_collection,
            fetched_at=self._fetched_at,
            raw_snapshot_key=self._raw_snapshot_key,
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return _normalize_feature(self.metadata, raw_item)

    def run(self) -> AdapterRunResult:
        fetched = self.fetch()
        normalized: list[NormalizedEvidence] = []
        rejected: list[str] = []

        for raw_item in fetched:
            evidence = self.normalize(raw_item)
            if evidence is None:
                rejected.append(raw_item.source_id)
            else:
                normalized.append(evidence)

        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=tuple(normalized),
            rejected=tuple(rejected),
        )


def parse_flood_potential_geojson_payload(
    payload: Mapping[str, Any],
    *,
    source_url: str,
) -> Mapping[str, Any]:
    if payload.get("type") != "FeatureCollection":
        raise FloodPotentialGeoJsonPayloadError(
            "Flood potential GeoJSON payload is not a FeatureCollection"
        )

    features = payload.get("features")
    if not isinstance(features, list):
        raise FloodPotentialGeoJsonPayloadError(
            "Flood potential GeoJSON payload is missing features list"
        )

    parsed_features: list[Mapping[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        parsed_features.append(_feature_with_source_url(feature, source_url=source_url))

    return {**payload, "features": parsed_features}


def _feature_collection_raw_items(
    feature_collection: Mapping[str, Any],
    *,
    fetched_at: datetime,
    raw_snapshot_key: str | None,
) -> tuple[RawSourceItem, ...]:
    features = feature_collection.get("features", ())
    return tuple(
        RawSourceItem(
            source_id=_source_id(feature),
            source_url=str(feature.get("properties", {}).get("source_url", "")),
            fetched_at=fetched_at,
            payload=feature,
            raw_snapshot_key=raw_snapshot_key,
        )
        for feature in features
        if isinstance(feature, Mapping)
    )


def _normalize_feature(
    metadata: AdapterMetadata,
    raw_item: RawSourceItem,
) -> NormalizedEvidence | None:
    payload = raw_item.payload
    properties = payload.get("properties", {})
    if not isinstance(properties, Mapping):
        return None

    area_name = str(properties.get("area_name", "")).strip()
    updated_at = parse_datetime(properties.get("updated_at"))
    depth_class = optional_str(properties.get("depth_class"))

    if not area_name or updated_at is None or depth_class is None or not raw_item.source_url:
        return None

    return_period_years = optional_str(properties.get("return_period_years"))
    summary = f"Flood potential depth class: {depth_class}"
    if return_period_years:
        summary = f"{summary}; return period {return_period_years} years"

    return NormalizedEvidence(
        evidence_id=stable_evidence_id(metadata.key, raw_item.source_id),
        adapter_key=metadata.key,
        source_family=metadata.family,
        event_type=EventType.FLOOD_POTENTIAL,
        source_id=raw_item.source_id,
        source_url=raw_item.source_url,
        source_title=f"Flood potential area: {area_name}",
        source_timestamp=updated_at,
        fetched_at=raw_item.fetched_at,
        summary=summary,
        location_text=area_name,
        confidence=float(properties.get("confidence", 0.85)),
        status=IngestionStatus.NORMALIZED,
        attribution=optional_str(properties.get("attribution"))
        or FLOOD_POTENTIAL_GEOJSON_ATTRIBUTION,
        tags=("official", "flood_potential", "geojson"),
    )


def _source_id(feature: Mapping[str, Any]) -> str:
    feature_id = optional_str(feature.get("id"))
    if feature_id:
        return feature_id
    properties = feature.get("properties", {})
    if isinstance(properties, Mapping):
        return str(properties["area_id"])
    return "unknown-feature"


def _feature_with_source_url(
    feature: Mapping[str, Any],
    *,
    source_url: str,
) -> Mapping[str, Any]:
    properties = feature.get("properties")
    if isinstance(properties, Mapping):
        return {**feature, "properties": {**properties, "source_url": source_url}}
    return {**feature, "properties": {"source_url": source_url}}


def _fetch_json(url: str, timeout_seconds: int) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/geo+json, application/json",
            "User-Agent": FLOOD_POTENTIAL_GEOJSON_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise FloodPotentialGeoJsonFetchError(
            f"Flood potential GeoJSON returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FloodPotentialGeoJsonFetchError(
            f"Flood potential GeoJSON request failed: {exc}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise FloodPotentialGeoJsonPayloadError(
            "Flood potential GeoJSON returned a non-object JSON payload"
        )
    return payload


def _flood_potential_source_url(geojson_url: str) -> str:
    parts = urlsplit(geojson_url)
    netloc = _source_url_netloc(parts.hostname, parts.port)
    query = urlencode(
        tuple(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower()
            not in {
                "authorization",
                "api_key",
                "apikey",
                "access_key",
                "access_token",
                "token",
            }
        )
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _source_url_netloc(hostname: str | None, port: int | None) -> str:
    if hostname is None:
        return ""
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    if port is None:
        return host
    return f"{host}:{port}"
