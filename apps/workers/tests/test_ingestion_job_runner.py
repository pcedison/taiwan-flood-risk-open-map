from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.contracts import (
    AdapterMetadata,
    AdapterRunResult,
    EventType,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
    SourceRejection,
    StationInventoryProof,
)
from app.adapters.news import SamplePublicWebNewsAdapter
from app.config import load_worker_settings
from app.jobs.ingestion import run_adapter_batch, run_adapter_batches, run_enabled_adapter_batches
from app.pipelines.staging import AdapterStagingBatch

FETCHED_AT = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)


def test_task9_result_and_summary_fields_have_backward_compatible_defaults() -> None:
    result = AdapterRunResult(
        adapter_key="test.defaults",
        fetched=(),
        normalized=(),
    )
    summary = run_adapter_batch(_EmptyAdapter())

    assert result.no_active_event is False
    assert summary.event_active_from_min is None
    assert summary.event_active_until_max is None


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


def test_complete_replace_summary_allows_reviewed_source_quality_partial_at_floor() -> None:
    writer = _MemoryWriter()

    summary = run_adapter_batch(
        _CompleteReplaceAdapter(valid_count=3, source_rejection_count=1),
        writer=writer,
    )

    assert summary.status == "partial"
    assert summary.items_fetched == 4
    assert summary.items_promoted == 3
    assert summary.items_rejected == 1
    assert summary.snapshot_generation_mode == "complete_replace"
    assert summary.snapshot_activation_eligible is True
    assert writer.batches[0].accepted[0].payload["snapshot_generation_mode"] == (
        "complete_replace"
    )


@pytest.mark.parametrize(
    ("valid_count", "source_rejection_count", "staging_rejection_count"),
    ((2, 1, 0), (1, 0, 1)),
)
def test_complete_replace_summary_rejects_low_fraction_or_staging_rejection(
    valid_count: int,
    source_rejection_count: int,
    staging_rejection_count: int,
) -> None:
    summary = run_adapter_batch(
        _CompleteReplaceAdapter(
            valid_count=valid_count,
            source_rejection_count=source_rejection_count,
            staging_rejection_count=staging_rejection_count,
        )
    )

    assert summary.snapshot_generation_mode == "complete_replace"
    assert summary.snapshot_activation_eligible is False


def test_ordinary_summary_has_no_snapshot_generation_lifecycle() -> None:
    summary = run_adapter_batch(_CompleteReplaceAdapter(valid_count=1, mode=None))

    assert summary.snapshot_generation_mode is None
    assert summary.snapshot_activation_eligible is False


def test_managed_generation_replaces_forged_adapter_generation(monkeypatch) -> None:
    started_at = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 24, 1, 0, 1, tzinfo=UTC)
    instants = iter((started_at, finished_at))
    monkeypatch.setattr("app.jobs.ingestion._now", lambda: next(instants))
    writer = _MemoryWriter()

    summary = run_adapter_batch(_ForgedGenerationAdapter(), writer=writer)

    assert summary.started_at == started_at
    assert (
        writer.batches[0].accepted[0].payload["ingestion_generation_started_at"]
        == started_at.isoformat()
    )


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


def test_run_adapter_batch_marks_source_specific_rejection_as_partial() -> None:
    summary = run_adapter_batch(_SourceSpecificRejectionAdapter())

    assert summary.status == "partial"
    assert summary.items_fetched == 1
    assert summary.items_promoted == 0
    assert summary.items_rejected == 1
    assert summary.error_code is None


def test_ncdr_dump_fetch_rejection_is_partial_not_healthy_empty() -> None:
    raw = RawSourceItem(
        source_id="ncdr-transport:0123456789abcdef01234567",
        source_url="https://alerts.ncdr.nat.gov.tw/api/dump/datastore",
        fetched_at=FETCHED_AT,
        payload={"transport_capid": "CAP-001", "error": "NCDR CAP dump fetch failed"},
    )
    result = AdapterRunResult(
        adapter_key="official.ncdr.cap",
        fetched=(raw,),
        normalized=(),
        rejected=(raw.source_id,),
        source_rejections=(SourceRejection(raw.source_id, "ncdr_dump_fetch_failed"),),
    )

    summary = run_adapter_batch(_StaticResultAdapter(result))

    assert summary.status == "partial"
    assert summary.error_code is None
    assert summary.items_fetched == 1
    assert summary.items_rejected == 1


