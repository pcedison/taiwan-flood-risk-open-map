from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.cap_identity import cap_source_id
from app.adapters.civil_iot.flood_sensor import FloodSensorAdapter
from app.adapters.contracts import (
    AdapterRunResult,
    EventType,
    NormalizedEvidence,
    RawSourceItem,
    SourceFamily,
    SourceRejection,
)
from app.adapters.ncdr import NcdrCapAlertAdapter
from app.adapters.news import SamplePublicWebNewsAdapter
from app.pipelines.promotion import (
    EvidencePromotionPayload,
    PromotionCandidate,
    promote_accepted_staging,
)
from app.pipelines.staging import AdapterStagingBatch, build_staging_batch, persist_staging_batch

FETCHED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


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


def test_complete_replace_snapshot_uses_full_content_stable_worker_owned_raw_ref() -> None:
    first = build_staging_batch(
        _complete_replace_result(
            fetched_at=FETCHED_AT,
            raw_snapshot_key="raw/adapter-controlled/a.json",
            dataset_revision="revision-a",
        ),
        raw_ref="raw/caller-controlled/mutable.json",
        snapshot_generation_mode="complete_replace",
    )
    identical = build_staging_batch(
        _complete_replace_result(
            fetched_at=datetime(2026, 4, 29, 10, 0, tzinfo=UTC),
            raw_snapshot_key="raw/adapter-controlled/b.json",
            dataset_revision="revision-a",
        ),
        snapshot_generation_mode="complete_replace",
    )
    changed = build_staging_batch(
        _complete_replace_result(
            fetched_at=FETCHED_AT,
            raw_snapshot_key="raw/adapter-controlled/a.json",
            dataset_revision="revision-b",
        ),
        snapshot_generation_mode="complete_replace",
    )

    assert first.raw_snapshot.raw_ref == identical.raw_snapshot.raw_ref
    assert first.raw_snapshot.raw_ref != changed.raw_snapshot.raw_ref
    assert first.raw_snapshot.raw_ref == (
        f"raw/official/test/history/{first.raw_snapshot.content_hash}.json"
    )
    assert len(first.raw_snapshot.content_hash) == 64
    assert first.accepted[0].payload["snapshot_generation_mode"] == "complete_replace"
    assert first.raw_snapshot.metadata["snapshot_generation_mode"] == "complete_replace"


def test_ordinary_snapshot_keeps_existing_adapter_raw_ref_contract() -> None:
    batch = build_staging_batch(
        _complete_replace_result(
            fetched_at=FETCHED_AT,
            raw_snapshot_key="raw/adapter-controlled/a.json",
            dataset_revision="revision-a",
        )
    )

    assert batch.raw_snapshot.raw_ref == "raw/adapter-controlled/a.json"
    assert "snapshot_generation_mode" not in batch.accepted[0].payload


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


def test_source_rejection_is_audited_without_staging_evidence() -> None:
    raw = RawSourceItem(
        source_id="cap:unreviewed-town",
        source_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
        payload={"admin_code": "67037000", "areaDesc": "安南區"},
    )
    result = AdapterRunResult(
        adapter_key="official.cwa.heavy_rain_warning",
        fetched=(raw,),
        normalized=(),
        rejected=(raw.source_id,),
        source_rejections=(
            SourceRejection(raw.source_id, "cwa_unreviewed_admin_geometry"),
        ),
    )

    batch = build_staging_batch(result)

    assert batch.accepted == ()
    assert batch.rejected == ()
    assert batch.rejected_raw_source_ids == (raw.source_id,)
    assert batch.raw_snapshot.metadata["source_rejections"] == [
        {
            "source_id": "cap:unreviewed-town",
            "reason_code": "cwa_unreviewed_admin_geometry",
        }
    ]
    assert batch.raw_snapshot.metadata["source_rejection_count"] == 1


