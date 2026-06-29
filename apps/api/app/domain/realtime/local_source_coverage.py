from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


LocalDirectSourceStatus = Literal[
    "ready_implemented",
    "candidate",
    "needs_review",
    "metadata_only",
    "not_found",
    "needs_application",
]
LocalSourceNextAction = Literal[
    "operate_adapter",
    "verify_public_api_contract",
    "verify_live_smoke",
    "request_official_authorization",
    "monitor_open_data_release",
    "continue_official_discovery",
]

NATIONAL_BASELINE_BACKBONE_KEYS = (
    "official.cwa.rainfall",
    "official.wra.water_level",
    "official.ncdr.cap",
)
CENTRAL_BACKBONE_REQUIRED_SIGNAL_TYPES = (
    "rainfall",
    "cap_alert",
    "hydrologic_observation",
)
HYDROLOGIC_BACKBONE_SIGNAL_TYPES = frozenset(
    {
        "river_water_level",
        "flood_depth",
        "sewer_water_level",
        "pump_water_level",
        "gate_water_level",
        "pond_water_level",
    }
)
BACKBONE_SIGNAL_TYPES_BY_ADAPTER_KEY = {
    "official.cwa.rainfall": "rainfall",
    "official.wra.water_level": "river_water_level",
    "official.ncdr.cap": "cap_alert",
    "official.wra_iow.flood_depth": "flood_depth",
    "official.civil_iot.flood_sensor": "flood_depth",
    "official.civil_iot.river_water_level": "river_water_level",
    "official.civil_iot.pond_water_level": "pond_water_level",
    "official.civil_iot.sewer_water_level": "sewer_water_level",
    "official.civil_iot.pump_water_level": "pump_water_level",
    "official.civil_iot.gate_water_level": "gate_water_level",
}
LOCAL_SIGNAL_TYPES_BY_ADAPTER_KEY = {
    "local.taipei.sewer_water_level": "sewer_water_level",
    "local.taipei.river_water_level": "water_level",
    "local.taipei.pump_station": "pump_or_gate_status",
    "local.new_taipei.water_level": "water_level",
    "local.new_taipei.flood_sensor": "flood_depth",
    "local.new_taipei.rainfall": "rainfall",
    "local.new_taipei.drainage_water_level": "sewer_water_level",
    "local.keelung.water_level": "water_level",
    "local.keelung.flood_sensor": "flood_depth",
    "local.keelung.rainfall": "rainfall",
    "local.taoyuan.flood_sensor": "flood_depth",
    "local.taoyuan.water_level": "water_level",
    "local.taoyuan.rainfall": "rainfall",
    "local.hsinchu_city.sewer_water_level": "sewer_water_level",
    "local.hsinchu_city.flood_sensor": "flood_depth",
    "local.hsinchu_county.flood_sensor": "flood_depth",
    "local.miaoli.flood_sensor": "flood_depth",
    "local.taichung.water_level": "water_level",
    "local.changhua.flood_sensor": "flood_depth",
    "local.nantou.sewer_water_level": "sewer_water_level",
    "local.yunlin.water_level": "water_level",
    "local.chiayi_city.water_level": "water_level",
    "local.chiayi_city.rainfall": "rainfall",
    "local.chiayi_county.flood_sensor": "flood_depth",
    "local.tainan.flood_sensor": "flood_depth",
    "local.kaohsiung.sewer_water_level": "sewer_water_level",
    "local.kaohsiung.flood_sensor": "flood_depth",
    "local.kaohsiung.rainfall": "rainfall",
    "local.pingtung.flood_sensor": "flood_depth",
    "local.yilan.flood_sensor": "flood_depth",
    "local.yilan.water_level": "water_level",
    "local.hualien.flood_sensor": "flood_depth",
    "local.taitung.flood_sensor": "flood_depth",
    "local.penghu.water_level": "water_level",
}
COVERAGE_SIGNAL_TYPES = (
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
    "pump_or_gate_status",
)


