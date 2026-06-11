"""GDELT public-news backfill CLI commands (rehearsal and production candidate)."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime

from app.adapters.news.public_web import GdeltQueryPlace
from app.cli.persistence import build_demo_persistence_writers
from app.config import WorkerSettings, env_flag, env_int, env_list, env_str
from app.jobs.historical_news_backfill import (
    DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
    DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
    DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
    HistoricalNewsBackfillConfig,
    ensure_historical_news_backfill_production_candidate_gates,
    run_historical_news_backfill_production_candidate,
    run_historical_news_backfill_rehearsal,
)
from app.jobs.taiwan_news_query_plan import (
    DEFAULT_TERMS_PER_QUERY,
    TaiwanQueryScope,
    build_taiwan_flood_news_queries,
    load_taiwan_geocoder_query_places,
)


def _build_gdelt_news_backfill_config(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
    fetched_at: datetime,
    production_database_url: str | None = None,
) -> HistoricalNewsBackfillConfig:
    is_production_candidate = bool(
        getattr(args, "run_gdelt_news_production_candidate", False)
    )
    query_env_name = (
        "GDELT_PRODUCTION_QUERIES"
        if is_production_candidate
        else "GDELT_REHEARSAL_QUERIES"
    )
    max_records_env_name = (
        "GDELT_PRODUCTION_MAX_RECORDS_PER_QUERY"
        if is_production_candidate
        else "GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY"
    )
    cadence_env_name = (
        "GDELT_PRODUCTION_CADENCE_SECONDS"
        if is_production_candidate
        else "GDELT_REHEARSAL_CADENCE_SECONDS"
    )

    env_queries = env_list(os.environ, query_env_name)
    queries = tuple(args.gdelt_query or ()) or env_queries
    query_places, query_plan_metadata = _build_gdelt_geocoder_query_plan(args)
    if not queries and query_places:
        generated_queries = build_taiwan_flood_news_queries(
            (place.term for place in query_places),
            terms_per_query=_positive_int(
                args.gdelt_geocoder_terms_per_query
                or env_int(
                    os.environ,
                    "GDELT_GEOCODER_TERMS_PER_QUERY",
                    default=DEFAULT_TERMS_PER_QUERY,
                ),
                default=DEFAULT_TERMS_PER_QUERY,
            ),
        )
        queries = _slice_generated_queries(
            generated_queries,
            offset=args.gdelt_query_offset
            if args.gdelt_query_offset is not None
            else env_int(os.environ, "GDELT_QUERY_OFFSET", default=0),
            limit=args.gdelt_query_limit
            if args.gdelt_query_limit is not None
            else env_int(os.environ, "GDELT_QUERY_LIMIT", default=0),
        )
        query_plan_metadata = {
            **query_plan_metadata,
            "generated_query_count_total": len(generated_queries),
            "generated_query_offset": max(
                0,
                args.gdelt_query_offset
                if args.gdelt_query_offset is not None
                else env_int(os.environ, "GDELT_QUERY_OFFSET", default=0),
            ),
            "generated_query_limit": (
                args.gdelt_query_limit
                if args.gdelt_query_limit is not None
                else env_int(os.environ, "GDELT_QUERY_LIMIT", default=0)
            )
            or None,
        }
    max_records = (
        args.gdelt_max_records
        if args.gdelt_max_records is not None
        else env_int(
            os.environ,
            max_records_env_name,
            default=DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY,
        )
    )
    cadence_seconds = args.gdelt_cadence_seconds
    if cadence_seconds is None:
        cadence_seconds = env_int(
            os.environ,
            cadence_env_name,
            default=DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS,
        )

    return HistoricalNewsBackfillConfig(
        start_datetime=args.gdelt_start,
        end_datetime=args.gdelt_end,
        fetched_at=fetched_at,
        queries=queries if queries is not None else DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES,
        max_records_per_query=max_records,
        request_cadence_seconds=cadence_seconds,
        gdelt_source_enabled=args.gdelt_source_enabled
        or env_flag(os.environ, "GDELT_SOURCE_ENABLED"),
        gdelt_backfill_enabled=args.gdelt_backfill_enabled
        or env_flag(os.environ, "GDELT_BACKFILL_ENABLED"),
        source_news_enabled=settings.source_news_enabled is True,
        source_terms_review_ack=settings.source_terms_review_ack,
        gdelt_production_ingestion_enabled=args.gdelt_production_enabled
        or env_flag(os.environ, "GDELT_PRODUCTION_INGESTION_ENABLED"),
        gdelt_production_approval_evidence_path=args.gdelt_approval_evidence_path
        or env_str(os.environ, "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH"),
        gdelt_production_approval_evidence_ack=args.gdelt_approval_evidence_ack
        or env_flag(os.environ, "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK"),
        production_persist_intent=args.persist,
        production_database_url=production_database_url,
        query_places=query_places,
        require_query_place_match=args.gdelt_require_geocoder_match
        or env_flag(os.environ, "GDELT_REQUIRE_GEOCODER_MATCH"),
        progress_log_interval=args.gdelt_progress_log_interval
        if args.gdelt_progress_log_interval is not None
        else env_int(os.environ, "GDELT_PROGRESS_LOG_INTERVAL", default=0),
        query_plan_metadata=query_plan_metadata,
    )


def _build_gdelt_geocoder_query_plan(
    args: argparse.Namespace,
) -> tuple[tuple[GdeltQueryPlace, ...], dict[str, object]]:
    raw_paths = tuple(args.gdelt_geocoder_term_path or ()) or env_list(
        os.environ,
        "GDELT_GEOCODER_TERM_PATHS",
    )
    if not raw_paths:
        return (), {}

    scopes = _parse_gdelt_geocoder_scopes(
        args.gdelt_geocoder_scopes
        or os.environ.get("GDELT_GEOCODER_SCOPES")
        or "village,road"
    )
    term_limit = (
        args.gdelt_geocoder_term_limit
        if args.gdelt_geocoder_term_limit is not None
        else env_int(os.environ, "GDELT_GEOCODER_TERM_LIMIT", default=0)
    )
    loaded_places = load_taiwan_geocoder_query_places(
        raw_paths,
        scopes=scopes,
        limit=term_limit if term_limit and term_limit > 0 else None,
    )
    query_places = tuple(
        GdeltQueryPlace(
            term=place.term,
            lat=place.lat,
            lng=place.lng,
            scope=place.scope,
            canonical_name=place.canonical_name,
            precision=place.precision,
            source_key=place.source_key,
            source_record_id=place.source_record_id,
        )
        for place in loaded_places
    )
    return query_places, {
        "geocoder_query_plan": True,
        "geocoder_term_paths": tuple(str(path) for path in raw_paths),
        "geocoder_scopes": scopes,
        "geocoder_term_limit": term_limit or None,
        "geocoder_query_place_count_total": len(query_places),
    }


def _parse_gdelt_geocoder_scopes(raw: str) -> tuple[TaiwanQueryScope, ...]:
    allowed: set[TaiwanQueryScope] = {"county", "town", "village", "road"}
    scopes: list[TaiwanQueryScope] = []
    for part in raw.replace("\n", ",").split(","):
        scope = part.strip().lower()
        if scope in allowed and scope not in scopes:
            scopes.append(scope)  # type: ignore[arg-type]
    return tuple(scopes) or ("village", "road")


def _slice_generated_queries(
    queries: tuple[str, ...],
    *,
    offset: int,
    limit: int,
) -> tuple[str, ...]:
    start = max(0, offset)
    if limit and limit > 0:
        return queries[start : start + limit]
    return queries[start:]


def _positive_int(value: int, *, default: int) -> int:
    return value if value > 0 else default


def _validate_gdelt_bounded_window(args: argparse.Namespace) -> int | None:
    if args.gdelt_start is None or args.gdelt_end is None:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "missing_bounded_window",
                    "message": "--gdelt-start and --gdelt-end are required",
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 1
    if args.gdelt_start >= args.gdelt_end:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "invalid_bounded_window",
                    "message": "--gdelt-start must be earlier than --gdelt-end",
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 1
    return None


def rehearse_gdelt_news_backfill(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    window_exit_code = _validate_gdelt_bounded_window(args)
    if window_exit_code is not None:
        return window_exit_code

    config = _build_gdelt_news_backfill_config(
        args=args,
        settings=settings,
        fetched_at=datetime.now(UTC),
    )

    try:
        result = run_historical_news_backfill_rehearsal(
            config,
            mode=args.gdelt_rehearsal_mode,
        )
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": str(exc),
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result.as_payload(), sort_keys=True))
    return 0


def run_gdelt_news_production_candidate(
    *,
    args: argparse.Namespace,
    settings: WorkerSettings,
) -> int:
    window_exit_code = _validate_gdelt_bounded_window(args)
    if window_exit_code is not None:
        return window_exit_code
    if args.gdelt_promotion_limit is not None and args.gdelt_promotion_limit < 1:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "invalid_promotion_limit",
                    "message": "--gdelt-promotion-limit must be greater than 0",
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 1

    resolved_database_url = args.database_url or settings.database_url
    config = _build_gdelt_news_backfill_config(
        args=args,
        settings=settings,
        fetched_at=datetime.now(UTC),
        production_database_url=resolved_database_url,
    )

    try:
        ensure_historical_news_backfill_production_candidate_gates(config)
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "mode": "production-candidate",
                    "reason": str(exc),
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 0

    persistence = build_demo_persistence_writers(
        settings,
        database_url=args.database_url,
    )
    try:
        result = run_historical_news_backfill_production_candidate(
            config,
            staging_writer=persistence.staging_writer,
            run_writer=persistence.run_writer,
            promotion_writer=persistence.promotion_writer,
            promotion_limit=args.gdelt_promotion_limit,
        )
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "mode": "production-candidate",
                    "reason": str(exc),
                    "network_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "mode": "production-candidate",
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result.as_payload(), sort_keys=True))
    return 1 if result.failed else 0
