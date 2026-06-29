from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import secrets
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import psycopg
from psycopg.rows import dict_row

from app.api.errors import error_payload
from app.api.schemas import (
    AdminJobsResponse,
    AdminLocalSourceActionPlanResponse,
    AdminLocalSourceCoverageResponse,
    AdminSourcesResponse,
    AdminUserReportPrivacyRedaction,
    AdminUserReport,
    AdminUserReportsResponse,
    DataSource,
    FreshnessState,
    HealthStatus,
    IngestionJob,
    JobStatus,
    LatLng,
    LocalSourceActionPlan,
    LocalSourceCoverage,
    LocalSourceCoverageSummary,
    UserReportModerationRequest,
    UserReportModerationResponse,
    UserReportPrivacyRedactionRequest,
    UserReportPrivacyRedactionResponse,
)
from app.core.config import get_settings
from app.domain.realtime.local_source_coverage import (
    LocalSourceCoverageRecord,
    list_local_source_coverage,
    local_source_coverage_generated_at,
)
from app.domain.realtime.local_source_action_plan import build_local_source_action_plan
from app.domain.reports import (
    UserReportModerationRecord,
    UserReportPrivacyRedactionRecord,
    UserReportRepositoryUnavailable,
    list_pending_user_reports,
    moderate_user_report,
    redact_user_report_privacy,
)