def test_run_adapter_batch_skips_empty_fetches() -> None:
    summary = run_adapter_batch(_EmptyAdapter())

    assert summary.status == "skipped"
    assert summary.items_fetched == 0
    assert summary.error_code == "empty_fetch"


@pytest.mark.parametrize(
    "adapter_key",
    (
        "official.cwa.heavy_rain_warning",
        "official.ncdr.cap",
        "official.wra.flood_warning",
    ),
)
def test_valid_empty_warning_poll_is_success_not_skipped(adapter_key: str) -> None:
    writer = _MemoryWriter()

    summary = run_adapter_batch(
        _NamedEmptyAdapter(adapter_key, no_active_event=True),
        writer=writer,
    )

    assert summary.status == "succeeded"
    assert summary.items_fetched == 0
    assert summary.error_code == "no_active_event"
    assert summary.source_timestamp_max is None
    assert writer.batches == []


@pytest.mark.parametrize(
    "adapter_key",
    (
        "official.cwa.heavy_rain_warning",
        "official.ncdr.cap",
        "official.wra.flood_warning",
    ),
)
def test_plain_or_rejected_empty_warning_is_not_no_active_event(
    adapter_key: str,
) -> None:
    plain = run_adapter_batch(_NamedEmptyAdapter(adapter_key))
    rejected = run_adapter_batch(
        _NamedEmptyAdapter(
            adapter_key,
            no_active_event=True,
            rejected=("malformed-cap",),
        )
    )

    assert plain.status == "skipped"
    assert plain.error_code == "empty_fetch"
    assert rejected.status != "succeeded"
    assert rejected.error_code != "no_active_event"


def test_wra_warning_context_is_valid_empty_but_never_retires_latest() -> None:
    from app.jobs.ingestion import (
        VALID_EMPTY_WARNING_ADAPTER_KEYS,
        WARNING_EVENT_ADAPTER_KEYS,
    )
    from app.pipelines.promotion import (
        REVIEWED_WARNING_ADAPTER_KEYS,
        PostgresEvidencePromotionWriter,
    )

    assert "official.wra.flood_warning" in VALID_EMPTY_WARNING_ADAPTER_KEYS
    assert "official.wra.flood_warning" not in WARNING_EVENT_ADAPTER_KEYS
    assert "official.wra.flood_warning" not in REVIEWED_WARNING_ADAPTER_KEYS

    writer = PostgresEvidencePromotionWriter(connection_factory=_unreachable_connection)
    with pytest.raises(ValueError):
        writer.retire_warning_latest_for_no_active_event(
            adapter_key="official.wra.flood_warning",
            generation_started_at=datetime(2026, 8, 26, 2, 0, tzinfo=UTC),
            completed_at=datetime(2026, 8, 26, 2, 1, tzinfo=UTC),
        )


def _unreachable_connection() -> object:  # pragma: no cover - must never be called
    raise AssertionError("no database connection may be opened")


def test_station_empty_result_cannot_use_no_active_event_branch() -> None:
    summary = run_adapter_batch(
        _NamedEmptyAdapter("official.cwa.rainfall", no_active_event=True)
    )

    assert summary.status == "skipped"
    assert summary.error_code == "empty_fetch"


def test_complete_nonempty_station_collection_without_observations_fails_precisely() -> None:
    proof = StationInventoryProof(
        upstream_total=2,
        pages_fetched=1,
        pagination_complete=True,
        source_items_seen=2,
        missing_station_id_count=0,
        duplicate_station_id_count=1,
        station_ids=("station-1",),
    )
    result = AdapterRunResult(
        adapter_key="official.civil_iot.flood_sensor",
        fetched=(),
        normalized=(),
        station_inventory_proof=proof,
    )

    summary = run_adapter_batch(_StaticResultAdapter(result))

    assert summary.status == "failed"
    assert summary.error_code == "upstream_observations_empty"
    assert summary.station_inventory_proof is proof
    assert summary.station_inventory_proof.inventory_complete is False


def test_adapter_result_key_mismatch_fails_under_trusted_configured_key() -> None:
    summary = run_adapter_batch(_MismatchedResultKeyAdapter())

    assert summary.adapter_key == "official.cwa.heavy_rain_warning"
    assert summary.status == "failed"
    assert summary.error_code == "ValueError"
    assert summary.error_message is not None
    assert "adapter result key mismatch" in summary.error_message


