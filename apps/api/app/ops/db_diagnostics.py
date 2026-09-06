"""Read-only PostgreSQL diagnostics for hosted latency triage.

The hosted deployment runs on a 2 GB node we cannot reach with a psql client, so
production query latency has to be diagnosed through the application.  Local
reproductions of the risk-assessment path run one to two orders of magnitude
faster than production (see docs/reviews/assess-query-plans-2026-09-05.md), which
points at node-level state -- heap and index bloat from the 48 hour retention
cycle, autovacuum falling behind, or plans that differ because nothing stays
resident in cache -- rather than at the SQL itself.

**These plans are not request latency.** Each probe runs under its own 8 s
budget, which is deliberately larger than the budget the request path gives the
same query.  Since #359 the coverage supplement is abandoned after 250 ms when
``official_realtime_latest`` has already answered, so its probe here measures
how long the abandoned query *would* have taken, not what a request waits for.
Read the plans as evidence about the database -- rows examined, buffers touched,
index choice, bloat -- and read ``Server-Timing`` for what users experience.

Everything here is read-only.  Each probe runs in a ``READ ONLY`` transaction,
and every statement carries a bounded timeout.  It exposes catalog statistics
and query plans; it never returns evidence content, user data, SQL text, or
connection strings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from app.domain.evidence.repository import (
    DEFAULT_COVERAGE_RADIUS_BUCKETS_M,
    nearby_evidence_coverage_statement,
    query_nearby_evidence,
    query_realtime_jurisdiction_context,
)

# Tables on the risk-assessment read path plus the two the retention cycle
# rewrites most aggressively.  A name that does not exist simply returns no row.
DIAGNOSTIC_TABLES: tuple[str, ...] = (
    "evidence",
    "staging_evidence",
    "official_realtime_latest",
    "ingestion_jobs",
    "location_queries",
)
# Taipei City Hall. A fixed public coordinate so plans are comparable between
# runs and no user query is ever replayed here.
SAMPLE_LAT = 25.033
SAMPLE_LNG = 121.5654
SAMPLE_RADIUS_M = 500
SAMPLE_COVERAGE_BUCKETS_M = DEFAULT_COVERAGE_RADIUS_BUCKETS_M
# Each probe gets its own budget. Production segments run 1.5-5.6 s, so 8 s
# leaves headroom for a plan that is merely slow while still bounding a plan
# that will never finish. Catalog reads share the budget so no section of this
# endpoint can hang on a lock.
STATEMENT_TIMEOUT_MS = 8_000
EXPLAIN_STATEMENT_TIMEOUT_MS = STATEMENT_TIMEOUT_MS
STATEMENT_STATS_LIMIT = 10
# The partial index from migration 0042 over
# evidence ((properties ->> 'staging_evidence_id')). Its entry count is exactly
# the number of evidence rows that record which staging row produced them, so
# pg_class.reltuples for this index is a usable estimate when counting the rows
# outright does not finish.
STAGING_USE_INDEX = "idx_evidence_staging_evidence_id"
# The probe budget exceeds what the request path allows, so a plan here can
# report work the real request would have abandoned. Say so next to the number.
EXPLAIN_BUDGET_NOTE = (
    f"probe ran under a {STATEMENT_TIMEOUT_MS} ms budget, which is larger than "
    "the request path allows; treat this as evidence about the database, not as "
    "request latency"
)

ConnectionFactory = Callable[[], Any]


def collect_db_diagnostics(
    *,
    database_url: str,
    connection_factory: ConnectionFactory | None = None,
) -> dict[str, Any]:
    """Collect table, index, plan and statement diagnostics.

    Every section is isolated: a section that fails reports its own error and
    the rest of the payload is still returned, because a partial answer is what
    makes this useful during an incident.
    """

    return {
        "captured_at": datetime.now(UTC).replace(microsecond=0),
        "sample_point": {
            "lat": SAMPLE_LAT,
            "lng": SAMPLE_LNG,
            "radius_m": SAMPLE_RADIUS_M,
        },
        "tables": _table_stats(database_url, connection_factory),
        "indexes": _index_stats(database_url, connection_factory),
        "staging_status_counts": _staging_status_counts(
            database_url, connection_factory
        ),
        "staging_used_by_evidence_estimate": _staging_used_by_evidence_estimate(
            database_url, connection_factory
        ),
        "query_plans": _query_plans(database_url, connection_factory),
        "statements": _statement_stats(database_url, connection_factory),
    }


def _connect(database_url: str, connection_factory: ConnectionFactory | None) -> Any:
    if connection_factory is not None:
        return connection_factory()
    return psycopg.connect(database_url, connect_timeout=5, row_factory=dict_row)


def _apply_read_only_budget(cursor: Any) -> None:
    """Bound every statement and make writes impossible at the server.

    The queries here are all ``SELECT``s, so ``READ ONLY`` changes nothing today.
    It is structural insurance: an admin endpoint that runs EXPLAIN ANALYZE --
    which really executes the statement -- should not be one editing mistake away
    from mutating production.
    """

    cursor.execute("SET TRANSACTION READ ONLY")
    cursor.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (f"{STATEMENT_TIMEOUT_MS}ms",),
    )


def _table_stats(
    database_url: str, connection_factory: ConnectionFactory | None
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            stat.relname AS relname,
            stat.n_live_tup AS n_live_tup,
            stat.n_dead_tup AS n_dead_tup,
            CASE
                WHEN COALESCE(stat.n_live_tup, 0) + COALESCE(stat.n_dead_tup, 0) = 0
                    THEN NULL
                ELSE round(
                    stat.n_dead_tup::numeric
                        / (stat.n_live_tup + stat.n_dead_tup)::numeric,
                    4
                )::double precision
            END AS dead_tuple_ratio,
            stat.n_tup_ins AS n_tup_ins,
            stat.n_tup_upd AS n_tup_upd,
            stat.n_tup_del AS n_tup_del,
            stat.last_vacuum AS last_vacuum,
            stat.last_autovacuum AS last_autovacuum,
            stat.last_analyze AS last_analyze,
            stat.last_autoanalyze AS last_autoanalyze,
            stat.autovacuum_count AS autovacuum_count,
            pg_total_relation_size(stat.relid) AS total_relation_size_bytes,
            pg_relation_size(stat.relid) AS table_size_bytes,
            pg_indexes_size(stat.relid) AS indexes_size_bytes
        FROM pg_stat_user_tables stat
        WHERE stat.relname = ANY(%s)
        ORDER BY stat.relname
    """
    return _rows(database_url, connection_factory, sql, (list(DIAGNOSTIC_TABLES),))


