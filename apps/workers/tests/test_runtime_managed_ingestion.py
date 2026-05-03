from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    IngestionStatus,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)
from app.adapters.news import SamplePublicWebNewsAdapter
from app.config import WorkerSettings, load_worker_settings
from app.jobs.ingestion import AdapterBatchRunSummary
from app.jobs.runtime_managed import run_managed_runtime_ingestion_cycle
from app.pipelines.promotion import EvidencePromotionPayload, PromotionCandidate
from app.pipelines.staging import AdapterStagingBatch


FETCHED_AT = datetime.now(UTC)


def test_managed_runtime_cycle_persists_enabled_adapters_and_promotes() -> None:
    adapter = _sample_adapter()
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])

    result = run_managed_runtime_ingestion_cycle(
        {
            adapter.metadata.key: adapter,
            "official.wra.water_level": _ExplodingAdapter("official.wra.water_level"),
        },
        settings=_settings("news.public_web.sample"),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=True,
        promotion_limit=25,
        job_key="test.runtime.managed",
    )

    assert result.status == "succeeded"
    assert result.reason is None
    assert [summary.adapter_key for summary in result.summaries] == ["news.public_web.sample"]
    assert result.freshness_checks[0].status == "fresh"
    assert result.promoted == 1
    assert result.evidence_ids == ("evidence-1",)
    assert len(staging_writer.batches) == 1
    assert staging_writer.batches[0].accepted[0].source_id == "sample-news-001"
    assert run_writer.calls == [
        (
            result.summaries[0],
            "test.runtime.managed",
            {
                "enabled_adapter_keys": ("news.public_web.sample",),
                "available_adapter_keys": (
                    "news.public_web.sample",
                    "official.wra.water_level",
                ),
            },
        )
    ]
    assert promotion_writer.requested_limit == 25
    assert promotion_writer.requested_adapter_keys == ("news.public_web.sample",)
    assert promotion_writer.payloads[0].source_id == "sample-news-001"


def test_managed_runtime_cycle_uses_injected_adapter_builder() -> None:
    captured: dict[str, WorkerSettings] = {}
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    settings = _settings("news.public_web.sample")

    def adapter_builder(builder_settings: WorkerSettings) -> dict[str, SamplePublicWebNewsAdapter]:
        captured["settings"] = builder_settings
        adapter = _sample_adapter(source_id="builder-news-001")
        return {adapter.metadata.key: adapter}

    result = run_managed_runtime_ingestion_cycle(
        settings=settings,
        adapter_builder=adapter_builder,
        staging_writer=staging_writer,
        run_writer=run_writer,
    )

    assert result.status == "succeeded"
    assert captured["settings"] == settings
    assert staging_writer.batches[0].accepted[0].source_id == "builder-news-001"


def test_managed_runtime_cycle_promotes_adapter_keys_from_ran_summaries() -> None:
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])
    official_adapter = _SuccessfulAdapter(
        "official.wra.water_level",
        family=SourceFamily.OFFICIAL,
        event_type=EventType.WATER_LEVEL,
        raw_ref="raw/official-demo/wra-water-level.json",
    )
    sample_adapter = _sample_adapter()

    result = run_managed_runtime_ingestion_cycle(
        {
            official_adapter.metadata.key: official_adapter,
            sample_adapter.metadata.key: sample_adapter,
        },
        settings=_settings("official.wra.water_level", "news.public_web.sample"),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        promote=True,
        job_key="test.runtime.managed",
    )

    assert result.status == "succeeded"
    assert [summary.adapter_key for summary in result.summaries] == [
        "official.wra.water_level",
        "news.public_web.sample",
    ]
    assert promotion_writer.requested_adapter_keys == (
        "official.wra.water_level",
        "news.public_web.sample",
    )
    parameters = run_writer.calls[0][2]
    assert parameters is not None
    assert parameters["enabled_adapter_keys"] == (
        "official.wra.water_level",
        "news.public_web.sample",
    )


def test_managed_runtime_cycle_noops_without_database_url_before_building_adapters() -> None:
    called = False

    def adapter_builder(settings: WorkerSettings) -> dict[str, SamplePublicWebNewsAdapter]:
        nonlocal called
        called = True
        raise AssertionError("adapter builder should not run without persistence")

    result = run_managed_runtime_ingestion_cycle(
        settings=_settings("news.public_web.sample"),
        adapter_builder=adapter_builder,
        promote=True,
    )

    assert result.status == "skipped"
    assert result.reason == "no_database_url"
    assert called is False