def test_nonempty_normalized_warning_result_is_not_no_active_event() -> None:
    summary = run_adapter_batch(_MalformedNoActiveWarningAdapter())

    assert summary.adapter_key == "official.cwa.heavy_rain_warning"
    assert summary.status != "succeeded"
    assert summary.error_code != "no_active_event"


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
    assert run_writer.runtime_selections[0][0] == ("official.wra.water_level",)


def test_run_enabled_adapter_batches_marks_enabled_but_missing_adapter_as_failed() -> None:
    settings = load_worker_settings(
        {"WORKER_ENABLED_ADAPTER_KEYS": "official.wra.water_level"}
    )
    run_writer = _MemoryRunWriter()

    summaries = run_enabled_adapter_batches({}, settings=settings, run_writer=run_writer)

    assert summaries == ()
    assert run_writer.runtime_selections[0][0] == ("official.wra.water_level",)
    assert len(run_writer.pipeline_statuses) == 1
    adapter_keys, status, complete, run_at = run_writer.pipeline_statuses[0]
    assert adapter_keys == ("official.wra.water_level",)
    assert status == "failed"
    assert complete is False
    assert isinstance(run_at, datetime)


class _MemoryWriter:
    def __init__(self) -> None:
        self.batches: list[AdapterStagingBatch] = []

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        self.batches.append(batch)


class _FailingWriter:
    def write_batch(self, batch: AdapterStagingBatch) -> None:
        raise RuntimeError("write failed")


