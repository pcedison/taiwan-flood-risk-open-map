"""Public-safe manual application packets for official incident sources.

The module is deliberately inert: it holds fixed, reviewable text and performs
no network, mail, browser, or credential work of any kind. Nothing here sends
anything. A human reads the rendered packet, decides what to submit, and submits
it through the organization's own official channel.

Every packet records where its public entry point came from:

``repo_reviewed_local_source_evidence``
    The URL is already carried by this repository's reviewed local-source
    coverage records, backed by a dated smoke note.
``unverified_pending_operator_confirmation``
    The organization is real and named in the approved design, but this exact
    landing page has not been verified from inside this repository. The operator
    must confirm the current entry point before submitting.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

EXPECTED_PACKET_IDS = (
    "ncdr-citizen-disaster-report",
    "ncdr-edxl-sitrep",
    "kinmen-kwis-read-api",
    "hualien-senslink-read-api",
    "miaoli-drainage-read-api",
    "pingtung-pteoc-read-api",
    "taitung-water-read-api",
    "lienchiang-live-water-feed",
    "waze-for-cities-flood-incidents",
)

REPO_REVIEWED = "repo_reviewed_local_source_evidence"
UNVERIFIED = "unverified_pending_operator_confirmation"

_SHARED_RETENTION_ZH = (
    "僅保存風險評估所需的最小欄位與有界原始快照；不保存完整文章、作者、留言、"
    "HTML、截圖或原始媒體。"
)
_SHARED_DELETION_ZH = (
    "來源撤回授權或本專案停用該來源時，於七日內刪除該來源的原始快照與衍生"
    "evidence，並保留刪除稽核紀錄。"
)

_PACKETS: tuple[MappingProxyType[str, Any], ...] = tuple(
    MappingProxyType(packet)
    for packet in (
        {
            "packet_id": "ncdr-citizen-disaster-report",
            "title_zh": "NCDR 公民回報災情事件讀取申請",
            "target_organization": "National Science and Technology Center for Disaster Reduction",
            "target_organization_zh": "國家災害防救科技中心",
            "purpose_zh": (
                "取得公民回報的淹水／道路積水事件，作為官方評估旁邊的顯示用脈絡，"
                "不用於計分，也不會單篇改變風險等級。"
            ),
            "requested_fields": (
                "event_id",
                "event_category",
                "reported_at",
                "location_point_wgs84",
                "administrative_area_code",
                "verification_state",
                "resolution_state",
            ),
            "expected_cadence": "polling every 5 to 15 minutes during flood events",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://alerts.ncdr.nat.gov.tw/",
            "source_url_verification": UNVERIFIED,
            "notes_zh": (
                (
                    "本專案已在來源目錄登錄 NCDR CAP 告警入口；公民回報災情事件屬不同"
                    "資料集，需由承辦單位確認申請窗口與可讀欄位。"
                ),
                "申請時應載明：不轉載通報全文、不保存回報者身分、不對外重製原始媒體。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "ncdr-edxl-sitrep",
            "title_zh": "NCDR EDXL-SitRep 災情整合資料讀取申請",
            "target_organization": "National Science and Technology Center for Disaster Reduction",
            "target_organization_zh": "國家災害防救科技中心",
            "purpose_zh": (
                "取得跨機關整合的災情摘要，用於顯示官方已彙整的事件脈絡與資料缺口說明，"
                "不進入風險計分。"
            ),
            "requested_fields": (
                "sitrep_id",
                "incident_category",
                "issued_at",
                "effective_window",
                "administrative_area_code",
                "reporting_agency",
                "status",
            ),
            "expected_cadence": "on publication, polled at most every 5 minutes",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://alerts.ncdr.nat.gov.tw/",
            "source_url_verification": UNVERIFIED,
            "notes_zh": (
                (
                    "需確認 EDXL-SitRep 的釋出對象是否限定政府單位；若限定，本專案不申請，"
                    "改以既有公開 CAP 來源為準。"
                ),
                "需確認是否含個人資料欄位；若含，申請時明確要求排除。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "kinmen-kwis-read-api",
            "title_zh": "金門縣水情系統 KWIS 讀取權限申請",
            "target_organization": "Kinmen County Government",
            "target_organization_zh": "金門縣政府",
            "purpose_zh": (
                "取得金門縣地方直出的雨量、水位、淹水感測與抽水站狀態讀值，"
                "補足中央聚合資料以外的地方即時觀測。"
            ),
            "requested_fields": (
                "station_id",
                "station_name",
                "coordinates_wgs84",
                "observed_at",
                "rainfall_mm",
                "water_level_m",
                "flood_depth_cm",
                "pump_station_state",
            ),
            "expected_cadence": "10-minute polling, with the published rate limit confirmed in writing",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://kwis.kinmen.gov.tw/",
            "source_url_verification": REPO_REVIEWED,
            "notes_zh": (
                (
                    "2026-06-30 已對 KWIS ASMX/WSDL 做過公開服務清單檢視；本申請要求的是"
                    "正式讀取核可、可讀欄位清單、速率限制與使用範圍的書面確認。"
                ),
                "申請文件不得填入任何實際憑證字串；核發程序由縣府決定。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "hualien-senslink-read-api",
            "title_zh": "花蓮縣 SensLink 行動水情 M2M 讀取申請",
            "target_organization": "Hualien County Government",
            "target_organization_zh": "花蓮縣政府",
            "purpose_zh": "取得花蓮縣地方水情儀表板背後的機器可讀讀值，補足中央聚合站點以外的覆蓋。",
            "requested_fields": (
                "station_id",
                "coordinates_wgs84",
                "observed_at",
                "water_level_m",
                "rainfall_mm",
                "sensor_health_state",
            ),
            "expected_cadence": "10-minute polling",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index",
            "source_url_verification": REPO_REVIEWED,
            "notes_zh": (
                "2026-06-28 記錄：花蓮行動水情屬登入型儀表板，未經核可無法確認完整讀取契約。",
                "本專案不會登入、不會使用個人帳號、不會繞過登入頁取得資料。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "miaoli-drainage-read-api",
            "title_zh": "苗栗縣雨水下水道即時水情讀取契約申請",
            "target_organization": "Miaoli County Government",
            "target_organization_zh": "苗栗縣政府",
            "purpose_zh": "取得苗栗縣雨水下水道即時水情監測系統的公開讀取契約，補足都市排水積淹水訊號。",
            "requested_fields": (
                "station_id",
                "coordinates_wgs84",
                "observed_at",
                "water_level_m",
                "flood_depth_cm",
                "station_operational_state",
            ),
            "expected_cadence": "10-minute polling",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": (
                "https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx"
                "?n=563&s=922337&sms=9560"
            ),
            "source_url_verification": REPO_REVIEWED,
            "notes_zh": (
                (
                    "2026-06-28 記錄：苗栗雨水下水道即時水情監測系統尚未公開讀取契約；"
                    "縣府站點目前經由 FHY Broker 提供中央聚合讀值。"
                ),
                "本申請只要求公開契約文件與欄位定義，不要求任何私有介面。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "pingtung-pteoc-read-api",
            "title_zh": "屏東縣防災平台 PTEOC 讀取契約申請",
            "target_organization": "Pingtung County Government",
            "target_organization_zh": "屏東縣政府",
            "purpose_zh": (
                "取得屏東防災平台雨量、河川與淹水頁面背後的機器可讀讀值，"
                "特別是明確的觀測時間與官方座標。"
            ),
            "requested_fields": (
                "station_id",
                "coordinates_wgs84",
                "observed_at",
                "rainfall_mm",
                "river_stage_m",
                "flood_depth_cm",
            ),
            "expected_cadence": "10-minute polling",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://pteoc.pthg.gov.tw/",
            "source_url_verification": REPO_REVIEWED,
            "notes_zh": (
                (
                    "2026-06-28 記錄：PTEOC 的 HTML 頁面可讀，雨量表格有數值，但缺明確"
                    "observed_at 與官方座標對應；本專案不會用抓取時間冒充觀測時間。"
                ),
                "缺少可信觀測時間時，本專案寧可顯示資料缺口，也不產生風險數值。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "taitung-water-read-api",
            "title_zh": "臺東縣洪水與淹水預警系統讀取契約申請",
            "target_organization": "Taitung County Government",
            "target_organization_zh": "臺東縣政府",
            "purpose_zh": "取得臺東縣地方水情與淹水預警的公開讀取契約，補足目前僅有極少數中央聚合站點的覆蓋。",
            "requested_fields": (
                "station_id",
                "coordinates_wgs84",
                "observed_at",
                "water_level_m",
                "flood_depth_cm",
                "warning_stage",
            ),
            "expected_cadence": "10-minute polling",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": (
                "https://www.taitung.gov.tw/News_Content.aspx?n=13370&s=131527&sms=12652"
            ),
            "source_url_verification": REPO_REVIEWED,
            "notes_zh": (
                "2026-06-28 記錄：臺東縣經 FHY Broker 僅有 2 站；地方讀取契約仍未公開。",
                "覆蓋不足時，本專案對該轄區維持 unknown，不以鄰近站點外推。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "lienchiang-live-water-feed",
            "title_zh": "連江縣即時水情資料讀取申請",
            "target_organization": "Lienchiang County Government",
            "target_organization_zh": "連江縣政府",
            "purpose_zh": "詢問連江縣是否存在可公開讀取的即時水情資料，作為目前完全缺乏地方即時來源的補充。",
            "requested_fields": (
                "station_id",
                "coordinates_wgs84",
                "observed_at",
                "water_level_m",
                "rainfall_mm",
            ),
            "expected_cadence": "10-minute polling if a live feed exists",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5",
            "source_url_verification": REPO_REVIEWED,
            "notes_zh": (
                (
                    "2026-06-30 記錄：目前只查到水庫水位月報 PDF 與放流水環保監測，"
                    "兩者都不能當作水文觀測風險量測。"
                ),
                "若確認沒有即時來源，本專案將持續在該轄區揭露資料缺口，而非改用替代推估。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
        {
            "packet_id": "waze-for-cities-flood-incidents",
            "title_zh": "Waze for Cities 淹水與道路事件合作資格詢問",
            "target_organization": "Waze for Cities Program",
            "target_organization_zh": "Waze for Cities 計畫",
            "purpose_zh": (
                "確認本專案是否具備合作資格，以及淹水／道路事件資料的使用條款，"
                "作為顯示用道路事件脈絡。"
            ),
            "requested_fields": (
                "incident_id",
                "incident_category",
                "reported_at",
                "location_point_wgs84",
                "road_segment_reference",
                "confidence_or_report_count",
            ),
            "expected_cadence": "to be defined by the program terms",
            "retention_policy_zh": _SHARED_RETENTION_ZH,
            "deletion_policy_zh": _SHARED_DELETION_ZH,
            "public_source_url": "https://www.waze.com/wazeforcities",
            "source_url_verification": UNVERIFIED,
            "notes_zh": (
                (
                    "先確認資格與使用條款；在條款明確允許之前，本專案不接入、不快取、"
                    "也不顯示任何 Waze 資料。"
                ),
                "不逆向 Waze Live Map、不繞過反爬機制、不使用個人帳號。",
            ),
            "requires_human_intervention": True,
            "submission_mode": "manual_only",
            "contact_name": None,
            "contact_email": None,
        },
    )
)

_PACKETS_BY_ID = {str(packet["packet_id"]): packet for packet in _PACKETS}


def build_official_incident_request_packets() -> tuple[dict[str, object], ...]:
    """Return the fixed public-safe set of manual application packets."""

    return tuple(dict(_PACKETS_BY_ID[packet_id]) for packet_id in EXPECTED_PACKET_IDS)


def render_official_incident_request_packets_markdown(
    packets: tuple[dict[str, object], ...],
) -> str:
    """Render reviewable packets without sending them."""

    lines: list[str] = [
        "# Official incident source request packets",
        "",
        "These packets are **generated for human review only**. Nothing in this",
        "repository submits them. An operator reads each packet, confirms the current",
        "public entry point, and applies through the organization's own official channel.",
        "",
        "No packet contains a credential of any kind, and every contact field is",
        "deliberately empty so a person fills it in at submission time.",
        "",
        f"Total packets: {len(packets)}",
        "",
    ]
    for packet in packets:
        lines.extend(_render_packet(packet))
    return "\n".join(lines).rstrip("\n") + "\n"


def _render_packet(packet: dict[str, object]) -> list[str]:
    lines = [
        f"## {packet['packet_id']}",
        "",
        f"- Title: {packet['title_zh']}",
        f"- Organization: {packet['target_organization']}（{packet['target_organization_zh']}）",
        f"- Submission mode: `{packet['submission_mode']}`",
        f"- Requires human intervention: {str(packet['requires_human_intervention']).lower()}",
        f"- Public entry point: {packet['public_source_url']}",
        f"- Entry point verification: `{packet['source_url_verification']}`",
        f"- Expected cadence: {packet['expected_cadence']}",
        "",
        f"用途：{packet['purpose_zh']}",
        "",
        "Requested fields:",
        "",
    ]
    lines.extend(f"- `{field}`" for field in _string_sequence(packet["requested_fields"]))
    lines.extend(
        [
            "",
            f"保存政策：{packet['retention_policy_zh']}",
            "",
            f"刪除政策：{packet['deletion_policy_zh']}",
            "",
            "備註：",
            "",
        ]
    )
    lines.extend(f"- {note}" for note in _string_sequence(packet["notes_zh"]))
    lines.extend(
        [
            "",
            "Contact fields left empty on purpose:",
            "",
            f"- contact_name: {packet['contact_name']}",
            f"- contact_email: {packet['contact_email']}",
            "",
        ]
    )
    return lines


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):  # pragma: no cover - defensive
        raise TypeError("packet list fields must be a sequence of strings")
    return tuple(str(item) for item in value)
