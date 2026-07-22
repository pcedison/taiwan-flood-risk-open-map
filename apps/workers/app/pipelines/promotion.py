from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import math
import re
from typing import Any, Protocol


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

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        """Persist one promoted evidence record and return its evidence id."""


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
        evidence_ids.append(writer.write_evidence(build_evidence_promotion_payload(candidate)))

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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _accepted_staging_sql(limit=limit, adapter_keys=adapter_keys),
                    _accepted_staging_params(limit=limit, adapter_keys=adapter_keys),
                )
                return tuple(_candidate_from_row(row) for row in cursor.fetchall())

    def write_evidence(self, payload: EvidencePromotionPayload) -> str:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                enriched_payload = _with_admin_area_enrichment(cursor, payload)
                weighted_payload = _with_local_duplicate_suppression(cursor, enriched_payload)
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
                    DO UPDATE SET
                        updated_at = evidence.updated_at
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
                    raise RuntimeError("evidence insert did not return an id")
                evidence_id = str(row[0])
                if _should_upsert_official_realtime_latest(weighted_payload):
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
            WHERE EXCLUDED.observed_at >= official_realtime_latest.observed_at
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


def _with_local_duplicate_suppression(
    cursor: Any,
    payload: EvidencePromotionPayload,
) -> EvidencePromotionPayload:
    if not _should_check_local_duplicate(payload):
        return payload

    point_geometry = _geojson_point_geometry(payload.properties)
    if point_geometry is None:
        return payload

    cursor.execute(
        """
        SELECT adapter_key, station_id
        FROM official_realtime_latest
        WHERE adapter_key NOT LIKE 'local.%'
            AND event_type = %s
            AND observed_at >= %s - interval '30 minutes'
            AND observed_at <= %s + interval '30 minutes'
            AND ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)::geography,
                150
            )
        ORDER BY
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)::geography
            ) ASC,
            observed_at DESC
        LIMIT 1
        """,
        (
            payload.event_type,
            payload.observed_at,
            payload.observed_at,
            point_geometry,
            point_geometry,
        ),
    )
    row = cursor.fetchone()
    if row is None:
        return payload

    duplicate_adapter_key = _row_value(row, 0, "adapter_key")
    duplicate_station_id = _row_value(row, 1, "station_id")
    if duplicate_adapter_key is None or duplicate_station_id is None:
        return payload

    properties = dict(payload.properties)
    quality_flags = _quality_flags(properties)
    quality_flags.update(
        {
            "duplicate_candidate": True,
            "duplicate_of_adapter_key": duplicate_adapter_key,
            "duplicate_of_station_id": duplicate_station_id,
        }
    )
    properties["quality_flags"] = quality_flags
    properties["source_weight"] = min(
        _optional_float(properties.get("source_weight")) or 1.0,
        0.45,
    )
    return replace(payload, properties=properties)


def _should_check_local_duplicate(payload: EvidencePromotionPayload) -> bool:
    if not _should_upsert_official_realtime_latest(payload):
        return False
    if payload.adapter_key is None or not payload.adapter_key.startswith("local."):
        return False
    return payload.observed_at is not None


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
    if payload.adapter_key is None:
        return False
    if payload.event_type not in {
        "rainfall",
        "water_level",
        "flood_report",
        "flood_warning",
        "status_only",
    }:
        return False
    if payload.event_type == "flood_warning" and _is_expired_cap(payload.properties):
        return False
    return payload.observed_at is not None


def _official_realtime_station_id(payload: EvidencePromotionPayload) -> str | None:
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
    if isinstance(quality_flags, dict):
        return quality_flags
    return {}


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
