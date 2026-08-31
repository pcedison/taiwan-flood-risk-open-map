from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.assessment.models import AssessmentData, AssessmentSourceState
from app.domain.evidence import (
    EvidenceRecord,
    EvidenceRepositoryUnavailable,
    RealtimeJurisdictionContext,
    RiskAssessmentPersistence,
    persist_risk_assessment,
    query_nearby_evidence,
    query_nearby_observed_flood_history,
    query_nearby_latest_official,
    query_nearby_realtime_coverage_rows,
    query_nearby_recent_context,
    query_realtime_jurisdiction_context,
    query_realtime_source_health_rows,
)
from app.domain.realtime import (
    build_nearby_realtime_coverage,
    build_nearby_source_health,
    coverage_signal_type,
    public_realtime_source_id,
)

_NATIONAL_FALLBACK_KEYS = frozenset(
    {
        "official.cwa.rainfall",
        "official.cwa.heavy_rain_warning",
        "official.wra.water_level",
        "official.wra_iow.flood_depth",
        "official.ncdr.cap",
    }
)
_LOCAL_POLICY = {
    "67000000": ("local.tainan.flood_sensor", "臺南市地方淹水感測目前暫無可用更新"),
    "64000000": (None, "高雄市地方政府機器介面尚未核准"),
    "10013000": (None, "屏東縣地方政府機器介面尚未核准"),
}
_REALTIME_SUPPORT_RADIUS_M = 5_000
_SCORING_CURRENT_ADAPTER_EVENTS = frozenset(
    {
        ("official.cwa.rainfall", "rainfall"),
        ("official.wra.water_level", "water_level"),
        ("official.wra_iow.flood_depth", "flood_report"),
        ("local.tainan.flood_sensor", "flood_report"),
        ("official.cwa.heavy_rain_warning", "flood_warning"),
        ("official.ncdr.cap", "flood_warning"),
    }
)
_REVIEWED_SIGNAL_CONTRACT_REVISIONS = {
    "rainfall": "2026-08-24-v1-baseline",
    "water_level": "2026-08-24-v1-baseline",
    "flood_depth": "2026-08-24-v1-baseline",
    "sewer_water_level": "2026-08-29-sewer-publication",
}


class AssessmentRepository(Protocol):
    def load(
        self,
        *,
        lat: float,
        lng: float,
        radius_m: int,
        as_of: datetime,
    ) -> AssessmentData: ...

    def persist(self, assessment: RiskAssessmentPersistence) -> None: ...


