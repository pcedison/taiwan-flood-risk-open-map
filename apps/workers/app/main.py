from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from app.adapters.registry import enabled_adapter_keys
from app.cli import gdelt, maintenance_cli, profiles_cli, queue_cli, runtime_cli
from app.cli.parser import build_parser, parse_query_heat_periods
from app.config import load_worker_settings
from app.jobs.sample import run_sample_job
from app.logging import log_event
from app.scheduler import (
    run_enabled_adapters_loop,
    run_enabled_adapters_once,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_worker_settings()

    if args.list_adapters:
        for adapter_key in enabled_adapter_keys(settings):
            print(adapter_key)
        return 0

    if args.rehearse_gdelt_news_backfill:
        return gdelt.rehearse_gdelt_news_backfill(args=args, settings=settings)

    if args.run_gdelt_news_production_candidate:
        return gdelt.run_gdelt_news_production_candidate(args=args, settings=settings)

    if args.validate_gdelt_live_acceptance:
        from app.jobs.gdelt_live_acceptance import (
            render_gdelt_live_acceptance_json,
            validate_gdelt_live_acceptance_file,
        )

        gdelt_acceptance = validate_gdelt_live_acceptance_file(
            Path(args.validate_gdelt_live_acceptance)
        )
        print(render_gdelt_live_acceptance_json(gdelt_acceptance))
        return 1 if gdelt_acceptance.status == "failed" else 0

    if args.list_runtime_dead_letter_jobs:
        return queue_cli.list_runtime_dead_letter_jobs(
            settings=settings,
            database_url=args.database_url,
            queue_name=args.dead_letter_queue_name,
            limit=args.dead_letter_limit,
        )

    if args.summarize_runtime_dead_letter_jobs:
        return queue_cli.summarize_runtime_dead_letter_jobs(
            settings=settings,
            database_url=args.database_url,
            queue_name=args.dead_letter_queue_name,
        )

    if args.export_runtime_queue_metrics:
        return queue_cli.export_runtime_queue_metrics(
            settings=settings,
            database_url=args.database_url,
            queue_name=args.dead_letter_queue_name,
            output_format=args.runtime_queue_metrics_format,
            metrics_path=args.runtime_queue_metrics_path,
        )

    if args.requeue_runtime_job:
        return queue_cli.requeue_runtime_job(
            settings=settings,
            database_url=args.database_url,
            job_id=args.requeue_runtime_job,
            reset_attempts=not args.requeue_keep_attempts,
            requested_by=args.requeue_requested_by,
            reason=args.requeue_reason,
        )

    if args.work_runtime_queue:
        return queue_cli.work_runtime_queue(
            settings=settings,
            once=args.once,
            max_ticks=args.max_ticks,
            persist=args.persist,
            database_url=args.database_url,
        )

    if args.enqueue_runtime_jobs:
        return queue_cli.enqueue_runtime_jobs(
            settings=settings,
            scheduler=args.scheduler,
            once=args.once,
            max_ticks=args.max_ticks,
        )

    if args.maintenance:
        return maintenance_cli.run_maintenance(
            settings=settings,
            scheduler=args.scheduler,
            once=args.once,
            max_ticks=args.max_ticks,
            periods=parse_query_heat_periods(args.query_heat_periods),
            retention_days=args.query_heat_retention_days,
            tile_layer_id=args.tile_layer_id,
            tile_feature_limit=args.tile_feature_limit,
            tile_prune_limit=args.tile_prune_limit,
        )

    if args.aggregate_query_heat:
        return maintenance_cli.aggregate_query_heat(
            settings=settings,
            periods=parse_query_heat_periods(args.query_heat_periods),
            created_at_start=args.query_heat_created_at_start,
            created_at_end=args.query_heat_created_at_end,
            retention_days=args.query_heat_retention_days,
        )

    if args.seed_risk_profiles:
        return profiles_cli.seed_risk_profiles(
            settings=settings,
            database_url=args.database_url,
            profile_kind=args.seed_profile_kind,
            source_key=args.profile_seed_source_key,
            limit=args.profile_seed_limit,
            grid_system=args.profile_grid_system,
            grid_resolution=args.profile_grid_resolution,
            include_privacy_bucket_fallback=args.profile_include_privacy_bucket_fallback,
            enqueue_refresh=not args.profile_no_enqueue_refresh,
        )

    if args.rebuild_risk_profile:
        return profiles_cli.rebuild_one_risk_profile(
            settings=settings,
            database_url=args.database_url,
            profile_kind=args.profile_kind,
            profile_key=args.profile_key,
        )

    if args.work_profile_refresh_jobs:
        return profiles_cli.work_profile_refresh_jobs(
            settings=settings,
            database_url=args.database_url,
            worker_id=args.profile_refresh_worker_id,
            limit=args.profile_refresh_limit,
            lease_seconds=args.profile_refresh_lease_seconds,
            statement_timeout_ms=args.profile_refresh_statement_timeout_ms,
            cooldown_seconds=args.profile_refresh_cooldown_seconds,
        )

    if args.refresh_tile_features:
        return maintenance_cli.refresh_tile_features(
            settings=settings,
            layer_id=args.tile_layer_id,
            limit=args.tile_feature_limit,
        )

    if args.once:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        return 0

    if args.run_enabled_adapters:
        if args.persist:
            if args.scheduler:
                return runtime_cli.run_managed_enabled_adapters_loop(
                    settings=settings,
                    database_url=args.database_url,
                    once=args.once,
                    max_ticks=args.max_ticks,
                )
            return runtime_cli.run_managed_enabled_adapters(
                settings=settings,
                database_url=args.database_url,
            )
        result = run_enabled_adapters_once(settings=settings, job_key="worker.runtime.run_once")
        return 1 if result.has_alerts else 0

    if args.scheduler:
        results = run_enabled_adapters_loop(
            settings=settings,
            max_ticks=max(1, args.max_ticks) if args.max_ticks is not None else None,
        )
        return 1 if any(result.has_alerts for result in results) else 0

    if args.run_official_demo:
        return runtime_cli.run_official_demo(
            settings=settings,
            persist=args.persist,
            database_url=args.database_url,
        )

    log_event("worker.started", mode="placeholder", enabled_adapters=enabled_adapter_keys(settings))
    while True:
        run_sample_job(enabled_adapters=enabled_adapter_keys(settings))
        time.sleep(settings.worker_idle_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
