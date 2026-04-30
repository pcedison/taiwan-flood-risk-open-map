from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
)
from app.adapters.news import SamplePublicWebNewsAdapter
from app.config import load_worker_settings
from app.jobs.ingestion import run_adapter_batch, run_adapter_batches, run_enabled_adapter_batches
from app.pipelines.staging import AdapterStagingBatch


FETCHED_AT = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)


def test_run_adapter_batch_builds_and_persists_staging_batch() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "sample-news-001",
                "url": "https://example.test/news/flood-001",
                "title": "Street flooding reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": "2026-04-28T08:30:00+00:00",
                "location_text": "Riverside District",
                "confidence": 0.72,
            }
        ],
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/news-public-web/sample.json",
    )
    writer = _MemoryWriter()

    summary = run_adapter_batch(adapter, writer=writer)

    assert summary.adapter_key == "news.public_web.sample"
    assert summary.status == "succeeded"
    assert summary.items_fetched == 1
    assert summary.items_promoted == 1
    assert summary.items_rejected == 0
    assert summary.raw_ref == "raw/news-public-web/sample.json"
    assert len(writer.batches) == 1
    assert writer.batches[0].accepted[0].source_id == "sample-news-001"


def test_run_adapter_batch_marks_validation_rejections_as_partial() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "bad-confidence",
                "url": "https://example.test/news/bad-confidence",
                "title": "Bad confidence fixture",
                "summary": "Fixture keeps required fields but has invalid confidence.",
                "published_at": "2026-04-28T09:10:00+00:00",
                "confidence": 1.5,
            },
            {
                "id": "missing-summary",
                "url": "https://example.test/news/missing-summary",
                "title": "Missing summary fixture",
                "published_at": "2026-04-28T09:10:00+00:00",
            },
        ],
        fetched_at=FETCHED_AT,
    )

    summary = run_adapter_batch(adapter)

    assert summary.status == "partial"
    assert summary.items_fetched == 2
    assert summary.items_promoted == 0
    assert summary.items_rejected == 2


def test_run_adapter_batch_skips_empty_fetches() -> None:
    summary = run_adapter_batch(_EmptyAdapter())

    assert summary.status == "skipped"
    assert summary.items_fetched == 0
    assert summary.error_code == "empty_fetch"


def test_run_adapter_batch_reports_adapter_failure() -> None:
    summary = run_adapter_batch(_FailingAdapter())

    assert summary.status == "failed"
    assert summary.error_code == "RuntimeError"
    assert summary.error_message == "fetch failed"


def test_run_adapter_batch_reports_writer_failure_with_fetch_count() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "sample-news-001",
                "url": "https://example.test/news/flood-001",
                "title": "Street flooding reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": "2026-04-28T08:30:00+00:00",
                "confidence": 0.72,
            }
        ],
        fetched_at=FETCHED_AT,
    )

    summary = run_adapter_batch(adapter, writer=_FailingWriter())

    assert summary.status == "failed"
    assert summary.items_fetched == 1
    assert summary.items_promoted == 0
    assert summary.error_code == "RuntimeError"
    assert summary.error_message == "write failed"


def test_run_adapter_batches_runs_each_adapter() -> None:
    summaries = run_adapter_batches((_EmptyAdapter(), _FailingAdapter()))

    assert [summary.status for summary in summaries] == ["skipped", "failed"]


def test_run_enabled_adapter_batches_uses_configured_adapter_allowlist() -> None:
    first = _NamedEmptyAdapter("official.cwa.rainfall")
    second = _NamedEmptyAdapter("official.wra.water_level")
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.wra.water_level"}
    )
    run_writer = _MemoryRunWriter()

    summaries = run_enabled_adapter_batches(
        {
            first.metadata.key: first,
            second.metadata.key: second,
        },
        settings=settings,
        run_writer=run_writer,
    )

    assert [summary.adapter_key for summary in summaries] == ["official.wra.water_level"]
    assert run_writer.parameters == [
        {
            "enabled_adapter_keys": ("official.wra.water_level",),
            "available_adapter_keys": (
                "official.cwa.rainfall",
                "official.wra.water_level",
            ),
        }
    ]


class _MemoryWriter:
    def __init__(self) -> None:
        self.batches: list[AdapterStagingBatch] = []

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        self.batches.append(batch)


class _FailingWriter:
    def write_batch(self, batch: AdapterStagingBatch) -> None:
        raise RuntimeError("write failed")


class _EmptyAdapter:
    metadata = AdapterMetadata(
        key="test.empty",
        family=SourceFamily.DERIVED,
        enabled_by_default=False,
        display_name="Empty test adapter",
    )

    def run(self) -> AdapterRunResult:
        return AdapterRunResult(adapter_key=self.metadata.key, fetched=(), normalized=())

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return ()

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _FailingAdapter:
    metadata = AdapterMetadata(
        key="test.failing",
        family=SourceFamily.DERIVED,
        enabled_by_default=False,
        display_name="Failing test adapter",
    )

    def run(self) -> AdapterRunResult:
        raise RuntimeError("fetch failed")

    def fetch(self) -> tuple[RawSourceItem, ...]:
        raise RuntimeError("fetch failed")

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _NamedEmptyAdapter:
    def __init__(self, key: str) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name=f"{key} test adapter",
        )

    def run(self) -> AdapterRunResult:
        return AdapterRunResult(adapter_key=self.metadata.key, fetched=(), normalized=())

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return ()

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _MemoryRunWriter:
    def __init__(self) -> None:
        self.parameters: list[dict[str, object] | None] = []

    def write_summary(
        self,
        summary: object,
        *,
        job_key: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        del summary, job_key
        self.parameters.append(parameters)