def test_build_staging_batch_uses_source_timestamp_as_observed_at() -> None:
    source_ts = datetime(2026, 6, 27, 10, 0, tzinfo=UTC)
    fetched_at = datetime(2026, 6, 27, 10, 5, tzinfo=UTC)
    adapter = FloodSensorAdapter(
        (
            {
                "station_id": "FS-001",
                "station_name": "淹水感測器",
                "observed_at": source_ts.isoformat(),
                "value": 12.0,
                "source_url": "https://example.test/official/civil-iot/flood-sensor",
                "authority": "水利署",
                "county": "臺南市",
                "town": "仁德區",
                "county_code": "67000",
                "area_code": "67000270",
                "datastream_name": "淹水深度",
            },
        ),
        fetched_at=fetched_at,
    )

    batch = build_staging_batch(adapter.run())

    assert batch.accepted[0].observed_at == source_ts
    assert batch.accepted[0].occurred_at == source_ts
    assert batch.raw_snapshot.fetched_at == fetched_at
    assert batch.accepted[0].payload["flood_depth_cm"] == 12.0
    assert batch.accepted[0].payload["station_id"] == "FS-001"
    assert batch.accepted[0].payload["station_name"] == "淹水感測器"
    assert batch.accepted[0].payload["authority"] == "水利署"
    assert batch.accepted[0].payload["county"] == "臺南市"
    assert batch.accepted[0].payload["town"] == "仁德區"
    assert batch.accepted[0].payload["county_code"] == "67000"
    assert batch.accepted[0].payload["area_code"] == "67000270"


def test_ncdr_unreviewed_admin_geometry_never_enters_accepted_staging() -> None:
    cap_xml = """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
      <identifier>NCDR-CAP-001</identifier><sender>ncdr@example.test</sender>
      <sent>2026-06-15T10:30:00+08:00</sent><status>Actual</status>
      <msgType>Alert</msgType><scope>Public</scope><info><event>淹水警戒</event>
      <effective>2026-06-15T10:30:00+08:00</effective>
      <expires>2026-06-15T15:00:00+08:00</expires><area><areaDesc>臺南市</areaDesc>
      <geocode><valueName>TOWNCODE</valueName><value>67000</value></geocode>
      </area></info></alert>"""
    adapter = NcdrCapAlertAdapter(
        api_key="test-secret",
        fetched_at=datetime(2026, 6, 15, 3, 10, tzinfo=UTC),
        fetch_json=lambda _url, _params, _timeout: {"data": [{"capid": "CAP-001"}]},
        fetch_text=lambda _url, _params, _timeout: cap_xml,
    )

    batch = build_staging_batch(adapter.run())

    assert batch.accepted == ()
    assert batch.rejected == ()
    assert len(batch.rejected_raw_source_ids) == 1
    assert batch.raw_snapshot.metadata["source_rejections"][0]["reason_code"] == (
        "ncdr_unreviewed_admin_geometry"
    )


