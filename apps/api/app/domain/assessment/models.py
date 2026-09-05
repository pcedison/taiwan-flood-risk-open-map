from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.api.schemas import NearbyRealtimeCoverage
from app.domain.evidence import EvidenceRecord

RiskLevel = Literal["低", "中", "高", "極高", "未知"]
ConfidenceLevel = Literal["低", "中", "高", "未知"]
DominantMode = Literal["realtime", "historical_context", "community_warning", "unknown"]
SourceState = Literal["fresh", "degraded", "stale", "failed", "disabled", "not_applicable"]


@dataclass(frozen=True)
class AssessmentSourceState:
    source_key: str
    signal_type: str
    state: SourceState
    observed_at: datetime | None
    checked_at: datetime | None
    message: str | None


@dataclass(frozen=True)
class AssessmentData:
    current_official: tuple[EvidenceRecord, ...]
    historical: tuple[EvidenceRecord, ...]
    nearby_coverage: NearbyRealtimeCoverage
    source_states: tuple[AssessmentSourceState, ...]
    required_realtime_source_keys: frozenset[str]
    current_available: bool
    historical_available: bool
    coverage_available: bool
    health_available: bool
    jurisdiction_available: bool
    resolved_admin_code: str | None
    resolved_admin_name: str | None
    local_machine_feed_missing: tuple[str, ...]
    recent_incident_context: tuple[EvidenceRecord, ...] = field(default_factory=tuple)
    # Internal latency profile in milliseconds, keyed by read phase.  Never part
    # of any public payload; see docs/runbooks/assess-latency-profiling.md.
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class OverallDecision:
    level: RiskLevel
    confidence: ConfidenceLevel
    dominant_mode: DominantMode
    reasons: tuple[str, ...]
