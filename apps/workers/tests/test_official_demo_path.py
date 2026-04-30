from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from app.adapters.wra.water_level import WraWaterLevelAdapter
from app.jobs.official_demo import build_official_demo_adapters
from app.pipelines.promotion import (
    PromotionCandidate,
    build_evidence_promotion_payload,
    promote_accepted_staging,
)
from app.pipelines.staging import build_staging_batch


FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)


def test_wra_official_demo_path_raw_snapshot_to_staging_to_promotion_payload() -> None:
    records = json.loads((FIXTURES / "wra_water_level_sample.json").read_text(encoding="utf-8"))
    adapter = WraWaterLevelAdapter(
        records,
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/official/wra/water-level-demo.json",
    )

    batch = build_staging_batch(adapter.run())
    staged = batch.accepted[0]
    candidate = PromotionCandidate(
        staging_evidence_id="staging-wra-1",
        raw_snapshot_id="raw-snapshot-wra-1",
        raw_ref=batch.raw_snapshot.raw_ref,
        data_source_id="data-source-wra",
        source_id=staged.source_id,
        source_type=staged.source_type,
        event_type=staged.event_type,
        title=staged.title,
        summary=staged.summary,
        url=staged.url,
        occurred_at=staged.occurred_at,
        observed_at=staged.observed_at,
        confidence=staged.confidence,
        validation_status=staged.validation_status,
        payload={
            **staged.payload,
            "adapter_key": staged.adapter_key,
            "raw_ref": staged.raw_ref,
        },
    )

    payload = build_evidence_promotion_payload(candidate)
    result = promote_accepted_staging(_MemoryPromotionWriter([candidate]))

    assert batch.adapter_key == "official.wra.water_level"
    assert batch.raw_snapshot.raw_ref == "raw/official/wra/water-level-demo.json"
    assert batch.raw_snapshot.metadata["items_fetched"] == 2
    assert len(batch.accepted) == 2
    assert staged.source_type == "official"
    assert staged.event_type == "water_level"
    assert payload.adapter_key == "official.wra.water_level"
    assert payload.raw_ref == "raw/official/wra/water-level-demo.json"
    assert payload.properties["staging_evidence_id"] == "staging-wra-1"
    assert result.evidence_ids == ("evidence-1",)


def test_official_demo_flood_potential_keeps_geometry_in_promotion_payload() -> None:
    adapter = build_official_demo_adapters(fetched_at=FETCHED_AT)[
        "official.flood_potential.geojson"
    ]
    batch = build_staging_batch(adapter.run())
    staged = batch.accepted[0]
    candidate = PromotionCandidate(
        staging_evidence_id="staging-flood-potential-1",
        raw_snapshot_id="raw-snapshot-flood-potential-1",
        raw_ref=batch.raw_snapshot.raw_ref,
        data_source_id="data-source-flood-potential",
        source_id=staged.source_id,
        source_type=staged.source_type,
        event_type=staged.event_type,
        title=staged.title,
        summary=staged.summary,
        url=staged.url,
        occurred_at=staged.occurred_at,
        observed_at=staged.observed_at,
        confidence=staged.confidence,
        validation_status=staged.validation_status,
        payload={
            **staged.payload,
            "adapter_key": staged.adapter_key,
            "raw_ref": staged.raw_ref,
        },
    )

    payload = build_evidence_promotion_payload(candidate)

    assert batch.raw_snapshot.raw_ref == "raw/official-demo/flood-potential.geojson"
    assert payload.properties["location_text"] == "Taipei Demo Low-Lying Area"
    assert payload.properties["location_payload"]["geometry"]["type"] == "Polygon"
    assert payload.raw_ref == "raw/official-demo/flood-potential.geojson"


class _MemoryPromotionWriter:
    def __init__(self, candidates: list[PromotionCandidate]) -> None:
        self._candidates = tuple(candidates)

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        del limit, adapter_keys
        return self._candidates

    def write_evidence(self, payload: object) -> str:
        del payload
        return "evidence-1"
