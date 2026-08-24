from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.adapters._helpers import parse_datetime
from app.adapters.cap_identity import cap_message_digest

ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class PromotionCandidate:
    staging_evidence_id: str
    raw_snapshot_id: str | None
    raw_ref: str | None
    data_source_id: str | None
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str | None
    occurred_at: datetime | None
    observed_at: datetime | None
    confidence: float
    validation_status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidencePromotionPayload:
    data_source_id: str | None
    adapter_key: str | None
    source_id: str
    source_type: str
    event_type: str
    title: str
    summary: str
    url: str | None
    occurred_at: datetime | None
    observed_at: datetime | None
    confidence: float
    raw_ref: str | None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromotionResult:
    promoted: int
    evidence_ids: tuple[str, ...]


class EvidencePromotionWriter(Protocol):
    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        """Load staging rows that are ready to become evidence records."""

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        """Persist one evidence row, or terminally consume a non-write candidate."""


def build_evidence_promotion_payload(candidate: PromotionCandidate) -> EvidencePromotionPayload:
    if candidate.validation_status != "accepted":
        raise ValueError("only accepted staging evidence can be promoted")

    return EvidencePromotionPayload(
        data_source_id=candidate.data_source_id,
        adapter_key=_payload_adapter_key(candidate.payload),
        source_id=candidate.source_id,
        source_type=candidate.source_type,
        event_type=candidate.event_type,
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        occurred_at=candidate.occurred_at,
        observed_at=candidate.observed_at,
        confidence=candidate.confidence,
        raw_ref=candidate.raw_ref,
        properties={
            **candidate.payload,
            "staging_evidence_id": candidate.staging_evidence_id,
            "raw_snapshot_id": candidate.raw_snapshot_id,
        },
    )


def promote_accepted_staging(
    writer: EvidencePromotionWriter,
    *,
    limit: int | None = None,
    adapter_keys: tuple[str, ...] | None = None,
) -> PromotionResult:
    evidence_ids: list[str] = []
    seen_keys: set[tuple[str, str | None]] = set()
    for candidate in writer.fetch_accepted_staging(limit=limit, adapter_keys=adapter_keys):
        promotion_key = (candidate.source_id, candidate.raw_ref)
        if promotion_key in seen_keys:
            continue
        seen_keys.add(promotion_key)
        evidence_id = writer.write_evidence(build_evidence_promotion_payload(candidate))
        if evidence_id is not None:
            evidence_ids.append(evidence_id)

    return PromotionResult(promoted=len(evidence_ids), evidence_ids=tuple(evidence_ids))