@dataclass(frozen=True)
class LocalSourceCoverageRecord:
    county: str
    local_direct_statuses: tuple[LocalDirectSourceStatus, ...]
    production_adapter_keys: tuple[str, ...] = ()
    production_source_urls: tuple[str, ...] = ()
    central_backbone_adapter_keys: tuple[str, ...] = NATIONAL_BASELINE_BACKBONE_KEYS
    candidate_source_names: tuple[str, ...] = ()
    candidate_source_urls: tuple[str, ...] = ()
    metadata_source_names: tuple[str, ...] = ()
    metadata_source_urls: tuple[str, ...] = ()
    status_only_source_names: tuple[str, ...] = ()
    status_only_source_urls: tuple[str, ...] = ()
    status_only_signal_types: tuple[str, ...] = ()
    application_urls: tuple[str, ...] = ()
    requires_application: bool = False
    application_note: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def local_direct_complete(self) -> bool:
        return "ready_implemented" in self.local_direct_statuses

    @property
    def central_backbone_available(self) -> bool:
        return bool(self.central_backbone_adapter_keys)

    @property
    def central_backbone_signal_types(self) -> tuple[str, ...]:
        signal_types: list[str] = []
        for adapter_key in self.central_backbone_adapter_keys:
            signal_type = BACKBONE_SIGNAL_TYPES_BY_ADAPTER_KEY.get(adapter_key)
            if signal_type is not None and signal_type not in signal_types:
                signal_types.append(signal_type)
        return tuple(signal_types)

    @property
    def local_signal_types(self) -> tuple[str, ...]:
        signal_types: list[str] = []
        for adapter_key in self.production_adapter_keys:
            signal_type = LOCAL_SIGNAL_TYPES_BY_ADAPTER_KEY.get(adapter_key)
            if signal_type is not None and signal_type not in signal_types:
                signal_types.append(signal_type)
        return tuple(signal_types)

    @property
    def coverage_signal_types(self) -> tuple[str, ...]:
        available = {
            _coverage_signal_type(signal_type)
            for signal_type in (*self.local_signal_types, *self.central_backbone_signal_types)
            if _coverage_signal_type(signal_type) is not None
        }
        return tuple(signal_type for signal_type in COVERAGE_SIGNAL_TYPES if signal_type in available)

    @property
    def rainfall_available(self) -> bool:
        return "rainfall" in self.coverage_signal_types

    @property
    def water_level_available(self) -> bool:
        return "water_level" in self.coverage_signal_types

    @property
    def flood_depth_available(self) -> bool:
        return "flood_depth" in self.coverage_signal_types

    @property
    def sewer_water_level_available(self) -> bool:
        return "sewer_water_level" in self.coverage_signal_types

    @property
    def pump_or_gate_status_available(self) -> bool:
        return "pump_or_gate_status" in self.coverage_signal_types

    @property
    def status_only_available(self) -> bool:
        return bool(self.status_only_source_names or self.status_only_signal_types)

    @property
    def missing_signal_types(self) -> tuple[str, ...]:
        available = set(self.coverage_signal_types)
        return tuple(signal_type for signal_type in COVERAGE_SIGNAL_TYPES if signal_type not in available)

    @property
    def central_backbone_required_signal_types(self) -> tuple[str, ...]:
        return CENTRAL_BACKBONE_REQUIRED_SIGNAL_TYPES

    @property
    def central_backbone_missing_signal_types(self) -> tuple[str, ...]:
        available = set(self.central_backbone_signal_types)
        missing: list[str] = []
        for signal_type in ("rainfall", "cap_alert"):
            if signal_type not in available:
                missing.append(signal_type)
        if not available.intersection(HYDROLOGIC_BACKBONE_SIGNAL_TYPES):
            missing.append("hydrologic_observation")
        return tuple(missing)

    @property
    def central_backbone_minimum_complete(self) -> bool:
        return not self.central_backbone_missing_signal_types

    @property
    def central_backbone_coverage_level(self) -> str:
        missing = set(self.central_backbone_missing_signal_types)
        if not missing:
            return "minimum_met"
        if missing == {"hydrologic_observation"}:
            return "needs_hydrologic_backbone"
        return "incomplete"

    @property
    def next_action_code(self) -> LocalSourceNextAction:
        if "needs_application" in self.local_direct_statuses:
            return "request_official_authorization"
        if "needs_review" in self.local_direct_statuses:
            return "verify_live_smoke"
        if "candidate" in self.local_direct_statuses:
            return "verify_public_api_contract"
        if "ready_implemented" in self.local_direct_statuses:
            return "operate_adapter"
        if "metadata_only" in self.local_direct_statuses:
            return "monitor_open_data_release"
        return "continue_official_discovery"

    @property
    def upgrade_priority(self) -> int:
        priority_by_action = {
            "request_official_authorization": 1,
            "verify_live_smoke": 2,
            "verify_public_api_contract": 2,
            "monitor_open_data_release": 3,
            "continue_official_discovery": 4,
            "operate_adapter": 5,
        }
        return priority_by_action[self.next_action_code]

    @property
    def blocking_reason(self) -> str | None:
        if self.next_action_code == "operate_adapter":
            return None
        if self.next_action_code == "request_official_authorization":
            return self.application_note or "需要地方政府核發帳密、key 或合作授權。"
        if self.next_action_code == "verify_live_smoke":
            return "官方 API contract 已知，但仍需完成 live smoke、freshness、座標或欄位語意複核。"
        if self.next_action_code == "verify_public_api_contract":
            return "候選系統存在，但尚未找到官方公開 live read API contract 或 open-data landing page。"
        if self.next_action_code == "monitor_open_data_release":
            return "目前只有靜態清冊、站點、抽水站、水門或易淹區 metadata，尚無即時觀測欄位。"
        return "尚未找到可追溯的地方政府公開即時水情來源。"


