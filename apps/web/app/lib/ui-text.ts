import type { Coordinate, CoordinateSource, GeocodeCandidate, RiskAssessmentResponse } from "./page-types";
import { normalizeRiskLevel } from "./risk-display";

export const text = {
  appLabel: "台灣淹水風險地圖",
  eyebrow: "公開資料風險查詢",
  title: "台灣淹水風險開放地圖",
  mapStatus: "地圖狀態",
  mapStatusLoading: "底圖載入中",
  mapStatusReady: "互動地圖",
  mapHint: "可拖曳縮放，也可以直接點選地圖更新查詢座標",
  mapLabel: "台灣互動地圖，點選地圖可設定查詢座標",
  panelLabel: "風險查詢面板",
  searchPlace: "搜尋地點",
  searchPlaceholder: "輸入地標、地址或行政區",
  betaLimitTitle: "重要提醒：本工具不是官方災害通報",
  betaLimitAction: "查看限制",
  betaLimitMessage:
    "本服務整合公開資料與歷史/潛勢圖資，查詢結果僅供風險參考，不是即時災害通報，也不能作為購屋或居住安全的保證；地址如果定位不夠精準，會退回顯示道路或行政區的概略範圍。",
  radius: "分析半徑",
  assessRisk: "查詢風險",
  currentCoordinate: "目前座標",
  latitude: "緯度",
  longitude: "經度",
  riskSummary: "風險摘要",
  pendingData: "尚未查詢",
  riskPlaceholder: "搜尋地點或點選地圖後，按下查詢即可整理半徑內公開淹水相關資料。",
  insufficientData: "資料不足",
  riskMeter: "風險等級",
  riskDecisionSummary: "風險判讀摘要",
  riskQuestion: "回答：目前要看哪個風險？為什麼採這個等級？",
  riskMethodSummary: "查看分級依據",
  realtime: "即時",
  historical: "歷史參考",
  confidence: "資料信心",
  nearbySensingKicker: "附近即時感測",
  nearbySensingQuestion: "回答：附近感測器有沒有足夠覆蓋？",
  nearbySensingGaps: "缺口",
  evidenceKicker: "資料證據",
  evidenceTitle: "重點資料線索",
  evidenceQuestion: "回答：哪些資料支撐這次判讀？",
  evidenceScopeNote: "優先列出官方、即時與可驗證資料；歷史新聞暫停顯示。",
  hiddenNewsEvidence: "已隱藏歷史新聞來源",
  evidenceSource: "來源",
  evidenceConfidence: "信心",
  evidenceDistance: "距離",
  evidenceObservedAt: "觀測",
  evidenceCountSuffix: "筆來源",
  evidenceTime: "觀測 / 發布",
  evidenceUrl: "來源連結",
  evidenceOpenSource: "開啟來源",
  evidenceMissingUrl: "未提供連結",
  evidenceEmpty: "本次查詢尚未回傳可列出的資料佐證。",
  profileEvidenceEmpty: "本次還沒有逐筆列出的資料佐證，請先看上方的區域概略估計說明與資料限制。",
  evidenceLoading: "正在載入完整資料佐證。",
  evidenceError: "完整資料佐證載入失敗，先顯示風險摘要中的預覽資料。",
  latestNewsSources: "最新新聞來源",
  limitations: "資料限制",
  nearbyCoverageKicker: "附近即時觀測",
  nearbyCoveragePending: "等待風險查詢後顯示附近感測覆蓋。",
  nearbyCoverageEmpty: "本次回應沒有附近即時覆蓋資訊。",
  nearbyCoverageCountyNote: "縣市資料源不等於查詢點附近感測器",
  nearbyCoverageNearest: "最近距離",
  nearbyCoverageObservedAt: "最近觀測",
  evidenceFlood: "尚未查詢附近淹水事件。",
  evidenceRain: "查詢後會顯示雨量、水位與淹水潛勢資料。",
  evidenceTerrain: "公開資料會保留來源與時間，方便回頭查證。",
  freshness: "資料新鮮度",
  layers: "圖層管線",
  layerReady: "可顯示",
  layerLimited: "部分可用",
  layerEmpty: "無圖層資料",
  layerPending: "等待查詢",
  layerContract: "圖層資料合約",
  layerFallback: "由資料狀態與證據推導",
  layerNoTile: "尚未提供圖磚位址",
  layerNoData: "本次查詢未回傳可展示的圖層或資料來源。",
  layerFeatureCount: "資料筆數",
  offline: "尚未連線",
  online: "已連線",
  loading: "查詢中",
  queryLoadingHint: "查詢中，公開資料可能需要幾秒鐘，請稍候…",
  queryFailed: "查詢失敗，請稍後再試。",
  noGeocodeResult: "找不到這個地點，請換一個關鍵字再試。",
  geocodeAmbiguous: "不太確定是哪一個地點，你是不是要找下面其中一個？請點選正確的地點。",
  geocodeCandidatesLabel: "候選地點清單",
  geocodeNeedsConfirmation: "定位只到較粗範圍，系統會以代表點查詢並標示資料限制。",
  geocodePrecision: "定位精度",
  lastSync: "最後同步：--",
  freshnessNote: "查詢後會顯示資料來源的最新狀態。",
  diagnosticsKicker: "診斷資訊",
  diagnosticsTitle: "來源與圖層狀態",
  diagnosticsPending: "尚未查詢",
  diagnosticsReady: "查看資料來源、圖層與同步狀態",
  diagnosticsCoverageTitle: "附近即時覆蓋明細",
  diagnosticsCoverageNoSignals: "本次回應沒有 signal breakdown。",
  diagnosticsCoverageBuckets: "半徑計數",
  diagnosticsCoverageFreshness: "新鮮 / 更新較慢 / 過期 / 狀態線索",
  diagnosticsCoverageMissingReason: "缺口原因",
  diagnosticsCoverageLocalBoundary:
    "縣市有資料源，只代表可用目錄或來源存在；附近覆蓋仍以查詢點半徑內的新鮮感測資料為準。",
  diagnosticsSourceHealthKicker: "即時來源健康狀態",
  diagnosticsSourceHealthTitle: "逐來源公開診斷",
  diagnosticsSourceHealthLegacy: "此回應尚未提供逐來源健康狀態（舊版格式）。",
  diagnosticsSourceHealthUnavailable:
    "本次未能完成來源健康檢查，不能把缺少觀測解讀為附近沒有測站。",
  diagnosticsSourceHealthEmpty:
    "來源健康檢查已完成，但目前沒有已登錄的即時來源。",
  diagnosticsSourceStationCount: "已觀測站數",
  diagnosticsSourceInventory: "站點清冊",
  diagnosticsSourceInventoryComplete: "完整性已驗證",
  diagnosticsSourceInventoryUnverified: "完整性待驗證",
  diagnosticsSourceUpstreamCount: "上游總站數",
  diagnosticsSourcePagination: "分頁證明",
  diagnosticsSourceManifest: "清冊校驗",
  diagnosticsSourceJurisdictions: "適用縣市",
  diagnosticsJurisdiction: "管轄判定",
  diagnosticsJurisdictionVerified: "官方邊界已解析",
  diagnosticsJurisdictionUnverified: "邊界或來源目錄待驗證",
  diagnosticsSourceScope: "涵蓋範圍",
  diagnosticsSourceScopeNational: "全國",
  diagnosticsSourceScopeLocal: "地方",
  diagnosticsSourceObservedAt: "最後觀測",
  diagnosticsSourceCheckedAt: "健康檢查",
  defaultSource: "預設位置",
  mapSource: "地圖點選",
  searchSource: "搜尋定位",
  taipeiMainStation: "台北火車站",
  locatedPrefix: "已定位",
  selectedPrefix: "已選取",
  publicReportKicker: "民眾通報",
  publicReportTitle: "回報現地淹水線索",
  reportLocation: "通報座標",
  reportObservation: "觀察內容",
  reportPlaceholder: "簡短描述看見的積水、淹水深度或道路影響。",
  reportValidation: "請先輸入簡短觀察內容。",
  reportSubmit: "送出通報",
  reportDisabledTitle: "民眾通報目前停用",
  reportDisabledAction: "查看原因",
  reportDisabledMessage: "此功能會等法律、隱私、審核與治理流程完成後再開放。",
  provided: "已提供",
  tileLabel: "圖磚",
};

