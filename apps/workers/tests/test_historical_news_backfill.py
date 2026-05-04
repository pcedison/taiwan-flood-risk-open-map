from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from app.jobs.historical_news_backfill import (
    HistoricalNewsBackfillConfig,
    build_historical_news_backfill_batch,
    run_historical_news_backfill_production_candidate,
    run_historical_news_backfill_rehearsal,
)
from app.jobs.ingestion import AdapterBatchRunSummary
from app.pipelines.promotion import EvidencePromotionPayload, PromotionCandidate
from app.pipelines.staging import AdapterStagingBatch


@pytest.mark.parametrize(
    (
        "gdelt_source_enabled",
        "gdelt_backfill_enabled",
        "source_news_enabled",
        "terms_ack",
        "message",
    ),
    [
        (False, False, False, False, "GDELT_SOURCE_ENABLED=true"),
        (True, False, False, False, "disabled by default"),
        (True, True, False, False, "SOURCE_NEWS_ENABLED=true"),
        (True, True, True, False, "SOURCE_TERMS_REVIEW_ACK=true"),
    ],
)
def test_historical_news_backfill_is_no_network_until_all_gates_pass(
    gdelt_source_enabled: bool,
    gdelt_backfill_enabled: bool,
    source_news_enabled: bool,
    terms_ack: bool,
    message: str,
) -> None:
    calls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"articles": []}

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台灣豪雨",),
        gdelt_source_enabled=gdelt_source_enabled,
        gdelt_backfill_enabled=gdelt_backfill_enabled,
        source_news_enabled=source_news_enabled,
        source_terms_review_ack=terms_ack,
        fetch_json=fetch_json,
    )

    with pytest.raises(RuntimeError, match=message):
        build_historical_news_backfill_batch(config)

    assert calls == []


@pytest.mark.parametrize(
    ("news_enabled", "terms_ack", "message"),
    [
        (False, True, "SOURCE_NEWS_ENABLED=true"),
        (True, False, "SOURCE_TERMS_REVIEW_ACK=true"),
    ],
)
def test_historical_news_backfill_requires_news_and_terms_gates(
    news_enabled: bool,
    terms_ack: bool,
    message: str,
) -> None:
    calls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"articles": []}

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台灣豪雨",),
        gdelt_source_enabled=True,
        gdelt_backfill_enabled=True,
        source_news_enabled=news_enabled,
        source_terms_review_ack=terms_ack,
        fetch_json=fetch_json,
    )

    with pytest.raises(RuntimeError, match=message):
        build_historical_news_backfill_batch(config)

    assert calls == []


def test_historical_news_backfill_uses_injected_fetcher_when_all_gates_pass() -> None:
    calls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "articles": [
                {
                    "url": "https://example.test/news/annnan-flood",
                    "title": "台南市安南區積淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                }
            ]
        }

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台南市安南區積淹水",),
        gdelt_source_enabled=True,
        gdelt_backfill_enabled=True,
        source_news_enabled=True,
        source_terms_review_ack=True,
        fetch_json=fetch_json,
    )

    batch = build_historical_news_backfill_batch(config)

    assert len(calls) == 1
    assert batch.adapter_key == "news.public_web.gdelt_backfill"
    assert len(batch.accepted) == 1
    assert batch.rejected == ()


