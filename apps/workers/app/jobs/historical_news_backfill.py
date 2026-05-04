from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.adapters.news.public_web import (
    GDELT_MAX_RECORDS_PER_QUERY,
    FetchJson,
    GdeltPublicNewsBackfillAdapter,
    Sleep,
)
from app.adapters.contracts import AdapterRunResult
from app.jobs.ingestion import AdapterBatchRunSummary, run_adapter_batch
from app.pipelines.promotion import (
    EvidencePromotionWriter,
    PromotionResult,
    promote_accepted_staging,
)
from app.pipelines.staging import AdapterStagingBatch, build_staging_batch
from app.pipelines.staging import StagingBatchWriter
from app.jobs.ingestion import IngestionRunSummaryWriter


DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES = (
    '(淹水 OR 積淹水 OR 積水 OR 豪雨) (台灣 OR 台北 OR 新北 OR 桃園 OR 新竹 OR 苗栗 OR 台中 OR 彰化 OR 雲林 OR 嘉義 OR 台南 OR 高雄 OR 屏東 OR 宜蘭 OR 花蓮 OR 台東)',
    '(道路淹水 OR 地下道淹水 OR 排水不及 OR 側溝排水不及) sourcecountry:TW',
)
DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY = 10
DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS = 60
GDELT_BACKFILL_ADAPTER_KEY = "news.public_web.gdelt_backfill"
DEFAULT_GDELT_PRODUCTION_CANDIDATE_JOB_KEY = "worker.gdelt_news.production_candidate"

GdeltRehearsalMode = Literal["dry-run", "staging-batch"]
GdeltProductionCandidateStatus = Literal["succeeded", "partial", "failed", "skipped"]


@dataclass(frozen=True)
class HistoricalNewsBackfillConfig:
    start_datetime: datetime
    end_datetime: datetime
    fetched_at: datetime
    queries: tuple[str, ...] = DEFAULT_TAIWAN_FLOOD_NEWS_QUERIES
    max_records_per_query: int = DEFAULT_GDELT_REHEARSAL_MAX_RECORDS_PER_QUERY
    request_cadence_seconds: int = DEFAULT_GDELT_REHEARSAL_CADENCE_SECONDS
    gdelt_source_enabled: bool = False
    gdelt_backfill_enabled: bool = False
    source_news_enabled: bool = False
    source_terms_review_ack: bool = False
    gdelt_production_ingestion_enabled: bool = False
    gdelt_production_approval_evidence_path: str | None = None
    gdelt_production_approval_evidence_ack: bool = False
    production_persist_intent: bool = False
    production_database_url: str | None = None
    fetch_json: FetchJson | None = None
    sleep: Sleep | None = None


@dataclass(frozen=True)
class HistoricalNewsBackfillRehearsalResult:
    mode: GdeltRehearsalMode
    adapter_key: str
    fetched_count: int
    normalized_count: int
    rejected_count: int
    metadata: dict[str, Any]
    batch: AdapterStagingBatch | None = None

    @property
    def status(self) -> str:
        return "succeeded"

    def as_payload(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "mode": self.mode,
            "adapter_key": self.adapter_key,
            "fetched_count": self.fetched_count,
            "normalized_count": self.normalized_count,
            "rejected_count": self.rejected_count,
            "metadata": self.metadata,
        }
        if self.batch is not None:
            payload["raw_ref"] = self.batch.raw_snapshot.raw_ref
            payload["accepted_count"] = len(self.batch.accepted)
            payload["staging_rejected_count"] = len(self.batch.rejected)
        return payload


@dataclass(frozen=True)
class HistoricalNewsBackfillProductionCandidateResult:
    status: GdeltProductionCandidateStatus
    metadata: dict[str, Any]
    summary: AdapterBatchRunSummary | None = None
    promoted: int = 0
    evidence_ids: tuple[str, ...] = ()
    reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "mode": "production-candidate",
            "adapter_key": GDELT_BACKFILL_ADAPTER_KEY,
            "promoted": self.promoted,
            "evidence_ids": list(self.evidence_ids),
            "metadata": self.metadata,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.error_code is not None:
            payload["error_code"] = self.error_code
        if self.error_message is not None:
            payload["error_message"] = self.error_message
        if self.summary is not None:
            payload["run"] = {
                "adapter_key": self.summary.adapter_key,
                "status": self.summary.status,
                "items_fetched": self.summary.items_fetched,
                "accepted_count": self.summary.items_promoted,
                "rejected_count": self.summary.items_rejected,
                "raw_ref": self.summary.raw_ref,
                "source_timestamp_min": (
                    self.summary.source_timestamp_min.isoformat()
                    if self.summary.source_timestamp_min is not None
                    else None
                ),
                "source_timestamp_max": (
                    self.summary.source_timestamp_max.isoformat()
                    if self.summary.source_timestamp_max is not None
                    else None
                ),
            }
        return payload