router = APIRouter(prefix="/admin/v1", tags=["Admin"])
admin_bearer = HTTPBearer(auto_error=False)
REALTIME_FRESH_SECONDS = 10 * 60
REALTIME_DEGRADED_SECONDS = 30 * 60
REALTIME_STALE_SECONDS = 60 * 60
CENTRAL_BACKBONE_REQUIRED_FAMILIES = ("CWA", "WRA", "NCDR", "Civil IoT")
CENTRAL_BACKBONE_REQUIRED_ADAPTER_KEYS = (
    "official.cwa.rainfall",
    "official.cwa.tide_level",
    "official.wra.water_level",
    "official.ncdr.cap",
    "official.wra_iow.flood_depth",
    "official.civil_iot.flood_sensor",
    "official.civil_iot.sewer_water_level",
    "official.civil_iot.pump_water_level",
    "official.civil_iot.gate_water_level",
)
CENTRAL_BACKBONE_FAMILY_BY_ADAPTER_KEY = {
    "official.cwa.rainfall": "CWA",
    "official.cwa.tide_level": "CWA",
    "official.wra.water_level": "WRA",
    "official.wra_iow.flood_depth": "WRA",
    "official.ncdr.cap": "NCDR",
    "official.civil_iot.flood_sensor": "Civil IoT",
    "official.civil_iot.sewer_water_level": "Civil IoT",
    "official.civil_iot.pump_water_level": "Civil IoT",
    "official.civil_iot.gate_water_level": "Civil IoT",
}
REALTIME_ADAPTER_KEYS = frozenset(
    {
        "official.cwa.rainfall",
        "official.cwa.tide_level",
        "official.wra.water_level",
        "official.civil_iot.flood_sensor",
        "official.civil_iot.river_water_level",
        "official.civil_iot.pond_water_level",
        "official.civil_iot.sewer_water_level",
        "official.civil_iot.pump_water_level",
        "official.civil_iot.gate_water_level",
        "official.wra_iow.flood_depth",
        "local.taipei.sewer_water_level",
        "local.taipei.river_water_level",
        "local.taipei.pump_station",
        "local.taoyuan.flood_sensor",
        "local.taoyuan.water_level",
        "local.taoyuan.rainfall",
        "local.chiayi_city.water_level",
        "local.chiayi_city.rainfall",
        "local.taichung.water_level",
        "local.hsinchu_city.sewer_water_level",
        "local.hsinchu_city.flood_sensor",
        "local.nantou.sewer_water_level",
        "local.chiayi_county.flood_sensor",
        "local.kaohsiung.sewer_water_level",
        "local.kaohsiung.flood_sensor",
        "local.kaohsiung.rainfall",
        "local.keelung.water_level",
        "local.keelung.flood_sensor",
        "local.keelung.rainfall",
        "local.yunlin.water_level",
        "local.yilan.flood_sensor",
        "local.yilan.water_level",
        "local.tainan.flood_sensor",
    }
)
STATIC_SLOW_CADENCE_ADAPTER_KEYS = frozenset({"official.flood_potential.geojson"})
SOURCE_GATE_NAMES = {
    "official.cwa.rainfall": ("SOURCE_CWA_ENABLED", "SOURCE_CWA_API_ENABLED"),
    "official.cwa.tide_level": ("SOURCE_CWA_ENABLED", "SOURCE_CWA_API_ENABLED"),
    "official.wra.water_level": ("SOURCE_WRA_ENABLED", "SOURCE_WRA_API_ENABLED"),
    "official.ncdr.cap": ("SOURCE_NCDR_CAP_ENABLED", "SOURCE_NCDR_CAP_API_ENABLED"),
    "official.flood_potential.geojson": (
        "SOURCE_FLOOD_POTENTIAL_ENABLED",
        "SOURCE_FLOOD_POTENTIAL_GEOJSON_ENABLED",
    ),
    "official.civil_iot.flood_sensor": (
        "SOURCE_FLOOD_SENSOR_ENABLED",
        "SOURCE_FLOOD_SENSOR_API_ENABLED",
        "SOURCE_FLOOD_SENSOR_USE_LIVE",
    ),
    "official.civil_iot.river_water_level": (
        "SOURCE_CIVIL_IOT_RIVER_ENABLED",
        "SOURCE_CIVIL_IOT_RIVER_API_ENABLED",
    ),
    "official.civil_iot.pond_water_level": (
        "SOURCE_CIVIL_IOT_POND_ENABLED",
        "SOURCE_CIVIL_IOT_POND_API_ENABLED",
    ),
    "official.civil_iot.sewer_water_level": (
        "SOURCE_CIVIL_IOT_SEWER_ENABLED",
        "SOURCE_CIVIL_IOT_SEWER_API_ENABLED",
    ),
    "official.civil_iot.pump_water_level": (
        "SOURCE_CIVIL_IOT_PUMP_ENABLED",
        "SOURCE_CIVIL_IOT_PUMP_API_ENABLED",
    ),
    "official.civil_iot.gate_water_level": (
        "SOURCE_CIVIL_IOT_GATE_ENABLED",
        "SOURCE_CIVIL_IOT_GATE_API_ENABLED",
    ),
    "official.wra_iow.flood_depth": (
        "SOURCE_WRA_IOW_FLOOD_DEPTH_ENABLED",
        "SOURCE_WRA_IOW_FLOOD_DEPTH_API_ENABLED",
    ),
    "local.taipei.sewer_water_level": (
        "SOURCE_TAIPEI_SEWER_WATER_LEVEL_ENABLED",
        "SOURCE_TAIPEI_SEWER_WATER_LEVEL_API_ENABLED",
    ),
    "local.taipei.river_water_level": (
        "SOURCE_TAIPEI_RIVER_WATER_LEVEL_ENABLED",
        "SOURCE_TAIPEI_RIVER_WATER_LEVEL_API_ENABLED",
    ),
    "local.taipei.pump_station": (
        "SOURCE_TAIPEI_PUMP_STATION_ENABLED",
        "SOURCE_TAIPEI_PUMP_STATION_API_ENABLED",
    ),
    "local.taoyuan.flood_sensor": (
        "SOURCE_TAOYUAN_FLOOD_SENSOR_ENABLED",
        "SOURCE_TAOYUAN_FLOOD_SENSOR_API_ENABLED",
    ),
    "local.taoyuan.water_level": (
        "SOURCE_TAOYUAN_WATER_LEVEL_ENABLED",
        "SOURCE_TAOYUAN_WATER_LEVEL_API_ENABLED",
    ),
    "local.taoyuan.rainfall": (
        "SOURCE_TAOYUAN_RAINFALL_ENABLED",
        "SOURCE_TAOYUAN_RAINFALL_API_ENABLED",
    ),
    "local.chiayi_city.water_level": (
        "SOURCE_CHIAYI_CITY_WATER_LEVEL_ENABLED",
        "SOURCE_CHIAYI_CITY_WATER_LEVEL_API_ENABLED",
    ),
    "local.chiayi_city.rainfall": (
        "SOURCE_CHIAYI_CITY_RAINFALL_ENABLED",
        "SOURCE_CHIAYI_CITY_RAINFALL_API_ENABLED",
    ),
    "local.taichung.water_level": (
        "SOURCE_TAICHUNG_WATER_LEVEL_ENABLED",
        "SOURCE_TAICHUNG_WATER_LEVEL_API_ENABLED",
    ),
    "local.hsinchu_city.sewer_water_level": (
        "SOURCE_HSINCHU_CITY_SEWER_WATER_LEVEL_ENABLED",
        "SOURCE_HSINCHU_CITY_SEWER_WATER_LEVEL_API_ENABLED",
    ),
    "local.hsinchu_city.flood_sensor": (
        "SOURCE_HSINCHU_CITY_FLOOD_SENSOR_ENABLED",
        "SOURCE_HSINCHU_CITY_FLOOD_SENSOR_API_ENABLED",
    ),
    "local.nantou.sewer_water_level": (
        "SOURCE_NANTOU_SEWER_WATER_LEVEL_ENABLED",
        "SOURCE_NANTOU_SEWER_WATER_LEVEL_API_ENABLED",
    ),
    "local.chiayi_county.flood_sensor": (
        "SOURCE_CHIAYI_COUNTY_FLOOD_SENSOR_ENABLED",
        "SOURCE_CHIAYI_COUNTY_FLOOD_SENSOR_API_ENABLED",
    ),
    "local.kaohsiung.sewer_water_level": (
        "SOURCE_KAOHSIUNG_SEWER_WATER_LEVEL_ENABLED",
        "SOURCE_KAOHSIUNG_SEWER_WATER_LEVEL_API_ENABLED",
    ),
    "local.kaohsiung.flood_sensor": (
        "SOURCE_KAOHSIUNG_FLOOD_SENSOR_ENABLED",
        "SOURCE_KAOHSIUNG_FLOOD_SENSOR_API_ENABLED",
    ),
    "local.kaohsiung.rainfall": (
        "SOURCE_KAOHSIUNG_RAINFALL_ENABLED",
        "SOURCE_KAOHSIUNG_RAINFALL_API_ENABLED",
    ),
    "local.keelung.water_level": (
        "SOURCE_KEELUNG_WATER_LEVEL_ENABLED",
        "SOURCE_KEELUNG_WATER_LEVEL_API_ENABLED",
    ),
    "local.keelung.flood_sensor": (
        "SOURCE_KEELUNG_FLOOD_SENSOR_ENABLED",
        "SOURCE_KEELUNG_FLOOD_SENSOR_API_ENABLED",
    ),
    "local.keelung.rainfall": (
        "SOURCE_KEELUNG_RAINFALL_ENABLED",
        "SOURCE_KEELUNG_RAINFALL_API_ENABLED",
    ),
    "local.yunlin.water_level": (
        "SOURCE_YUNLIN_WATER_LEVEL_ENABLED",
        "SOURCE_YUNLIN_WATER_LEVEL_API_ENABLED",
    ),
    "local.yilan.flood_sensor": (
        "SOURCE_YILAN_FLOOD_SENSOR_ENABLED",
        "SOURCE_YILAN_FLOOD_SENSOR_API_ENABLED",
    ),
    "local.yilan.water_level": (
        "SOURCE_YILAN_WATER_LEVEL_ENABLED",
        "SOURCE_YILAN_WATER_LEVEL_API_ENABLED",
    ),
    "local.tainan.flood_sensor": (
        "SOURCE_TAINAN_FLOOD_SENSOR_ENABLED",
        "SOURCE_TAINAN_FLOOD_SENSOR_API_ENABLED",
    ),
}
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
TAIWAN_COUNTIES = (
    "臺北市",
    "新北市",
    "基隆市",
    "桃園市",
    "新竹市",
    "新竹縣",
    "苗栗縣",
    "臺中市",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義市",
    "嘉義縣",
    "臺南市",
    "高雄市",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "臺東縣",
    "澎湖縣",
    "金門縣",
    "連江縣",
)