def test_gdelt_rehearsal_staging_batch_contract_is_bounded_and_metadata_only() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "articles": [
                {
                    "url": f"https://example.test/news/{len(calls)}",
                    "title": "台南安南區長溪路二段淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "body": "must not be staged",
                }
            ]
        }

    config = HistoricalNewsBackfillConfig(
        start_datetime=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 8, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        queries=("台南淹水", "安南區豪雨"),
        max_records_per_query=7,
        request_cadence_seconds=30,
        gdelt_source_enabled=True,
        gdelt_backfill_enabled=True,
        source_news_enabled=True,
        source_terms_review_ack=True,
        fetch_json=fetch_json,
        sleep=sleeps.append,
    )

    result = run_historical_news_backfill_rehearsal(config, mode="staging-batch")

    assert len(calls) == 2
    assert "maxrecords=7" in calls[0]
    assert sleeps == [30.0]
    assert result.batch is not None
    assert result.batch.adapter_key == "news.public_web.gdelt_backfill"
    assert len(result.batch.accepted) == 2
    assert result.metadata["metadata_only"] is True
    assert result.metadata["rate_limit_contract"] == "one bounded GDELT DOC request per query"
    assert result.metadata["cadence_seconds"] == 30
    assert result.metadata["max_records_per_query"] == 7
    assert result.batch.raw_snapshot.metadata["items_fetched"] == 2


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({}, "GDELT_PRODUCTION_INGESTION_ENABLED=true"),
        (
            {"gdelt_production_ingestion_enabled": True, "production_persist_intent": False},
            "--persist",
        ),
        (
            {"gdelt_production_ingestion_enabled": True, "production_database_url": None},
            "database-url",
        ),
        (
            {
                "gdelt_production_ingestion_enabled": True,
            },
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK=true",
        ),
        (
            {
                "gdelt_production_ingestion_enabled": True,
                "gdelt_production_approval_evidence_path": None,
            },
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH",
        ),
        (
            {
                "gdelt_production_ingestion_enabled": True,
                "gdelt_production_approval_evidence_path": None,
                "gdelt_production_approval_evidence_ack": True,
            },
            "ACK cannot replace concrete evidence",
        ),
    ],
)
def test_gdelt_production_candidate_gates_prevent_network_before_fetch(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    calls: list[str] = []
    approval_path = tmp_path / "gdelt-approval.md"
    approval_path.write_text("external approval evidence placeholder", encoding="utf-8")

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {"articles": []}

    config = _production_candidate_config(
        approval_path=approval_path,
        fetch_json=fetch_json,
        **overrides,
    )

    with pytest.raises(RuntimeError, match=message):
        run_historical_news_backfill_production_candidate(
            config,
            staging_writer=_MemoryStagingWriter(),
            run_writer=_MemoryRunWriter(),
            promotion_writer=_MemoryPromotionWriter([]),
        )

    assert calls == []


def test_gdelt_production_candidate_persists_run_and_promotes_with_injected_fetcher(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    approval_path = tmp_path / "gdelt-approval.md"
    approval_path.write_text("external approval evidence placeholder", encoding="utf-8")

    def fetch_json(url: str) -> dict[str, object]:
        calls.append(url)
        return {
            "articles": [
                {
                    "url": "https://example.test/news/production-candidate-flood",
                    "title": "台南安南區長溪路二段淹水",
                    "seendate": "20250802T012800Z",
                    "domain": "example.test",
                    "sourcecountry": "TW",
                    "body": "must not be staged",
                }
            ]
        }

    staging_writer = _MemoryStagingWriter()
    run_writer = _MemoryRunWriter()
    promotion_writer = _MemoryPromotionWriter([_candidate()])

    result = run_historical_news_backfill_production_candidate(
        _production_candidate_config(
            approval_path=approval_path,
            fetch_json=fetch_json,
            gdelt_production_ingestion_enabled=True,
            gdelt_production_approval_evidence_ack=True,
        ),
        staging_writer=staging_writer,
        run_writer=run_writer,
        promotion_writer=promotion_writer,
        job_key="test.gdelt.production_candidate",
    )

    assert len(calls) == 1
    assert result.status == "succeeded"
    assert result.promoted == 1
    assert result.evidence_ids == ("evidence-1",)
    assert len(staging_writer.batches) == 1
    assert staging_writer.batches[0].adapter_key == "news.public_web.gdelt_backfill"
    assert staging_writer.batches[0].raw_snapshot.metadata["items_fetched"] == 1
    assert staging_writer.batches[0].accepted[0].payload["tags"] == [
        "flood-history",
        "public-news",
        "backfill",
    ]
    assert run_writer.calls[0][1] == "test.gdelt.production_candidate"
    assert run_writer.calls[0][2] is not None
    assert run_writer.calls[0][2]["mode"] == "production-candidate"
    assert run_writer.calls[0][2]["network_allowed"] is True
    assert promotion_writer.requested_limit == 1
    assert promotion_writer.requested_adapter_keys == ("news.public_web.gdelt_backfill",)
    payload = result.as_payload()
    assert payload["mode"] == "production-candidate"
    assert payload["metadata"]["production_candidate"] is True
    assert payload["metadata"]["network_allowed"] is True
    assert payload["metadata"]["approval_evidence_path"] == str(approval_path)
    assert payload["metadata"]["approval_evidence_ack"] is True
    assert payload["run"]["accepted_count"] == 1


def _production_candidate_config(
    *,
    approval_path: Path,
    fetch_json: Any,
    **overrides: object,
) -> HistoricalNewsBackfillConfig:
    values: dict[str, object] = {
        "start_datetime": datetime(2025, 8, 1, tzinfo=timezone.utc),
        "end_datetime": datetime(2025, 8, 5, tzinfo=timezone.utc),
        "fetched_at": datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc),
        "queries": ("台南淹水",),
        "max_records_per_query": 7,
        "request_cadence_seconds": 30,
        "gdelt_source_enabled": True,
        "gdelt_backfill_enabled": True,
        "source_news_enabled": True,
        "source_terms_review_ack": True,
        "gdelt_production_ingestion_enabled": False,
        "gdelt_production_approval_evidence_path": str(approval_path),
        "gdelt_production_approval_evidence_ack": False,
        "production_persist_intent": True,
        "production_database_url": "postgresql://worker:test@localhost/flood",
        "fetch_json": fetch_json,
    }
    values.update(overrides)
    return HistoricalNewsBackfillConfig(**cast(Any, values))


def _candidate() -> PromotionCandidate:
    occurred_at = datetime(2025, 8, 2, 1, 28, tzinfo=timezone.utc)
    observed_at = datetime(2026, 4, 29, 8, 0, tzinfo=timezone.utc)
    return PromotionCandidate(
        staging_evidence_id="staging-id",
        raw_snapshot_id="raw-snapshot-id",
        raw_ref="raw/news/public_web/gdelt_backfill/test.json",
        data_source_id="data-source-id",
        source_id="gdelt_source",
        source_type="news",
        event_type="flood_report",
        title="台南安南區長溪路二段淹水",
        summary="Public news title mentions a flood-related event.",
        url="https://example.test/news/production-candidate-flood",
        occurred_at=occurred_at,
        observed_at=observed_at,
        confidence=0.72,
        validation_status="accepted",
        payload={"adapter_key": "news.public_web.gdelt_backfill"},
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