def build_historical_news_backfill_batch(
    config: HistoricalNewsBackfillConfig,
) -> AdapterStagingBatch:
    _ensure_historical_news_backfill_gates(config)
    return build_staging_batch(_run_historical_news_backfill_adapter(config))


def run_historical_news_backfill_rehearsal(
    config: HistoricalNewsBackfillConfig,
    *,
    mode: GdeltRehearsalMode = "dry-run",
) -> HistoricalNewsBackfillRehearsalResult:
    if mode not in ("dry-run", "staging-batch"):
        raise ValueError("GDELT rehearsal mode must be dry-run or staging-batch")

    _ensure_historical_news_backfill_gates(config)
    result = _run_historical_news_backfill_adapter(config)
    batch = build_staging_batch(result) if mode == "staging-batch" else None
    return HistoricalNewsBackfillRehearsalResult(
        mode=mode,
        adapter_key=result.adapter_key,
        fetched_count=len(result.fetched),
        normalized_count=len(result.normalized),
        rejected_count=len(result.rejected),
        metadata=_rehearsal_contract_metadata(config),
        batch=batch,
    )


def ensure_historical_news_backfill_production_candidate_gates(
    config: HistoricalNewsBackfillConfig,
) -> None:
    _ensure_historical_news_backfill_gates(config)
    if not config.gdelt_production_ingestion_enabled:
        raise RuntimeError(
            "GDELT production-candidate backfill requires "
            "GDELT_PRODUCTION_INGESTION_ENABLED=true"
        )
    if not config.production_persist_intent:
        raise RuntimeError("GDELT production-candidate backfill requires --persist")
    if not (config.production_database_url or "").strip():
        raise RuntimeError(
            "GDELT production-candidate backfill requires --database-url, "
            "WORKER_DATABASE_URL, or DATABASE_URL"
        )
    _ensure_gdelt_production_approval_evidence(config)


def run_historical_news_backfill_production_candidate(
    config: HistoricalNewsBackfillConfig,
    *,
    staging_writer: StagingBatchWriter,
    run_writer: IngestionRunSummaryWriter,
    promotion_writer: EvidencePromotionWriter,
    job_key: str = DEFAULT_GDELT_PRODUCTION_CANDIDATE_JOB_KEY,
    promotion_limit: int | None = None,
) -> HistoricalNewsBackfillProductionCandidateResult:
    ensure_historical_news_backfill_production_candidate_gates(config)
    adapter = _build_historical_news_backfill_adapter(config)
    metadata = _production_candidate_contract_metadata(config)
    summary = run_adapter_batch(
        adapter,
        writer=staging_writer,
        run_writer=run_writer,
        job_key=job_key,
        parameters=_production_candidate_parameters(config),
    )
    if summary.status == "failed":
        return HistoricalNewsBackfillProductionCandidateResult(
            status="failed",
            reason="ingestion_failed",
            summary=summary,
            metadata=metadata,
            error_code=summary.error_code,
            error_message=summary.error_message,
        )
    if summary.status == "skipped":
        return HistoricalNewsBackfillProductionCandidateResult(
            status="skipped",
            reason=summary.error_code or "ingestion_skipped",
            summary=summary,
            metadata=metadata,
            error_code=summary.error_code,
            error_message=summary.error_message,
        )

    promotion = PromotionResult(promoted=0, evidence_ids=())
    if summary.items_promoted > 0:
        try:
            promotion = promote_accepted_staging(
                promotion_writer,
                limit=promotion_limit or summary.items_promoted,
                adapter_keys=(GDELT_BACKFILL_ADAPTER_KEY,),
            )
        except Exception as exc:
            return HistoricalNewsBackfillProductionCandidateResult(
                status="failed",
                reason="promotion_failed",
                summary=summary,
                metadata=metadata,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )

    return HistoricalNewsBackfillProductionCandidateResult(
        status=summary.status,
        summary=summary,
        metadata=metadata,
        promoted=promotion.promoted,
        evidence_ids=promotion.evidence_ids,
    )