def test_managed_runtime_cycle_noops_without_adapters_when_writers_are_injected() -> None:
    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()

    result = run_managed_runtime_ingestion_cycle(
        settings=_settings("news.public_web.sample"),
        staging_writer=staging_writer,
        run_writer=run_writer,
    )

    assert result.status == "skipped"
    assert result.reason == "no_adapters"
    assert staging_writer.batches == []
    assert run_writer.calls == []


def _settings(*adapter_keys: str) -> WorkerSettings:
    return load_worker_settings(
        {
            "WORKER_ENABLED_ADAPTER_KEYS": ",".join(adapter_keys),
            "SOURCE_SAMPLE_DATA_ENABLED": "true",
            "FRESHNESS_MAX_AGE_SECONDS": "86400",
        }
    )


def _sample_adapter(
    *,
    source_id: str = "sample-news-001",
) -> SamplePublicWebNewsAdapter:
    return SamplePublicWebNewsAdapter(
        [
            {
                "id": source_id,
                "url": f"https://example.test/news/{source_id}",
                "title": "Street flooding reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": FETCHED_AT.isoformat(),
                "location_text": "Riverside District",
                "confidence": 0.72,
            }
        ],
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/news-public-web/sample.json",
    )


def _candidate() -> PromotionCandidate:
    return PromotionCandidate(
        staging_evidence_id="staging-id",
        raw_snapshot_id="raw-snapshot-id",
        raw_ref="raw/news-public-web/sample.json",
        data_source_id="data-source-id",
        source_id="sample-news-001",
        source_type="news",
        event_type="flood_report",
        title="Street flooding reported near riverside district",
        summary="Public report describes street flooding near the riverside district.",
        url="https://example.test/news/sample-news-001",
        occurred_at=FETCHED_AT,
        observed_at=FETCHED_AT,
        confidence=0.72,
        validation_status="accepted",
        payload={"adapter_key": "news.public_web.sample"},
    )


class _MemoryStagingWriter:
    def __init__(self) -> None:
        self.batches: list[AdapterStagingBatch] = []

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        self.batches.append(batch)


class _MemoryRunWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[AdapterBatchRunSummary, str, dict[str, Any] | None]] = []

    def write_summary(
        self,
        summary: AdapterBatchRunSummary,
        *,
        job_key: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append((summary, job_key, parameters))


class _MemoryPromotionWriter:
    def __init__(self, candidates: list[PromotionCandidate]) -> None:
        self._candidates = tuple(candidates)
        self.requested_limit: int | None = None
        self.requested_adapter_keys: tuple[str, ...] | None = None
        self.payloads: list[EvidencePromotionPayload] = []

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        self.requested_limit = limit
        self.requested_adapter_keys = adapter_keys
        return self._candidates

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        self.payloads.append(payload)
        return f"evidence-{len(self.payloads)}"


class _ExplodingAdapter:
    def __init__(self, key: str) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name=f"{key} test adapter",
        )

    def run(self) -> AdapterRunResult:
        raise AssertionError(f"{self.metadata.key} should not run")

    def fetch(self) -> tuple[RawSourceItem, ...]:
        raise AssertionError(f"{self.metadata.key} should not fetch")

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        raise AssertionError(f"{self.metadata.key} should not normalize")


class _SuccessfulAdapter:
    def __init__(
        self,
        key: str,
        *,
        family: SourceFamily,
        event_type: EventType,
        raw_ref: str,
    ) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=family,
            enabled_by_default=True,
            display_name=f"{key} test adapter",
        )
        self._event_type = event_type
        self._raw_ref = raw_ref

    def run(self) -> AdapterRunResult:
        raw_item = RawSourceItem(
            source_id=f"{self.metadata.key}:source",
            source_url=f"https://example.test/{self.metadata.key}",
            fetched_at=FETCHED_AT,
            payload={"title": self.metadata.display_name},
            raw_snapshot_key=self._raw_ref,
        )
        evidence = NormalizedEvidence(
            evidence_id=f"{self.metadata.key}:evidence",
            adapter_key=self.metadata.key,
            source_family=self.metadata.family,
            event_type=self._event_type,
            source_id=raw_item.source_id,
            source_url=raw_item.source_url,
            source_title=self.metadata.display_name,
            source_timestamp=FETCHED_AT,
            fetched_at=FETCHED_AT,
            summary=f"{self.metadata.display_name} summary",
            location_text=None,
            confidence=0.8,
            status=IngestionStatus.NORMALIZED,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw_item,),
            normalized=(evidence,),
            rejected=(),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]