@router.get("/jobs", response_model=AdminJobsResponse)
def list_admin_jobs(
    _admin: Annotated[str, Depends(_require_admin)],
    status: JobStatus | None = None,
    job_key: str | None = Query(default=None, min_length=1, max_length=120),
) -> AdminJobsResponse:
    settings = get_settings()
    try:
        jobs = _db_jobs(status=status, job_key=job_key)
    except (OSError, psycopg.Error) as exc:
        if settings.admin_sample_data_enabled:
            jobs = _filter_jobs(_sample_jobs(), status=status, job_key=job_key)
        else:
            raise _admin_repository_unavailable(
                "Admin jobs repository is temporarily unavailable."
            ) from exc
    return AdminJobsResponse(jobs=jobs)


@router.get("/sources", response_model=AdminSourcesResponse)
def list_admin_sources(
    _admin: Annotated[str, Depends(_require_admin)],
    health_status: HealthStatus | None = None,
) -> AdminSourcesResponse:
    settings = get_settings()
    try:
        sources = _db_sources(health_status=health_status)
    except (OSError, psycopg.Error) as exc:
        if settings.admin_sample_data_enabled:
            sources = _filter_sources(_sample_sources(), health_status=health_status)
        else:
            raise _admin_repository_unavailable(
                "Admin sources repository is temporarily unavailable."
            ) from exc
    return AdminSourcesResponse(sources=sources)