def test_build_staging_batch_preserves_only_reviewed_metadata_fields() -> None:
    raw = RawSourceItem(
        source_id="reviewed-1",
        source_url="https://example.test/source",
        fetched_at=FETCHED_AT,
        payload={
            "evidence_scope": "historical",
            "location_precision": "polygon",
            "limitations": [" Public limitation ", "Public limitation"],
            "admin_code": "67000000",
            "dataset_revision": " 2026-08-v1 ",
            "geometry": {
                "type": "Point",
                "coordinates": [120.2, 22.99],
            },
            "private_note": "never publish",
            "quality_flags": {"internal_probe": "never publish"},
        },
    )
    normalized = NormalizedEvidence(
        evidence_id="ev-reviewed-1",
        adapter_key="official.test.history",
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw.source_id,
        source_url=raw.source_url,
        source_title="Reviewed metadata",
        source_timestamp=FETCHED_AT,
        fetched_at=FETCHED_AT,
        summary="Reviewed metadata staging contract.",
        location_text="臺南市",
        confidence=0.9,
    )

    staged = build_staging_batch(
        AdapterRunResult(
            adapter_key=normalized.adapter_key,
            fetched=(raw,),
            normalized=(normalized,),
        )
    ).accepted[0]

    assert staged.payload["evidence_scope"] == "historical"
    assert staged.payload["location_precision"] == "polygon"
    assert staged.payload["limitations"] == ["Public limitation"]
    assert staged.payload["admin_code"] == "67000000"
    assert staged.payload["dataset_revision"] == "2026-08-v1"
    assert staged.payload["location_payload"]["geometry"] == raw.payload["geometry"]
    assert "private_note" not in staged.payload
    assert "quality_flags" not in staged.payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_scope", "unspecified"),
        ("location_precision", "exact_address"),
        ("admin_code", "67000"),
        ("admin_code", 67000000),
        ("admin_code", "６７００００００"),
        ("limitations", [f"limitation-{index}" for index in range(17)]),
        ("limitations", ["x" * 257]),
        ("dataset_revision", "x" * 257),
    ],
)
def test_build_staging_batch_rejects_invalid_reviewed_metadata(
    field: str, value: object
) -> None:
    raw = RawSourceItem(
        source_id="invalid-metadata",
        source_url="https://example.test/source",
        fetched_at=FETCHED_AT,
        payload={field: value},
    )
    normalized = NormalizedEvidence(
        evidence_id="ev-invalid-metadata",
        adapter_key="official.test.history",
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw.source_id,
        source_url=raw.source_url,
        source_title="Invalid metadata",
        source_timestamp=FETCHED_AT,
        fetched_at=FETCHED_AT,
        summary="Invalid metadata staging contract.",
        location_text=None,
        confidence=0.9,
    )

    batch = build_staging_batch(
        AdapterRunResult(
            adapter_key=normalized.adapter_key,
            fetched=(raw,),
            normalized=(normalized,),
        )
    )

    assert batch.accepted == ()
    assert batch.rejected[0].validation_status == "rejected"
    assert "invalid staging metadata" in (batch.rejected[0].rejection_reason or "")


def test_orphan_normalized_evidence_without_matching_raw_item_fails_closed() -> None:
    raw = RawSourceItem(
        source_id="raw-a",
        source_url="https://example.test/source",
        fetched_at=FETCHED_AT,
        payload={"evidence_scope": "context"},
    )
    normalized = NormalizedEvidence(
        evidence_id="ev-orphan-b",
        adapter_key="official.test.context",
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_REPORT,
        source_id="orphan-b",
        source_url=raw.source_url,
        source_title="Orphan normalized row",
        source_timestamp=FETCHED_AT,
        fetched_at=FETCHED_AT,
        summary="No raw item has this source id.",
        location_text=None,
        confidence=0.9,
    )

    batch = build_staging_batch(
        AdapterRunResult(
            adapter_key=normalized.adapter_key,
            fetched=(raw,),
            normalized=(normalized,),
        )
    )

    assert batch.accepted == ()
    assert batch.rejected[0].validation_status == "rejected"
    assert "matching fetched raw item" in (batch.rejected[0].rejection_reason or "")


def test_build_staging_batch_preserves_validated_cap_lifecycle_fields() -> None:
    generation = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    result = _cap_result()

    staged = build_staging_batch(
        result,
        ingestion_generation_started_at=generation,
    ).accepted[0]

    assert staged.payload["cap_sender"] == "sender@example.test"
    assert staged.payload["cap_identifier"] == "alert-1"
    assert staged.payload["cap_sent"] == "2026-08-24T01:00:00+00:00"
    assert staged.payload["cap_references"] == []
    assert staged.payload["cap_status"] == "Actual"
    assert staged.payload["cap_message_type"] == "Alert"
    assert staged.payload["active_from"] == "2026-08-24T01:00:00+00:00"
    assert staged.payload["active_until"] == "2026-08-24T03:00:00+00:00"
    assert staged.payload["ingestion_generation_started_at"] == generation.isoformat()
    assert "xml_body" not in staged.payload


