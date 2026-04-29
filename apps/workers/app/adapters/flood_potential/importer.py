from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

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


class FloodPotentialGeoJsonAdapter:
    metadata = AdapterMetadata(
        key="official.flood_potential.geojson",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=True,
        display_name="Flood potential GeoJSON import adapter",
    )

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
        features = self._feature_collection.get("features", ())
        return tuple(
            RawSourceItem(
                source_id=_source_id(feature),
                source_url=str(feature.get("properties", {}).get("source_url", "")),
                fetched_at=self._fetched_at,
                payload=feature,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for feature in features
            if isinstance(feature, Mapping)
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
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
            evidence_id=stable_evidence_id(self.metadata.key, raw_item.source_id),
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
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
            attribution=optional_str(properties.get("attribution")) or "Official flood potential dataset",
            tags=("official", "flood_potential", "geojson"),
        )

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


def _source_id(feature: Mapping[str, Any]) -> str:
    feature_id = optional_str(feature.get("id"))
    if feature_id:
        return feature_id
    properties = feature.get("properties", {})
    if isinstance(properties, Mapping):
        return str(properties["area_id"])
    return "unknown-feature"