@router.get("/local-source-coverage", response_model=AdminLocalSourceCoverageResponse)
def list_admin_local_source_coverage(
    _admin: Annotated[str, Depends(_require_admin)],
) -> AdminLocalSourceCoverageResponse:
    records = list_local_source_coverage()
    return AdminLocalSourceCoverageResponse(
        generated_at=local_source_coverage_generated_at(),
        summary=_local_source_coverage_summary(records),
        counties=[
            LocalSourceCoverage(
                county=record.county,
                local_direct_statuses=list(record.local_direct_statuses),
                local_direct_complete=record.local_direct_complete,
                central_backbone_available=record.central_backbone_available,
                production_adapter_keys=list(record.production_adapter_keys),
                production_source_urls=list(record.production_source_urls),
                central_backbone_adapter_keys=list(record.central_backbone_adapter_keys),
                central_backbone_signal_types=list(record.central_backbone_signal_types),
                central_backbone_required_signal_types=list(
                    record.central_backbone_required_signal_types
                ),
                central_backbone_minimum_complete=record.central_backbone_minimum_complete,
                central_backbone_missing_signal_types=list(
                    record.central_backbone_missing_signal_types
                ),
                central_backbone_coverage_level=record.central_backbone_coverage_level,
                rainfall_available=record.rainfall_available,
                water_level_available=record.water_level_available,
                flood_depth_available=record.flood_depth_available,
                sewer_water_level_available=record.sewer_water_level_available,
                pump_or_gate_status_available=record.pump_or_gate_status_available,
                status_only_available=record.status_only_available,
                missing_signal_types=list(record.missing_signal_types),
                candidate_source_names=list(record.candidate_source_names),
                candidate_source_urls=list(record.candidate_source_urls),
                metadata_source_names=list(record.metadata_source_names),
                metadata_source_urls=list(record.metadata_source_urls),
                status_only_source_names=list(record.status_only_source_names),
                status_only_source_urls=list(record.status_only_source_urls),
                status_only_signal_types=list(record.status_only_signal_types),
                non_qualifying_source_names=list(record.non_qualifying_source_names),
                non_qualifying_source_urls=list(record.non_qualifying_source_urls),
                non_qualifying_source_reasons=list(
                    record.non_qualifying_source_reasons
                ),
                application_urls=list(record.application_urls),
                requires_application=record.requires_application,
                application_note=record.application_note,
                next_action_code=record.next_action_code,
                upgrade_priority=record.upgrade_priority,
                blocking_reason=record.blocking_reason,
                notes=list(record.notes),
            )
            for record in records
        ],
    )


@router.get("/local-source-action-plan", response_model=AdminLocalSourceActionPlanResponse)
def list_admin_local_source_action_plan(
    _admin: Annotated[str, Depends(_require_admin)],
) -> AdminLocalSourceActionPlanResponse:
    records = list_local_source_coverage()
    return AdminLocalSourceActionPlanResponse(
        generated_at=local_source_coverage_generated_at(),
        plan=LocalSourceActionPlan.model_validate(build_local_source_action_plan(records)),
    )


def _local_source_coverage_summary(
    records: tuple[LocalSourceCoverageRecord, ...],
) -> LocalSourceCoverageSummary:
    total_counties = len(records)
    local_direct_complete_count = sum(1 for record in records if record.local_direct_complete)
    central_backbone_minimum_complete_count = sum(
        1 for record in records if record.central_backbone_minimum_complete
    )
    available_central_adapter_keys = {
        adapter_key
        for record in records
        for adapter_key in record.central_backbone_adapter_keys
    }
    central_backbone_missing_adapter_keys = [
        adapter_key
        for adapter_key in CENTRAL_BACKBONE_REQUIRED_ADAPTER_KEYS
        if adapter_key not in available_central_adapter_keys
    ]
    available_central_families = {
        family
        for adapter_key in available_central_adapter_keys
        if (family := CENTRAL_BACKBONE_FAMILY_BY_ADAPTER_KEY.get(adapter_key)) is not None
    }
    central_backbone_missing_families = [
        family
        for family in CENTRAL_BACKBONE_REQUIRED_FAMILIES
        if family not in available_central_families
    ]
    return LocalSourceCoverageSummary(
        total_counties=total_counties,
        local_direct_complete_count=local_direct_complete_count,
        local_direct_incomplete_count=total_counties - local_direct_complete_count,
        local_direct_incomplete_counties=[
            record.county for record in records if not record.local_direct_complete
        ],
        central_backbone_minimum_complete_count=central_backbone_minimum_complete_count,
        central_backbone_minimum_incomplete_count=(
            total_counties - central_backbone_minimum_complete_count
        ),
        counties_missing_hydrologic_backbone=[
            record.county
            for record in records
            if "hydrologic_observation" in record.central_backbone_missing_signal_types
        ],
        request_official_authorization_count=_count_local_source_action(
            records,
            "request_official_authorization",
        ),
        verify_live_smoke_count=_count_local_source_action(records, "verify_live_smoke"),
        verify_public_api_contract_count=_count_local_source_action(
            records,
            "verify_public_api_contract",
        ),
        counties_requiring_official_authorization=_counties_for_local_source_action(
            records,
            "request_official_authorization",
        ),
        counties_requiring_live_smoke=_counties_for_local_source_action(
            records,
            "verify_live_smoke",
        ),
        counties_requiring_public_api_contract=_counties_for_local_source_action(
            records,
            "verify_public_api_contract",
        ),
        counties_requiring_metadata_release_monitoring=_counties_with_local_source_status(
            records,
            "metadata_only",
        ),
        counties_requiring_official_discovery=_counties_with_local_source_status(
            records,
            "not_found",
        ),
        central_backbone_required_families=list(CENTRAL_BACKBONE_REQUIRED_FAMILIES),
        central_backbone_missing_families=central_backbone_missing_families,
        central_backbone_family_complete=not central_backbone_missing_families,
        central_backbone_required_adapter_keys=list(CENTRAL_BACKBONE_REQUIRED_ADAPTER_KEYS),
        central_backbone_missing_adapter_keys=central_backbone_missing_adapter_keys,
    )