class PostgresAssessmentRepository:
    def __init__(self, database_url: str, *, enabled: bool = True) -> None:
        self._database_url = database_url
        self._enabled = enabled

    def load(
        self,
        *,
        lat: float,
        lng: float,
        radius_m: int,
        as_of: datetime,
    ) -> AssessmentData:
        if not self._enabled:
            jurisdiction = _unavailable_jurisdiction()
            coverage = build_nearby_realtime_coverage(
                rows=(),
                query_radius_m=radius_m,
                evaluated_at=as_of,
                repository_unavailable=True,
                source_health_unavailable=True,
                jurisdiction_status="unavailable",
            )
            return AssessmentData(
                current_official=(),
                historical=(),
                nearby_coverage=coverage,
                source_states=(),
                required_realtime_source_keys=frozenset(),
                current_available=False,
                historical_available=False,
                coverage_available=False,
                health_available=False,
                jurisdiction_available=False,
                resolved_admin_code=jurisdiction.home_jurisdiction_code,
                resolved_admin_name=jurisdiction.home_jurisdiction_name,
                local_machine_feed_missing=(),
            )

        jurisdiction, jurisdiction_available = self._load_jurisdiction(
            lat=lat,
            lng=lng,
            search_radius_m=radius_m,
        )
        applicable_keys = (
            frozenset(jurisdiction.adapter_keys)
            if jurisdiction_available and jurisdiction.resolution_status == "verified"
            else _NATIONAL_FALLBACK_KEYS
        )
        required_keys = (
            frozenset(
                mapping.adapter_key
                for mapping in jurisdiction.source_mappings
                if mapping.requirement_role == "required"
            )
            if applicable_keys
            else frozenset()
        )
        latest, current_available = self._load_latest(
            lat=lat,
            lng=lng,
            radius_m=max(radius_m, _REALTIME_SUPPORT_RADIUS_M),
            as_of=as_of,
        )
        history, historical_available = self._load_history(
            lat=lat,
            lng=lng,
            radius_m=radius_m,
        )
        observed_flood_history, observed_flood_history_available = (
            self._load_observed_flood_history(
                lat=lat,
                lng=lng,
                radius_m=radius_m,
                as_of=as_of,
            )
        )
        coverage_rows, coverage_available = self._load_coverage(
            lat=lat,
            lng=lng,
            as_of=as_of,
        )
        recent_context = self._load_recent_context(
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            as_of=as_of,
        )
        latest = tuple(item for item in latest if item.adapter_key in applicable_keys)
        coverage_rows = tuple(item for item in coverage_rows if item.adapter_key in applicable_keys)
        health_rows, health_available = self._load_health(tuple(sorted(applicable_keys)))
        source_health = build_nearby_source_health(
            health_rows,
            evaluated_at=as_of,
            jurisdictions_by_adapter=_jurisdictions_by_adapter(jurisdiction),
            required_adapter_keys=required_keys,
        )
        coverage = build_nearby_realtime_coverage(
            rows=coverage_rows,
            query_radius_m=radius_m,
            evaluated_at=as_of,
            repository_unavailable=not coverage_available,
            source_health=source_health,
            source_health_unavailable=not health_available,
            source_health_checked=health_available,
            jurisdiction_status=jurisdiction.resolution_status,
            jurisdiction_checked=jurisdiction_available,
            # Only the verified branch can yield an empty key set; the national
            # fallback is a non-empty constant.  So an empty set here means the
            # resolved jurisdiction produced no reviewed source mapping, and every
            # read below was filtered against nothing rather than answered.
            jurisdiction_mapping_missing=not applicable_keys,
            jurisdiction_complete_signal_types=_complete_signal_types(jurisdiction),
            home_jurisdiction=jurisdiction.home_jurisdiction_name,
            considered_jurisdictions=tuple(
                name for _, name in jurisdiction.considered_jurisdictions
            ),
            jurisdiction_mapping_revisions=jurisdiction.mapping_revisions,
        )
        return AssessmentData(
            current_official=_official_current(latest),
            historical=(*observed_flood_history, *_historical_only(history)),
            nearby_coverage=coverage,
            source_states=_source_states(
                source_health=source_health,
                applicable_keys=applicable_keys,
                required_keys=required_keys,
            ),
            required_realtime_source_keys=required_keys,
            current_available=current_available,
            historical_available=(
                historical_available and observed_flood_history_available
            ),
            coverage_available=coverage_available,
            health_available=health_available,
            jurisdiction_available=jurisdiction_available,
            resolved_admin_code=jurisdiction.home_jurisdiction_code,
            resolved_admin_name=jurisdiction.home_jurisdiction_name,
            local_machine_feed_missing=_local_machine_gaps(jurisdiction, source_health),
            recent_incident_context=recent_context,
        )

    def persist(self, assessment: RiskAssessmentPersistence) -> None:
        if not self._enabled:
            return
        persist_risk_assessment(database_url=self._database_url, assessment=assessment)

    def _load_jurisdiction(
        self, *, lat: float, lng: float, search_radius_m: int
    ) -> tuple[RealtimeJurisdictionContext, bool]:
        try:
            return (
                query_realtime_jurisdiction_context(
                    database_url=self._database_url,
                    lat=lat,
                    lng=lng,
                    search_radius_m=search_radius_m,
                ),
                True,
            )
        except EvidenceRepositoryUnavailable:
            return _unavailable_jurisdiction(), False

    def _load_latest(
        self, *, lat: float, lng: float, radius_m: int, as_of: datetime
    ) -> tuple[tuple[EvidenceRecord, ...], bool]:
        try:
            return (
                query_nearby_latest_official(
                    database_url=self._database_url,
                    lat=lat,
                    lng=lng,
                    radius_m=radius_m,
                    as_of=as_of,
                ),
                True,
            )
        except EvidenceRepositoryUnavailable:
            return (), False

    def _load_history(
        self, *, lat: float, lng: float, radius_m: int
    ) -> tuple[tuple[EvidenceRecord, ...], bool]:
        try:
            return (
                query_nearby_evidence(
                    database_url=self._database_url,
                    lat=lat,
                    lng=lng,
                    radius_m=radius_m,
                ),
                True,
            )
        except EvidenceRepositoryUnavailable:
            return (), False

    def _load_observed_flood_history(
        self, *, lat: float, lng: float, radius_m: int, as_of: datetime
    ) -> tuple[tuple[EvidenceRecord, ...], bool]:
        try:
            return (
                query_nearby_observed_flood_history(
                    database_url=self._database_url,
                    lat=lat,
                    lng=lng,
                    radius_m=radius_m,
                    as_of=as_of,
                ),
                True,
            )
        except EvidenceRepositoryUnavailable:
            return (), False

    def _load_recent_context(
        self, *, lat: float, lng: float, radius_m: int, as_of: datetime
    ) -> tuple[EvidenceRecord, ...]:
        """Load display-only context; a failure here must never degrade scoring."""

        try:
            return query_nearby_recent_context(
                database_url=self._database_url,
                lat=lat,
                lng=lng,
                radius_m=radius_m,
                as_of=as_of,
            )
        except (EvidenceRepositoryUnavailable, ValueError):
            return ()

    def _load_coverage(self, *, lat: float, lng: float, as_of: datetime) -> tuple[tuple, bool]:
        try:
            return (
                query_nearby_realtime_coverage_rows(
                    database_url=self._database_url,
                    lat=lat,
                    lng=lng,
                    observed_since=None,
                ),
                True,
            )
        except EvidenceRepositoryUnavailable:
            return (), False

    def _load_health(self, adapter_keys: tuple[str, ...]) -> tuple[tuple, bool]:
        try:
            return (
                query_realtime_source_health_rows(
                    database_url=self._database_url,
                    adapter_keys=adapter_keys,
                ),
                True,
            )
        except EvidenceRepositoryUnavailable:
            return (), False