def _coverage_signal_type(signal_type: str) -> str | None:
    if signal_type in {"river_water_level", "pond_water_level"}:
        return "water_level"
    if signal_type in {"pump_water_level", "gate_water_level", "gate_status", "pump_status"}:
        return "pump_or_gate_status"
    if signal_type in COVERAGE_SIGNAL_TYPES:
        return signal_type
    return None


TAIWAN_LOCAL_SOURCE_COVERAGE: tuple[LocalSourceCoverageRecord, ...] = (
    LocalSourceCoverageRecord(
        county="臺北市",
        local_direct_statuses=("ready_implemented", "needs_review"),
        production_adapter_keys=(
            "local.taipei.sewer_water_level",
            "local.taipei.river_water_level",
            "local.taipei.pump_station",
        ),
        production_source_urls=(
            "https://wic.gov.taipei/OpenData/API/Sewer/Get?stationNo=&loginId=sewer01&dataKey=BD3E513A",
            "https://wic.gov.taipei/OpenData/API/Water/Get?stationNo=&loginId=river&dataKey=9E2648AA",
            "https://heopublic.gov.taipei/taipei-heo-api/openapi/pumb/latest",
        ),
        candidate_source_names=("臺北市疏散門即時監測",),
        candidate_source_urls=(
            "https://wic.heo.taipei/OpenData/API/Evacuate/Get?stationNo=&loginId=watergate&dataKey=44D76DA6",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.pump_water_level",
            "official.civil_iot.gate_water_level",
        ),
    ),
    LocalSourceCoverageRecord(
        county="新北市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.new_taipei.water_level",
            "local.new_taipei.flood_sensor",
            "local.new_taipei.rainfall",
            "local.new_taipei.drainage_water_level",
        ),
        production_source_urls=(
            "https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/flood/getFloodListData",
            "https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/rain/getRainFallBaseData",
            "https://newtaipei.wavegis.com.tw/api/javaapi/water_extra_api/water/getDrainage",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        metadata_source_names=("新北市各抽水站資訊", "新北市水門資料"),
        metadata_source_urls=(
            "https://data.ntpc.gov.tw/datasets/3cdc5b9c-ce48-4dd6-8079-b9b3fa4b7296",
            "https://data.ntpc.gov.tw/datasets/bf784279-31aa-44bc-a210-33151d03e7ab",
        ),
        notes=(
            "2026-06-28 smoke：新北 WaveGIS 委外公開 JSON API 免 token；"
            "water、flood、rain、drainage 均含 datatime 與 WGS84 座標。"
            "data.ntpc.gov.tw 抽水站/水門清冊仍只作靜態 metadata 背景。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="基隆市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.keelung.water_level",
            "local.keelung.flood_sensor",
            "local.keelung.rainfall",
        ),
        production_source_urls=(
            "https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/flood/getFloodListData",
            "https://smartflood.klcg.gov.tw/api/r/javaapinew/water_extra_api/rain/getRainFallBaseData",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        notes=(
            "2026-06-28 smoke：基隆智慧防汛網 JSON API 免 key；water 11 筆、"
            "flood 49 筆、rain 18 筆；本輪 live adapter normalized water 11、flood 49、"
            "rain 16，2 個 stale 雨量站保留 raw 但拒收。pump station 狀態語意另案建模，"
            "未轉成水位 evidence。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="桃園市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.taoyuan.flood_sensor",
            "local.taoyuan.water_level",
            "local.taoyuan.rainfall",
        ),
        production_source_urls=(
            "https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERFLOOD.xml",
            "https://winfo.tycg.gov.tw/Transfer/UploadFile/WATERLEVEL.xml",
            "https://opendata.tycg.gov.tw/api/dataset/eabd93d1-d526-4de0-b378-b529aa61a4be/resource/6a555cf5-ccc9-4706-9cb6-62c25f23ec4e/download",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
        ),
    ),
    LocalSourceCoverageRecord(
        county="新竹市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.hsinchu_city.sewer_water_level",
            "local.hsinchu_city.flood_sensor",
        ),
        production_source_urls=(
            "https://swc.hccg.gov.tw/api/map/sewer/rt",
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.pump_water_level",
            "official.civil_iot.gate_water_level",
        ),
        metadata_source_names=("新竹市抽水站資訊", "新竹市區域排水資料"),
        metadata_source_urls=(
            "https://data.gov.tw/dataset/67718",
            "https://data.gov.tw/dataset/67721",
        ),
        notes=(
            "2026-06-28 smoke：新竹市 sewer base/rt API 免 key 回傳 50 筆；"
            "FHY Broker station/realtime API 免 key，依 CityCode 10018 過濾新竹市淹水感測器。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="新竹縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.hsinchu_county.flood_sensor",),
        production_source_urls=(
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        notes=(
            "2026-06-28 smoke：FHY Broker station/realtime API 免 key，CityCode 10004；"
            "Supplier=新竹縣政府 22 站，本輪 local adapter fetched 22、normalized 20、"
            "stale reject 2。水利署分署 supplier 不納入 local adapter。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="苗栗縣",
        local_direct_statuses=("ready_implemented", "candidate"),
        production_adapter_keys=("local.miaoli.flood_sensor",),
        production_source_urls=(
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        candidate_source_names=("苗栗縣雨水下水道即時水情監測",),
        candidate_source_urls=(
            "https://www.miaoli.gov.tw/economic_affairs/News_Content.aspx?n=563&s=922337&sms=9560",
        ),
        notes=(
            "2026-06-28 smoke：FHY Broker station/realtime API 免 key，CityCode 10005；"
            "Supplier=苗栗縣政府 42 站，本輪 local adapter fetched 42、normalized 40、"
            "stale reject 2。苗栗雨水下水道即時水情監測系統仍未公開 read API contract。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="臺中市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.taichung.water_level",),
        production_source_urls=(
            "https://wrbeocin.taichung.gov.tw/TCSAFE/UploadFile/WATERLEVEL/WATERLEVEL_NEW.JSON",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.wra_iow.flood_depth",
        ),
    ),
    LocalSourceCoverageRecord(
        county="彰化縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.changhua.flood_sensor",),
        production_source_urls=(
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.gate_water_level",
            "official.wra_iow.flood_depth",
        ),
        metadata_source_names=("彰化縣縣管區域排水清冊", "彰化縣下水道/抽水站年度統計"),
        metadata_source_urls=(
            "https://data.gov.tw/dataset/41415",
            "https://data.gov.tw/dataset/28916",
        ),
        notes=(
            "2026-06-28 smoke：FHY Broker station/realtime API 免 key，CityCode 10007；"
            "Supplier=彰化縣政府 70 站，本輪 local adapter fetched/normalized 70。"
            "彰化 ArcGIS 水位計 layer 目前只作 station metadata，無 observed_at 或即時值。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="南投縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.nantou.sewer_water_level",),
        production_source_urls=("https://dpinfo.nantou.gov.tw/Api/Proxy/GetKML",),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.wra_iow.flood_depth",
            "official.civil_iot.sewer_water_level",
        ),
        notes=(
            "2026-06-28 smoke：南投雨水下水道 KML 免 key 回傳 69 個 Placemark，"
            "description 內含水位高度、時雨量與更新時間。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="雲林縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.yunlin.water_level",),
        production_source_urls=(
            "https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.pump_water_level",
            "official.civil_iot.gate_water_level",
        ),
        metadata_source_names=("雲林縣淹水感測器座標", "雲林縣抽水站資料", "雲林縣水門點位"),
        metadata_source_urls=(
            "https://opendata.yunlin.gov.tw/OpenDataContent.aspx?n=8350&s=1427",
            "https://yliflood.yunlin.gov.tw/ifloodboard",
        ),
        status_only_source_names=("雲林 iflood 淹水感測狀態",),
        status_only_source_urls=(
            "https://yliflood.yunlin.gov.tw/api/v1/IfloodStation/StationTypes/Areas/Stations?context=5",
        ),
        status_only_signal_types=("flood_sensor_status",),
        notes=(
            "2026-06-28 smoke：雲林 iflood station API 免 key，totalCount 2473；"
            "stationType 水位 161 站，其中 102 筆具 levelHeight/latestUpdateTime/座標，"
            "本輪 live adapter normalized 101、1 筆 stale 拒收。淹水感測 173 站目前公開"
            "清單未曝露 depth 欄位；alarmState 已標示為 status-only 診斷線索，"
            "不以其假造淹水深度。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="嘉義市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.chiayi_city.water_level",
            "local.chiayi_city.rainfall",
        ),
        production_source_urls=(
            "https://data.chiayi.gov.tw/opendata/api/getResource?oid=df063695-0076-4dd6-9237-39c5f8ae6b4a&rid=d4c7da5c-b08f-4fd1-97c0-913c949c4613",
            "https://data.chiayi.gov.tw/opendata/api/getResource?oid=0c766c28-c16e-4eaa-8520-f7ffeee3776b&rid=5ad1cdc5-6a8a-48d4-b6b4-7edb9b384e1a",
        ),
        central_backbone_adapter_keys=NATIONAL_BASELINE_BACKBONE_KEYS,
    ),
    LocalSourceCoverageRecord(
        county="嘉義縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.chiayi_county.flood_sensor",),
        production_source_urls=("https://api.floodsolution.aiot.ing/api/public/devices/RFD",),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.wra_iow.flood_depth",
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.pump_water_level",
            "official.civil_iot.gate_water_level",
        ),
        candidate_source_names=("嘉義縣智慧防汛網",),
        candidate_source_urls=("https://www.cyhg.gov.tw/News_Content.aspx?n=16&s=249470",),
        metadata_source_names=("嘉義縣轄內抽水站 CSV",),
        metadata_source_urls=(
            "https://wrb.cyhg.gov.tw/OpenData.aspx?SN=C58B0984AE840F04",
            "https://data.gov.tw/dataset/99764",
        ),
        notes=(
            "2026-06-28 smoke：公開 RFD API 免 key 回傳 253 站，latest 內含 "
            "waterDepth 與 ISO observed time；登入型 /api/v1 管理端點未納入 production。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="臺南市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.tainan.flood_sensor",),
        production_source_urls=(
            "https://soa.tainan.gov.tw/Api/Service/Get/21b31a27-3e61-48b8-8259-83c2001bec8c",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.wra_iow.flood_depth",
            "official.civil_iot.flood_sensor",
        ),
    ),
    LocalSourceCoverageRecord(
        county="高雄市",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.kaohsiung.sewer_water_level",
            "local.kaohsiung.flood_sensor",
            "local.kaohsiung.rainfall",
        ),
        production_source_urls=(
            "https://wrbswi.kcg.gov.tw/SFC/api/sewer/rt",
            "https://wrbswi.kcg.gov.tw/SFC/api/khfloodinfo/sta_info/lastest/wrs_flooding_sensor",
            "https://wrbswi.kcg.gov.tw/SFC/api/rain/rt",
            "https://wrbswi.kcg.gov.tw/SFC/api/rain/base",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.pump_water_level",
        ),
        metadata_source_names=("高雄市閘門及抽水站靜態資料",),
        metadata_source_urls=("https://data.gov.tw/dataset/104708",),
        notes=(
            "2026-06-28 smoke：高雄 SFC sewer/rt 免 key 回傳 296 筆下水道水位，"
            "wrs_flooding_sensor 免 key 回傳 171 筆淹水感測。2026-06-29 複核："
            "rain/rt live adapter 87 筆 normalized，可用 ST_NO join rain/base 88 筆 "
            "WGS84 metadata，站數會隨平台即時狀態浮動；已納入地方雨量補強，"
            "只補足 CWA 空間密度，不取代 CWA。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="屏東縣",
        local_direct_statuses=("ready_implemented", "candidate"),
        production_adapter_keys=("local.pingtung.flood_sensor",),
        production_source_urls=(
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.pump_water_level",
            "official.civil_iot.gate_water_level",
        ),
        candidate_source_names=("屏東防災資訊整合平台",),
        candidate_source_urls=(
            "https://pteoc.pthg.gov.tw/",
            "https://pteoc.pthg.gov.tw/RainStation",
            "https://pteoc.pthg.gov.tw/River",
            "https://pteoc.pthg.gov.tw/Flood",
            "https://pteoc.pthg.gov.tw/Crawler",
        ),
        notes=(
            "2026-06-28 smoke：FHY Broker station/realtime API 免 key，CityCode 10013；"
            "Supplier=屏東縣政府 20 站，本輪 local adapter fetched/normalized 20。"
            "屏東防災平台 HTML 可讀，RainStation 表格含雨量值，但缺明確 observed_at "
            "與官方座標 join；不得以 fetched_at 偽裝觀測時間。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="宜蘭縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=(
            "local.yilan.flood_sensor",
            "local.yilan.water_level",
        ),
        production_source_urls=(
            "https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer/0/query?where=1%3D1&outFields=*&f=json",
            "https://wragis.e-land.gov.tw/arcgis/rest/services/HDST/%E9%98%B2%E6%B1%9B%E5%84%80%E8%A1%A8%E6%9D%BF/MapServer/2/query?where=1%3D1&outFields=*&f=json",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        notes=(
            "2026-06-28 smoke：宜蘭防汛儀表板 ArcGIS layer 0 回傳 85 筆淹水感測，"
            "layer 2 回傳 154 筆水位計；write_date 為 epoch milliseconds。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="花蓮縣",
        local_direct_statuses=("ready_implemented", "needs_application"),
        production_adapter_keys=("local.hualien.flood_sensor",),
        production_source_urls=(
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
            "official.civil_iot.gate_water_level",
        ),
        requires_application=True,
        application_urls=(
            "https://gov.senslink.net/Dashboard/Hualien/WebApp/Home/Index",
            "https://www.hl.gov.tw/News_Content.aspx?n=32725&s=116294",
        ),
        application_note=(
            "花蓮行動水情首頁可讀，但水情、路淹、抽水站與看板頁面會導向登入；"
            "需要帳密或官方授權後才能確認 read API contract。"
        ),
        notes=(
            "2026-06-28 smoke：FHY Broker station/realtime API 免 key，CityCode 10015；"
            "Supplier=花蓮縣政府 13 站，本輪 local adapter fetched/normalized 13。"
            "花蓮行動水情登入型儀表板仍需授權才可確認更完整 read API contract。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="臺東縣",
        local_direct_statuses=("ready_implemented", "candidate"),
        production_adapter_keys=("local.taitung.flood_sensor",),
        production_source_urls=(
            "https://www.dprcflood.org.tw/SGDS/WS/FHYBrokerWS.asmx/GetFHYFloodSensorInfoRt",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        candidate_source_names=("臺東洪水與淹水預警系統",),
        candidate_source_urls=(
            "https://www.taitung.gov.tw/News_Content.aspx?n=13370&s=131527&sms=12652",
        ),
        notes=(
            "2026-06-28 smoke：FHY Broker station/realtime API 免 key，CityCode 10014；"
            "Supplier=臺東縣政府 2 站，本輪 local adapter fetched/normalized 2。"
            "臺東洪水與淹水預警系統仍未公開地方 read API contract。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="澎湖縣",
        local_direct_statuses=("ready_implemented",),
        production_adapter_keys=("local.penghu.water_level",),
        production_source_urls=(
            "https://ph3dgis.penghu.gov.tw/server/rest/services/SewerNew/PHSewer_Basemap/MapServer/6/query",
        ),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.sewer_water_level",
        ),
        metadata_source_names=("澎湖縣區域排水疏濬工程",),
        metadata_source_urls=("https://data.gov.tw/dataset/156926",),
        notes=(
            "2026-06-28 smoke：澎湖智慧水位計 ArcGIS REST layer 6 免 token；"
            "38 筆 normalized，含 measure_time、water_level、water_level_percent、"
            "battery、rssi 與 WGS84 geometry。measure_time 以台灣本地 wall-clock "
            "epoch 編碼，adapter 會扣 8 小時後再做 freshness check。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="金門縣",
        local_direct_statuses=("needs_application",),
        central_backbone_adapter_keys=(
            *NATIONAL_BASELINE_BACKBONE_KEYS,
            "official.civil_iot.flood_sensor",
            "official.civil_iot.sewer_water_level",
        ),
        requires_application=True,
        application_urls=(
            "https://kwis.kinmen.gov.tw/",
            "https://kwis.kinmen.gov.tw/KWIS/Doc/%E9%87%91%E9%96%80%E7%B8%A3%E6%94%BF%E5%BA%9C%E7%AC%AC%E4%B8%89%E6%96%B9%E5%96%AE%E4%BD%8D%E8%B3%87%E6%96%99%E4%B8%8A%E5%82%B3%5B%E9%87%91%E9%96%80%E6%B0%B4%E6%83%85%E7%B3%BB%E7%B5%B1%5D%E4%B9%8BAPI%E4%BB%8B%E6%8E%A5%E7%94%B3%E8%AB%8B%E5%8F%8A%E4%BD%BF%E7%94%A8%E8%AA%AA%E6%98%8E.pdf",
        ),
        application_note="KWIS SOAP/ASMX 介接需要縣府審核帳密/key/token，且目前文件用途是第三方設備上傳，不是公開 read API。",
        notes=(
            "2026-06-28 Civil IoT live smoke：金門縣中央主幹已有淹水感測 7 站、"
            "RainSewer 29 站；這些是中央聚合 read API，可補即時水文觀測，"
            "但不等於金門縣府地方直出 read API。",
        ),
    ),
    LocalSourceCoverageRecord(
        county="連江縣",
        local_direct_statuses=("metadata_only", "not_found"),
        central_backbone_adapter_keys=(
            "official.cwa.rainfall",
            "official.ncdr.cap",
        ),
        metadata_source_names=("連江縣大潮、豪雨易淹水地區 ODS",),
        metadata_source_urls=(
            "https://eip.matsu.gov.tw/matsuopendata/chhtml/dataquery/5",
            "https://www.matsu.gov.tw/upload/f-20230922134042.ods",
        ),
        notes=("尚未找到地方 live API。",),
    ),
)


def local_source_coverage_generated_at() -> datetime:
    return datetime(2026, 6, 29, tzinfo=UTC)


def list_local_source_coverage() -> tuple[LocalSourceCoverageRecord, ...]:
    return TAIWAN_LOCAL_SOURCE_COVERAGE