def test_unreviewed_status_alias_cannot_overwrite_validated_cap_status() -> None:
    generation = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)

    staged = build_staging_batch(
        _cap_result(cap_status="Actual", status="Test"),
        ingestion_generation_started_at=generation,
    ).accepted[0]

    assert staged.payload["cap_status"] == "Actual"
    assert "status" not in staged.payload


def test_non_warning_status_is_not_reinterpreted_as_cap_lifecycle_metadata() -> None:
    raw = RawSourceItem(
        source_id="ordinary-status",
        source_url="https://example.test/source",
        fetched_at=FETCHED_AT,
        payload={"status": "online", "evidence_scope": "context"},
    )
    normalized = NormalizedEvidence(
        evidence_id="ev-ordinary-status",
        adapter_key="official.test.context",
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw.source_id,
        source_url=raw.source_url,
        source_title="Ordinary source status",
        source_timestamp=FETCHED_AT,
        fetched_at=FETCHED_AT,
        summary="Non-CAP metadata must not cross the lifecycle boundary.",
        location_text=None,
        confidence=0.9,
    )

    staged = build_staging_batch(
        AdapterRunResult(
            adapter_key=normalized.adapter_key,
            fetched=(raw,),
            normalized=(normalized,),
        )
    ).accepted[0]

    assert "cap_status" not in staged.payload


def test_cap_staging_without_worker_generation_fails_closed() -> None:
    batch = build_staging_batch(_cap_result())

    assert batch.accepted == ()
    assert "CAP lifecycle requires an ingestion generation" in (
        batch.rejected[0].rejection_reason or ""
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"cap_sender": "x" * 513}, "cap_sender"),
        ({"cap_status": "Test"}, "cap_status"),
        ({"cap_sent": "2026-08-24T01:00:00"}, "cap_sent"),
        ({"cap_message_type": "Update", "cap_references": []}, "earlier reference"),
        (
            {
                "cap_references": [
                    {
                        "sender": "sender@example.test",
                        "identifier": f"alert-{index}",
                        "sent": "2026-08-24T00:00:00+00:00",
                    }
                    for index in range(65)
                ]
            },
            "at most 64",
        ),
    ],
)
def test_invalid_cap_lifecycle_metadata_is_rejected(
    overrides: dict[str, object], reason: str
) -> None:
    generation = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)

    batch = build_staging_batch(
        _cap_result(**overrides),
        ingestion_generation_started_at=generation,
    )

    assert batch.accepted == ()
    assert reason in (batch.rejected[0].rejection_reason or "")


def test_cap_reference_duplicates_collapse_by_canonical_utc_triple() -> None:
    generation = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    references = [
        {
            "sender": " sender@example.test ",
            "identifier": " alert-0 ",
            "sent": "2026-08-24T08:00:00+08:00",
        },
        {
            "sender": "sender@example.test",
            "identifier": "alert-0",
            "sent": "2026-08-24T00:00:00+00:00",
        },
    ]

    staged = build_staging_batch(
        _cap_result(cap_message_type="Update", cap_references=references),
        ingestion_generation_started_at=generation,
    ).accepted[0]

    assert staged.payload["cap_references"] == [
        {
            "sender": "sender@example.test",
            "identifier": "alert-0",
            "sent": "2026-08-24T00:00:00+00:00",
        }
    ]


