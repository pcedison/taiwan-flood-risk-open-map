from __future__ import annotations

from contextlib import contextmanager
from contextvars import Context
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from threading import Barrier, local

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app.api.schemas import LatLng, RiskAssessmentResponse, RiskAssessRequest
from app.api.services.assessment import AssessmentService
from app.core import db
from app.domain.assessment.repository import PostgresAssessmentRepository
from app.domain.risk import score_risk


class Pool:
    def __init__(self, *, exhausted: bool = True) -> None:
        self.exhausted = exhausted
        self.attempts = 0
        self.timeout_budget = 0.0
        self.exits = 0

    @contextmanager
    def connection(self, timeout: float) -> Any:
        self.attempts += 1
        if self.exhausted:
            self.timeout_budget += timeout
            raise PoolTimeout("test pool cannot acquire a connection")
        try:
            yield object()
        finally:
            self.exits += 1


class Cache:
    def __init__(self) -> None:
        self.writes = 0

    def get(self, request: RiskAssessRequest, *, now: datetime) -> None:
        return None

    def set(
        self, request: RiskAssessRequest, response: RiskAssessmentResponse, *, now: datetime
    ) -> None:
        self.writes += 1


def test_full_assessment_waits_once_including_persist_and_keeps_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = Pool()
    monkeypatch.setattr(db, "_get_pool", lambda _: pool)
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "5")
    cache = Cache()
    service = AssessmentService(
        PostgresAssessmentRepository("unused-test-dsn"), score_risk, response_cache=cache
    )
    request = RiskAssessRequest(
        point=LatLng(lat=22.9997, lng=120.227), radius_m=750, time_context="now"
    )
    now = datetime(2026, 10, 24, tzinfo=UTC)

    # Undecorated service reproduces the original serial wait multiplication,
    # using actual repositories and an exhausted fake pool, without sleeping.
    baseline = service.assess.__wrapped__(service, request, now=now)  # type: ignore[attr-defined]
    assert pool.attempts == 8
    assert pool.timeout_budget == 40
    pool.attempts = 0
    pool.timeout_budget = 0

    outcome = service.assess(request, now=now)
    assert pool.attempts == 1
    assert pool.timeout_budget == 5
    assert outcome.response.realtime.level == "\u672a\u77e5"
    assert outcome.response.realtime == baseline.response.realtime
    assert outcome.response.historical == baseline.response.historical
    assert outcome.response.overall == baseline.response.overall
    assert outcome.response.data_status == baseline.response.data_status
    assert outcome.response.explanation == baseline.response.explanation
    assert outcome.response.evidence == []
    assert outcome.cache_hit is False
    assert cache.writes == 0
    # A later assessment retries rather than inheriting the previous outage.
    service.assess(request, now=now)
    assert pool.attempts == 2


def test_scope_recovers_on_next_request_and_does_not_block_other_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = Pool()
    monkeypatch.setattr(db, "_get_pool", lambda _: pool)
    with db.database_attempt_scope():
        with pytest.raises(PoolTimeout), db.pooled_connection("first"):
            pass
        pool.exhausted = False
        with pytest.raises(PoolTimeout), db.pooled_connection("first"):
            pass
        with db.pooled_connection("other"):
            pass
    with db.database_attempt_scope(), db.pooled_connection("first"):
        pass
    assert pool.attempts == 3
    assert pool.exits == 2


@pytest.mark.parametrize(
    "error_type",
    [psycopg.errors.QueryCanceled, psycopg.errors.UndefinedTable,
     psycopg.OperationalError, PoolTimeout, ValueError],
)
def test_query_body_failure_does_not_poison_later_acquisitions(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    pool = Pool(exhausted=False)
    monkeypatch.setattr(db, "_get_pool", lambda _: pool)
    with db.database_attempt_scope():
        with pytest.raises(error_type), db.pooled_connection("first"):
            raise error_type("query-specific failure")
        with db.pooled_connection("first"):
            pass
    assert pool.attempts == 2
    assert pool.exits == 2


def test_scope_is_reset_after_unhandled_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = Pool()
    monkeypatch.setattr(db, "_get_pool", lambda _: pool)
    with pytest.raises(PoolTimeout), db.database_attempt_scope(), db.pooled_connection("first"):
        pass
    pool.exhausted = False
    with db.pooled_connection("first"):
        pass
    assert pool.attempts == 2


def test_independent_context_does_not_inherit_failed_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = Pool()
    monkeypatch.setattr(db, "_get_pool", lambda _: pool)

    def independent_request() -> None:
        with db.database_attempt_scope(), db.pooled_connection("first"):
            pass

    with db.database_attempt_scope():
        with pytest.raises(PoolTimeout), db.pooled_connection("first"):
            pass
        pool.exhausted = False
        Context().run(independent_request)
        with pytest.raises(PoolTimeout), db.pooled_connection("first"):
            pass
    assert pool.attempts == 2


def test_timeout_after_success_stops_only_subsequent_acquisitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = Pool(exhausted=False)
    monkeypatch.setattr(db, "_get_pool", lambda _: pool)
    with db.database_attempt_scope():
        with db.pooled_connection("first") as earlier:
            assert earlier is not None
        pool.exhausted = True
        with pytest.raises(PoolTimeout), db.pooled_connection("first"):
            pass
        with pytest.raises(PoolTimeout), db.pooled_connection("first"):
            pass
    assert pool.attempts == 2
    assert pool.exits == 1


def test_transaction_exit_timeout_does_not_trip_acquisition_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    class CleanupFailingPool:
        @contextmanager
        def connection(self, timeout: float) -> Any:
            attempts.append(timeout)
            try:
                yield object()
            finally:
                raise PoolTimeout("transaction exit failed after acquisition")

    monkeypatch.setattr(db, "_get_pool", lambda _: CleanupFailingPool())
    with db.database_attempt_scope():
        for _ in range(2):
            with pytest.raises(PoolTimeout), db.pooled_connection("first"):
                pass
    assert len(attempts) == 2


def test_concurrent_assessments_do_not_share_failed_acquisitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = local()
    rendezvous = Barrier(2, timeout=5)

    class ThreadPool:
        @contextmanager
        def connection(self, timeout: float) -> Any:
            state.attempts += 1
            if state.exhausted:
                raise PoolTimeout("test request acquisition failed")
            yield object()

    monkeypatch.setattr(db, "_get_pool", lambda _: ThreadPool())

    def request(exhausted: bool) -> int:
        state.exhausted = exhausted
        state.attempts = 0
        with db.database_attempt_scope():
            if exhausted:
                with pytest.raises(PoolTimeout), db.pooled_connection("same-database"):
                    pass
            rendezvous.wait()
            if exhausted:
                with pytest.raises(PoolTimeout), db.pooled_connection("same-database"):
                    pass
            else:
                with db.pooled_connection("same-database"):
                    pass
        return state.attempts

    with ThreadPoolExecutor(max_workers=2) as executor:
        broken = executor.submit(request, True)
        healthy = executor.submit(request, False)
        assert broken.result(timeout=10) == 1
        assert healthy.result(timeout=10) == 1