def _count_local_source_action(
    records: tuple[LocalSourceCoverageRecord, ...],
    action_code: str,
) -> int:
    return sum(1 for record in records if record.next_action_code == action_code)


def _counties_for_local_source_action(
    records: tuple[LocalSourceCoverageRecord, ...],
    action_code: str,
) -> list[str]:
    return [record.county for record in records if record.next_action_code == action_code]


def _counties_with_local_source_status(
    records: tuple[LocalSourceCoverageRecord, ...],
    status: str,
) -> list[str]:
    return [record.county for record in records if status in record.local_direct_statuses]


@router.get("/reports/pending", response_model=AdminUserReportsResponse)
def list_pending_admin_reports(
    _admin: Annotated[str, Depends(_require_admin)],
    limit: int = Query(default=100, ge=1, le=100),
) -> AdminUserReportsResponse:
    settings = get_settings()
    try:
        reports = list_pending_user_reports(database_url=settings.database_url, limit=limit)
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report moderation storage is temporarily unavailable.",
            )["error"],
        ) from exc
    return AdminUserReportsResponse(reports=[_admin_report_from_record(report) for report in reports])


@router.patch("/reports/{report_id}/moderation", response_model=UserReportModerationResponse)
def moderate_admin_report(
    report_id: UUID,
    request: UserReportModerationRequest,
    admin_actor: Annotated[str, Depends(_require_admin)],
) -> UserReportModerationResponse:
    settings = get_settings()
    try:
        report = moderate_user_report(
            database_url=settings.database_url,
            report_id=str(report_id),
            status=request.status,
            reason_code=request.reason_code,
            actor_ref=admin_actor,
        )
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report moderation storage is temporarily unavailable.",
            )["error"],
        ) from exc

    if report is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", "User report was not found.")["error"],
        )
    return UserReportModerationResponse(report=_admin_report_from_record(report))


@router.post(
    "/reports/{report_id}/privacy-redaction",
    response_model=UserReportPrivacyRedactionResponse,
)
def redact_admin_report_privacy(
    report_id: UUID,
    request: UserReportPrivacyRedactionRequest,
    admin_actor: Annotated[str, Depends(_require_admin)],
) -> UserReportPrivacyRedactionResponse:
    settings = get_settings()
    try:
        redaction = redact_user_report_privacy(
            database_url=settings.database_url,
            report_id=str(report_id),
            reason_code=request.reason_code,
            actor_ref=admin_actor,
        )
    except UserReportRepositoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_payload(
                "repository_unavailable",
                "User report privacy redaction storage is temporarily unavailable.",
            )["error"],
        ) from exc

    if redaction is None:
        raise HTTPException(
            status_code=404,
            detail=error_payload("not_found", "User report was not found.")["error"],
        )
    return UserReportPrivacyRedactionResponse(
        redaction=_privacy_redaction_from_record(redaction)
    )


async def _require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(admin_bearer)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail=error_payload("unauthorized", "Missing admin bearer token.")["error"],
        )

    settings = get_settings()
    if not settings.admin_bearer_token:
        raise HTTPException(
            status_code=403,
            detail=error_payload("forbidden", "Admin API is not configured.")["error"],
        )

    if not secrets.compare_digest(credentials.credentials, settings.admin_bearer_token):
        raise HTTPException(
            status_code=401,
            detail=error_payload("unauthorized", "Invalid admin bearer token.")["error"],
        )
    return "admin_api"