def _ensure_historical_news_backfill_gates(config: HistoricalNewsBackfillConfig) -> None:
    if not config.gdelt_source_enabled:
        raise RuntimeError("GDELT backfill requires GDELT_SOURCE_ENABLED=true")
    if not config.gdelt_backfill_enabled:
        raise RuntimeError("GDELT backfill is disabled by default")
    if not config.source_news_enabled:
        raise RuntimeError("GDELT backfill requires SOURCE_NEWS_ENABLED=true")
    if not config.source_terms_review_ack:
        raise RuntimeError("GDELT backfill requires SOURCE_TERMS_REVIEW_ACK=true")


def _ensure_gdelt_production_approval_evidence(config: HistoricalNewsBackfillConfig) -> None:
    raw_path = (config.gdelt_production_approval_evidence_path or "").strip()
    if not raw_path:
        raise RuntimeError(
            "GDELT production-candidate backfill requires "
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH; "
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK cannot replace concrete evidence"
        )
    if not Path(raw_path).is_file():
        raise RuntimeError(
            "GDELT production-candidate approval evidence path must exist"
        )
    if not config.gdelt_production_approval_evidence_ack:
        raise RuntimeError(
            "GDELT production-candidate backfill requires "
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK=true in addition to "
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH"
        )


def _run_historical_news_backfill_adapter(
    config: HistoricalNewsBackfillConfig,
) -> AdapterRunResult:
    return _build_historical_news_backfill_adapter(config).run()


def _build_historical_news_backfill_adapter(
    config: HistoricalNewsBackfillConfig,
) -> GdeltPublicNewsBackfillAdapter:
    return GdeltPublicNewsBackfillAdapter(
        config.queries,
        fetched_at=config.fetched_at,
        start_datetime=config.start_datetime,
        end_datetime=config.end_datetime,
        max_records_per_query=config.max_records_per_query,
        request_cadence_seconds=config.request_cadence_seconds,
        fetch_json=config.fetch_json,
        sleep=config.sleep,
    )


def _rehearsal_contract_metadata(config: HistoricalNewsBackfillConfig) -> dict[str, Any]:
    return {
        "network_allowed": True,
        "source_gate": "GDELT_SOURCE_ENABLED",
        "news_gate": "SOURCE_NEWS_ENABLED",
        "terms_gate": "SOURCE_TERMS_REVIEW_ACK",
        "backfill_gate": "GDELT_BACKFILL_ENABLED",
        "metadata_only": True,
        "rate_limit_contract": "one bounded GDELT DOC request per query",
        "cadence_seconds": max(0, config.request_cadence_seconds),
        "max_records_per_query": max(
            1,
            min(config.max_records_per_query, GDELT_MAX_RECORDS_PER_QUERY),
        ),
        "query_count": len(tuple(query for query in config.queries if query.strip())),
        "start_datetime": config.start_datetime.isoformat(),
        "end_datetime": config.end_datetime.isoformat(),
    }


def _production_candidate_contract_metadata(
    config: HistoricalNewsBackfillConfig,
) -> dict[str, Any]:
    return {
        **_rehearsal_contract_metadata(config),
        "production_candidate": True,
        "metadata_only": True,
        "database_url_configured": True,
        "persist_intent": True,
        "production_gate": "GDELT_PRODUCTION_INGESTION_ENABLED",
        "approval_evidence_gate": (
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_PATH+"
            "GDELT_PRODUCTION_APPROVAL_EVIDENCE_ACK"
        ),
        "approval_evidence_path": config.gdelt_production_approval_evidence_path,
        "approval_evidence_ack": config.gdelt_production_approval_evidence_ack,
        "promotion_adapter_keys": (GDELT_BACKFILL_ADAPTER_KEY,),
    }


def _production_candidate_parameters(
    config: HistoricalNewsBackfillConfig,
) -> dict[str, Any]:
    return {
        "mode": "production-candidate",
        "adapter_key": GDELT_BACKFILL_ADAPTER_KEY,
        "network_allowed": True,
        "metadata_only": True,
        "query_count": len(tuple(query for query in config.queries if query.strip())),
        "max_records_per_query": max(
            1,
            min(config.max_records_per_query, GDELT_MAX_RECORDS_PER_QUERY),
        ),
        "cadence_seconds": max(0, config.request_cadence_seconds),
        "start_datetime": config.start_datetime.isoformat(),
        "end_datetime": config.end_datetime.isoformat(),
        "approval_evidence_path": config.gdelt_production_approval_evidence_path,
        "approval_evidence_ack": config.gdelt_production_approval_evidence_ack,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