export const emergencyGuidance = {
  notice: "本工具不是官方災害通報，查詢結果僅供風險參考。",
  callToAction: "如遇緊急淹水危險，請立即撥打 119；即時官方水情請查看",
  officialLinkLabel: "水利署防災資訊網",
  officialLinkUrl: "https://fhy.wra.gov.tw",
};

export const sourceLabels: Record<CoordinateSource, string> = {
  default: text.defaultSource,
  map: text.mapSource,
  search: text.searchSource,
};

export const radiusOptions = [300, 500, 1000, 2000];

const healthLabels: Record<string, string> = {
  healthy: "正常",
  degraded: "受限",
  failed: "失敗",
  disabled: "停用",
  unknown: "未知",
};

export const healthLabel = (value: string) => healthLabels[value] ?? "未知";

const geocodePrecisionLabels: Record<string, string> = {
  admin_area: "行政區",
  exact_address: "門牌",
  map_click: "地圖點選",
  poi: "地標",
  road_or_lane: "道路 / 巷道",
  unknown: "未知",
};

export const geocodePrecisionLabel = (value?: string) =>
  geocodePrecisionLabels[value ?? "unknown"] ?? geocodePrecisionLabels.unknown;

const trimNoticeSentence = (value: string) => value.trim().replace(/[。．.]+$/u, "");

export const geocodeCandidateNotice = (candidate: GeocodeCandidate) => {
  const parts = [`${text.geocodePrecision}：${geocodePrecisionLabel(candidate.precision)}`];
  if (candidate.matched_query && candidate.matched_query !== candidate.name) {
    parts.push(`匹配：${candidate.matched_query}`);
  }
  if (candidate.limitations?.length) {
    parts.push(...candidate.limitations);
  }
  return parts.map(trimNoticeSentence).filter(Boolean).join("。");
};

const sourceTypeLabels: Record<string, string> = {
  official: "官方公開資料",
  news: "公開新聞",
  derived: "衍生資料",
  forum: "公開討論",
  public_web: "公開網頁",
  user_report: "使用者通報",
};

export const sourceTypeLabel = (value: string) => sourceTypeLabels[value] ?? "其他資料";

export const riskMeterPosition = (level?: string) => {
  const displayLevel = normalizeRiskLevel(level);
  if (displayLevel === "低") return "16%";
  if (displayLevel === "中") return "50%";
  if (displayLevel === "高") return "75%";
  if (displayLevel === "極高") return "92%";
  return "8%";
};

export const hasInsufficientRiskData = (assessment: RiskAssessmentResponse | null) =>
  Boolean(
    assessment &&
      normalizeRiskLevel(assessment.realtime.level) === "未知" &&
      normalizeRiskLevel(assessment.historical.level) === "未知" &&
      normalizeRiskLevel(assessment.confidence.level) === "未知" &&
      assessment.evidence.length === 0,
  );

export const coordinateSummary = (coordinate: Coordinate, locationLabel: string) =>
  coordinate.source === "search"
    ? `${text.locatedPrefix}：${locationLabel}`
    : `${text.selectedPrefix}：${sourceLabels[coordinate.source]}`;