def _admin_repository_unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_payload("repository_unavailable", message)["error"],
    )


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _db_jobs(*, status: JobStatus | None, job_key: str | None) -> list[IngestionJob]:
    where: list[str] = []
    params: list[str] = []
    if status is not None:
        where.append("status = %s")
        params.append(status)
    if job_key is not None:
        where.append("job_key = %s")
        params.append(job_key)

    query = """
        SELECT
            job_key,
            adapter_key,
            started_at,
            finished_at,
            status,
            items_fetched,
            items_promoted,
            items_rejected,
            error_code,
            error_message,
            source_timestamp_min,
            source_timestamp_max
        FROM ingestion_jobs
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY COALESCE(started_at, created_at) DESC, created_at DESC LIMIT 100"

    settings = get_settings()
    with psycopg.connect(settings.database_url, connect_timeout=2, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [IngestionJob(**row) for row in cursor.fetchall()]


def _db_sources(*, health_status: HealthStatus | None) -> list[DataSource]:
    where: list[str] = []
    params: list[str] = []
    if health_status is not None:
        if health_status == "disabled":
            where.append("(ds.health_status = %s OR ds.is_enabled = false)")
        else:
            where.append("ds.health_status = %s")
        params.append(health_status)

    query = """
        SELECT
            ds.id::text AS id,
            ds.name,
            ds.adapter_key,
            ds.source_type,
            ds.license,
            ds.update_frequency,
            ds.last_success_at,
            ds.last_failure_at,
            ds.health_status,
            ds.legal_basis,
            ds.source_timestamp_min,
            ds.source_timestamp_max,
            ds.is_enabled,
            COALESCE(latest.latest_observed_at, ds.source_timestamp_max) AS latest_observed_at,
            raw.latest_fetched_at,
            COALESCE(
                latest.latest_ingested_at,
                latest_run.finished_at,
                latest_job.finished_at,
                ds.last_success_at
            ) AS latest_ingested_at,
            COALESCE(latest.row_count, 0)::integer AS row_count,
            COALESCE(coverage.covered_counties, ARRAY[]::text[]) AS covered_counties,
            COALESCE(coverage.covered_county_count, 0)::integer AS covered_county_count,
            COALESCE(coverage.fresh_county_count, 0)::integer AS fresh_county_count,
            COALESCE(coverage.stale_county_count, 0)::integer AS stale_county_count,
            COALESCE(coverage.station_count_by_county, '{}'::jsonb) AS station_count_by_county,
            COALESCE(latest_run.status, latest_job.status, ds.health_status, 'unknown') AS upstream_status
        FROM data_sources ds
        LEFT JOIN (
            SELECT
                adapter_key,
                max(observed_at) AS latest_observed_at,
                max(ingested_at) AS latest_ingested_at,
                count(*) AS row_count
            FROM official_realtime_latest
            GROUP BY adapter_key
        ) latest ON latest.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT
                adapter_key,
                array_agg(county ORDER BY county) AS covered_counties,
                count(*)::integer AS covered_county_count,
                count(*) FILTER (
                    WHERE latest_county_observed_at >= now() - interval '1 hour'
                )::integer AS fresh_county_count,
                count(*) FILTER (
                    WHERE latest_county_observed_at < now() - interval '1 hour'
                )::integer AS stale_county_count,
                jsonb_object_agg(county, station_count ORDER BY county) AS station_count_by_county
            FROM (
                SELECT
                    latest.adapter_key,
                    NULLIF(e.properties ->> 'county', '') AS county,
                    count(DISTINCT latest.station_id)::integer AS station_count,
                    max(latest.observed_at) AS latest_county_observed_at
                FROM official_realtime_latest latest
                LEFT JOIN evidence e ON e.id = latest.evidence_id
                WHERE NULLIF(e.properties ->> 'county', '') IS NOT NULL
                GROUP BY latest.adapter_key, NULLIF(e.properties ->> 'county', '')
            ) county_coverage
            GROUP BY adapter_key
        ) coverage ON coverage.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT DISTINCT ON (adapter_key)
                adapter_key,
                fetched_at AS latest_fetched_at
            FROM raw_snapshots
            ORDER BY adapter_key, fetched_at DESC
        ) raw ON raw.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT DISTINCT ON (adapter_key)
                adapter_key,
                status,
                finished_at
            FROM adapter_runs
            ORDER BY adapter_key, COALESCE(finished_at, created_at) DESC
        ) latest_run ON latest_run.adapter_key = ds.adapter_key
        LEFT JOIN (
            SELECT DISTINCT ON (adapter_key)
                adapter_key,
                status,
                finished_at
            FROM ingestion_jobs
            WHERE adapter_key IS NOT NULL
            ORDER BY adapter_key, COALESCE(finished_at, created_at) DESC
        ) latest_job ON latest_job.adapter_key = ds.adapter_key
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY ds.name ASC, ds.adapter_key ASC LIMIT 100"

    settings = get_settings()
    with psycopg.connect(settings.database_url, connect_timeout=2, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return [_data_source_from_row(row) for row in cursor.fetchall()]


def _filter_jobs(
    jobs: list[IngestionJob], *, status: JobStatus | None, job_key: str | None
) -> list[IngestionJob]:
    if status is not None:
        jobs = [job for job in jobs if job.status == status]
    if job_key is not None:
        jobs = [job for job in jobs if job.job_key == job_key]
    return jobs


def _filter_sources(
    sources: list[DataSource], *, health_status: HealthStatus | None
) -> list[DataSource]:
    if health_status is not None:
        if health_status == "disabled":
            sources = [
                source
                for source in sources
                if source.health_status == health_status or not source.is_enabled
            ]
        else:
            sources = [source for source in sources if source.health_status == health_status]
    return sources


def _data_source_from_row(row: dict) -> DataSource:
    is_enabled = bool(row.get("is_enabled", True))
    health_status = cast(HealthStatus, row.get("health_status") or "unknown")
    if not is_enabled:
        health_status = "disabled"
    latest_observed_at = row.get("latest_observed_at") or row.get("source_timestamp_max")
    latest_ingested_at = row.get("latest_ingested_at") or row.get("last_success_at")
    upstream_status = _upstream_status(row, is_enabled=is_enabled)
    covered_counties = _string_list(row.get("covered_counties"))
    station_count_by_county = _int_mapping(row.get("station_count_by_county"))
    covered_county_count = _optional_nonnegative_int(
        row.get("covered_county_count"),
        default=len(covered_counties),
    )
    fresh_county_count = _optional_nonnegative_int(row.get("fresh_county_count"), default=0)
    stale_county_count = _optional_nonnegative_int(
        row.get("stale_county_count"),
        default=max(0, covered_county_count - fresh_county_count),
    )
    return DataSource(
        **{
            "id": row["id"],
            "name": row["name"],
            "adapter_key": row["adapter_key"],
            "source_type": row["source_type"],
            "license": row.get("license") or "",
            "update_frequency": row.get("update_frequency") or "",
            "last_success_at": row.get("last_success_at"),
            "last_failure_at": row.get("last_failure_at"),
            "health_status": health_status,
            "legal_basis": row["legal_basis"],
            "source_timestamp_min": row.get("source_timestamp_min"),
            "source_timestamp_max": row.get("source_timestamp_max"),
            "is_enabled": is_enabled,
            "latest_observed_at": latest_observed_at,
            "latest_fetched_at": row.get("latest_fetched_at"),
            "latest_ingested_at": latest_ingested_at,
            "lag_seconds": _lag_seconds(latest_observed_at),
            "row_count": row.get("row_count") or 0,
            "covered_counties": covered_counties,
            "covered_county_count": covered_county_count,
            "fresh_county_count": fresh_county_count,
            "stale_county_count": stale_county_count,
            "station_count_by_county": station_count_by_county,
            "missing_counties": _missing_counties(covered_counties),
            "upstream_status": upstream_status,
            "enabled_gates": _enabled_gates(row["adapter_key"], is_enabled=is_enabled),
            "freshness_state": _freshness_state(
                adapter_key=row["adapter_key"],
                health_status=health_status,
                is_enabled=is_enabled,
                source_timestamp_min=row.get("source_timestamp_min"),
                source_timestamp_max=row.get("source_timestamp_max"),
                latest_observed_at=latest_observed_at,
                upstream_status=upstream_status,
            ),
        }
    )


def _upstream_status(row: dict, *, is_enabled: bool) -> str:
    if not is_enabled:
        return "disabled"
    return str(row.get("upstream_status") or row.get("health_status") or "unknown")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item) for item in value if str(item or "").strip()})


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, int] = {}
    for key, raw_count in value.items():
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            parsed[str(key)] = count
    return dict(sorted(parsed.items()))