class _SourceSpecificRejectionAdapter:
    metadata = AdapterMetadata(
        key="official.cwa.heavy_rain_warning",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Source-specific rejection test adapter",
    )

    def run(self) -> AdapterRunResult:
        raw = RawSourceItem(
            source_id="cap:unreviewed-town",
            source_url="https://example.test/cap",
            fetched_at=FETCHED_AT,
            payload={"admin_code": "67037000", "areaDesc": "安南區"},
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw,),
            normalized=(),
            rejected=(raw.source_id,),
            source_rejections=(
                SourceRejection(raw.source_id, "cwa_unreviewed_admin_geometry"),
            ),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _CompleteReplaceAdapter:
    def __init__(
        self,
        *,
        valid_count: int,
        source_rejection_count: int = 0,
        staging_rejection_count: int = 0,
        mode: str | None = "complete_replace",
    ) -> None:
        self.metadata = AdapterMetadata(
            key="official.test.complete_replace",
            family=SourceFamily.OFFICIAL,
            enabled_by_default=False,
            display_name="Complete-replace fixture",
            snapshot_generation_mode=mode,
        )
        self.valid_count = valid_count
        self.source_rejection_count = source_rejection_count
        self.staging_rejection_count = staging_rejection_count

    def run(self) -> AdapterRunResult:
        normalized_count = self.valid_count + self.staging_rejection_count
        fetched_count = normalized_count + self.source_rejection_count
        fetched = tuple(
            RawSourceItem(
                source_id=f"history-{index}",
                source_url=f"https://example.test/history/{index}",
                fetched_at=FETCHED_AT,
                payload={"dataset_revision": "revision-a"},
            )
            for index in range(fetched_count)
        )
        normalized = tuple(
            NormalizedEvidence(
                evidence_id=f"ev-history-{index}",
                adapter_key=self.metadata.key,
                source_family=SourceFamily.OFFICIAL,
                event_type=EventType.FLOOD_REPORT,
                source_id=fetched[index].source_id,
                source_url=fetched[index].source_url,
                source_title="Historical fixture",
                source_timestamp=FETCHED_AT,
                fetched_at=FETCHED_AT,
                summary="Complete-replace activation eligibility fixture.",
                location_text="臺南市",
                confidence=(0.9 if index < self.valid_count else 1.5),
            )
            for index in range(normalized_count)
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=fetched,
            normalized=normalized,
            rejected=tuple(
                fetched[index].source_id
                for index in range(normalized_count, fetched_count)
            ),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        return next(
            (
                evidence
                for evidence in self.run().normalized
                if evidence.source_id == raw_item.source_id
            ),
            None,
        )


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
    def __init__(
        self,
        key: str,
        *,
        no_active_event: bool = False,
        rejected: tuple[str, ...] = (),
    ) -> None:
        self.metadata = AdapterMetadata(
            key=key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=True,
            display_name=f"{key} test adapter",
        )
        self.no_active_event = no_active_event
        self.rejected = rejected

    def run(self) -> AdapterRunResult:
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(),
            normalized=(),
            rejected=self.rejected,
            no_active_event=self.no_active_event,
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return ()

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _StaticResultAdapter:
    def __init__(self, result: AdapterRunResult) -> None:
        self._result = result
        self.metadata = AdapterMetadata(
            key=result.adapter_key,
            family=SourceFamily.OFFICIAL,
            enabled_by_default=False,
            display_name="Static adapter result fixture",
        )

    def run(self) -> AdapterRunResult:
        return self._result

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self._result.fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return None


class _ForgedGenerationAdapter:
    metadata = AdapterMetadata(
        key="official.test.generation",
        family=SourceFamily.OFFICIAL,
        enabled_by_default=False,
        display_name="Generation ownership fixture",
    )

    def run(self) -> AdapterRunResult:
        raw = RawSourceItem(
            source_id="generation-1",
            source_url="https://example.test/generation",
            fetched_at=FETCHED_AT,
            payload={
                "ingestion_generation_started_at": "1999-01-01T00:00:00+00:00"
            },
        )
        normalized = NormalizedEvidence(
            evidence_id="ev-generation-1",
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_REPORT,
            source_id=raw.source_id,
            source_url=raw.source_url,
            source_title="Generation fixture",
            source_timestamp=FETCHED_AT,
            fetched_at=FETCHED_AT,
            summary="Managed worker owns the ingestion generation.",
            location_text=None,
            confidence=0.9,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(raw,),
            normalized=(normalized,),
        )

    def fetch(self) -> tuple[RawSourceItem, ...]:
        return self.run().fetched

    def normalize(self, raw_item: RawSourceItem) -> NormalizedEvidence | None:
        del raw_item
        return self.run().normalized[0]


class _MismatchedResultKeyAdapter(_NamedEmptyAdapter):
    def __init__(self) -> None:
        super().__init__("official.cwa.heavy_rain_warning", no_active_event=True)

    def run(self) -> AdapterRunResult:
        return AdapterRunResult(
            adapter_key="official.ncdr.cap",
            fetched=(),
            normalized=(),
            no_active_event=True,
        )


class _MalformedNoActiveWarningAdapter(_NamedEmptyAdapter):
    def __init__(self) -> None:
        super().__init__("official.cwa.heavy_rain_warning", no_active_event=True)

    def run(self) -> AdapterRunResult:
        normalized = NormalizedEvidence(
            evidence_id="malformed-no-active",
            adapter_key=self.metadata.key,
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_WARNING,
            source_id="malformed-no-active",
            source_url="https://example.test/cap",
            source_title="Malformed no-active result",
            source_timestamp=FETCHED_AT,
            fetched_at=FETCHED_AT,
            summary="A nonempty normalized row cannot prove an empty warning poll.",
            location_text="臺南市",
            confidence=0.95,
        )
        return AdapterRunResult(
            adapter_key=self.metadata.key,
            fetched=(),
            normalized=(normalized,),
            no_active_event=True,
        )


class _MemoryRunWriter:
    def __init__(self) -> None:
        self.parameters: list[dict[str, object] | None] = []
        self.runtime_selections: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.pipeline_statuses: list[
            tuple[tuple[str, ...], str, bool, datetime | None]
        ] = []

    def write_summary(
        self,
        summary: object,
        *,
        job_key: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        del summary, job_key
        self.parameters.append(parameters)

    def write_runtime_selection(
        self,
        *,
        enabled_adapter_keys: tuple[str, ...],
        known_adapter_keys: tuple[str, ...],
        checked_at: datetime,
    ) -> None:
        del checked_at
        self.runtime_selections.append((enabled_adapter_keys, known_adapter_keys))

    def write_pipeline_status(
        self,
        *,
        adapter_keys: tuple[str, ...],
        status: str,
        complete: bool,
        checked_at: datetime,
        run_at: datetime | None,
    ) -> None:
        del checked_at
        self.pipeline_statuses.append((adapter_keys, status, complete, run_at))
