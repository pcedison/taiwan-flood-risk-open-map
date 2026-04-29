from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters.contracts import EventType, IngestionStatus, NormalizedEvidence, SourceFamily


@dataclass(frozen=True)
class EvidenceValidationResult:
    accepted: tuple[NormalizedEvidence, ...]
    rejected: tuple[tuple[NormalizedEvidence, tuple[str, ...]], ...] = field(default_factory=tuple)


def validate_evidence_for_promotion(
    evidence_items: tuple[NormalizedEvidence, ...],
) -> EvidenceValidationResult:
    accepted: list[NormalizedEvidence] = []
    rejected: list[tuple[NormalizedEvidence, tuple[str, ...]]] = []

    for evidence in evidence_items:
        errors = tuple(_evidence_errors(evidence))
        if errors:
            rejected.append((evidence, errors))
        else:
            accepted.append(evidence)

    return EvidenceValidationResult(accepted=tuple(accepted), rejected=tuple(rejected))


def _evidence_errors(evidence: NormalizedEvidence) -> list[str]:
    errors: list[str] = []

    if not evidence.evidence_id:
        errors.append("missing evidence_id")
    if not evidence.adapter_key:
        errors.append("missing adapter_key")
    if not evidence.source_id:
        errors.append("missing source_id")
    if not isinstance(evidence.source_family, SourceFamily):
        errors.append("source_family must be a known source family")
    if not isinstance(evidence.event_type, EventType):
        errors.append("event_type must be a known event type")
    if not evidence.source_url:
        errors.append("missing source_url")
    if not evidence.source_title:
        errors.append("missing source_title")
    if not evidence.summary:
        errors.append("missing summary")
    if not 0.0 <= evidence.confidence <= 1.0:
        errors.append("confidence must be between 0.0 and 1.0")
    if evidence.status is not IngestionStatus.NORMALIZED:
        errors.append("status must be normalized before promotion")

    return errors
