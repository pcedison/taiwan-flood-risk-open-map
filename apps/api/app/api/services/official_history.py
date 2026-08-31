from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.api.schemas import RiskAssessRequest
from app.domain.assessment import AssessmentData
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    upsert_public_evidence,
)
from app.domain.history.news_enrichment import search_taiwan_official_flood_citations


@dataclass(frozen=True)
class OfficialRecentHistoryLookup:
    database_url: str
    enabled: bool
    timeout_seconds: float
    max_records: int = 3

    def __call__(
        self,
        request: RiskAssessRequest,
        data: AssessmentData,
        *,
        now: datetime,
    ) -> tuple[EvidenceRecord, ...]:
        del data
        if not self.enabled:
            return ()
        result = search_taiwan_official_flood_citations(
            location_text=request.location_text,
            lat=request.point.lat,
            lng=request.point.lng,
            radius_m=request.radius_m,
            now=now,
            max_records=self.max_records,
            timeout_seconds=self.timeout_seconds,
        )
        if not result.records:
            return ()
        try:
            return upsert_public_evidence(
                database_url=self.database_url,
                records=result.records,
            )
        except EvidenceRepositoryUnavailable:
            # The risk request must remain available when either official egress
            # or metadata persistence is temporarily unavailable.
            return ()