def _optional_nonnegative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _missing_counties(covered_counties: list[str]) -> list[str]:
    covered = set(covered_counties)
    return [county for county in TAIWAN_COUNTIES if county not in covered]


def _lag_seconds(latest_observed_at: datetime | None) -> int | None:
    if latest_observed_at is None:
        return None
    observed_at = _aware_utc(latest_observed_at)
    return max(0, int((_now() - observed_at).total_seconds()))


def _freshness_state(
    *,
    adapter_key: str,
    health_status: HealthStatus,
    is_enabled: bool,
    source_timestamp_min: datetime | None,
    source_timestamp_max: datetime | None,
    latest_observed_at: datetime | None,
    upstream_status: str,
) -> FreshnessState:
    if not is_enabled:
        return "stale"
    if upstream_status == "failed" or health_status == "failed":
        return "failed"
    if adapter_key == "official.ncdr.cap":
        return _ncdr_cap_freshness_state(
            effective_at=source_timestamp_min,
            expires_at=source_timestamp_max,
            health_status=health_status,
        )
    if adapter_key in STATIC_SLOW_CADENCE_ADAPTER_KEYS:
        if latest_observed_at is not None or upstream_status == "succeeded":
            return "fresh"
        return "stale"
    if latest_observed_at is None:
        return "stale"
    if adapter_key in REALTIME_ADAPTER_KEYS:
        age_seconds = _lag_seconds(latest_observed_at)
        if age_seconds is None:
            return "stale"
        if age_seconds <= REALTIME_FRESH_SECONDS:
            return "fresh"
        if age_seconds <= REALTIME_DEGRADED_SECONDS:
            return "degraded"
        if age_seconds <= REALTIME_STALE_SECONDS:
            return "stale"
        return "failed"
    if health_status == "healthy":
        return "fresh"
    if health_status == "degraded":
        return "degraded"
    return "stale"