class PostgresEvidencePromotionWriter:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        if database_url is None and connection_factory is None:
            raise ValueError("database_url or connection_factory is required")
        self._database_url = database_url
        self._connection_factory = connection_factory

    def fetch_accepted_staging(
        self,
        *,
        limit: int | None = None,
        adapter_keys: tuple[str, ...] | None = None,
    ) -> tuple[PromotionCandidate, ...]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                _accepted_staging_sql(limit=limit, adapter_keys=adapter_keys),
                _accepted_staging_params(limit=limit, adapter_keys=adapter_keys),
            )
            return tuple(_candidate_from_row(row) for row in cursor.fetchall())

    def write_evidence(self, payload: EvidencePromotionPayload) -> str | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                staging_authorization = _authorize_staging_candidate(cursor, payload)
                if staging_authorization is False:
                    return None
                current_rejection_reason = _current_candidate_rejection_reason(payload)
                if current_rejection_reason is not None:
                    _terminally_reject_staging(
                        cursor,
                        payload,
                        reason=current_rejection_reason,
                        authorized=staging_authorization is True,
                    )
                    connection.commit()
                    return None
                promote_latest = _should_upsert_official_realtime_latest(payload)
                cap_lifecycle_candidate = _is_current_cap_lifecycle_candidate(payload)
                if promote_latest or cap_lifecycle_candidate:
                    _lock_realtime_decision(cursor, payload)
                if staging_authorization is True and _staging_evidence_was_already_used(
                    cursor, payload
                ):
                    return None
                cap_rejection_reason = (
                    _cap_rejection_reason(cursor, payload)
                    if cap_lifecycle_candidate
                    else None
                )
                if cap_rejection_reason is not None:
                    _terminally_reject_staging(
                        cursor,
                        payload,
                        reason=cap_rejection_reason,
                        authorized=staging_authorization is True,
                    )
                    connection.commit()
                    return None
                if cap_lifecycle_candidate and _canonical_cap_message_exists(
                    cursor, payload
                ):
                    _terminally_reject_staging(
                        cursor,
                        payload,
                        reason="idempotent_existing_cap_message",
                        authorized=staging_authorization is True,
                    )
                    connection.commit()
                    return None
                duplicate_decision = (
                    _handle_exact_central_local_duplicate(cursor, payload)
                    if promote_latest
                    else None
                )
                if duplicate_decision == "duplicate_central":
                    _terminally_reject_staging(
                        cursor,
                        payload,
                        reason="duplicate_central",
                        authorized=staging_authorization is True,
                    )
                    connection.commit()
                    return None
                decision = (
                    _classify_latest_decision(cursor, payload)
                    if promote_latest and payload.event_type != "flood_warning"
                    else "insert"
                )
                if decision in {"idempotent", "conflict"}:
                    _terminally_reject_staging(
                        cursor,
                        payload,
                        reason=(
                            "idempotent_existing_observation"
                            if decision == "idempotent"
                            else "conflicting_latest"
                        ),
                        authorized=staging_authorization is True,
                    )
                    connection.commit()
                    return None
                if decision == "historical_only":
                    promote_latest = False
                enriched_payload = _with_admin_area_enrichment(cursor, payload)
                weighted_payload = enriched_payload
                cursor.execute(
                    """
                    INSERT INTO evidence (
                        data_source_id,
                        source_id,
                        source_type,
                        event_type,
                        title,
                        summary,
                        url,
                        occurred_at,
                        observed_at,
                        confidence,
                        geom,
                        raw_ref,
                        ingestion_status,
                        properties
                    )
                    VALUES (
                        COALESCE(%s, (SELECT id FROM data_sources WHERE adapter_key = %s)),
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        CASE
                            WHEN %s::text IS NULL THEN NULL
                            ELSE ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)
                        END,
                        %s,
                        'accepted',
                        %s::jsonb
                    )
                    ON CONFLICT ON CONSTRAINT evidence_source_raw_ref_unique
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        weighted_payload.data_source_id,
                        weighted_payload.adapter_key,
                        weighted_payload.source_id,
                        weighted_payload.source_type,
                        weighted_payload.event_type,
                        weighted_payload.title,
                        weighted_payload.summary,
                        weighted_payload.url,
                        weighted_payload.occurred_at,
                        weighted_payload.observed_at,
                        weighted_payload.confidence,
                        _geojson_geometry(weighted_payload.properties),
                        _geojson_geometry(weighted_payload.properties),
                        weighted_payload.raw_ref,
                        _json(weighted_payload.properties),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                evidence_id = str(row[0])
                if cap_lifecycle_candidate and weighted_payload.properties.get(
                    "cap_message_type"
                ) in {"Update", "Cancel"}:
                    _retire_cap_references(cursor, weighted_payload)
                if weighted_payload.properties.get("cap_message_type") == "Cancel":
                    promote_latest = False
                if promote_latest and _should_upsert_official_realtime_latest(weighted_payload):
                    self._upsert_official_realtime_latest(
                        cursor,
                        payload=weighted_payload,
                        evidence_id=evidence_id,
                    )
            connection.commit()

        return evidence_id
    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()

        import psycopg

        assert self._database_url is not None
        return psycopg.connect(self._database_url)

    def _upsert_official_realtime_latest(
        self,
        cursor: Any,
        *,
        payload: EvidencePromotionPayload,
        evidence_id: str,
    ) -> None:
        station_id = _official_realtime_station_id(payload)
        if station_id is None:
            return

        point_geometry = _geojson_point_geometry(payload.properties)
        if point_geometry is None:
            return

        cursor.execute(
            """
            INSERT INTO official_realtime_latest (
                source_id,
                adapter_key,
                event_type,
                station_id,
                station_name,
                authority,
                observed_at,
                geom,
                rainfall_mm_1h,
                rainfall_mm_24h,
                water_level_m,
                flood_depth_cm,
                warning_level_m,
                confidence,
                freshness_score,
                source_weight,
                risk_factor,
                evidence_id,
                source_url,
                attribution,
                quality_flags
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                CASE
                    WHEN %s::text IS NULL THEN NULL
                    ELSE ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)
                END,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            ON CONFLICT (adapter_key, event_type, station_id)
            DO UPDATE SET
                source_id = EXCLUDED.source_id,
                station_name = EXCLUDED.station_name,
                authority = EXCLUDED.authority,
                observed_at = EXCLUDED.observed_at,
                ingested_at = now(),
                geom = EXCLUDED.geom,
                rainfall_mm_1h = EXCLUDED.rainfall_mm_1h,
                rainfall_mm_24h = EXCLUDED.rainfall_mm_24h,
                water_level_m = EXCLUDED.water_level_m,
                flood_depth_cm = EXCLUDED.flood_depth_cm,
                warning_level_m = EXCLUDED.warning_level_m,
                confidence = EXCLUDED.confidence,
                freshness_score = EXCLUDED.freshness_score,
                source_weight = EXCLUDED.source_weight,
                risk_factor = EXCLUDED.risk_factor,
                evidence_id = EXCLUDED.evidence_id,
                source_url = EXCLUDED.source_url,
                attribution = EXCLUDED.attribution,
                quality_flags = EXCLUDED.quality_flags,
                updated_at = now()
            WHERE EXCLUDED.observed_at > official_realtime_latest.observed_at
            """,
            (
                payload.source_id,
                payload.adapter_key,
                payload.event_type,
                station_id,
                _optional_text(payload.properties.get("station_name")),
                _optional_text(payload.properties.get("authority")),
                payload.observed_at,
                point_geometry,
                point_geometry,
                _optional_float(payload.properties.get("rainfall_mm_1h")),
                _optional_float(payload.properties.get("rainfall_mm_24h")),
                _optional_float(payload.properties.get("water_level_m")),
                _optional_float(payload.properties.get("flood_depth_cm")),
                _optional_float(payload.properties.get("warning_level_m")),
                payload.confidence,
                _optional_float(payload.properties.get("freshness_score")),
                _official_realtime_source_weight(payload),
                _official_realtime_risk_factor(payload),
                evidence_id,
                _optional_text(payload.properties.get("source_url")),
                _optional_text(payload.properties.get("attribution")),
                _json(_quality_flags(payload.properties)),
            ),
        )


def warning_lifecycle_lock_key(adapter_key: str) -> str:
    return f"official-warning-lifecycle|{adapter_key}"


def _lock_realtime_decision(cursor: Any, payload: EvidencePromotionPayload) -> None:
    station_id = _official_realtime_station_id(payload)
    keys: list[str] = []
    if payload.event_type == "flood_warning" and payload.adapter_key is not None:
        keys.append(warning_lifecycle_lock_key(payload.adapter_key))
        keys.extend(sorted(_cap_origin_lock_keys(payload)))
        if station_id is not None and payload.properties.get("cap_message_type") != "Cancel":
            keys.append(
                "official-realtime-latest|"
                f"{payload.adapter_key}|{payload.event_type}|{station_id}"
            )
    elif station_id is not None and payload.observed_at is not None:
        keys.extend(
            (
                (
                    "official-realtime-dedupe|"
                    f"{payload.event_type}|{payload.observed_at.astimezone(UTC).isoformat()}"
                ),
                (
                    "official-realtime-latest|"
                    f"{payload.adapter_key}|{payload.event_type}|{station_id}"
                ),
            )
        )
    for key in keys:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (key,),
        )


def _cap_origin_lock_keys(payload: EvidencePromotionPayload) -> set[str]:
    message_type = payload.properties.get("cap_message_type")
    triples: list[tuple[str, str, datetime]] = []
    if message_type in {"Alert", "Update"}:
        own = _cap_triple(
            payload.properties.get("cap_sender"),
            payload.properties.get("cap_identifier"),
            payload.properties.get("cap_sent"),
        )
        if own is not None:
            triples.append(own)
    if message_type in {"Update", "Cancel"}:
        references = payload.properties.get("cap_references")
        if isinstance(references, list):
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                triple = _cap_triple(
                    reference.get("sender"),
                    reference.get("identifier"),
                    reference.get("sent"),
                )
                if triple is not None:
                    triples.append(triple)
    return {
        "official-warning-origin|"
        + cap_message_digest(sender=sender, identifier=identifier, sent=sent)
        for sender, identifier, sent in triples
    }


def _cap_triple(
    sender_value: object, identifier_value: object, sent_value: object
) -> tuple[str, str, datetime] | None:
    if not isinstance(sender_value, str) or not isinstance(identifier_value, str):
        return None
    sender = sender_value.strip()
    identifier = identifier_value.strip()
    sent = parse_datetime(sent_value)
    if (
        not sender
        or len(sender) > 512
        or not identifier
        or len(identifier) > 512
        or sent is None
        or sent.tzinfo is None
        or sent.utcoffset() is None
    ):
        return None
    return sender, identifier, sent


def _cap_reference_triples(
    value: object,
) -> tuple[tuple[str, str, datetime], ...] | None:
    if not isinstance(value, list):
        return None
    canonical: dict[tuple[str, str, datetime], None] = {}
    for reference in value:
        if not isinstance(reference, dict) or set(reference) != {
            "sender",
            "identifier",
            "sent",
        }:
            return None
        triple = _cap_triple(
            reference.get("sender"),
            reference.get("identifier"),
            reference.get("sent"),
        )
        if triple is None:
            return None
        sender, identifier, sent = triple
        canonical[(sender, identifier, sent.astimezone(UTC))] = None
    if len(canonical) > 64:
        return None
    return tuple(sorted(canonical))


def _canonical_cap_message_exists(cursor: Any, payload: EvidencePromotionPayload) -> bool:
    if payload.adapter_key is None:
        return False
    triple = _cap_triple(
        payload.properties.get("cap_sender"),
        payload.properties.get("cap_identifier"),
        payload.properties.get("cap_sent"),
    )
    if triple is None:
        return False
    sender, identifier, sent = triple
    admin_code = _optional_text(payload.properties.get("admin_code"))
    discriminator = "area" if admin_code is not None else "message"
    cursor.execute(
        """
        /* canonical-cap-idempotence */
        SELECT 1
        FROM evidence cap_evidence
        LEFT JOIN data_sources cap_source ON cap_source.id = cap_evidence.data_source_id
        WHERE COALESCE(
                cap_source.adapter_key,
                cap_evidence.properties ->> 'adapter_key'
            ) = %s
            AND cap_evidence.source_type = 'official'
            AND cap_evidence.event_type = 'flood_warning'
            AND cap_evidence.properties ->> 'evidence_scope' = 'current'
            AND cap_evidence.properties ->> 'cap_status' = 'Actual'
            AND cap_evidence.properties ->> 'cap_sender' = %s
            AND cap_evidence.properties ->> 'cap_identifier' = %s
            AND CASE
                WHEN pg_input_is_valid(
                    cap_evidence.properties ->> 'cap_sent',
                    'timestamptz'
                )
                    THEN (cap_evidence.properties ->> 'cap_sent')::timestamptz = %s
                ELSE false
            END
            AND CASE
                WHEN %s = 'area'
                    THEN cap_evidence.properties ->> 'admin_code' = %s
                ELSE cap_evidence.properties ->> 'admin_code' IS NULL
            END
        LIMIT 1
        """,
        (
            payload.adapter_key,
            sender,
            identifier,
            sent,
            discriminator,
            admin_code,
        ),
    )
    return cursor.fetchone() is not None


def _validated_staging_id(payload: EvidencePromotionPayload) -> str | None:
    value = payload.properties.get("staging_evidence_id")
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _authorize_staging_candidate(
    cursor: Any, payload: EvidencePromotionPayload
) -> bool | None:
    if "staging_evidence_id" not in payload.properties:
        return None
    staging_id = _validated_staging_id(payload)
    if staging_id is None:
        return False
    raw_snapshot_id = payload.properties.get("raw_snapshot_id")
    cursor.execute(
        """
        /* authorize-staging-candidate */
        SELECT se.id
        FROM staging_evidence se
        JOIN raw_snapshots rs ON rs.id = se.raw_snapshot_id
        LEFT JOIN data_sources ds
            ON ds.id = COALESCE(se.data_source_id, rs.data_source_id)
        WHERE se.id = %s::uuid
            AND se.validation_status = 'accepted'
            AND COALESCE(se.data_source_id, rs.data_source_id, ds.id)::text
                IS NOT DISTINCT FROM %s
            AND se.source_id IS NOT DISTINCT FROM %s
            AND se.source_type = %s
            AND se.event_type = %s
            AND se.occurred_at IS NOT DISTINCT FROM %s
            AND se.observed_at IS NOT DISTINCT FROM %s
            AND COALESCE(se.payload ->> 'adapter_key', rs.adapter_key, ds.adapter_key)
                IS NOT DISTINCT FROM %s
            AND rs.raw_ref IS NOT DISTINCT FROM %s
            AND se.raw_snapshot_id::text IS NOT DISTINCT FROM %s
        FOR UPDATE OF se
        """,
        (
            staging_id,
            str(payload.data_source_id) if payload.data_source_id is not None else None,
            payload.source_id,
            payload.source_type,
            payload.event_type,
            payload.occurred_at,
            payload.observed_at,
            payload.adapter_key,
            payload.raw_ref,
            str(raw_snapshot_id) if raw_snapshot_id is not None else None,
        ),
    )
    return cursor.fetchone() is not None


def _staging_evidence_was_already_used(
    cursor: Any, payload: EvidencePromotionPayload
) -> bool:
    staging_id = _validated_staging_id(payload)
    if staging_id is None:
        return False
    cursor.execute(
        """
        /* same-staging-evidence */
        SELECT 1
        FROM evidence
        WHERE properties ->> 'staging_evidence_id' = %s
        LIMIT 1
        """,
        (staging_id,),
    )
    return cursor.fetchone() is not None


def _classify_latest_decision(cursor: Any, payload: EvidencePromotionPayload) -> str:
    station_id = _official_realtime_station_id(payload)
    if station_id is None or payload.adapter_key is None or payload.observed_at is None:
        return "historical_only"
    cursor.execute(
        """
        /* latest-decision */
        SELECT
            observed_at,
            station_id,
            rainfall_mm_1h,
            rainfall_mm_24h,
            water_level_m,
            flood_depth_cm,
            warning_level_m,
            ST_AsGeoJSON(geom)
        FROM official_realtime_latest
        WHERE adapter_key = %s
            AND event_type = %s
            AND station_id = %s
        FOR UPDATE
        """,
        (payload.adapter_key, payload.event_type, station_id),
    )
    row = cursor.fetchone()
    if row is None:
        return "insert"
    existing_observed_at = row[0]
    if payload.observed_at < existing_observed_at:
        return "historical_only"
    if payload.observed_at > existing_observed_at:
        return "update"
    existing_fingerprint = (
        payload.event_type,
        str(row[1]),
        _optional_float(row[2]),
        _optional_float(row[3]),
        _optional_float(row[4]),
        _optional_float(row[5]),
        _optional_float(row[6]),
        _rounded_geometry(row[7]),
        existing_observed_at.astimezone(UTC).isoformat(),
    )
    candidate_fingerprint = (
        payload.event_type,
        station_id,
        _optional_float(payload.properties.get("rainfall_mm_1h")),
        _optional_float(payload.properties.get("rainfall_mm_24h")),
        _optional_float(payload.properties.get("water_level_m")),
        _optional_float(payload.properties.get("flood_depth_cm")),
        _optional_float(payload.properties.get("warning_level_m")),
        _rounded_geometry(_geojson_point_geometry(payload.properties)),
        payload.observed_at.astimezone(UTC).isoformat(),
    )
    return "idempotent" if candidate_fingerprint == existing_fingerprint else "conflict"


def _handle_exact_central_local_duplicate(
    cursor: Any, payload: EvidencePromotionPayload
) -> str | None:
    if payload.event_type != "flood_report" or payload.observed_at is None:
        return None
    if payload.adapter_key == "local.tainan.flood_sensor":
        peer_adapter_key = "official.wra_iow.flood_depth"
        local_candidate = True
    elif payload.adapter_key == "official.wra_iow.flood_depth":
        peer_adapter_key = "local.tainan.flood_sensor"
        local_candidate = False
    else:
        return None
    station_id = _official_realtime_station_id(payload)
    point_geometry = _geojson_point_geometry(payload.properties)
    flood_depth_cm = _optional_float(payload.properties.get("flood_depth_cm"))
    if station_id is None or point_geometry is None or flood_depth_cm is None:
        return None
    cursor.execute(
        """
        /* exact-central-local-duplicate */
        SELECT adapter_key, station_id
        FROM official_realtime_latest
        WHERE adapter_key = %s
            AND event_type = 'flood_report'
            AND observed_at = %s
            AND flood_depth_cm = %s
            AND (
                station_id = %s
                OR ST_DWithin(
                    geom::geography,
                    ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)::geography,
                    150
                )
            )
        ORDER BY station_id
        LIMIT 1
        """,
        (
            peer_adapter_key,
            payload.observed_at,
            flood_depth_cm,
            station_id,
            point_geometry,
        ),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    if local_candidate:
        return "duplicate_central"
    cursor.execute(
        """
        DELETE FROM official_realtime_latest
        WHERE adapter_key = %s
            AND event_type = 'flood_report'
            AND station_id = %s
            AND observed_at = %s
            AND flood_depth_cm = %s
        """,
        (peer_adapter_key, str(row[1]), payload.observed_at, flood_depth_cm),
    )
    return "replaced_local"


def _cap_rejection_reason(
    cursor: Any, payload: EvidencePromotionPayload
) -> str | None:
    message_type = payload.properties.get("cap_message_type")
    if _is_expired_cap(payload.properties):
        return "inactive_cap_window"
    if payload.properties.get("cap_status") != "Actual" or message_type not in {
        "Alert",
        "Update",
        "Cancel",
    }:
        return "invalid_cap_lifecycle"
    triple = _cap_triple(
        payload.properties.get("cap_sender"),
        payload.properties.get("cap_identifier"),
        payload.properties.get("cap_sent"),
    )
    if triple is None:
        return "invalid_cap_identity"
    sender, identifier, sent = triple
    admin_code = _optional_text(payload.properties.get("admin_code"))
    if message_type in {"Alert", "Update"} and (
        admin_code is None or re.fullmatch(r"[0-9]{8}", admin_code) is None
    ):
        return "invalid_cap_identity"
    if message_type == "Cancel" and admin_code is not None and re.fullmatch(
        r"[0-9]{8}", admin_code
    ) is None:
        return "invalid_cap_identity"
    references = _cap_reference_triples(payload.properties.get("cap_references"))
    if references is None:
        return "invalid_cap_lifecycle"
    if message_type in {"Update", "Cancel"} and not any(
        reference_sent < sent for _, _, reference_sent in references
    ):
        return "invalid_cap_lifecycle"
    generation = parse_datetime(
        payload.properties.get("ingestion_generation_started_at")
    )
    if (
        generation is None
        or generation.tzinfo is None
        or generation.utcoffset() is None
    ):
        return "invalid_ingestion_generation"
    if message_type in {"Alert", "Update"}:
        active_from = parse_datetime(payload.properties.get("active_from"))
        active_until = parse_datetime(payload.properties.get("active_until"))
        checked_at = datetime.now(UTC)
        if (
            active_from is None
            or active_until is None
            or active_from.tzinfo is None
            or active_until.tzinfo is None
            or not (active_from <= checked_at < active_until)
        ):
            return "inactive_cap_window"
        cursor.execute(
            """
            /* retained-cap-tombstone */
            SELECT 1
            FROM evidence lifecycle_evidence
            LEFT JOIN data_sources lifecycle_source
                ON lifecycle_source.id = lifecycle_evidence.data_source_id
            WHERE lifecycle_evidence.event_type = 'flood_warning'
                AND lifecycle_evidence.source_type = 'official'
                AND lifecycle_evidence.properties ->> 'evidence_scope' = 'current'
                AND lifecycle_evidence.properties ->> 'cap_status' = 'Actual'
                AND COALESCE(
                        lifecycle_source.adapter_key,
                        lifecycle_evidence.properties ->> 'adapter_key'
                    ) IN (
                        'official.cwa.heavy_rain_warning',
                        'official.ncdr.cap'
                    )
                AND lifecycle_evidence.properties ->> 'cap_message_type'
                    IN ('Update', 'Cancel')
                AND pg_input_is_valid(
                    lifecycle_evidence.properties
                        ->> 'ingestion_generation_started_at',
                    'timestamptz'
                )
                AND CASE
                    WHEN jsonb_typeof(
                        lifecycle_evidence.properties -> 'cap_references'
                    ) = 'array'
                        THEN jsonb_array_length(
                            lifecycle_evidence.properties -> 'cap_references'
                        ) BETWEEN 1 AND 64
                    ELSE false
                END
                AND EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(
                        CASE
                            WHEN jsonb_typeof(
                                lifecycle_evidence.properties -> 'cap_references'
                            ) = 'array'
                                THEN lifecycle_evidence.properties -> 'cap_references'
                            ELSE '[]'::jsonb
                        END
                    ) reference
                    WHERE jsonb_typeof(reference) = 'object'
                        AND reference ?& ARRAY['sender', 'identifier', 'sent']
                        AND reference - ARRAY['sender', 'identifier', 'sent']
                            = '{}'::jsonb
                        AND reference ->> 'sender' = %s
                        AND reference ->> 'identifier' = %s
                        AND CASE
                            WHEN pg_input_is_valid(
                                reference ->> 'sent',
                                'timestamptz'
                            )
                                THEN (reference ->> 'sent')::timestamptz = %s
                            ELSE false
                        END
                )
            LIMIT 1
            """,
            (sender, identifier, sent),
        )
        if cursor.fetchone() is not None:
            return "retired_cap_replay"
    return None


def _rounded_geometry(value: object) -> object:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict) or value.get("type") != "Point":
        return None
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return None
    try:
        return (round(float(coordinates[0]), 7), round(float(coordinates[1]), 7))
    except (TypeError, ValueError):
        return None


def _terminally_reject_staging(
    cursor: Any,
    payload: EvidencePromotionPayload,
    *,
    reason: str,
    authorized: bool,
) -> None:
    if not authorized:
        return
    staging_id = _validated_staging_id(payload)
    if staging_id is None:
        return
    cursor.execute(
        """
        UPDATE staging_evidence
        SET validation_status = 'rejected', rejection_reason = %s
        WHERE id = %s::uuid AND validation_status = 'accepted'
        """,
        (reason, staging_id),
    )


def _retire_cap_references(cursor: Any, payload: EvidencePromotionPayload) -> None:
    references = payload.properties.get("cap_references")
    if not isinstance(references, list) or not references:
        return
    cursor.execute(
        """
        /* retire-cap-references */
        DELETE FROM official_realtime_latest latest
        USING evidence linked_evidence
        LEFT JOIN data_sources linked_source
            ON linked_source.id = linked_evidence.data_source_id
        WHERE latest.evidence_id = linked_evidence.id
            AND latest.event_type = 'flood_warning'
            AND latest.adapter_key IN (
                'official.cwa.heavy_rain_warning',
                'official.ncdr.cap'
            )
            AND linked_evidence.source_type = 'official'
            AND linked_evidence.event_type = 'flood_warning'
            AND linked_evidence.properties ->> 'evidence_scope' = 'current'
            AND linked_evidence.properties ->> 'cap_status' = 'Actual'
            AND linked_evidence.properties ->> 'cap_message_type'
                IN ('Alert', 'Update')
            AND COALESCE(
                    linked_source.adapter_key,
                    linked_evidence.properties ->> 'adapter_key'
                ) = latest.adapter_key
            AND linked_evidence.properties ->> 'admin_code' ~ '^[0-9]{8}$'
            AND length(btrim(linked_evidence.properties ->> 'cap_sender'))
                BETWEEN 1 AND 512
            AND length(btrim(linked_evidence.properties ->> 'cap_identifier'))
                BETWEEN 1 AND 512
            AND pg_input_is_valid(
                linked_evidence.properties ->> 'cap_sent',
                'timestamptz'
            )
            AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements(%s::jsonb) reference
                WHERE linked_evidence.properties ->> 'cap_sender' = reference ->> 'sender'
                    AND linked_evidence.properties ->> 'cap_identifier'
                        = reference ->> 'identifier'
                    AND pg_input_is_valid(reference ->> 'sent', 'timestamptz')
                    AND CASE
                        WHEN pg_input_is_valid(
                            linked_evidence.properties ->> 'cap_sent',
                            'timestamptz'
                        ) AND pg_input_is_valid(
                            reference ->> 'sent',
                            'timestamptz'
                        )
                            THEN (
                                linked_evidence.properties ->> 'cap_sent'
                            )::timestamptz = (reference ->> 'sent')::timestamptz
                        ELSE false
                    END
            )
        """,
        (json.dumps(references, sort_keys=True, separators=(",", ":")),),
    )


def _accepted_staging_sql(
    *,
    limit: int | None,
    adapter_keys: tuple[str, ...] | None,
) -> str:
    adapter_filter = (
        "AND COALESCE(se.payload ->> 'adapter_key', rs.adapter_key) = ANY(%s)"
        if adapter_keys is not None
        else ""
    )
    limit_clause = "LIMIT %s" if limit is not None else ""
    return f"""
        SELECT DISTINCT ON (se.source_id, rs.raw_ref)
            se.id,
            se.raw_snapshot_id,
            rs.raw_ref,
            COALESCE(se.data_source_id, rs.data_source_id, ds.id) AS data_source_id,
            se.source_id,
            se.source_type,
            se.event_type,
            se.title,
            se.summary,
            se.url,
            se.occurred_at,
            se.observed_at,
            se.confidence,
            se.validation_status,
            se.payload
        FROM staging_evidence se
        LEFT JOIN raw_snapshots rs ON rs.id = se.raw_snapshot_id
        LEFT JOIN data_sources ds ON ds.adapter_key = COALESCE(se.payload ->> 'adapter_key', rs.adapter_key)
        WHERE se.validation_status = 'accepted'
            {adapter_filter}
            AND NOT EXISTS (
                SELECT 1
                FROM evidence e
                WHERE e.source_id = se.source_id
                    AND e.raw_ref IS NOT DISTINCT FROM rs.raw_ref
            )
        ORDER BY se.source_id ASC, rs.raw_ref ASC, se.created_at ASC, se.id ASC
        {limit_clause}
    """


def _accepted_staging_params(
    *,
    limit: int | None,
    adapter_keys: tuple[str, ...] | None,
) -> tuple[object, ...]:
    params: list[object] = []
    if adapter_keys is not None:
        if not adapter_keys:
            raise ValueError("adapter_keys must contain at least one key when provided")
        params.append(list(adapter_keys))
    if limit is None:
        return tuple(params)
    if limit < 1:
        raise ValueError("limit must be greater than 0")
    params.append(limit)
    return tuple(params)


def _candidate_from_row(row: tuple[Any, ...]) -> PromotionCandidate:
    payload = row[14]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if payload is None:
        payload = {}

    return PromotionCandidate(
        staging_evidence_id=str(row[0]),
        raw_snapshot_id=str(row[1]) if row[1] is not None else None,
        raw_ref=str(row[2]) if row[2] is not None else None,
        data_source_id=str(row[3]) if row[3] is not None else None,
        source_id=str(row[4]),
        source_type=str(row[5]),
        event_type=str(row[6]),
        title=str(row[7]),
        summary=str(row[8]),
        url=str(row[9]) if row[9] is not None else None,
        occurred_at=row[10],
        observed_at=row[11],
        confidence=float(row[12]),
        validation_status=str(row[13]),
        payload=dict(payload),
    )


def _with_admin_area_enrichment(
    cursor: Any,
    payload: EvidencePromotionPayload,
) -> EvidencePromotionPayload:
    if not _should_upsert_official_realtime_latest(payload):
        return payload
    if payload.event_type == "flood_warning":
        return _with_reviewed_warning_boundary(cursor, payload)
    if _official_realtime_station_id(payload) is None:
        return payload
    if not _needs_admin_area_enrichment(payload.properties):
        return payload

    point_geometry = _geojson_point_geometry(payload.properties)
    if point_geometry is None:
        return payload

    cursor.execute(
        """
        SELECT county_name, town_name, village_name
        FROM admin_area_profiles
        WHERE ST_Covers(geom, ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326))
        ORDER BY
            CASE scope
                WHEN 'village' THEN 0
                WHEN 'town' THEN 1
                WHEN 'county' THEN 2
                ELSE 3
            END,
            ST_Area(geom::geography) ASC
        LIMIT 1
        """,
        (point_geometry,),
    )
    row = cursor.fetchone()
    if row is None:
        return payload

    admin_area = _admin_area_from_row(row)
    if not admin_area:
        return payload

    enriched = dict(payload.properties)
    for key, value in admin_area.items():
        if _optional_text(enriched.get(key)) is None:
            enriched[key] = value
    return replace(payload, properties=enriched)


def _with_reviewed_warning_boundary(
    cursor: Any, payload: EvidencePromotionPayload
) -> EvidencePromotionPayload:
    if _geojson_geometry(payload.properties) is not None:
        return payload
    admin_code = _optional_text(payload.properties.get("admin_code"))
    if admin_code is None or re.fullmatch(r"[0-9]{8}", admin_code) is None:
        return payload
    cursor.execute(
        """
        /* reviewed-warning-boundary */
        WITH active_snapshot_candidates AS (
            SELECT snapshot.id
            FROM realtime_jurisdiction_boundary_snapshots snapshot
            WHERE snapshot.is_active
                AND snapshot.is_complete
                AND snapshot.expected_count = 22
                AND snapshot.imported_count = snapshot.expected_count
                AND snapshot.reviewed_at IS NOT NULL
                AND snapshot.review_ref IS NOT NULL
                AND snapshot.manifest_sha256 IS NOT NULL
                AND snapshot.manifest_sha256 = snapshot.approved_manifest_sha256
                AND (
                    SELECT count(*)
                    FROM realtime_jurisdiction_boundaries boundary_count
                    WHERE boundary_count.snapshot_id = snapshot.id
                ) = snapshot.expected_count
                AND NOT EXISTS (
                    SELECT 1
                    FROM realtime_jurisdiction_boundaries boundary_integrity
                    WHERE boundary_integrity.snapshot_id = snapshot.id
                        AND (
                            ST_IsEmpty(boundary_integrity.geom)
                            OR NOT ST_IsValid(boundary_integrity.geom)
                            OR boundary_integrity.geom_sha256 <> encode(
                                digest(ST_AsEWKB(boundary_integrity.geom), 'sha256'),
                                'hex'
                            )
                        )
                )
                AND snapshot.manifest_sha256 = (
                    SELECT encode(
                        digest(
                            convert_to(
                                COALESCE(
                                    jsonb_agg(
                                        jsonb_build_array(
                                            boundary_manifest.jurisdiction_code,
                                            boundary_manifest.geom_sha256
                                        )
                                        ORDER BY boundary_manifest.jurisdiction_code
                                    ),
                                    '[]'::jsonb
                                )::text,
                                'UTF8'
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                    FROM realtime_jurisdiction_boundaries boundary_manifest
                    WHERE boundary_manifest.snapshot_id = snapshot.id
                )
        ),
        active_snapshot AS (
            SELECT candidate.id
            FROM active_snapshot_candidates candidate
            WHERE (SELECT count(*) FROM active_snapshot_candidates) = 1
        )
        SELECT
            ST_AsGeoJSON(boundary.geom),
            ST_AsGeoJSON(ST_PointOnSurface(boundary.geom))
        FROM active_snapshot snapshot
        JOIN realtime_jurisdiction_boundaries boundary
            ON boundary.snapshot_id = snapshot.id
        WHERE boundary.jurisdiction_code = %s
            AND NOT ST_IsEmpty(boundary.geom)
            AND ST_IsValid(boundary.geom)
            AND GeometryType(boundary.geom) IN ('POLYGON', 'MULTIPOLYGON')
        """,
        (admin_code,),
    )
    row = cursor.fetchone()
    if row is None:
        return payload
    try:
        boundary = json.loads(str(row[0]))
        point = json.loads(str(row[1]))
    except (json.JSONDecodeError, TypeError):
        return payload
    if boundary.get("type") == "Polygon":
        boundary = {"type": "MultiPolygon", "coordinates": [boundary.get("coordinates", [])]}
    if boundary.get("type") != "MultiPolygon" or point.get("type") != "Point":
        return payload
    properties = dict(payload.properties)
    properties["location_payload"] = {"geometry": boundary}
    properties["latest_point_geometry"] = point
    properties["location_precision"] = "admin_area"
    return replace(payload, properties=properties)


def _needs_admin_area_enrichment(properties: dict[str, Any]) -> bool:
    return any(
        _optional_text(properties.get(key)) is None
        for key in ("county", "town", "village")
    )


def _admin_area_from_row(row: Any) -> dict[str, str]:
    values = {
        "county": _row_value(row, 0, "county_name"),
        "town": _row_value(row, 1, "town_name"),
        "village": _row_value(row, 2, "village_name"),
    }
    return {key: value for key, value in values.items() if value is not None}


def _row_value(row: Any, index: int, key: str) -> str | None:
    if isinstance(row, dict):
        return _optional_text(row.get(key))
    try:
        return _optional_text(row[index])
    except (IndexError, TypeError, KeyError):
        return None


def _payload_adapter_key(payload: dict[str, Any]) -> str | None:
    adapter_key = payload.get("adapter_key")
    return str(adapter_key) if adapter_key else None


def _geojson_geometry(properties: dict[str, Any]) -> str | None:
    location_payload = properties.get("location_payload")
    if not isinstance(location_payload, dict):
        return None
    geometry = location_payload.get("geometry")
    if not isinstance(geometry, dict):
        return None
    return json.dumps(geometry, sort_keys=True, separators=(",", ":"))


def _geojson_point_geometry(properties: dict[str, Any]) -> str | None:
    latest_point_geometry = properties.get("latest_point_geometry")
    if isinstance(latest_point_geometry, dict) and latest_point_geometry.get("type") == "Point":
        return json.dumps(latest_point_geometry, sort_keys=True, separators=(",", ":"))
    location_payload = properties.get("location_payload")
    if not isinstance(location_payload, dict):
        return None
    geometry = location_payload.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") != "Point":
        return None
    return json.dumps(geometry, sort_keys=True, separators=(",", ":"))


def _should_upsert_official_realtime_latest(payload: EvidencePromotionPayload) -> bool:
    if payload.source_type != "official":
        return False
    if payload.properties.get("evidence_scope") != "current":
        return False
    if (payload.adapter_key, payload.event_type) not in {
        ("official.cwa.rainfall", "rainfall"),
        ("official.wra.water_level", "water_level"),
        ("official.wra_iow.flood_depth", "flood_report"),
        ("local.tainan.flood_sensor", "flood_report"),
        ("official.cwa.heavy_rain_warning", "flood_warning"),
        ("official.ncdr.cap", "flood_warning"),
    }:
        return False
    return payload.observed_at is not None


def _current_candidate_rejection_reason(
    payload: EvidencePromotionPayload,
) -> str | None:
    if not _is_reviewed_current_candidate(payload):
        return None
    if not _is_aware_datetime(payload.observed_at) or (
        payload.occurred_at is not None and not _is_aware_datetime(payload.occurred_at)
    ):
        return "invalid_observation_time"
    assert payload.observed_at is not None
    generation = parse_datetime(
        payload.properties.get("ingestion_generation_started_at")
    )
    reference_time = generation if _is_aware_datetime(generation) else datetime.now(UTC)
    assert reference_time is not None
    if payload.observed_at > reference_time + timedelta(minutes=15):
        return "future_observation"
    if _has_invalid_explicit_point(payload.properties):
        return "invalid_point_geometry"
    return None


def _is_reviewed_current_candidate(payload: EvidencePromotionPayload) -> bool:
    return (
        payload.source_type == "official"
        and payload.properties.get("evidence_scope") == "current"
        and (payload.adapter_key, payload.event_type)
        in {
            ("official.cwa.rainfall", "rainfall"),
            ("official.wra.water_level", "water_level"),
            ("official.wra_iow.flood_depth", "flood_report"),
            ("local.tainan.flood_sensor", "flood_report"),
            ("official.cwa.heavy_rain_warning", "flood_warning"),
            ("official.ncdr.cap", "flood_warning"),
        }
    )


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _has_invalid_explicit_point(properties: dict[str, Any]) -> bool:
    latest_point = properties.get("latest_point_geometry")
    if latest_point is not None and (
        not isinstance(latest_point, dict)
        or latest_point.get("type") != "Point"
        or not _valid_wgs84_point(latest_point)
    ):
        return True
    location_payload = properties.get("location_payload")
    if not isinstance(location_payload, dict):
        return False
    geometry = location_payload.get("geometry")
    return (
        isinstance(geometry, dict)
        and geometry.get("type") == "Point"
        and not _valid_wgs84_point(geometry)
    )


def _valid_wgs84_point(geometry: dict[str, Any]) -> bool:
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return False
    longitude, latitude = coordinates
    if (
        not isinstance(longitude, (int, float))
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or isinstance(latitude, bool)
    ):
        return False
    return (
        math.isfinite(float(longitude))
        and math.isfinite(float(latitude))
        and -180 <= float(longitude) <= 180
        and -90 <= float(latitude) <= 90
    )


def _is_current_cap_lifecycle_candidate(payload: EvidencePromotionPayload) -> bool:
    return (
        payload.source_type == "official"
        and payload.properties.get("evidence_scope") == "current"
        and (payload.adapter_key, payload.event_type)
        in {
            ("official.cwa.heavy_rain_warning", "flood_warning"),
            ("official.ncdr.cap", "flood_warning"),
        }
    )


def _official_realtime_station_id(payload: EvidencePromotionPayload) -> str | None:
    if payload.event_type == "flood_warning":
        admin_code = _optional_text(payload.properties.get("admin_code"))
        sender = _optional_text(payload.properties.get("cap_sender"))
        identifier = _optional_text(payload.properties.get("cap_identifier"))
        sent = parse_datetime(payload.properties.get("cap_sent"))
        if (
            admin_code is None
            or re.fullmatch(r"[0-9]{8}", admin_code) is None
            or sender is None
            or identifier is None
            or sent is None
            or sent.tzinfo is None
            or sent.utcoffset() is None
        ):
            return None
        return "cap:" + admin_code + ":" + cap_message_digest(
            sender=sender,
            identifier=identifier,
            sent=sent,
        )
    station_id = _optional_text(payload.properties.get("station_id"))
    if station_id is not None:
        return station_id
    if not _can_fallback_station_id(payload):
        return None
    return _station_id_from_source_id(payload.source_id)


def _station_id_from_source_id(source_id: str) -> str | None:
    for separator in (":", "|", "@"):
        head, found, _tail = source_id.partition(separator)
        candidate = head.strip()
        if found and _looks_like_station_id(candidate):
            return candidate
    return None


def _can_fallback_station_id(payload: EvidencePromotionPayload) -> bool:
    return (payload.adapter_key, payload.event_type) in {
        ("official.cwa.rainfall", "rainfall"),
        ("official.wra.water_level", "water_level"),
        ("official.civil_iot.flood_sensor", "flood_report"),
    }


def _looks_like_station_id(candidate: str) -> bool:
    if "." in candidate:
        return False
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{1,30}[A-Za-z0-9])?", candidate) is None:
        return False
    return any(char.isdigit() for char in candidate) or any(char.isupper() for char in candidate)


def _is_expired_cap(properties: dict[str, Any]) -> bool:
    if properties.get("expired") is True:
        return True
    status = _optional_text(properties.get("cap_status"))
    return status in {"expired", "cancelled", "canceled"}


def _official_realtime_risk_factor(payload: EvidencePromotionPayload) -> float | None:
    if payload.event_type == "rainfall":
        rainfall_1h = _optional_float(payload.properties.get("rainfall_mm_1h"))
        if rainfall_1h is None:
            return None
        return _rainfall_realtime_risk_factor(rainfall_1h)

    if payload.event_type == "water_level":
        water_level_m = _optional_float(payload.properties.get("water_level_m"))
        warning_level_m = _optional_float(payload.properties.get("warning_level_m"))
        if water_level_m is None or warning_level_m is None or warning_level_m <= 0:
            return None
        ratio = water_level_m / warning_level_m
        if ratio >= 1.0:
            return 1.0
        if ratio >= 0.8:
            return 0.8
        if ratio >= 0.5:
            return 0.5
        if ratio >= 0.25:
            return 0.25
        return 0.0

    if payload.event_type == "flood_report":
        flood_depth_cm = _optional_float(payload.properties.get("flood_depth_cm"))
        if flood_depth_cm is None:
            return None
        if flood_depth_cm >= 50:
            return 1.0
        if flood_depth_cm >= 30:
            return 0.8
        if flood_depth_cm >= 15:
            return 0.5
        if flood_depth_cm >= 3:
            return 0.25
        return 0.0

    if payload.event_type == "flood_warning":
        return 1.0

    return None


def _official_realtime_source_weight(payload: EvidencePromotionPayload) -> float | None:
    return _optional_float(payload.properties.get("source_weight"))


def _rainfall_realtime_risk_factor(rainfall_1h_mm: float) -> float:
    if rainfall_1h_mm >= 80:
        return 1.0
    if rainfall_1h_mm >= 40:
        return 0.7
    if rainfall_1h_mm >= 20:
        return 0.35
    if rainfall_1h_mm >= 10:
        return 0.15
    return 0.0


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _quality_flags(properties: dict[str, Any]) -> dict[str, Any]:
    quality_flags = properties.get("quality_flags")
    result = dict(quality_flags) if isinstance(quality_flags, dict) else {}
    for key in (
        "location_precision",
        "active_from",
        "active_until",
        "ingestion_generation_started_at",
    ):
        value = properties.get(key)
        if isinstance(value, str) and value:
            result[key] = value
    triple = _cap_triple(
        properties.get("cap_sender"),
        properties.get("cap_identifier"),
        properties.get("cap_sent"),
    )
    if triple is not None:
        sender, identifier, sent = triple
        result["cap_message_digest"] = cap_message_digest(
            sender=sender,
            identifier=identifier,
            sent=sent,
        )
    return result


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