@pytest.mark.parametrize(
    "reference_sent",
    ["2026-08-24T01:00:00+00:00", "2026-08-24T04:00:00+00:00"],
)
def test_cap_mutation_without_any_earlier_reference_fails_closed(
    reference_sent: str,
) -> None:
    generation = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    reference = {
        "sender": "sender@example.test",
        "identifier": "alert-0",
        "sent": reference_sent,
    }

    batch = build_staging_batch(
        _cap_result(cap_message_type="Update", cap_references=[reference]),
        ingestion_generation_started_at=generation,
    )

    assert batch.accepted == ()
    assert "earlier reference" in (batch.rejected[0].rejection_reason or "")


def test_cap_mutation_mixed_reference_list_is_retained_when_one_is_earlier() -> None:
    generation = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    references = [
        {
            "sender": "sender@example.test",
            "identifier": "alert-0",
            "sent": "2026-08-24T04:00:00+00:00",
        },
        {
            "sender": "sender@example.test",
            "identifier": "alert-0",
            "sent": "2026-08-24T00:00:00+00:00",
        },
    ]

    staged = build_staging_batch(
        _cap_result(cap_message_type="Update", cap_references=references),
        ingestion_generation_started_at=generation,
    ).accepted[0]

    assert [reference["sent"] for reference in staged.payload["cap_references"]] == [
        "2026-08-24T00:00:00+00:00",
        "2026-08-24T04:00:00+00:00",
    ]


def test_area_alert_and_area_less_cancel_survive_staging_and_promotion_distinct() -> None:
    generation = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
    sender = "sender@example.test"
    alert_sent = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    cancel_sent = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
    alert_source_id = cap_source_id(
        sender=sender,
        identifier="alert-1",
        sent=alert_sent,
        admin_code="67000000",
    )
    cancel_source_id = cap_source_id(
        sender=sender,
        identifier="cancel-1",
        sent=cancel_sent,
        admin_code=None,
        message_level=True,
    )
    alert_payload: dict[str, object] = {
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "admin_code": "67000000",
        "cap_sender": sender,
        "cap_identifier": "alert-1",
        "cap_sent": alert_sent.isoformat(),
        "cap_references": [],
        "cap_status": "Actual",
        "cap_message_type": "Alert",
        "active_from": alert_sent.isoformat(),
        "active_until": "2026-08-24T04:00:00+00:00",
    }
    cancel_payload: dict[str, object] = {
        "evidence_scope": "current",
        "location_precision": "unknown",
        "cap_sender": sender,
        "cap_identifier": "cancel-1",
        "cap_sent": cancel_sent.isoformat(),
        "cap_references": [
            {
                "sender": sender,
                "identifier": "alert-1",
                "sent": alert_sent.isoformat(),
            }
        ],
        "cap_status": "Actual",
        "cap_message_type": "Cancel",
    }
    raw_items = (
        RawSourceItem(
            source_id=alert_source_id,
            source_url="https://example.test/cap",
            fetched_at=FETCHED_AT,
            payload=alert_payload,
        ),
        RawSourceItem(
            source_id=cancel_source_id,
            source_url="https://example.test/cap",
            fetched_at=FETCHED_AT,
            payload=cancel_payload,
        ),
    )
    normalized = tuple(
        NormalizedEvidence(
            evidence_id=f"ev-{raw.source_id}",
            adapter_key="official.cwa.heavy_rain_warning",
            source_family=SourceFamily.OFFICIAL,
            event_type=EventType.FLOOD_WARNING,
            source_id=raw.source_id,
            source_url=raw.source_url,
            source_title="CAP warning",
            source_timestamp=alert_sent if raw is raw_items[0] else cancel_sent,
            fetched_at=FETCHED_AT,
            summary="Synthetic CAP identity matrix fixture.",
            location_text="臺南市" if raw is raw_items[0] else None,
            confidence=0.9,
        )
        for raw in raw_items
    )
    batch = build_staging_batch(
        AdapterRunResult(
            adapter_key="official.cwa.heavy_rain_warning",
            fetched=raw_items,
            normalized=normalized,
        ),
        raw_ref="raw/cap/synthetic-identity-matrix.xml",
        ingestion_generation_started_at=generation,
    )

    assert {item.source_id for item in batch.accepted} == {
        alert_source_id,
        cancel_source_id,
    }
    candidates = tuple(
        PromotionCandidate(
            staging_evidence_id=f"staging-{index}",
            raw_snapshot_id="snapshot-1",
            raw_ref=item.raw_ref,
            data_source_id=None,
            source_id=item.source_id,
            source_type=item.source_type,
            event_type=item.event_type,
            title=item.title,
            summary=item.summary,
            url=item.url,
            occurred_at=item.occurred_at,
            observed_at=item.observed_at,
            confidence=item.confidence,
            validation_status=item.validation_status,
            payload=item.payload,
        )
        for index, item in enumerate(batch.accepted)
    )
    writer = _SyntheticPromotionWriter(candidates)

    result = promote_accepted_staging(writer)

    assert result.promoted == 2
    assert {payload.source_id for payload in writer.payloads} == {
        alert_source_id,
        cancel_source_id,
    }


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


