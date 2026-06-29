from __future__ import annotations

from typing import Any, Mapping


def build_official_request_packets(
    action_plan: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    packets: list[dict[str, Any]] = []
    packets.extend(
        _authorization_packet(item)
        for item in action_plan.get("authorization_requests", [])
    )
    packets.extend(
        _metadata_release_packet(item)
        for item in action_plan.get("metadata_release_monitors", [])
    )
    packets.extend(
        _public_api_contract_packet(item)
        for item in action_plan.get("public_api_contract_reviews", [])
    )
    return tuple(packets)


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


def _authorization_packet(item: Mapping[str, Any]) -> dict[str, Any]:
    county = str(item["county"])
    required_fields = list(item.get("required_read_api_fields", []))
    source_urls = list(item.get("application_urls", []))
    reason = str(item.get("reason", ""))
    system_name = _authorization_system_name(item, reason)
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
        "request_body": (
            f"目前{county}地方直連即時水情來源仍需要官方授權。請確認 {system_name} "
            "是否可提供最新觀測 read API，不是設備上傳 API。若可提供，請協助提供正式 "
            "API contract、申請方式、授權條款、rate limit、測站清冊、座標 metadata "
            "與範例 response。"
        ),
        "checklist": [
            "確認是否可提供最新觀測 read API",
            "確認 API contract、授權條款與 rate limit",
            "取得測站清冊、座標 metadata 與範例 response",
            "確認資料欄位可滿足 production adapter 必備欄位",
        ],
    }


def _metadata_release_packet(item: Mapping[str, Any]) -> dict[str, Any]:
    county = str(item["county"])
    source_urls = list(item.get("metadata_source_urls", []))
    target_signal_types = list(item.get("central_backbone_missing_signal_types", []))
    area_hint = "南竿、北竿、莒光、東引" if county == "連江縣" else county
    return {
        "county": county,
        "packet_type": "metadata_release_request",
        "requires_human_intervention": True,
        "subject": f"{county}即時水文觀測資料釋出請求",
        "source_urls": source_urls,
        "requested_counterparty": item.get("requested_counterparty"),
        "tracking_status": item.get("tracking_status"),
        "last_followed_up_at": item.get("last_followed_up_at"),
        "target_signal_types": target_signal_types,
        "required_read_api_fields": list(item.get("required_read_api_fields", [])),
        "request_body": (
            f"目前{county}僅找到靜態或 metadata 類公開資料，尚未找到可機器讀取的"
            f"即時水文觀測 read API。請協助釋出{area_hint}的雨水下水道水位、道路"
            "淹水感測器、抽水站或水門水位、易淹區鄰近水位站等資料，或確認是否可加入 "
            "Civil IoT / WRA 等中央公開 SensorThings 主幹。"
        ),
        "checklist": [
            "確認是否可提供最新觀測 read API",
            "確認是否可加入 Civil IoT 或 WRA 公開主幹",
            "取得站點 ID、觀測時間、測值、單位與座標",
            "確認短期無感測器時的建置計畫或資料釋出時程",
        ],
    }


def _public_api_contract_packet(item: Mapping[str, Any]) -> dict[str, Any]:
    county = str(item["county"])
    source_urls = list(item.get("candidate_source_urls", []))
    required_fields = list(item.get("required_read_api_fields", []))
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
        "request_body": (
            f"目前{county}已有官方系統或成果頁線索，但尚未找到可公開機器讀取的"
            "最新觀測 read API contract。請協助確認是否可提供 JSON、CSV、XML、"
            "ArcGIS REST 或 SensorThings 等 read API，並提供授權條款、rate limit、"
            "站點 metadata 與範例 response。"
        ),
        "checklist": [
            "確認公開 read API URL 與 response 格式",
            "確認觀測時間、站點 ID、測值、單位與座標欄位",
            "確認授權條款、rate limit 與維運窗口",
            "取得可重跑 live smoke 的範例 response",
        ],
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
    if packet.get("last_followed_up_at"):
        lines.append(f"- 最後追蹤時間：{packet['last_followed_up_at']}")
    if packet.get("source_urls"):
        lines.append("- 來源：")
        lines.extend(f"  - {url}" for url in packet["source_urls"])
    if packet.get("required_read_api_fields"):
        fields = "、".join(f"`{field}`" for field in packet["required_read_api_fields"])
        lines.append(f"- Production read API 必備欄位：{fields}")
    if packet.get("target_signal_types"):
        lines.append(
            "- 待補中央主幹訊號："
            + "、".join(str(signal) for signal in packet["target_signal_types"])
        )
    lines.extend(["", packet["request_body"], "", "待辦："])
    lines.extend(f"- [ ] {item}" for item in packet.get("checklist", []))
    lines.append("")
    return lines