def _index_stats(
    database_url: str, connection_factory: ConnectionFactory | None
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            stat.relname AS relname,
            stat.indexrelname AS indexrelname,
            stat.idx_scan AS idx_scan,
            stat.idx_tup_read AS idx_tup_read,
            stat.idx_tup_fetch AS idx_tup_fetch,
            pg_relation_size(stat.indexrelid) AS index_size_bytes
        FROM pg_stat_user_indexes stat
        WHERE stat.relname = ANY(%s)
        ORDER BY stat.relname, stat.indexrelname
    """
    return _rows(database_url, connection_factory, sql, (list(DIAGNOSTIC_TABLES),))


def _staging_status_counts(
    database_url: str, connection_factory: ConnectionFactory | None
) -> dict[str, Any]:
    """Break ``staging_evidence`` down by ``validation_status``.

    #367 needs to know what share of the 14 M staging rows is terminal
    ``rejected`` (safe to prune) versus still ``accepted`` (which promotion and
    historical coverage read, and which the schema gives no ``promoted`` state
    to subdivide). The exact answer needs ``min``/``max(created_at)`` per group,
    which no index can serve, so on a bloated table it is a full heap scan that
    will not fit the 8 s budget. When that happens the section reports the
    timeout and falls back to the planner's own sampled distribution, which
    costs one catalog read -- a proportion is what the retention decision needs.
    """

    sql = """
        SELECT
            staging.validation_status AS validation_status,
            count(*)::bigint AS rows,
            min(staging.created_at) AS oldest,
            max(staging.created_at) AS newest
        FROM staging_evidence staging
        GROUP BY staging.validation_status
        ORDER BY count(*) DESC, staging.validation_status
    """
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            _apply_read_only_budget(cursor)
            cursor.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()]
    except psycopg.errors.QueryCanceled:
        estimated = _estimated_status_counts(database_url, connection_factory)
        return {
            "status": "timeout",
            "method": "pg_stats_estimate" if estimated else None,
            "rows": estimated,
            "error": "timeout",
        }
    except (OSError, psycopg.Error) as exc:
        # Only the exception class: psycopg renders the full conninfo, which
        # would put the database host and password in the payload.
        return {
            "status": "unavailable",
            "method": None,
            "rows": [],
            "error": type(exc).__name__,
        }
    return {"status": "ok", "method": "exact", "rows": rows, "error": None}


def _estimated_status_counts(
    database_url: str, connection_factory: ConnectionFactory | None
) -> list[dict[str, Any]]:
    """Estimate the status split from ANALYZE statistics, or return nothing.

    ``most_common_vals``/``most_common_freqs`` hold the sampled distribution and
    ``reltuples`` the sampled row count, so their product estimates each status
    without touching the table. Statuses too rare to reach the most-common list
    are missing, and the estimate is only as fresh as the last ANALYZE -- read
    it as a proportion, never as a row count.
    """

    sql = """
        SELECT
            -- most_common_vals is anyarray, which casts only via text.
            -- validation_status values are bare identifiers, so the text
            -- form round-trips through the array parser unambiguously.
            stat.most_common_vals::text::text[] AS common_values,
            stat.most_common_freqs AS common_freqs,
            (
                SELECT cls.reltuples
                FROM pg_class cls
                WHERE cls.oid = 'staging_evidence'::regclass
            ) AS reltuples
        FROM pg_stats stat
        WHERE stat.schemaname = current_schema()
            AND stat.tablename = 'staging_evidence'
            AND stat.attname = 'validation_status'
    """
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            _apply_read_only_budget(cursor)
            cursor.execute(sql)
            row = cursor.fetchone()
    except (OSError, psycopg.Error):
        return []
    if row is None:
        return []
    values = row["common_values"] or []
    freqs = row["common_freqs"] or []
    reltuples = row["reltuples"] or 0
    # PostgreSQL reports -1 for a relation that has never been analyzed.
    if reltuples <= 0:
        return []
    estimated = [
        {
            "validation_status": str(value),
            "rows": int(round(float(freq) * float(reltuples))),
            "oldest": None,
            "newest": None,
        }
        for value, freq in zip(values, freqs)
    ]
    return sorted(estimated, key=lambda item: (-item["rows"], item["validation_status"]))


def _staging_used_by_evidence_estimate(
    database_url: str, connection_factory: ConnectionFactory | None
) -> dict[str, Any]:
    """Count the evidence rows that name the staging row they came from.

    Subtracting this from the ``accepted`` staging count is how #367 sizes the
    already-promoted population the schema cannot label. The partial index from
    migration 0042 makes the exact count an index-only scan; when even that does
    not fit the budget, the index's own ``reltuples`` is the same number
    estimated from catalog statistics.
    """

    result: dict[str, Any] = {
        "status": "ok",
        "method": "exact",
        "rows": None,
        "index_name": STAGING_USE_INDEX,
        "error": None,
    }
    sql = """
        SELECT count(*)::bigint AS rows
        FROM evidence
        WHERE evidence.properties ? 'staging_evidence_id'
    """
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            _apply_read_only_budget(cursor)
            cursor.execute(sql)
            row = cursor.fetchone()
    except psycopg.errors.QueryCanceled:
        estimated = _estimated_staging_use(database_url, connection_factory)
        return {
            **result,
            "status": "timeout",
            "method": "index_reltuples_estimate" if estimated is not None else None,
            "rows": estimated,
            "error": "timeout",
        }
    except (OSError, psycopg.Error) as exc:
        return {
            **result,
            "status": "unavailable",
            "method": None,
            "error": type(exc).__name__,
        }
    return {**result, "rows": _scalar_rows(row)}


def _estimated_staging_use(
    database_url: str, connection_factory: ConnectionFactory | None
) -> int | None:
    sql = """
        SELECT cls.reltuples AS rows
        FROM pg_class cls
        WHERE cls.relname = %s
            AND cls.relkind = 'i'
    """
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            _apply_read_only_budget(cursor)
            cursor.execute(sql, (STAGING_USE_INDEX,))
            row = cursor.fetchone()
    except (OSError, psycopg.Error):
        return None
    estimated = _scalar_rows(row)
    # -1 means the index has never been analyzed, which is not an estimate.
    return estimated if estimated is not None and estimated >= 0 else None


def _scalar_rows(row: Any) -> int | None:
    if row is None:
        return None
    value = row["rows"] if isinstance(row, dict) else row[0]
    return None if value is None else int(value)


def _statement_stats(
    database_url: str, connection_factory: ConnectionFactory | None
) -> list[dict[str, Any]] | None:
    """Return the slowest statements, or ``None`` when the extension is absent.

    ``pg_stat_statements`` is not installed on every environment, and a missing
    extension is a normal answer here rather than a diagnostic failure.
    """

    # No query text. pg_stat_statements only normalises literals in statements
    # it can parse as DML; utility statements are stored verbatim, so a
    # `CREATE ROLE ... PASSWORD '...'` or an `ALTER USER` would put a live
    # credential in this payload. queryid is enough to correlate with a plan.
    sql = f"""
        SELECT
            stat.queryid::text AS queryid,
            stat.calls AS calls,
            round(stat.total_exec_time::numeric, 2)::double precision
                AS total_exec_time_ms,
            round(stat.mean_exec_time::numeric, 2)::double precision
                AS mean_exec_time_ms,
            stat.rows AS rows,
            stat.shared_blks_read AS shared_blks_read,
            stat.shared_blks_hit AS shared_blks_hit
        FROM pg_stat_statements stat
        ORDER BY stat.total_exec_time DESC
        LIMIT {STATEMENT_STATS_LIMIT}
    """
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            _apply_read_only_budget(cursor)
            cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]
    except psycopg.errors.UndefinedTable:
        return None
    except (OSError, psycopg.Error):
        return None


def _rows(
    database_url: str,
    connection_factory: ConnectionFactory | None,
    sql: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            _apply_read_only_budget(cursor)
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    except (OSError, psycopg.Error):
        return []


class _CaptureCursor:
    """Record the SQL a repository function would run, without running it.

    Returning empty results is safe for all three captured readers: they either
    build records from ``fetchall`` or treat a ``None`` row as "not resolved".
    """

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    def __enter__(self) -> "_CaptureCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: Any, params: Any = None) -> None:
        text = query if isinstance(query, str) else str(query)
        if "set_config" in text:
            return
        self.statements.append((text, params))

    def fetchall(self) -> list[Any]:
        return []

    def fetchone(self) -> None:
        return None


class _CaptureConnection:
    def __init__(self, cursor: _CaptureCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_CaptureConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _CaptureCursor:
        return self._cursor


def _capture_statement(
    reader: Callable[[ConnectionFactory], Any],
) -> tuple[str, Any] | None:
    """Extract the SQL and parameters a reader would execute."""

    cursor = _CaptureCursor()
    connection = _CaptureConnection(cursor)
    try:
        reader(lambda: connection)
    except Exception:  # noqa: BLE001 - capture is best effort, the plan reports it
        pass
    if not cursor.statements:
        return None
    return cursor.statements[0]


# The radius each probe searches, and how it relates to the request path. The
# request path calls all three with the caller's radius, so the probes must use
# it too -- a jurisdiction probe left on the 15 km default resolves a different
# number of county polygons than the 500 m the request actually asks for.
PROBE_NOTES: dict[str, str] = {
    "nearby_evidence": (
        "matches the request path: same radius and the same unbounded lookback"
    ),
    "coverage_supplement": (
        "since #359 the request path abandons this query after 250 ms once "
        "official_realtime_latest has answered, so this measures how long the "
        "abandoned query would have taken, not what a request waits for"
    ),
    "jurisdiction": (
        "searches the request radius; the reader defaults to 15 km, which the "
        "request path never uses"
    ),
}


def _statement_sources() -> tuple[tuple[str, int, Callable[[], tuple[str, Any] | None]], ...]:
    """Pair each probe with its search radius and the statement to EXPLAIN.

    The coverage reader exposes its statement directly. The other two build
    their SQL inline while executing, so their statement is recovered by
    running them against a connection that records instead of querying --
    which keeps this module from holding a second copy of that SQL.
    """

    return (
        (
            "nearby_evidence",
            SAMPLE_RADIUS_M,
            lambda: _capture_statement(
                lambda factory: query_nearby_evidence(
                    database_url="",
                    lat=SAMPLE_LAT,
                    lng=SAMPLE_LNG,
                    radius_m=SAMPLE_RADIUS_M,
                    connection_factory=factory,
                )
            ),
        ),
        (
            "coverage_supplement",
            max(SAMPLE_COVERAGE_BUCKETS_M),
            lambda: nearby_evidence_coverage_statement(
                lat=SAMPLE_LAT,
                lng=SAMPLE_LNG,
                radius_buckets_m=SAMPLE_COVERAGE_BUCKETS_M,
                observed_since=None,
            ),
        ),
        (
            "jurisdiction",
            SAMPLE_RADIUS_M,
            lambda: _capture_statement(
                lambda factory: query_realtime_jurisdiction_context(
                    database_url="",
                    lat=SAMPLE_LAT,
                    lng=SAMPLE_LNG,
                    search_radius_m=SAMPLE_RADIUS_M,
                    connection_factory=factory,
                )
            ),
        ),
    )


def _query_plans(
    database_url: str, connection_factory: ConnectionFactory | None
) -> list[dict[str, Any]]:
    return [
        _explain(name, radius_m, statement, database_url, connection_factory)
        for name, radius_m, statement in _statement_sources()
    ]


def _plan_result(
    name: str,
    radius_m: int,
    *,
    status: str,
    plan: list[dict[str, Any]] | None,
    error: str | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "radius_m": radius_m,
        "status": status,
        "plan": plan,
        "error": error,
        "note": f"{PROBE_NOTES[name]}; {EXPLAIN_BUDGET_NOTE}",
    }


def _explain(
    name: str,
    radius_m: int,
    statement: Callable[[], tuple[str, Any] | None],
    database_url: str,
    connection_factory: ConnectionFactory | None,
) -> dict[str, Any]:
    try:
        captured = statement()
    except Exception:  # noqa: BLE001 - a probe must never break the payload
        captured = None
    if captured is None:
        return _plan_result(
            name, radius_m, status="skipped", plan=None, error="sql_unavailable"
        )
    sql, params = captured
    try:
        with (
            _connect(database_url, connection_factory) as connection,
            connection.cursor() as cursor,
        ):
            # EXPLAIN ANALYZE really runs the statement, so the read-only
            # transaction matters more here than anywhere else in this module.
            _apply_read_only_budget(cursor)
            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
                params,
            )
            row = cursor.fetchone()
    except psycopg.errors.QueryCanceled:
        # The sole reason this endpoint exists is queries that do not finish, so
        # a timeout is a result to report rather than an error to raise.
        return _plan_result(name, radius_m, status="timeout", plan=None, error="timeout")
    except (OSError, psycopg.Error) as exc:
        # Deliberately only the exception class: a psycopg connection error
        # renders the full conninfo, which would leak the database host.
        return _plan_result(
            name, radius_m, status="unavailable", plan=None, error=type(exc).__name__
        )
    plan = _plan_from_row(row)
    if plan is None:
        return _plan_result(
            name, radius_m, status="unavailable", plan=None, error="empty_plan"
        )
    return _plan_result(name, radius_m, status="ok", plan=plan, error=None)


def _plan_from_row(row: Any) -> list[dict[str, Any]] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        value = row.get("QUERY PLAN")
    else:
        value = row[0]
    if isinstance(value, list):
        return value
    return None
