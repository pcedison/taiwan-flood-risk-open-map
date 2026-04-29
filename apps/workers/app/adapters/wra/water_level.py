from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

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


class WraWaterLevelAdapter:
    metadata = AdapterMetadata(
        key="official.wra.water_level",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=True,
        display_name="WRA water level observation adapter",
    )

    def __init__(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        fetched_at: datetime,
        raw_snapshot_key: str | None = None,
    ) -> None:
        self._records = tuple(records)
        self._fetched_at = fetched_at
        self._raw_snapshot_key = raw_snapshot_key

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return tuple(
            RawSourceItem(
                source_id=_source_id(record),
                source_url=str(record["source_url"]),
                fetched_at=self._fetched_at,
                payload=record,
                raw_snapshot_key=self._raw_snapshot_key,
            )
            for record in self._records
        )

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        payload = raw_item.payload
        station_name = str(payload.get("station_name", "")).strip()
        observed_at = parse_datetime(payload.get("observed_at"))
        water_level_m = _optional_float(payload.get("water_level_m"))
        warning_level_m = _optional_float(payload.get("warning_level_m"))

        if not station_name or observed_at is None or water_level_m is None:
            return None

        river_name = optional_str(payload.get("river_name"))
        location_text = " ".join(part for part in (river_name, station_name) if part)
        summary = f"Observed water level: {water_level_m:.2f} m"
        tags = ["official", "wra", "water_level"]
        if warning_level_m is not None:
            gap = warning_level_m - water_level_m
            summary = f"{summary}; {gap:.2f} m below warning level"
            if gap <= 0:
                tags.append("warning_threshold_reached")

        return NormalizedEvidence(
            evidence_id=stable_evidence_id(self.metadata.key, raw_item.source_id),
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=EventType.WATER_LEVEL,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=f"WRA water level observation: {station_name}",
            source_timestamp=observed_at,
            fetched_at=raw_item.fetched_at,
            summary=summary,
            location_text=location_text or station_name,
            confidence=float(payload.get("confidence", 0.9)),
            status=IngestionStatus.NORMALIZED,
            attribution=optional_str(payload.get("attribution")) or "Water Resources Agency",
            tags=tuple(tags),
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


def _source_id(record: Mapping[str, Any]) -> str:
    station_id = str(record["station_id"])
    observed_at = str(record["observed_at"])
    return f"{station_id}:{observed_at}"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