class _SyntheticPromotionWriter:
    def __init__(self, candidates: tuple[PromotionCandidate, ...]) -> None:
        self.candidates = candidates
        self.payloads: list[EvidencePromotionPayload] = []

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        del limit, adapter_keys
        return self.candidates

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        self.payloads.append(payload)
        return f"evidence-{len(self.payloads)}"


def _complete_replace_result(
    *,
    fetched_at: datetime,
    raw_snapshot_key: str,
    dataset_revision: str,
) -> AdapterRunResult:
    raw = RawSourceItem(
        source_id="historical-1",
        source_url="https://example.test/history",
        fetched_at=fetched_at,
        payload={
            "dataset_revision": dataset_revision,
            "snapshot_generation_mode": "adapter-forged-value",
        },
        raw_snapshot_key=raw_snapshot_key,
    )
    normalized = NormalizedEvidence(
        evidence_id="ev-historical-1",
        adapter_key="official.test.history",
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_REPORT,
        source_id=raw.source_id,
        source_url=raw.source_url,
        source_title="Historical fixture",
        source_timestamp=FETCHED_AT,
        fetched_at=fetched_at,
        summary="Content-stable complete-replace fixture.",
        location_text="臺南市",
        confidence=0.9,
    )
    return AdapterRunResult(
        adapter_key=normalized.adapter_key,
        fetched=(raw,),
        normalized=(normalized,),
    )


def _cap_result(**overrides: object) -> AdapterRunResult:
    payload: dict[str, object] = {
        "evidence_scope": "current",
        "location_precision": "admin_area",
        "admin_code": "67000000",
        "cap_sender": "sender@example.test",
        "cap_identifier": "alert-1",
        "cap_sent": "2026-08-24T01:00:00+00:00",
        "cap_references": [],
        "cap_status": "Actual",
        "cap_message_type": "Alert",
        "active_from": "2026-08-24T01:00:00+00:00",
        "active_until": "2026-08-24T03:00:00+00:00",
        "xml_body": "<alert>private raw body</alert>",
    }
    payload.update(overrides)
    raw = RawSourceItem(
        source_id="cap-source-1",
        source_url="https://example.test/cap",
        fetched_at=FETCHED_AT,
        payload=payload,
    )
    normalized = NormalizedEvidence(
        evidence_id="ev-cap-source-1",
        adapter_key="official.cwa.heavy_rain_warning",
        source_family=SourceFamily.OFFICIAL,
        event_type=EventType.FLOOD_WARNING,
        source_id=raw.source_id,
        source_url=raw.source_url,
        source_title="CAP warning",
        source_timestamp=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
        fetched_at=FETCHED_AT,
        summary="CAP lifecycle staging fixture.",
        location_text="臺南市",
        confidence=0.9,
    )
    return AdapterRunResult(
        adapter_key=normalized.adapter_key,
        fetched=(raw,),
        normalized=(normalized,),
    )
