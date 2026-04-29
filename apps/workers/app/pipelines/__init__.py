"""Worker ingestion pipelines."""

from app.pipelines.staging import (
    AdapterStagingBatch,
    RawSnapshotUpsert,
    StagingEvidenceUpsert,
    build_raw_snapshot,
    build_staging_batch,
    persist_staging_batch,
)
from app.pipelines.postgres_writer import PostgresStagingBatchWriter
from app.pipelines.promotion import (
    EvidencePromotionPayload,
    EvidencePromotionWriter,
    PostgresEvidencePromotionWriter,
    PromotionCandidate,
    PromotionResult,
    build_evidence_promotion_payload,
    promote_accepted_staging,
)
from app.pipelines.validation import EvidenceValidationResult, validate_evidence_for_promotion

__all__ = [
    "AdapterStagingBatch",
    "EvidencePromotionPayload",
    "EvidencePromotionWriter",
    "EvidenceValidationResult",
    "PostgresEvidencePromotionWriter",
    "PostgresStagingBatchWriter",
    "PromotionCandidate",
    "PromotionResult",
    "RawSnapshotUpsert",
    "StagingEvidenceUpsert",
    "build_evidence_promotion_payload",
    "build_raw_snapshot",
    "build_staging_batch",
    "persist_staging_batch",
    "promote_accepted_staging",
    "validate_evidence_for_promotion",
]
