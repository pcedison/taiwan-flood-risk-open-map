from __future__ import annotations

from datetime import datetime, timezone
import json

from app.pipelines.promotion import (
    PostgresEvidencePromotionWriter,
    PromotionCandidate,
    build_evidence_promotion_payload,
    promote_accepted_staging,
)


OCCURRED_AT = datetime(2026, 4, 28, 8, 30, tzinfo=timezone.utc)
OBSERVED_AT = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)


def test_build_evidence_promotion_payload_maps_accepted_staging_row() -> None:
    candidate = _candidate()

    payload = build_evidence_promotion_payload(candidate)

    assert payload.source_id == "sample-news-001"
    assert payload.source_type == "news"
    assert payload.event_type == "flood_report"
    assert payload.raw_ref == "raw/news-public-web/sample.json"
    assert payload.properties["location_text"] == "Riverside District"
    assert payload.properties["staging_evidence_id"] == "staging-id"
    assert payload.properties["raw_snapshot_id"] == "raw-snapshot-id"


def test_build_evidence_promotion_payload_rejects_non_accepted_staging_row() -> None:
    candidate = _candidate(validation_status="rejected")

    try:
        build_evidence_promotion_payload(candidate)
    except ValueError as exc:
        assert str(exc) == "only accepted staging evidence can be promoted"
    else:
        raise AssertionError("expected ValueError")


def test_promote_accepted_staging_uses_writer_protocol() -> None:
    writer = _MemoryPromotionWriter([_candidate()])

    result = promote_accepted_staging(writer, limit=10)

    assert result.promoted == 1
    assert result.evidence_ids == ("evidence-1",)
    assert writer.requested_limit == 10
    assert len(writer.payloads) == 1
    assert writer.payloads[0].source_id == "sample-news-001"


def test_postgres_promotion_writer_fetches_accepted_rows_and_inserts_evidence() -> None:
    connection = _FakeConnection(
        rows=[
            (
                "staging-id",
                "raw-snapshot-id",
                "raw/news-public-web/sample.json",
                "data-source-id",
                "sample-news-001",
                "news",
                "flood_report",
                "Heavy rain reported near riverside district",
                "Public report describes street flooding near the riverside district.",
                "https://example.test/news/flood-001",
                OCCURRED_AT,
                OBSERVED_AT,
                0.72,
                "accepted",
                json.dumps({"location_text": "Riverside District"}),
            )
        ],
        evidence_id="evidence-id",
    )
    writer = PostgresEvidencePromotionWriter(connection_factory=lambda: connection)

    candidates = writer.fetch_accepted_staging(limit=5)
    evidence_id = writer.write_evidence(build_evidence_promotion_payload(candidates[0]))

    assert evidence_id == "evidence-id"
    assert connection.committed is True
    assert len(connection.cursor_instance.executions) == 2
    select_sql, select_params = connection.cursor_instance.executions[0]
    insert_sql, insert_params = connection.cursor_instance.executions[1]
    assert "FROM staging_evidence se" in select_sql
    assert "se.validation_status = 'accepted'" in select_sql
    assert "NOT EXISTS" in select_sql
    assert select_params == (5,)
    assert "INSERT INTO evidence" in insert_sql
    assert insert_params[1] == "sample-news-001"
    assert insert_params[10] == "raw/news-public-web/sample.json"
    properties = json.loads(str(insert_params[11]))
    assert properties["location_text"] == "Riverside District"
    assert properties["staging_evidence_id"] == "staging-id"


def test_postgres_promotion_writer_requires_database_url_or_connection_factory() -> None:
    try:
        PostgresEvidencePromotionWriter()
    except ValueError as exc:
        assert str(exc) == "database_url or connection_factory is required"
    else:
        raise AssertionError("expected ValueError")


def _candidate(*, validation_status: str = "accepted") -> PromotionCandidate:
    return PromotionCandidate(
        staging_evidence_id="staging-id",
        raw_snapshot_id="raw-snapshot-id",
        raw_ref="raw/news-public-web/sample.json",
        data_source_id="data-source-id",
        source_id="sample-news-001",
        source_type="news",
        event_type="flood_report",
        title="Heavy rain reported near riverside district",
        summary="Public report describes street flooding near the riverside district.",
        url="https://example.test/news/flood-001",
        occurred_at=OCCURRED_AT,
        observed_at=OBSERVED_AT,
        confidence=0.72,
        validation_status=validation_status,
        payload={"location_text": "Riverside District"},
    )


class _MemoryPromotionWriter:
    def __init__(self, candidates: list[PromotionCandidate]) -> None:
        self._candidates = tuple(candidates)
        self.requested_limit: int | None = None
        self.payloads: list[object] = []

    def fetch_accepted_staging(self, *, limit: int | None = None) -> tuple[PromotionCandidate, ...]:
        self.requested_limit = limit
        return self._candidates

    def write_evidence(self, payload: object) -> str:
        self.payloads.append(payload)
        return f"evidence-{len(self.payloads)}"


class _FakeConnection:
    def __init__(self, *, rows: list[tuple[object, ...]], evidence_id: str) -> None:
        self.cursor_instance = _FakeCursor(rows=rows, evidence_id=evidence_id)
        self.committed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


class _FakeCursor:
    def __init__(self, *, rows: list[tuple[object, ...]], evidence_id: str) -> None:
        self._rows = tuple(rows)
        self._evidence_id = evidence_id
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self._rows

    def fetchone(self) -> tuple[str]:
        return (self._evidence_id,)
