from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.news import SamplePublicWebNewsAdapter
from app.pipelines.staging import AdapterStagingBatch, build_staging_batch, persist_staging_batch


FETCHED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)


def test_build_staging_batch_maps_adapter_result_to_raw_snapshot_and_accepted_rows() -> None:
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "sample-news-001",
                "url": "https://example.test/news/flood-001",
                "title": "Heavy rain reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": "2026-04-28T08:30:00+00:00",
                "location_text": "Riverside District",
                "confidence": 0.72,
                "attribution": "Example Public News",
                "tags": ["rain", "street-flooding"],
            }
        ],
        fetched_at=FETCHED_AT,
        raw_snapshot_key="raw/news-public-web/sample.json",
    )

    batch = build_staging_batch(adapter.run())

    assert batch.adapter_key == "news.public_web.sample"
    assert batch.raw_snapshot.raw_ref == "raw/news-public-web/sample.json"
    assert batch.raw_snapshot.content_hash
    assert batch.raw_snapshot.retention_expires_at > FETCHED_AT
    assert batch.raw_snapshot.metadata["items_fetched"] == 1
    assert len(batch.accepted) == 1
    assert batch.rejected == ()

    staged = batch.accepted[0]
    assert staged.source_type == "news"
    assert staged.event_type == "flood_report"
    assert staged.validation_status == "accepted"
    assert staged.payload["location_text"] == "Riverside District"


def test_build_staging_batch_keeps_validation_rejections_separate_from_raw_rejections() -> None:
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
        raw_snapshot_key="raw/news-public-web/rejected.json",
    )

    batch = build_staging_batch(adapter.run())

    assert batch.accepted == ()
    assert len(batch.rejected) == 1
    assert batch.rejected[0].validation_status == "rejected"
    assert batch.rejected[0].rejection_reason == "confidence must be between 0.0 and 1.0"
    assert batch.rejected_raw_source_ids == ("missing-summary",)


def test_persist_staging_batch_uses_writer_protocol() -> None:
    writer = _MemoryWriter()
    adapter = SamplePublicWebNewsAdapter(
        [
            {
                "id": "sample-news-001",
                "url": "https://example.test/news/flood-001",
                "title": "Heavy rain reported near riverside district",
                "summary": "Public report describes street flooding near the riverside district.",
                "published_at": "2026-04-28T08:30:00+00:00",
                "confidence": 0.72,
            }
        ],
        fetched_at=FETCHED_AT,
    )
    batch = build_staging_batch(adapter.run())

    persist_staging_batch(batch, writer)

    assert writer.batches == [batch]


class _MemoryWriter:
    def __init__(self) -> None:
        self.batches: list[AdapterStagingBatch] = []

    def write_batch(self, batch: AdapterStagingBatch) -> None:
        self.batches.append(batch)
