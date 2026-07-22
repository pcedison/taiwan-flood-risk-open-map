from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Mapping

from app.ops.local_source.local_source_action_plan import (
    ACCEPTED_SIGNAL_EVIDENCE_STATUSES,
    ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES,
    COMPLETION_EVIDENCE_SCHEMA_VERSION,
)

PRODUCTION_OPERATIONAL_REQUIREMENTS = [
    "freshness_policy",
    "raw_snapshot_retention_policy",
    "monitored_scheduler_cadence",
    "hosted_egress_review",
    "worker_persisted_evidence_path",
]


def build_official_request_packets(
    action_plan: Mapping[str, Any],
    *,
    counties: Iterable[str] | None = None,
    signal_types: Iterable[str] | None = None,
    completion_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    packets: list[dict[str, Any]] = []
    priority_by_county = {
        str(item["county"]): item
        for item in action_plan.get("integration_priority_queue", [])
    }
    packets.extend(
        _authorization_packet(
            item,
            priority_item=priority_by_county.get(str(item["county"])),
        )
        for item in action_plan.get("authorization_requests", [])
    )
    packets.extend(
        _metadata_release_packet(
            item,
            priority_item=priority_by_county.get(str(item["county"])),
        )
        for item in action_plan.get("metadata_release_monitors", [])
    )
    packets.extend(
        _public_api_contract_packet(
            item,
            priority_item=priority_by_county.get(str(item["county"])),
        )
        for item in action_plan.get("public_api_contract_reviews", [])
    )
    packets.extend(
        _live_smoke_review_packet(
            item,
            priority_item=priority_by_county.get(str(item["county"])),
        )
        for item in action_plan.get("live_smoke_reviews", [])
    )
    packets.extend(
        _signal_gap_packet(
            item,
            priority_item=priority_by_county.get(str(item["county"])),
        )
        for item in action_plan.get("sensor_signal_gap_reviews", [])
    )
    ordered_packets = _remove_completed_packet_targets(
        tuple(sorted(packets, key=_packet_sort_key)),
        completion_evidence=completion_evidence,
    )
    return _filter_packets(
        ordered_packets,
        counties=counties,
        signal_types=signal_types,
    )


def build_signal_gap_request_batches(
    action_plan: Mapping[str, Any],
    *,
    signal_types: Iterable[str] | None = None,
    completion_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    signal_filter = (
        {str(signal_type) for signal_type in signal_types} if signal_types else None
    )
    accepted_signal_keys, _ = _accepted_completion_keys(completion_evidence)
    priority_by_county = {
        str(item["county"]): item
        for item in action_plan.get("integration_priority_queue", [])
        if isinstance(item, Mapping) and item.get("county")
    }
    batches: list[dict[str, Any]] = []
    for group in action_plan.get("signal_gap_priority_groups", []):
        if not isinstance(group, Mapping):
            continue
        request_batch = group.get("official_request_batch")
        if not isinstance(request_batch, Mapping):
            continue
        target_signal_type = str(request_batch.get("target_signal_type", ""))
        if signal_filter is not None and target_signal_type not in signal_filter:
            continue
        counties = [str(county) for county in request_batch.get("counties", [])]
        batch = dict(request_batch)
        batch.update(
            {
                "batch_id": f"signal-gap-batch/{target_signal_type}",
                "dispatch_status": "not_sent",
                "sent_at": None,
                "follow_up_due_at": None,
                "official_reply_ref": None,
                "private_evidence_ref_hint": (
                    "private-ops://local-source/signal-gap-batch/"
                    f"{target_signal_type}"
                ),
                "completion_evidence_targets": [
                    target
                    for county in counties
                    for target in _signal_gap_evidence_targets(
                        county,
                        signal_types=[target_signal_type],
                    )
                ],
            }
        )
        if accepted_signal_keys:
            remaining_targets = [
                target
                for target in batch["completion_evidence_targets"]
                if (
                    str(target.get("county", "")),
                    str(target.get("signal_type", "")),
                )
                not in accepted_signal_keys
            ]
            if len(remaining_targets) == len(batch["completion_evidence_targets"]):
                batches.append(batch)
                continue
            if not remaining_targets:
                continue
            remaining_counties = [
                str(target["county"])
                for target in remaining_targets
                if target.get("county")
            ]
            remaining_items = [
                priority_by_county[county]
                for county in remaining_counties
                if county in priority_by_county
            ]
            batch.update(
                {
                    "county_count": len(remaining_counties),
                    "counties": remaining_counties,
                    "requested_counterparties": list(
                        dict.fromkeys(
                            str(item["requested_counterparty"])
                            for item in remaining_items
                        )
                    ),
                    "tracking_statuses": list(
                        dict.fromkeys(
                            str(item["tracking_status"]) for item in remaining_items
                        )
                    ),
                    "packet_generator_command": _signal_gap_packet_generator_command(
                        target_signal_type,
                        counties=remaining_counties,
                    ),
                    "completion_evidence_targets": remaining_targets,
                }
            )
        batches.append(batch)
    return tuple(batches)


def _remove_completed_packet_targets(
    packets: tuple[dict[str, Any], ...],
    *,
    completion_evidence: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    accepted_signal_keys, accepted_source_contract_keys = _accepted_completion_keys(
        completion_evidence
    )
    if not accepted_signal_keys and not accepted_source_contract_keys:
        return packets

    filtered: list[dict[str, Any]] = []
    for packet in packets:
        original_targets = [
            target
            for target in packet.get("completion_evidence_targets", [])
            if isinstance(target, Mapping)
        ]
        if not original_targets:
            filtered.append(packet)
            continue
        remaining_targets = [
            dict(target)
            for target in original_targets
            if not _completion_target_is_accepted(
                target,
                accepted_signal_keys=accepted_signal_keys,
                accepted_source_contract_keys=accepted_source_contract_keys,
            )
        ]
        if len(remaining_targets) == len(original_targets):
            filtered.append(packet)
            continue
        if not remaining_targets:
            continue

        updated = dict(packet)
        updated["completion_evidence_targets"] = remaining_targets
        if "target_signal_types" in updated:
            remaining_signal_types = {
                str(target.get("signal_type", ""))
                for target in remaining_targets
                if target.get("manifest_section") == "signal_family_gap_evidence"
            }
            updated["target_signal_types"] = [
                str(signal_type)
                for signal_type in packet.get("target_signal_types", [])
                if str(signal_type) in remaining_signal_types
            ]
        filtered.append(updated)
    return tuple(filtered)


def _accepted_completion_keys(
    completion_evidence: Mapping[str, Any] | None,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    signal_keys: set[tuple[str, str]] = set()
    source_contract_keys: set[tuple[str, str]] = set()
    if (
        completion_evidence is None
        or completion_evidence.get("schema_version")
        != COMPLETION_EVIDENCE_SCHEMA_VERSION
    ):
        return signal_keys, source_contract_keys

    signal_items = completion_evidence.get("signal_family_gap_evidence")
    if isinstance(signal_items, list):
        for item in signal_items:
            if not isinstance(item, Mapping):
                continue
            if item.get("status") not in ACCEPTED_SIGNAL_EVIDENCE_STATUSES:
                continue
            county = _non_empty_text(item.get("county"))
            signal_type = _non_empty_text(item.get("signal_type"))
            evidence_ref = _reviewed_evidence_text(item.get("evidence_ref"))
            reviewed_at = _reviewed_evidence_text(item.get("reviewed_at"))
            if county and signal_type and evidence_ref and reviewed_at:
                signal_keys.add((county, signal_type))

    source_contract_items = completion_evidence.get("source_contract_evidence")
    if isinstance(source_contract_items, list):
        for item in source_contract_items:
            if not isinstance(item, Mapping):
                continue
            if item.get("status") not in ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES:
                continue
            county = _non_empty_text(item.get("county"))
            gate = _non_empty_text(item.get("gate"))
            evidence_ref = _reviewed_evidence_text(item.get("evidence_ref"))
            reviewed_at = _reviewed_evidence_text(item.get("reviewed_at"))
            if county and gate and evidence_ref and reviewed_at:
                source_contract_keys.add((county, gate))

    return signal_keys, source_contract_keys


def _completion_target_is_accepted(
    target: Mapping[str, Any],
    *,
    accepted_signal_keys: set[tuple[str, str]],
    accepted_source_contract_keys: set[tuple[str, str]],
) -> bool:
    section = str(target.get("manifest_section", ""))
    county = str(target.get("county", "")).strip()
    if section == "signal_family_gap_evidence":
        return (county, str(target.get("signal_type", "")).strip()) in accepted_signal_keys
    if section == "source_contract_evidence":
        return (county, str(target.get("gate", "")).strip()) in accepted_source_contract_keys
    return False


def _signal_gap_packet_generator_command(
    signal_type: str,
    *,
    counties: list[str],
) -> str:
    county_args = " ".join(f"--county {county}" for county in counties)
    return (
        "PYTHONPATH=apps/api python scripts/local-source-request-packets.py "
        f"--format markdown --signal-type {signal_type} {county_args}"
    )


def _non_empty_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _reviewed_evidence_text(value: Any) -> str | None:
    text = _non_empty_text(value)
    if text is None or text.upper().startswith("REPLACE_WITH_"):
        return None
    return text


def _filter_packets(
    packets: tuple[dict[str, Any], ...],
    *,
    counties: Iterable[str] | None,
    signal_types: Iterable[str] | None,
) -> tuple[dict[str, Any], ...]:
    county_filter = {str(county) for county in counties} if counties else None
    signal_filter = (
        {str(signal_type) for signal_type in signal_types} if signal_types else None
    )
    filtered: list[dict[str, Any]] = []
    for packet in packets:
        if county_filter is not None and str(packet.get("county", "")) not in county_filter:
            continue
        if signal_filter is not None:
            packet_signals = {
                str(signal_type)
                for signal_type in packet.get("target_signal_types", [])
            }
            if packet_signals.isdisjoint(signal_filter):
                continue
        filtered.append(packet)
    return tuple(filtered)


def render_official_request_packets_markdown(
    packets: tuple[dict[str, Any], ...],
) -> str:
    lines = [
        "# 地方即時水情官方請求包",
        "",
        "此文件由 local-source action plan 產生，用於追蹤尚需人工授權或官方資料釋出的地方即時水情缺口。",
        "",
    ]
    for packet in packets:
        lines.extend(_render_packet_markdown(packet))
    return "\n".join(lines).rstrip() + "\n"


def render_signal_gap_request_batches_markdown(
    batches: tuple[dict[str, Any], ...],
) -> str:
    lines = [
        "# Signal Gap Official Request Batches",
        "",
        "Generated from the local-source action plan. Each batch tracks one "
        "missing signal family and the counties that need an official read API, "
        "authorization-gated adapter path, production adapter, or official "
        "unavailable-source record.",
        "",
    ]
    for batch in batches:
        lines.extend(_render_signal_gap_batch_markdown(batch))
    return "\n".join(lines).rstrip() + "\n"


def build_signal_gap_dispatch_evidence_template(
    batches: tuple[dict[str, Any], ...],
    *,
    dispatch_evidence_ref: str,
    dispatched_at: str,
    follow_up_due_at: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    signal_family_gap_evidence: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for batch in batches:
        for target in batch.get("completion_evidence_targets", []):
            if not isinstance(target, Mapping):
                continue
            if str(target.get("manifest_section", "")) != "signal_family_gap_evidence":
                continue
            item = _signal_family_gap_dispatch_item(
                target,
                dispatch_evidence_ref=dispatch_evidence_ref,
                dispatched_at=dispatched_at,
                follow_up_due_at=follow_up_due_at,
            )
            key = (str(item["county"]), str(item["signal_type"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            signal_family_gap_evidence.append(item)

    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at or dispatched_at,
        "notes": [
            "Draft generated from signal-gap official request batches.",
            "request_dispatched records proof that an official request was sent; it does not satisfy completion gates.",
            "Replace status and evidence_ref only after official reply, adapter smoke, or private ops evidence is accepted.",
            "Do not commit filled private evidence refs, tokens, screenshots, or official reply transcripts.",
        ],
        "signal_family_gap_evidence": signal_family_gap_evidence,
        "source_contract_evidence": [],
        "production_gate_evidence": [],
    }


def build_source_contract_dispatch_evidence_template(
    packets: tuple[dict[str, Any], ...],
    *,
    dispatch_evidence_ref: str,
    dispatched_at: str,
    follow_up_due_at: str | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    source_contract_evidence: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for packet in packets:
        for target in packet.get("completion_evidence_targets", []):
            if not isinstance(target, Mapping):
                continue
            if str(target.get("manifest_section", "")) != "source_contract_evidence":
                continue
            item = _source_contract_dispatch_item(
                target,
                dispatch_evidence_ref=dispatch_evidence_ref,
                dispatched_at=dispatched_at,
                follow_up_due_at=follow_up_due_at,
            )
            key = (str(item["county"]), str(item["gate"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            source_contract_evidence.append(item)

    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at or dispatched_at,
        "notes": [
            "Draft generated from official request packets.",
            "request_dispatched records proof that an authorization or contract request was sent; it does not satisfy completion gates.",
            "Replace status and evidence_ref only after official reply, adapter smoke, contract review, or private ops evidence is accepted.",
            "Do not commit filled private evidence refs, tokens, screenshots, or official reply transcripts.",
        ],
        "signal_family_gap_evidence": [],
        "source_contract_evidence": source_contract_evidence,
        "production_gate_evidence": [],
    }


def build_completion_evidence_template(
    packets: tuple[dict[str, Any], ...],
    *,
    captured_at: str = "REPLACE_WITH_CAPTURED_AT",
) -> dict[str, Any]:
    source_contract_evidence: list[dict[str, Any]] = []
    signal_family_gap_evidence: list[dict[str, Any]] = []
    source_contract_keys: set[tuple[str, str]] = set()
    signal_gap_keys: set[tuple[str, str]] = set()

    for packet in packets:
        for target in packet.get("completion_evidence_targets", []):
            if not isinstance(target, Mapping):
                continue
            section = str(target.get("manifest_section", ""))
            if section == "source_contract_evidence":
                item = _source_contract_template_item(target)
                key = (str(item["county"]), str(item["gate"]))
                if key not in source_contract_keys:
                    source_contract_keys.add(key)
                    source_contract_evidence.append(item)
            elif section == "signal_family_gap_evidence":
                item = _signal_family_gap_template_item(target)
                key = (str(item["county"]), str(item["signal_type"]))
                if key not in signal_gap_keys:
                    signal_gap_keys.add(key)
                    signal_family_gap_evidence.append(item)

    return {
        "schema_version": COMPLETION_EVIDENCE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "notes": [
            "Draft generated from official request packets; every entry starts as pending.",
            "Replace status and evidence_ref only after official reply, adapter smoke, or private ops evidence is accepted.",
            "Do not commit filled private evidence refs, tokens, screenshots, or official reply transcripts.",
        ],
        "signal_family_gap_evidence": signal_family_gap_evidence,
        "source_contract_evidence": source_contract_evidence,
        "production_gate_evidence": [],
    }


def _source_contract_template_item(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "county": str(target.get("county", "")),
        "gate": str(target.get("gate", "")),
        "status": "pending",
        "accepted_statuses": [
            str(status) for status in target.get("accepted_statuses", [])
        ],
        "evidence_ref": str(target.get("private_evidence_ref_hint", "")),
    }


def _signal_family_gap_template_item(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "county": str(target.get("county", "")),
        "signal_type": str(target.get("signal_type", "")),
        "status": "pending",
        "accepted_statuses": [
            str(status) for status in target.get("accepted_statuses", [])
        ],
        "evidence_ref": str(target.get("private_evidence_ref_hint", "")),
    }


def _signal_family_gap_dispatch_item(
    target: Mapping[str, Any],
    *,
    dispatch_evidence_ref: str,
    dispatched_at: str,
    follow_up_due_at: str | None,
) -> dict[str, Any]:
    item = {
        "county": str(target.get("county", "")),
        "signal_type": str(target.get("signal_type", "")),
        "status": "request_dispatched",
        "accepted_statuses": [
            str(status) for status in target.get("accepted_statuses", [])
        ],
        "evidence_ref": dispatch_evidence_ref,
        "dispatched_at": dispatched_at,
    }
    if follow_up_due_at:
        item["follow_up_due_at"] = follow_up_due_at
    return item


def _source_contract_dispatch_item(
    target: Mapping[str, Any],
    *,
    dispatch_evidence_ref: str,
    dispatched_at: str,
    follow_up_due_at: str | None,
) -> dict[str, Any]:
    item = {
        "county": str(target.get("county", "")),
        "gate": str(target.get("gate", "")),
        "status": "request_dispatched",
        "accepted_statuses": [
            str(status) for status in target.get("accepted_statuses", [])
        ],
        "evidence_ref": dispatch_evidence_ref,
        "dispatched_at": dispatched_at,
    }
    if follow_up_due_at:
        item["follow_up_due_at"] = follow_up_due_at
    return item


def _authorization_packet(
    item: Mapping[str, Any],
    *,
    priority_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    county = str(item["county"])
    required_fields = list(item.get("required_read_api_fields", []))
    source_urls = list(item.get("application_urls", []))
    reason = str(item.get("reason", ""))
    system_name = _authorization_system_name(item, reason)
    target_signal_types = _priority_target_signal_types(priority_item)
    return {
        "county": county,
        "packet_type": "authorization_request",
        "requires_human_intervention": True,
        "subject": f"{county} {system_name} 即時水情 read API 授權請求",
        "source_urls": source_urls,
        "requested_counterparty": item.get("requested_counterparty"),
        "tracking_status": item.get("tracking_status"),
        "last_followed_up_at": item.get("last_followed_up_at"),
        "required_read_api_fields": required_fields,
        "completion_evidence_targets": (
            _source_contract_evidence_targets(county, gate="authorization_request")
            + _signal_gap_evidence_targets(county, signal_types=target_signal_types)
        ),
        "request_body": _authorization_request_body(county, system_name),
        "checklist": [
            "確認是否可提供最新觀測 read API",
            "確認 API contract、授權條款與 rate limit",
            "取得測站清冊、座標 metadata 與範例 response",
            "確認資料欄位可滿足 production adapter 必備欄位",
        ]
        + _production_operational_checklist(),
    } | _authorization_contract_fields(system_name) | _priority_packet_fields(priority_item)


def _authorization_request_body(county: str, system_name: str) -> str:
    if system_name == "KWIS":
        return (
            f"目前{county}地方直連即時水情來源仍需要官方授權。請確認 {system_name} "
            "既有 read API methods 的正式 Token、可讀範圍與 production 使用條款；"
            "不要將設備上傳 API 當作查詢 API。請協助提供正式 API contract、"
            "申請方式、授權條款、rate limit、測站清冊、座標 metadata 與範例 response。"
            f"{_production_operational_request_suffix()}"
        )
    return (
        f"目前{county}地方直連即時水情來源仍需要官方授權。請確認 {system_name} "
        "是否可提供最新觀測 read API，不是設備上傳 API。若可提供，請協助提供正式 "
        "API contract、申請方式、授權條款、rate limit、測站清冊、座標 metadata "
        "與範例 response。"
        f"{_production_operational_request_suffix()}"
    )


def _metadata_release_packet(
    item: Mapping[str, Any],
    *,
    priority_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    county = str(item["county"])
    source_urls = list(item.get("metadata_source_urls", []))
    central_missing_signal_types = list(
        item.get("central_backbone_missing_signal_types", [])
    )
    target_signal_types = _metadata_target_signal_types(
        item,
        priority_item=priority_item,
    )
    non_qualifying_reasons = list(item.get("non_qualifying_source_reasons", []))
    area_hint = "南竿、北竿、莒光、東引" if county == "連江縣" else county
    excluded_summary = _non_qualifying_request_summary(non_qualifying_reasons)
    if central_missing_signal_types:
        status_sentence = "因此仍未補足 hydrologic_observation。"
        request_body = (
            f"目前{county}僅找到靜態或 metadata 類公開資料，尚未找到可機器讀取的"
            f"即時水文觀測 read API。請協助釋出{area_hint}的雨水下水道水位、道路"
            "淹水感測器、抽水站或水門水位、易淹區鄰近水位站等資料，或確認是否可加入 "
            "Civil IoT / WRA 等中央公開 SensorThings 主幹。"
            f"{excluded_summary}{status_sentence}"
        )
        checklist = [
            "確認是否可提供最新觀測 read API",
            "確認是否可加入 Civil IoT 或 WRA 公開主幹",
            "取得站點 ID、觀測時間、測值、單位與座標",
            "確認短期無感測器時的建置計畫或資料釋出時程",
        ] + _production_operational_checklist()
    else:
        signal_summary = "、".join(str(signal) for signal in target_signal_types)
        status_sentence = (
            "目前中央最低水文骨幹已補足；仍需補足地方直連訊號："
            f"{signal_summary}。"
        )
        request_body = (
            f"目前{county}已由中央主幹補足最低水文脈絡，但地方公開資料仍只有靜態"
            f"或 metadata 類資料。請協助釋出{area_hint}的雨水下水道水位、道路"
            "淹水感測器、抽水站或水門水位、易淹區鄰近水位站等地方直連 read API。"
            f"{excluded_summary}{status_sentence}"
        )
        checklist = [
            "確認是否可提供地方最新觀測 read API",
            "取得站點 ID、觀測時間、測值、單位與座標",
            "確認短期無感測器時的建置計畫或資料釋出時程",
        ] + _production_operational_checklist()
    request_body = request_body + _production_operational_request_suffix()
    return {
        "county": county,
        "packet_type": "metadata_release_request",
        "requires_human_intervention": True,
        "subject": f"{county}地方即時水情資料釋出請求",
        "source_urls": source_urls,
        "non_qualifying_source_names": list(item.get("non_qualifying_source_names", [])),
        "non_qualifying_source_urls": list(item.get("non_qualifying_source_urls", [])),
        "non_qualifying_source_reasons": non_qualifying_reasons,
        "requested_counterparty": item.get("requested_counterparty"),
        "tracking_status": item.get("tracking_status"),
        "last_followed_up_at": item.get("last_followed_up_at"),
        "target_signal_types": target_signal_types,
        "required_read_api_fields": list(item.get("required_read_api_fields", [])),
        "completion_evidence_targets": (
            _source_contract_evidence_targets(county, gate="metadata_release_monitor")
            + _signal_gap_evidence_targets(county, signal_types=target_signal_types)
        ),
        "request_body": request_body,
        "checklist": checklist,
    } | _priority_packet_fields(priority_item)


def _metadata_target_signal_types(
    item: Mapping[str, Any],
    *,
    priority_item: Mapping[str, Any] | None,
) -> list[Any]:
    central_missing = list(item.get("central_backbone_missing_signal_types", []))
    if central_missing:
        return central_missing
    missing = list(item.get("missing_signal_types", []))
    if missing:
        return missing
    if priority_item is not None:
        priority_missing = list(priority_item.get("missing_signal_types", []))
        if priority_missing:
            return priority_missing
        return list(priority_item.get("central_backbone_missing_signal_types", []))
    return []


def _public_api_contract_packet(
    item: Mapping[str, Any],
    *,
    priority_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    county = str(item["county"])
    source_urls = list(item.get("candidate_source_urls", []))
    required_fields = list(item.get("required_read_api_fields", []))
    contract_findings = list(item.get("candidate_contract_findings", []))
    missing_fields = list(item.get("candidate_contract_missing_fields", []))
    non_measurement_notes = list(
        item.get("candidate_contract_non_measurement_notes", [])
    )
    target_signal_types = _priority_target_signal_types(priority_item)
    return {
        "county": county,
        "packet_type": "public_api_contract_request",
        "requires_human_intervention": True,
        "subject": f"{county}地方即時水情 read API contract 請求",
        "source_urls": source_urls,
        "requested_counterparty": item.get("requested_counterparty"),
        "tracking_status": item.get("tracking_status"),
        "last_followed_up_at": item.get("last_followed_up_at"),
        "required_read_api_fields": required_fields,
        "candidate_contract_findings": contract_findings,
        "candidate_contract_missing_fields": missing_fields,
        "candidate_contract_non_measurement_notes": non_measurement_notes,
        "completion_evidence_targets": (
            _source_contract_evidence_targets(county, gate="public_api_contract_review")
            + _signal_gap_evidence_targets(county, signal_types=target_signal_types)
        ),
        "request_body": (
            f"目前{county}已有官方系統或成果頁線索，但尚未找到可公開機器讀取的"
            "最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、"
            "ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、"
            "站點 metadata 與範例 response。"
            f"{_candidate_contract_request_summary(contract_findings, missing_fields, non_measurement_notes)}"
            f"{_production_operational_request_suffix()}"
        ),
        "checklist": [
            "確認公開 read API URL 與 response 格式",
            "確認觀測時間、站點 ID、測值、單位與座標欄位",
            "確認授權條款、rate limit 與維運窗口",
            "取得可重跑 live smoke 的範例 response",
        ]
        + _production_operational_checklist(),
    } | _priority_packet_fields(priority_item)


def _live_smoke_review_packet(
    item: Mapping[str, Any],
    *,
    priority_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    county = str(item["county"])
    source_urls = list(item.get("candidate_source_urls", []))
    source_names = list(item.get("candidate_source_names", []))
    required_fields = list(item.get("required_read_api_fields", []))
    target_signal_types = _priority_target_signal_types(priority_item)
    return {
        "county": county,
        "packet_type": "live_smoke_review_request",
        "requires_human_intervention": True,
        "subject": f"{county}地方即時水情 live smoke 複核請求",
        "source_urls": source_urls,
        "source_names": source_names,
        "production_adapter_keys": list(item.get("production_adapter_keys", [])),
        "requested_counterparty": item.get("requested_counterparty"),
        "tracking_status": item.get("tracking_status"),
        "last_followed_up_at": item.get("last_followed_up_at"),
        "required_read_api_fields": required_fields,
        "completion_evidence_targets": _signal_gap_evidence_targets(
            county,
            signal_types=target_signal_types,
        ),
        "request_body": (
            f"目前{county}已有候選或部分 production adapter，但仍需要 live smoke "
            "複核觀測時間、站點 ID、測值、單位、座標與欄位語意。狀態或開關資料"
            "不得替代水位、雨量或淹水深度；若只能提供狀態，需標示為 status-only "
            "診斷線索。"
            f"{_production_operational_request_suffix()}"
        ),
        "checklist": [
            "重跑 live smoke 並保存 response 範例",
            "確認 observed_at、station_or_device_id、measurement_value、單位與座標",
            "確認狀態或開關欄位不被誤標為水位、雨量或淹水深度",
            "更新 adapter gate、verification log 與 freshness policy",
        ]
        + _production_operational_checklist(),
    } | _priority_packet_fields(priority_item)


def _signal_gap_packet(
    item: Mapping[str, Any],
    *,
    priority_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    county = str(item["county"])
    missing_signal_types = list(item.get("missing_signal_types", []))
    required_fields = list(item.get("required_read_api_fields", []))
    signal_summary = "、".join(str(signal) for signal in missing_signal_types)
    return {
        "county": county,
        "packet_type": "signal_gap_request",
        "requires_human_intervention": True,
        "subject": f"{county}缺漏水資訊訊號補齊請求",
        "source_urls": list(item.get("candidate_source_urls", [])),
        "production_adapter_keys": list(item.get("production_adapter_keys", [])),
        "status_only_source_names": list(item.get("status_only_source_names", [])),
        "status_only_source_urls": list(item.get("status_only_source_urls", [])),
        "status_only_signal_types": list(item.get("status_only_signal_types", [])),
        "requested_counterparty": item.get("requested_counterparty"),
        "tracking_status": item.get("tracking_status"),
        "last_followed_up_at": item.get("last_followed_up_at"),
        "target_signal_types": missing_signal_types,
        "required_read_api_fields": required_fields,
        "completion_evidence_targets": _signal_gap_evidence_targets(
            county,
            signal_types=missing_signal_types,
        ),
        "request_body": (
            f"目前{county}既有 production adapter 仍未覆蓋所有必要水資訊訊號："
            f"{signal_summary}。請協助確認是否有官方公開 read API、開放資料或"
            "可授權資料來源可補齊這些訊號；若資料只有警戒、開關、警示燈或營運"
            "狀態，請明確標示為 status-only，不得替代水位、雨量、淹水深度或"
            "下水道水位量測。"
            f"{_production_operational_request_suffix()}"
        ),
        "checklist": [
            "確認缺漏 signal families 是否存在官方 read API 或開放資料",
            "確認觀測時間、站點 ID、測值、單位與座標欄位",
            "確認 status-only 資料不會被當成水位、雨量或淹水深度",
            "若官方確認不存在，記錄不可取得證據與後續追蹤窗口",
        ]
        + _production_operational_checklist(),
    } | _priority_packet_fields(priority_item)


def _priority_packet_fields(priority_item: Mapping[str, Any] | None) -> dict[str, Any]:
    fields = _production_operational_packet_fields()
    if priority_item is None:
        return fields
    target_signal_types = _priority_target_signal_types(priority_item)
    if target_signal_types:
        fields["target_signal_types"] = target_signal_types
    return fields | {
        "priority_rank": priority_item.get("rank"),
        "priority_tier": priority_item.get("priority_tier"),
        "workstream": priority_item.get("workstream"),
        "priority_why_now": priority_item.get("why_now"),
        "completion_gate": priority_item.get("completion_gate"),
        "metadata_source_names": priority_item.get(
            "metadata_source_names",
            [],
        ),
        "metadata_source_urls": priority_item.get(
            "metadata_source_urls",
            [],
        ),
        "non_qualifying_source_names": priority_item.get(
            "non_qualifying_source_names",
            [],
        ),
        "non_qualifying_source_urls": priority_item.get(
            "non_qualifying_source_urls",
            [],
        ),
        "non_qualifying_source_reasons": priority_item.get(
            "non_qualifying_source_reasons",
            [],
        ),
        "candidate_contract_findings": priority_item.get(
            "candidate_contract_findings",
            [],
        ),
        "candidate_contract_missing_fields": priority_item.get(
            "candidate_contract_missing_fields",
            [],
        ),
        "candidate_contract_non_measurement_notes": priority_item.get(
            "candidate_contract_non_measurement_notes",
            [],
        ),
    }


def _priority_target_signal_types(
    priority_item: Mapping[str, Any] | None,
) -> list[Any]:
    if priority_item is None:
        return []
    target_signal_types = list(priority_item.get("missing_signal_types", []))
    if target_signal_types:
        return target_signal_types
    return list(priority_item.get("central_backbone_missing_signal_types", []))


def _source_contract_evidence_targets(
    county: str,
    *,
    gate: str,
) -> list[dict[str, Any]]:
    return [
        {
            "manifest_section": "source_contract_evidence",
            "county": county,
            "gate": gate,
            "accepted_statuses": sorted(ACCEPTED_SOURCE_CONTRACT_EVIDENCE_STATUSES),
            "evidence_ref_required": True,
            "private_evidence_ref_hint": (
                f"private-ops://local-source/source-contract/{county}/{gate}"
            ),
        }
    ]


def _signal_gap_evidence_targets(
    county: str,
    *,
    signal_types: list[Any],
) -> list[dict[str, Any]]:
    return [
        {
            "manifest_section": "signal_family_gap_evidence",
            "county": county,
            "signal_type": str(signal_type),
            "accepted_statuses": sorted(ACCEPTED_SIGNAL_EVIDENCE_STATUSES),
            "evidence_ref_required": True,
            "private_evidence_ref_hint": (
                f"private-ops://local-source/signal-gap/{county}/{signal_type}"
            ),
        }
        for signal_type in signal_types
    ]


def _production_operational_packet_fields() -> dict[str, Any]:
    return {
        "production_operational_requirements": list(
            PRODUCTION_OPERATIONAL_REQUIREMENTS
        ),
    }


def _production_operational_request_suffix() -> str:
    return (
        " Production 上線前也需確認 freshness policy、raw snapshot retention、"
        "scheduler cadence、hosted egress review，並走 worker-persisted evidence path。"
    )


def _production_operational_checklist() -> list[str]:
    return [
        "確認 freshness policy 與 stale/degraded/failed 門檻",
        "確認 raw snapshot retention policy 與可稽核保存位置",
        "確認 scheduler cadence、重試策略與監控告警責任",
        "確認 hosted egress review 與 worker-persisted evidence path",
    ]


def _non_qualifying_request_summary(reasons: list[Any]) -> str:
    if not reasons:
        return ""
    reason_text = "；".join(str(reason).rstrip("。") for reason in reasons)
    return f" 已查核但排除的官方線索：{reason_text}。"


def _candidate_contract_request_summary(
    findings: list[Any],
    missing_fields: list[Any],
    non_measurement_notes: list[Any],
) -> str:
    details: list[str] = []
    if findings:
        details.append("已查核頁面事實：" + "；".join(str(item).rstrip("。") for item in findings))
    if missing_fields:
        details.append(
            "目前缺少 production 必備欄位："
            + "、".join(str(field) for field in missing_fields)
        )
    if non_measurement_notes:
        details.append(
            "不可當量測來源："
            + "；".join(str(item).rstrip("。") for item in non_measurement_notes)
        )
    if not details:
        return ""
    return (
        " "
        + " ".join(details)
        + "；在取得官方 read API 或可 join metadata 前，不得以 fetched_at 偽裝觀測時間。"
    )


def _packet_sort_key(packet: Mapping[str, Any]) -> tuple[int, str]:
    rank = packet.get("priority_rank")
    if not isinstance(rank, int):
        rank = 9999
    return (rank, str(packet.get("county", "")))


def _authorization_contract_fields(system_name: str) -> dict[str, Any]:
    if system_name != "KWIS":
        return {}
    service_root = "https://kwis.kinmen.gov.tw/KWIS_IOT_Data/KWIS_IOT_Data_Service.asmx"
    known_read_methods = [
        "KWIS_Get_Rain_Gauge_Basic_Unit_Data",
        "KWIS_Get_Water_Level_Gauge_Basic_Unit_Data",
        "KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data",
        "KWIS_Get_Pump_Basic_Unit_Data",
        "KWIS_Get_Monitoring_Station_Sensor_Device_List",
    ]
    return {
        "api_contract_risk": "token_gated_read_methods_require_authorization",
        "insufficient_api_purposes": [
            "credentialed_read_api_without_authorized_token",
            "device_upload_api",
            "third_party_upload_integration",
        ],
        "required_api_purpose": "latest_observation_read_api",
        "credential_requirements": [
            "KWIS_key",
            "account",
            "password",
            "Token",
        ],
        "known_read_method_names": known_read_methods,
        "known_read_endpoint_urls": [
            f"{service_root}?WSDL",
            *(f"{service_root}?op={method}" for method in known_read_methods),
        ],
        "unauthorized_smoke_result": (
            "Blank-token GET smoke against KWIS_Get_Pump_Basic_Unit_Data, "
            "KWIS_Get_Water_Level_Gauge_Basic_Unit_Data, and "
            "KWIS_Get_Flood_Sensing_Device_Basic_Unit_Data returned "
            "ErrMsg (7) invalid Token with Data: []."
        ),
        "request_clarification": (
            "公開文件仍包含第三方設備 upload-only 介接流程，公開服務另已列出 "
            "token-gated read API methods，但空 Token smoke 只回 Data: []；production "
            "adapter 仍需縣府核發正式 Token、可讀範圍、rate limit 與 response schema。"
        ),
    }


def _authorization_system_name(item: Mapping[str, Any], reason: str) -> str:
    text = " ".join(
        str(part)
        for part in (
            reason,
            item.get("application_note"),
            " ".join(str(url) for url in item.get("application_urls", [])),
        )
        if part
    )
    if "KWIS" in text:
        return "KWIS"
    if "Senslink" in text or "行動水情" in text:
        return "Senslink/行動水情"
    return "官方"


def _render_packet_markdown(packet: Mapping[str, Any]) -> list[str]:
    lines = [
        f"## {packet['county']}：{packet['subject']}",
        "",
        f"- 類型：{packet['packet_type']}",
        f"- 需要人工介入：{'是' if packet.get('requires_human_intervention') else '否'}",
    ]
    if packet.get("requested_counterparty"):
        lines.append(f"- 追蹤對象：{packet['requested_counterparty']}")
    if packet.get("tracking_status"):
        lines.append(f"- 追蹤狀態：{packet['tracking_status']}")
    if packet.get("priority_rank"):
        lines.append(
            f"- 整合優先序：#{packet['priority_rank']} / "
            f"{packet.get('priority_tier')} / {packet.get('workstream')}"
        )
    if packet.get("api_contract_risk"):
        lines.append(f"- API contract 風險：{packet['api_contract_risk']}")
    if packet.get("insufficient_api_purposes"):
        lines.append(
            "- 不足用途："
            + "、".join(str(purpose) for purpose in packet["insufficient_api_purposes"])
        )
    if packet.get("required_api_purpose"):
        lines.append(f"- 必要 API 用途：{packet['required_api_purpose']}")
    if packet.get("request_clarification"):
        lines.append(f"- 需釐清事項：{packet['request_clarification']}")
    if packet.get("credential_requirements"):
        lines.append(
            "- Credential requirements: "
            + ", ".join(str(item) for item in packet["credential_requirements"])
        )
    if packet.get("known_read_method_names"):
        lines.append(
            "- Known token-gated read methods: "
            + ", ".join(str(item) for item in packet["known_read_method_names"])
        )
    if packet.get("known_read_endpoint_urls"):
        lines.append("- Known read endpoint references:")
        lines.extend(f"  - {url}" for url in packet["known_read_endpoint_urls"])
    if packet.get("unauthorized_smoke_result"):
        lines.append(f"- Unauthorized smoke result: {packet['unauthorized_smoke_result']}")
    if packet.get("last_followed_up_at"):
        lines.append(f"- 最後追蹤時間：{packet['last_followed_up_at']}")
    if packet.get("source_urls"):
        lines.append("- 來源：")
        lines.extend(f"  - {url}" for url in packet["source_urls"])
    if packet.get("metadata_source_names"):
        lines.append(
            "- 靜態 metadata 線索："
            + "、".join(str(name) for name in packet["metadata_source_names"])
        )
    if packet.get("metadata_source_urls"):
        lines.append("- 靜態 metadata URL：")
        lines.extend(f"  - {url}" for url in packet["metadata_source_urls"])
    if packet.get("non_qualifying_source_names"):
        lines.append(
            "- 已排除官方線索："
            + "、".join(str(name) for name in packet["non_qualifying_source_names"])
        )
    if packet.get("non_qualifying_source_urls"):
        lines.append("- 已排除官方線索 URL：")
        lines.extend(f"  - {url}" for url in packet["non_qualifying_source_urls"])
    if packet.get("non_qualifying_source_reasons"):
        lines.append("- 排除原因：")
        lines.extend(
            f"  - {reason}" for reason in packet["non_qualifying_source_reasons"]
        )
    if packet.get("production_adapter_keys"):
        lines.append(
            "- 既有 production adapters："
            + "、".join(str(key) for key in packet["production_adapter_keys"])
        )
    if packet.get("status_only_source_names"):
        lines.append(
            "- 既有 status-only 來源："
            + "、".join(str(name) for name in packet["status_only_source_names"])
        )
    if packet.get("status_only_signal_types"):
        lines.append(
            "- 既有 status-only 訊號："
            + "、".join(str(signal) for signal in packet["status_only_signal_types"])
        )
    if packet.get("status_only_source_urls"):
        lines.append("- status-only 來源 URL：")
        lines.extend(f"  - {url}" for url in packet["status_only_source_urls"])
    if packet.get("required_read_api_fields"):
        fields = "、".join(f"`{field}`" for field in packet["required_read_api_fields"])
        lines.append(f"- Production read API 必備欄位：{fields}")
    if packet.get("production_operational_requirements"):
        requirements = ", ".join(
            str(requirement)
            for requirement in packet["production_operational_requirements"]
        )
        lines.append(f"- Production ops gates: {requirements}")
    if packet.get("completion_evidence_targets"):
        lines.append("- Completion evidence targets:")
        for target in packet["completion_evidence_targets"]:
            lines.append(f"  - {_completion_evidence_target_line(target)}")
    if packet.get("candidate_contract_missing_fields"):
        fields = "、".join(
            f"`{field}`" for field in packet["candidate_contract_missing_fields"]
        )
        lines.append(f"- 候選系統缺少欄位：{fields}")
    if packet.get("candidate_contract_findings"):
        lines.append("- 候選系統查核事實：")
        lines.extend(f"  - {finding}" for finding in packet["candidate_contract_findings"])
    if packet.get("candidate_contract_non_measurement_notes"):
        lines.append("- 候選系統不可當量測來源：")
        lines.extend(
            f"  - {note}"
            for note in packet["candidate_contract_non_measurement_notes"]
        )
    if packet.get("target_signal_types"):
        signal_label = "待補水資訊訊號"
        if packet.get("packet_type") == "metadata_release_request":
            signal_label = "待補地方直連訊號"
            if packet.get("workstream") == "restore_hydrologic_backbone":
                signal_label = "待補中央主幹訊號"
        lines.append(
            f"- {signal_label}："
            + "、".join(str(signal) for signal in packet["target_signal_types"])
        )
    if packet.get("priority_why_now"):
        lines.append(f"- 排入此順位原因：{packet['priority_why_now']}")
    if packet.get("completion_gate"):
        lines.append(f"- 完成門檻：{packet['completion_gate']}")
    lines.extend(["", packet["request_body"], "", "待辦："])
    lines.extend(f"- [ ] {item}" for item in packet.get("checklist", []))
    lines.append("")
    return lines


def _completion_evidence_target_line(target: Mapping[str, Any]) -> str:
    section = str(target.get("manifest_section", ""))
    if target.get("gate"):
        target_key = str(target["gate"])
    else:
        target_key = str(target.get("signal_type", ""))
    statuses = ", ".join(str(status) for status in target.get("accepted_statuses", []))
    evidence_ref_hint = str(target.get("private_evidence_ref_hint", ""))
    return (
        f"{section} / {target_key}; accepted statuses: {statuses}; "
        f"evidence_ref hint: {evidence_ref_hint}"
    )


def _render_signal_gap_batch_markdown(batch: Mapping[str, Any]) -> list[str]:
    target_signal_type = str(batch.get("target_signal_type", ""))
    lines = [
        f"## {target_signal_type}",
        "",
        f"- Batch id: `{batch.get('batch_id')}`",
        f"- Dispatch status: `{batch.get('dispatch_status')}`",
        f"- Sent at: `{batch.get('sent_at')}`",
        f"- Follow-up due at: `{batch.get('follow_up_due_at')}`",
        f"- Official reply ref: `{batch.get('official_reply_ref')}`",
        f"- County count: {batch.get('county_count')}",
        f"- Private evidence hint: `{batch.get('private_evidence_ref_hint')}`",
    ]
    if batch.get("counties"):
        lines.append("- Counties: " + ", ".join(str(county) for county in batch["counties"]))
    if batch.get("requested_counterparties"):
        lines.append("- Requested counterparties:")
        lines.extend(
            f"  - {counterparty}"
            for counterparty in batch["requested_counterparties"]
        )
    if batch.get("required_read_api_fields"):
        fields = ", ".join(f"`{field}`" for field in batch["required_read_api_fields"])
        lines.append(f"- Required read API fields: {fields}")
    if batch.get("production_operational_requirements"):
        requirements = ", ".join(
            f"`{requirement}`"
            for requirement in batch["production_operational_requirements"]
        )
        lines.append(f"- Production operational requirements: {requirements}")
    if batch.get("packet_generator_command"):
        lines.append(f"- Packet generator command: `{batch['packet_generator_command']}`")
    if batch.get("completion_gate"):
        lines.append(f"- Completion gate: {batch['completion_gate']}")
    if batch.get("completion_evidence_targets"):
        lines.append("- Completion evidence targets:")
        for target in batch["completion_evidence_targets"]:
            lines.append(f"  - {_completion_evidence_target_line(target)}")
    lines.append("")
    return lines
