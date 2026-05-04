from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from app.logging import log_event


ConnectionFactory = Callable[[], Any]
QueryHeatPeriod = Literal["P1D", "P7D"]

SUPPORTED_QUERY_HEAT_PERIODS: tuple[QueryHeatPeriod, ...] = ("P1D", "P7D")
QUERY_HEAT_PERIOD_ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)

_PERIOD_INTERVALS: dict[QueryHeatPeriod, str] = {
    "P1D": "1 day",
    "P7D": "7 days",
}


class QueryHeatAggregationUnavailable(RuntimeError):
    """Raised when query heat buckets cannot be materialized from the database."""


@dataclass(frozen=True)
class QueryHeatAggregationSummary:
    period: QueryHeatPeriod
    buckets_upserted: int
    started_at: datetime
    finished_at: datetime

    def log_fields(self) -> dict[str, object]:
        return {
            "period": self.period,
            "buckets_upserted": self.buckets_upserted,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class QueryHeatRetentionSummary:
    periods: tuple[QueryHeatPeriod, ...]
    retention_days: int
    cutoff: datetime
    buckets_pruned: int
    started_at: datetime
    finished_at: datetime

    def log_fields(self) -> dict[str, object]:
        return {
            "periods": self.periods,
            "retention_days": self.retention_days,
            "cutoff": self.cutoff,
            "buckets_pruned": self.buckets_pruned,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class PostgresQueryHeatAggregationJob:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def aggregate(
        self,
        *,
        periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
        created_at_start: datetime | None = None,
        created_at_end: datetime | None = None,
    ) -> tuple[QueryHeatAggregationSummary, ...]:
        resolved_periods = tuple(
            dict.fromkeys(_validate_period(period) for period in periods)
        )
        _validate_created_at_window(
            created_at_start=created_at_start,
            created_at_end=created_at_end,
        )
        if not resolved_periods:
            return ()

        started_at = _now()
        summaries: list[QueryHeatAggregationSummary] = []
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    for period in resolved_periods:
                        buckets_upserted = _aggregate_period(
                            cursor,
                            period=period,
                            created_at_start=created_at_start,
                            created_at_end=created_at_end,
                        )
                        summary = QueryHeatAggregationSummary(
                            period=period,
                            buckets_upserted=buckets_upserted,
                            started_at=started_at,
                            finished_at=_now(),
                        )
                        summaries.append(summary)
                connection.commit()
        except Exception as exc:
            raise QueryHeatAggregationUnavailable(str(exc)) from exc

        for summary in summaries:
            log_event("query_heat.aggregation.completed", **summary.log_fields())
        return tuple(summaries)

    def prune_retention(
        self,
        *,
        retention_days: int,
        periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
        now: datetime | None = None,
    ) -> QueryHeatRetentionSummary:
        resolved_periods = tuple(
            dict.fromkeys(_validate_period(period) for period in periods)
        )
        _validate_retention_days(retention_days)
        resolved_now = _validate_reference_time(now or _now())
        cutoff = resolved_now - timedelta(days=retention_days)
        started_at = _now()

        if not resolved_periods:
            summary = QueryHeatRetentionSummary(
                periods=(),
                retention_days=retention_days,
                cutoff=cutoff,
                buckets_pruned=0,
                started_at=started_at,
                finished_at=_now(),
            )
            log_event("query_heat.retention.completed", **summary.log_fields())
            return summary

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    buckets_pruned = _prune_retention(
                        cursor,
                        periods=resolved_periods,
                        cutoff=cutoff,
                    )
                connection.commit()
        except Exception as exc:
            raise QueryHeatAggregationUnavailable(str(exc)) from exc

        summary = QueryHeatRetentionSummary(
            periods=resolved_periods,
            retention_days=retention_days,
            cutoff=cutoff,
            buckets_pruned=buckets_pruned,
            started_at=started_at,
            finished_at=_now(),
        )
        log_event("query_heat.retention.completed", **summary.log_fields())
        return summary

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)


def run_query_heat_aggregation(
    *,
    database_url: str | None = None,
    connection_factory: ConnectionFactory | None = None,
    periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
    created_at_start: datetime | None = None,
    created_at_end: datetime | None = None,
) -> tuple[QueryHeatAggregationSummary, ...]:
    job = PostgresQueryHeatAggregationJob(
        database_url=database_url,
        connection_factory=connection_factory,
    )
    return job.aggregate(
        periods=periods,
        created_at_start=created_at_start,
        created_at_end=created_at_end,
    )


def run_query_heat_retention_cleanup(
    *,
    database_url: str | None = None,
    connection_factory: ConnectionFactory | None = None,
    retention_days: int,
    periods: Iterable[str] = SUPPORTED_QUERY_HEAT_PERIODS,
    now: datetime | None = None,
) -> QueryHeatRetentionSummary:
    job = PostgresQueryHeatAggregationJob(
        database_url=database_url,
        connection_factory=connection_factory,
    )
    return job.prune_retention(
        periods=periods,
        retention_days=retention_days,
        now=now,
    )


def _aggregate_period(
    cursor: Any,
    *,
    period: QueryHeatPeriod,
    created_at_start: datetime | None,
    created_at_end: datetime | None,
) -> int:
    cursor.execute(
        """
        WITH normalized_queries AS (
            SELECT
                COALESCE(NULLIF(lq.h3_index, ''), NULLIF(lq.privacy_bucket, '')) AS h3_index,
                lq.privacy_bucket,
                lq.id,
                lq.created_at
            FROM location_queries lq
            WHERE
                lq.created_at >= COALESCE(%s::timestamptz, '-infinity'::timestamptz)
                AND lq.created_at < COALESCE(%s::timestamptz, 'infinity'::timestamptz)
        ),
        aggregated AS (
            SELECT
                nq.h3_index,
                %s::text AS period,
                date_bin(%s::interval, nq.created_at, %s::timestamptz) AS period_started_at,
                COUNT(*)::integer AS query_count,
                COUNT(
                    DISTINCT COALESCE(NULLIF(nq.privacy_bucket, ''), nq.h3_index, nq.id::text)
                )::integer AS unique_approx_count
            FROM normalized_queries nq
            WHERE nq.h3_index IS NOT NULL
            GROUP BY
                nq.h3_index,
                period_started_at
        ),
        upserted AS (
            INSERT INTO query_heat_buckets (
                h3_index,
                period,
                period_started_at,
                query_count,
                unique_approx_count,
                updated_at
            )
            SELECT
                h3_index,
                period,
                period_started_at,
                query_count,
                unique_approx_count,
                now()
            FROM aggregated
            ON CONFLICT (h3_index, period, period_started_at) DO UPDATE SET
                query_count = EXCLUDED.query_count,
                unique_approx_count = EXCLUDED.unique_approx_count,
                updated_at = now()
            RETURNING h3_index
        )
        SELECT COUNT(*)::integer AS bucket_count
        FROM upserted
        """,
        (
            created_at_start,
            created_at_end,
            period,
            _PERIOD_INTERVALS[period],
            QUERY_HEAT_PERIOD_ORIGIN,
        ),
    )
    return _bucket_count(cursor.fetchone())


def _prune_retention(
    cursor: Any,
    *,
    periods: tuple[QueryHeatPeriod, ...],
    cutoff: datetime,
) -> int:
    cursor.execute(
        """
        WITH deleted AS (
            DELETE FROM query_heat_buckets
            WHERE
                period = ANY(%s::text[])
                AND period_started_at < %s::timestamptz
            RETURNING id
        )
        SELECT COUNT(*)::integer AS bucket_count
        FROM deleted
        """,
        (
            list(periods),
            cutoff,
        ),
    )
    return _bucket_count(cursor.fetchone())


def _validate_period(period: str) -> QueryHeatPeriod:
    if period in _PERIOD_INTERVALS:
        return cast(QueryHeatPeriod, period)
    supported = ", ".join(SUPPORTED_QUERY_HEAT_PERIODS)
    raise ValueError(f"unsupported query heat period {period!r}; supported: {supported}")


def _validate_created_at_window(
    *,
    created_at_start: datetime | None,
    created_at_end: datetime | None,
) -> None:
    if created_at_start is not None:
        _validate_aware_datetime(created_at_start, field_name="created_at_start")
    if created_at_end is not None:
        _validate_aware_datetime(created_at_end, field_name="created_at_end")
    if (
        created_at_start is not None
        and created_at_end is not None
        and created_at_start >= created_at_end
    ):
        raise ValueError("created_at_start must be before created_at_end")


def _validate_retention_days(retention_days: int) -> None:
    if retention_days < 1:
        raise ValueError("query heat retention_days must be positive")


def _validate_reference_time(reference_time: datetime) -> datetime:
    _validate_aware_datetime(reference_time, field_name="now")
    return reference_time


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"query heat {field_name} must be timezone-aware")


def _bucket_count(row: object | None) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row["bucket_count"])
    return int(cast(Any, row)[0])


def _now() -> datetime:
    return datetime.now(UTC)