def _ncdr_cap_freshness_state(
    *,
    effective_at: datetime | None,
    expires_at: datetime | None,
    health_status: HealthStatus,
) -> FreshnessState:
    if effective_at is None or expires_at is None:
        return "stale"
    resolved_effective_at = _aware_utc(effective_at)
    resolved_expires_at = _aware_utc(expires_at)
    now = _now()
    if resolved_expires_at < now:
        return "stale"
    if resolved_effective_at > now:
        return "degraded"
    if health_status == "degraded":
        return "degraded"
    return "fresh"


def _enabled_gates(adapter_key: str, *, is_enabled: bool) -> list[str]:
    if not is_enabled:
        return []
    gates = ["data_sources.is_enabled"]
    gates.extend(
        gate_name
        for gate_name in SOURCE_GATE_NAMES.get(adapter_key, ())
        if _env_flag_enabled(gate_name)
    )
    return gates


def _env_flag_enabled(name: str) -> bool:
    raw_value = os.getenv(name)
    return raw_value is not None and raw_value.strip().lower() in TRUE_VALUES


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _admin_report_from_record(report: UserReportModerationRecord) -> AdminUserReport:
    return AdminUserReport(
        report_id=report.id,
        status=report.status,
        point=LatLng(lat=report.lat, lng=report.lng),
        summary=report.summary,
        created_at=report.created_at,
        reviewed_at=report.reviewed_at,
    )


def _privacy_redaction_from_record(
    redaction: UserReportPrivacyRedactionRecord,
) -> AdminUserReportPrivacyRedaction:
    return AdminUserReportPrivacyRedaction(
        report_id=redaction.id,
        status=redaction.status,
        privacy_level=redaction.privacy_level,
        redacted_at=redaction.redacted_at,
    )


def _sample_jobs() -> list[IngestionJob]:
    now = _now()
    return [
        IngestionJob(
            job_key="ingest.cwa.rainfall",
            adapter_key="official.cwa.rainfall",
            started_at=now - timedelta(minutes=12),
            finished_at=now - timedelta(minutes=11),
            status="succeeded",
            items_fetched=2,
            items_promoted=2,
            items_rejected=0,
            source_timestamp_min=now - timedelta(minutes=20),
            source_timestamp_max=now - timedelta(minutes=15),
        ),
        IngestionJob(
            job_key="ingest.news.search",
            adapter_key="news.public_web.sample",
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=29),
            status="succeeded",
            items_fetched=2,
            items_promoted=2,
            items_rejected=0,
            source_timestamp_min=now - timedelta(hours=1),
            source_timestamp_max=now - timedelta(minutes=45),
        ),
    ]


def _sample_sources() -> list[DataSource]:
    now = _now()
    cwa_latest_observed_at = now - timedelta(minutes=5)
    cwa_latest_ingested_at = now - timedelta(minutes=4)
    news_latest_observed_at = now - timedelta(minutes=45)
    news_latest_ingested_at = now - timedelta(minutes=29)
    return [
        DataSource(
            id="cwa-rainfall",
            name="CWA rainfall observations",
            adapter_key="official.cwa.rainfall",
            source_type="official",
            license="Government open data",
            update_frequency="PT10M",
            last_success_at=cwa_latest_ingested_at,
            health_status="healthy",
            legal_basis="L1",
            source_timestamp_min=now - timedelta(minutes=20),
            source_timestamp_max=cwa_latest_observed_at,
            latest_observed_at=cwa_latest_observed_at,
            latest_fetched_at=now - timedelta(minutes=4),
            latest_ingested_at=cwa_latest_ingested_at,
            lag_seconds=5 * 60,
            row_count=2,
            upstream_status="succeeded",
            freshness_state="fresh",
        ),
        DataSource(
            id="news-public-web-sample",
            name="Sample L2 public web evidence",
            adapter_key="news.public_web.sample",
            source_type="news",
            license="Fixture only",
            update_frequency="fixture_only",
            last_success_at=news_latest_ingested_at,
            health_status="healthy",
            legal_basis="L2",
            source_timestamp_min=now - timedelta(hours=1),
            source_timestamp_max=news_latest_observed_at,
            latest_observed_at=news_latest_observed_at,
            latest_fetched_at=news_latest_ingested_at,
            latest_ingested_at=news_latest_ingested_at,
            lag_seconds=45 * 60,
            row_count=2,
            upstream_status="succeeded",
            freshness_state="fresh",
        ),
    ]