def _official_current(records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    filtered = tuple(
        item
        for item in records
        if item.source_type == "official"
        and item.evidence_scope == "current"
        and (item.adapter_key, item.event_type) in _SCORING_CURRENT_ADAPTER_EVENTS
    )
    output: list[EvidenceRecord] = []
    warning_index: dict[str, int] = {}
    for item in filtered:
        key = item.official_event_origin_key if item.event_type == "flood_warning" else None
        if key is None:
            output.append(item)
            continue
        index = warning_index.get(key)
        if index is None:
            warning_index[key] = len(output)
            output.append(item)
            continue
        if _warning_origin_rank(item) < _warning_origin_rank(output[index]):
            output[index] = item
    return tuple(output)


def _warning_origin_rank(item: EvidenceRecord) -> tuple[int, float]:
    authority_rank = {
        "official.cwa.heavy_rain_warning": 0,
        "official.ncdr.cap": 1,
    }.get(item.adapter_key or "", 2)
    observed_rank = -(item.observed_at.timestamp() if item.observed_at else 0.0)
    return authority_rank, observed_rank


def _historical_only(records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    """Keep historical footprints and flood-potential context only.

    Reported status-only incident context is display-only. It is loaded
    separately into ``AssessmentData.recent_incident_context`` and must never
    reach the historical scorer or the historical confidence calculation.
    """

    return tuple(
        item
        for item in records
        if item.source_type in {"official", "derived"}
        and (item.evidence_scope == "historical" or item.event_type == "flood_potential")
    )


def _source_states(*, source_health, applicable_keys, required_keys):
    by_public_id = {item.source_id: item for item in source_health}
    output: list[AssessmentSourceState] = []
    for key in sorted(applicable_keys):
        item = by_public_id.get(public_realtime_source_id(key))
        if item is None:
            output.append(
                AssessmentSourceState(
                    source_key=key,
                    signal_type=coverage_signal_type("status_only", key),
                    state="disabled" if key in required_keys else "not_applicable",
                    observed_at=None,
                    checked_at=None,
                    message=("必要來源尚未登錄或沒有健康紀錄。" if key in required_keys else None),
                )
            )
            continue
        output.append(
            AssessmentSourceState(
                source_key=key,
                signal_type=item.signal_types[0],
                state={
                    "healthy": "fresh",
                    "degraded": "degraded",
                    "failed": "failed",
                    "disabled": "disabled",
                    "unknown": "stale",
                }[item.health_status],
                observed_at=item.observed_at,
                checked_at=item.checked_at,
                message=item.message,
            )
        )
    return tuple(output)


def _unavailable_jurisdiction() -> RealtimeJurisdictionContext:
    return RealtimeJurisdictionContext(
        resolution_status="unavailable",
        home_jurisdiction_code=None,
        home_jurisdiction_name=None,
        considered_jurisdictions=(),
        signal_contracts=(),
        source_mappings=(),
    )


def _complete_signal_types(jurisdiction: RealtimeJurisdictionContext) -> tuple:
    considered_codes = {code for code, _ in jurisdiction.considered_jurisdictions}
    if not considered_codes:
        return ()
    complete: list[str] = []
    for signal_type, reviewed_revision in _REVIEWED_SIGNAL_CONTRACT_REVISIONS.items():
        valid_codes = {
            contract.jurisdiction_code
            for contract in jurisdiction.signal_contracts
            if contract.signal_type == signal_type
            and contract.catalog_status == "reviewed_complete"
            and contract.mapping_proof_valid
            and contract.mapping_revision == reviewed_revision
        }
        if considered_codes <= valid_codes:
            complete.append(signal_type)
    return tuple(sorted(complete))


def _jurisdictions_by_adapter(
    jurisdiction: RealtimeJurisdictionContext,
) -> dict[str, tuple[str, ...]]:
    output: dict[str, set[str]] = {}
    for mapping in jurisdiction.source_mappings:
        if mapping.jurisdiction_name:
            output.setdefault(mapping.adapter_key, set()).add(mapping.jurisdiction_name)
    return {key: tuple(sorted(names)) for key, names in output.items()}


def _local_machine_gaps(jurisdiction, source_health) -> tuple[str, ...]:
    policy = _LOCAL_POLICY.get(jurisdiction.home_jurisdiction_code)
    if policy is None:
        return ()
    adapter_key, message = policy
    if adapter_key is None:
        return (message,)
    source_id = public_realtime_source_id(adapter_key)
    state = next((item for item in source_health if item.source_id == source_id), None)
    return () if state and state.health_status in {"healthy", "degraded"} else (message,)


__all__ = ["AssessmentRepository", "PostgresAssessmentRepository"]
