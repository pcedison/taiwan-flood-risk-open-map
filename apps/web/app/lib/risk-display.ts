import type { NearbyCoverageLevel, NearbyRealtimeCoverage } from "./page-types";

export type Coordinate = {
  lat: number;
  lng: number;
};

export type EvidencePreview = {
  id: string;
  source_type: string;
  event_type: string;
  title: string;
  summary: string;
  confidence: number;
  occurred_at?: string | null;
  observed_at: string | null;
  ingested_at: string | null;
  published_at?: string | null;
  source_url?: string | null;
  url?: string | null;
  distance_to_query_m: number | null;
};

export type EvidenceItem = EvidencePreview & {
  source_id?: string;
  freshness_score?: number;
  source_weight?: number;
  privacy_level?: string;
  raw_ref?: string | null;
};

export type EvidenceStatus = "idle" | "loading" | "ready" | "error";

export type DataFreshnessItem = {
  source_id: string;
  name: string;
  health_status: string;
  observed_at: string | null;
  ingested_at: string | null;
  feature_count?: number | null;
  message: string | null;
};

export type LayerContractItem = {
  id?: string;
  layer_id?: string;
  source_id?: string;
  name: string;
  kind?: string;
  type?: string;
  health_status?: string;
  status?: string;
  availability?: string;
  observed_at?: string | null;
  updated_at?: string | null;
  ingested_at?: string | null;
  tile_url?: string | null;
  feature_count?: number | null;
  coverage_percent?: number | null;
  message?: string | null;
};

export type LayerDisplayItem = {
  id: string;
  name: string;
  kind: string;
  status: string;
  availability: "available" | "limited" | "empty" | "unavailable" | "pending";
  freshnessAt: string | null;
  tileUrl: string | null;
  featureCount: number | null;
  message: string | null;
};

export type LayerDisplayState = {
  items: LayerDisplayItem[];
  status: "pending" | "ready" | "limited" | "empty";
  hasTileContract: boolean;
};

export type SourceHealthSummary = {
  title: string;
  note: string;
  tone: "ready" | "limited" | "empty";
  items: Array<{
    key: "available" | "limited" | "empty" | "unavailable";
    label: string;
    count: number;
  }>;
};

const layerAvailabilityLabels: Record<LayerDisplayItem["availability"], string> = {
  available: "可顯示",
  empty: "無圖層資料",
  limited: "部分可用",
  pending: "等待查詢",
  unavailable: "不可用",
};

const dataAvailabilityLabels: Record<LayerDisplayItem["availability"], string> = {
  available: "來源可用",
  empty: "本來源 0 命中",
  limited: "部分可用",
  pending: "等待查詢",
  unavailable: "不可用",
};

export function layerAvailabilityDisplayLabel(
  item: Pick<LayerDisplayItem, "availability" | "kind">,
) {
  const labels = item.kind === "資料" ? dataAvailabilityLabels : layerAvailabilityLabels;
  return labels[item.availability] ?? "未知";
}

export type ProfilePreviewState = {
  isProfilePreview: boolean;
  label: string | null;
  message: string | null;
};

export type ProfileBasisText = {
  historicalNote: string | null;
  confidenceNote: string | null;
  limitationLead: string | null;
};

export type NearbySensingState = {
  badge: string;
  gaps: string[];
  tone: "good" | "warn" | "poor" | "muted";
  summary: string;
  items: Array<{
    id: string;
    label: string;
    detail: string;
  }>;
  note: string;
};

export type RiskDecisionSummary = {
  confidence: string;
  driver: string;
  method: string;
  narrative: string;
};

export type UserReportPayload = {
  point: {
    lat: number;
    lng: number;
  };
  summary: string;
};

export type UserReportPayloadState =
  | {
      isValid: true;
      payload: UserReportPayload;
      summary: string;
      validationMessage: null;
    }
  | {
      isValid: false;
      payload: null;
      summary: string;
      validationMessage: "summary_required";
    };

export type UserReportSubmissionStatus =
  | "idle"
  | "loading"
  | "success"
  | "feature_disabled"
  | "rate_limited"
  | "repository_unavailable"
  | "error";

export type UserReportSubmissionDisplayState = {
  kind: "neutral" | "loading" | "success" | "warning" | "error";
  message: string | null;
  submitLabel: string;
};

export const UNKNOWN_RISK_LEVEL = "未知";

const riskLevelAliases = new Map<string, string>([
  ["low", "低"],
  ["medium", "中"],
  ["moderate", "中"],
  ["high", "高"],
  ["very_high", "極高"],
  ["very-high", "極高"],
  ["extreme", "極高"],
  ["unknown", UNKNOWN_RISK_LEVEL],
  ["insufficient", UNKNOWN_RISK_LEVEL],
  ["低", "低"],
  ["中", "中"],
  ["高", "高"],
  ["極高", "極高"],
  ["未知", UNKNOWN_RISK_LEVEL],
]);

const riskLevelRanks = new Map<string, number>([
  [UNKNOWN_RISK_LEVEL, 0],
  ["低", 1],
  ["中", 2],
  ["高", 3],
  ["極高", 4],
]);

export type RiskOverlayPresentation = {
  level: string;
  fillColor: string;
  lineColor: string;
  fillOpacity: number;
  colorName: string;
  /**
   * Optional MapLibre `line-dasharray` pattern. Distinguishes risk levels by
   * line style (not just hue) so red/green colorblind users can still tell
   * them apart on the map overlay. Undefined means a solid line.
   */
  lineDasharray?: number[];
};

const riskOverlayByLevel: Record<
  string,
  Omit<RiskOverlayPresentation, "level" | "fillOpacity">
> = {
  [UNKNOWN_RISK_LEVEL]: {
    fillColor: "#7a8791",
    lineColor: "#626c76",
    colorName: "灰色",
  },
  低: {
    fillColor: "#2f8f5b",
    lineColor: "#236f47",
    colorName: "綠色",
  },
  中: {
    fillColor: "#d9b928",
    lineColor: "#a48314",
    colorName: "黃色",
    lineDasharray: [6, 3],
  },
  高: {
    fillColor: "#cf4f35",
    lineColor: "#983825",
    colorName: "紅色",
    lineDasharray: [2, 2],
  },
  極高: {
    fillColor: "#9f2f2f",
    lineColor: "#742222",
    colorName: "深紅色",
    lineDasharray: [1, 2],
  },
};

export function riskLevelRank(level?: string | null): number {
  return riskLevelRanks.get(normalizeRiskLevel(level)) ?? 0;
}

export function normalizeRiskLevel(level?: string | null): string {
  if (!level) return UNKNOWN_RISK_LEVEL;
  const trimmed = level.trim();
  if (!trimmed) return UNKNOWN_RISK_LEVEL;
  return riskLevelAliases.get(trimmed) ?? riskLevelAliases.get(trimmed.toLowerCase()) ?? trimmed;
}

export function combinedRiskLevel(
  realtimeLevel?: string | null,
  historicalLevel?: string | null,
): string {
  const candidates = [realtimeLevel, historicalLevel].map(normalizeRiskLevel).filter(
    (level): level is string => Boolean(level),
  );
  if (candidates.length === 0) {
    return UNKNOWN_RISK_LEVEL;
  }
  return candidates.reduce((current, next) =>
    riskLevelRank(next) > riskLevelRank(current) ? next : current,
  );
}

export function riskSummaryTitle(
  realtimeLevel?: string | null,
  historicalLevel?: string | null,
): string {
  const level = combinedRiskLevel(realtimeLevel, historicalLevel);
  return level === UNKNOWN_RISK_LEVEL ? "資料不足" : `綜合風險：${level}`;
}

export function riskSummaryBasis(
  realtimeLevel?: string | null,
  historicalLevel?: string | null,
): string {
  return `即時：${normalizeRiskLevel(realtimeLevel)}；歷史參考：${normalizeRiskLevel(
    historicalLevel,
  )}`;
}

export function riskSummaryDecisionText(input: {
  realtimeLevel?: string | null;
  historicalLevel?: string | null;
  confidenceLevel?: string | null;
}): string {
  const realtimeLevel = normalizeRiskLevel(input.realtimeLevel);
  const historicalLevel = normalizeRiskLevel(input.historicalLevel);
  const confidenceLevel = normalizeRiskLevel(input.confidenceLevel);
  const realtimeRank = riskLevelRank(realtimeLevel);
  const historicalRank = riskLevelRank(historicalLevel);
  const driver =
    realtimeRank === 0 && historicalRank === 0
      ? "目前沒有足夠即時或歷史證據可判定。"
      : realtimeRank > historicalRank
        ? "目前由即時雨量、水位或警戒訊號主導。"
        : historicalRank > realtimeRank
          ? "目前由歷史事件或淹水潛勢參考主導。"
          : "即時與歷史參考落在相同等級。";

  return `綜合風險取即時與歷史參考中的較高等級；資料信心（${confidenceLevel}）只描述證據可靠度，不會單獨拉高風險。${driver}`;
}

export function riskDecisionSummary(input: {
  realtimeLevel?: string | null;
  historicalLevel?: string | null;
  confidenceLevel?: string | null;
}): RiskDecisionSummary {
  const realtimeLevel = normalizeRiskLevel(input.realtimeLevel);
  const historicalLevel = normalizeRiskLevel(input.historicalLevel);
  const confidenceLevel = normalizeRiskLevel(input.confidenceLevel);
  const realtimeRank = riskLevelRank(realtimeLevel);
  const historicalRank = riskLevelRank(historicalLevel);
  const driver =
    realtimeRank === 0 && historicalRank === 0
      ? "資料不足"
      : realtimeRank > historicalRank
        ? "即時主導"
        : historicalRank > realtimeRank
          ? "歷史參考"
          : "兩者相同";
  const narrative =
    realtimeRank === 0 && historicalRank === 0
      ? "本次資料不足，暫不把即時或歷史參考推成結論。"
      : realtimeRank > historicalRank
        ? `本次採即時風險，因即時（${realtimeLevel}）高於歷史參考（${historicalLevel}）。`
        : historicalRank > realtimeRank
          ? `本次採歷史參考，因歷史參考（${historicalLevel}）高於即時（${realtimeLevel}）。`
          : `即時與歷史參考同為${realtimeLevel}，綜合維持${realtimeLevel}。`;

  return {
    confidence: `信心：${confidenceLevel}`,
    driver: `主導：${driver}`,
    method: "取即時/歷史較高",
    narrative,
  };
}

export function riskOverlayPresentation(
  level?: string | null,
  hasAssessment = true,
): RiskOverlayPresentation {
  const displayLevel = normalizeRiskLevel(level);
  const normalizedLevel =
    displayLevel && riskOverlayByLevel[displayLevel] ? displayLevel : UNKNOWN_RISK_LEVEL;
  const palette = riskOverlayByLevel[normalizedLevel];
  return {
    level: normalizedLevel,
    ...palette,
    fillOpacity: hasAssessment ? 0.85 : 0.18,
  };
}

/**
 * Text color for a normalized risk level ("低"/"中"/"高"/"極高"), reusing the
 * same palette as the map overlay so the two stay in sync. Returns undefined
 * for unknown/no-data so callers fall back to the default foreground color.
 */
export function riskLevelTextColor(level?: string | null): string | undefined {
  const normalized = normalizeRiskLevel(level);
  if (normalized === UNKNOWN_RISK_LEVEL) return undefined;
  return riskOverlayByLevel[normalized]?.lineColor;
}

export function formatCoordinate(value: number) {
  return value.toFixed(5);
}

export function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function formatDistance(value: number | null) {
  return value === null ? "未提供" : `${Math.round(value).toLocaleString("zh-TW")} 公尺`;
}

export type NearbyCoverageSummaryState = {
  badge: string;
  tone: "good" | "warn" | "poor" | "muted";
  summary: string;
};

const nearbyCoverageLabels: Record<NearbyCoverageLevel, string> = {
  high: "附近即時感測充足",
  low: "附近即時感測偏少",
  medium: "附近即時感測中等",
  no_local_sensor: "半徑內無新鮮在地感測",
  unavailable: "即時覆蓋暫時無法評估",
};

const nearbyCoverageFallbackSummaries: Record<NearbyCoverageLevel, string> = {
  high: "查詢點附近有新鮮即時感測資料，感測密度充足。",
  low: "查詢點附近有新鮮即時感測資料，但感測密度偏少。",
  medium: "查詢點附近有新鮮即時感測資料，感測密度中等。",
  no_local_sensor:
    "查詢點半徑內沒有新鮮在地感測資料；縣市或資料源仍可能有資料。",
  unavailable: "即時感測覆蓋暫時無法評估，不能判斷附近是否有感測器。",
};

export function nearbyCoverageLevelLabel(level: NearbyCoverageLevel): string {
  return nearbyCoverageLabels[level];
}

export function formatDistanceMeters(value: number | null): string {
  if (value === null) {
    return "半徑內無新鮮感測";
  }

  const normalized = Math.max(0, value);
  if (normalized < 1000) {
    return `${Math.round(normalized).toLocaleString("zh-TW")} 公尺`;
  }

  return `${new Intl.NumberFormat("zh-TW", {
    maximumFractionDigits: 1,
  }).format(normalized / 1000)} 公里`;
}

export function nearbyCoverageSummary(
  coverage: NearbyRealtimeCoverage | null,
): NearbyCoverageSummaryState {
  if (!coverage) {
    return {
      badge: nearbyCoverageLabels.unavailable,
      summary: "即時感測覆蓋尚未回傳，無法判斷附近是否有感測器。",
      tone: "muted",
    };
  }

  const tone: NearbyCoverageSummaryState["tone"] =
    coverage.overall_level === "high"
      ? "good"
      : coverage.overall_level === "no_local_sensor"
        ? "poor"
        : coverage.overall_level === "unavailable"
          ? "muted"
          : "warn";

  return {
    badge: nearbyCoverageLabels[coverage.overall_level],
    summary:
      coverage.summary.trim() ||
      nearbyCoverageFallbackSummaries[coverage.overall_level],
    tone,
  };
}

export function formatDateTime(value: string | null, options?: { timeZone?: string }) {
  if (!value) return "未提供";
  return new Intl.DateTimeFormat("zh-TW", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: options?.timeZone,
  }).format(new Date(value));
}

export function evidenceSourceUrl(item: EvidencePreview) {
  return item.url ?? item.source_url ?? null;
}

export function evidencePublishedAt(item: EvidencePreview) {
  return item.published_at ?? item.occurred_at ?? null;
}

export function evidenceTimeSummary(item: EvidencePreview) {
  const observedAt = item.observed_at;
  const publishedAt = evidencePublishedAt(item);

  if (observedAt && publishedAt) {
    return `${formatDateTime(observedAt)} / ${formatDateTime(publishedAt)}`;
  }

  return formatDateTime(observedAt ?? publishedAt ?? null);
}

export type NewsEvidenceLink = {
  id: string;
  title: string;
  url: string;
  time: string | null;
};

const historicalFreshnessSourceIds = new Set([
  "db-evidence",
  "historical-flood-records",
  "on-demand-public-news",
]);

export function latestNewsEvidenceLinks(items: EvidencePreview[], limit = 3): NewsEvidenceLink[] {
  return items
    .filter((item) => item.source_type === "news" && Boolean(evidenceSourceUrl(item)))
    .sort((left, right) => evidenceSortTime(right) - evidenceSortTime(left))
    .slice(0, Math.max(0, limit))
    .map((item) => ({
      id: item.id,
      title: item.title,
      url: evidenceSourceUrl(item) ?? "",
      time: evidencePublishedAt(item) ?? item.observed_at ?? item.ingested_at ?? null,
    }));
}

export function latestNewsLinksFreshnessSourceId(
  dataFreshness: DataFreshnessItem[],
  evidenceItems: Array<EvidencePreview & { source_id?: string | null }>,
) {
  const hasNewsLinks = latestNewsEvidenceLinks(evidenceItems, 1).length > 0;
  if (!hasNewsLinks) return null;

  const onDemand = dataFreshness.find((item) => item.source_id === "on-demand-public-news");
  const hasOnDemandEvidence = evidenceItems.some((item) =>
    Boolean(
      item.source_id?.startsWith("public-news-rss:") ||
        item.source_id?.startsWith("public-wiki:") ||
        item.source_id?.startsWith("gdelt-on-demand:"),
    ),
  );
  if (onDemand && ((onDemand.feature_count ?? 0) > 0 || hasOnDemandEvidence)) {
    return onDemand.source_id;
  }

  return dataFreshness.find((item) => historicalFreshnessSourceIds.has(item.source_id))?.source_id ?? null;
}

export function isHistoricalNewsEvidence(
  item: EvidencePreview & { source_id?: string | null },
) {
  return (
    item.source_type === "news" ||
    item.source_id?.startsWith("public-news") ||
    item.source_id?.startsWith("gdelt-on-demand:") ||
    item.source_id?.startsWith("news:")
  );
}

export function isHistoricalNewsFreshness(item: DataFreshnessItem) {
  return (
    item.source_id === "on-demand-public-news" ||
    item.source_id === "db-evidence" ||
    item.source_id.includes("news") ||
    item.name.includes("新聞") ||
    item.name.includes("Wiki")
  );
}

export type EvidenceDisplayText = {
  purpose: string;
  title: string;
  summary: string;
};

const evidenceEventDisplayText: Record<string, EvidenceDisplayText> = {
  flood: {
    purpose: "用途：淹水佐證",
    summary: "官方資料與本次查詢範圍相關，可作為淹水風險判讀的佐證。",
    title: "淹水資料線索",
  },
  flood_depth: {
    purpose: "用途：現地狀況",
    summary: "附近淹水深度觀測可輔助確認現地積淹水狀況。",
    title: "淹水深度觀測",
  },
  flood_potential: {
    purpose: "用途：地形 / 歷史參考",
    summary: "官方淹水潛勢圖資與本次查詢範圍重疊，可作為地形與歷史條件參考。",
    title: "淹水潛勢資料",
  },
  flood_warning: {
    purpose: "用途：官方警戒",
    summary: "官方警戒資訊與本次查詢範圍相關，請搭配發布時間判讀。",
    title: "官方警戒資訊",
  },
  pump_or_gate_status: {
    purpose: "用途：排水系統狀態",
    summary: "抽水站或水門狀態可輔助判讀附近排水系統運作情形。",
    title: "抽水站 / 水門狀態",
  },
  rainfall: {
    purpose: "用途：即時雨量",
    summary: "附近即時雨量觀測可輔助判讀當下降雨壓力。",
    title: "雨量觀測",
  },
  sewer_water_level: {
    purpose: "用途：排水壓力",
    summary: "附近下水道水位觀測可輔助判讀排水系統壓力。",
    title: "下水道水位觀測",
  },
  status_only: {
    purpose: "用途：補充狀態",
    summary: "附近即時狀態資料可作為補充線索，需搭配其他觀測判讀。",
    title: "即時狀態資料",
  },
  water_level: {
    purpose: "用途：即時水位",
    summary: "附近水位觀測可輔助判讀河川、排水或下游回堵狀況。",
    title: "水位觀測",
  },
};

const officialEvidenceDisplayText: EvidenceDisplayText = {
  purpose: "用途：官方佐證",
  summary: "官方資料與本次查詢範圍相關，請搭配時間、距離與資料限制判讀。",
  title: "官方資料線索",
};

const derivedEvidenceDisplayText: EvidenceDisplayText = {
  purpose: "用途：整理後佐證",
  summary: "系統整理後的公開資料線索，請搭配來源時間與信心分數判讀。",
  title: "整理後資料線索",
};

export function evidenceDisplayText(item: EvidencePreview): EvidenceDisplayText {
  if (isHistoricalNewsEvidence(item)) {
    return { purpose: "用途：歷史新聞參考", summary: item.summary, title: item.title };
  }

  const eventText = evidenceEventDisplayText[item.event_type];
  if (
    eventText &&
    (item.source_type === "official" || item.source_type === "derived" || isRealtimeEvidence(item))
  ) {
    return eventText;
  }

  if (item.source_type === "official") return officialEvidenceDisplayText;
  if (item.source_type === "derived") return derivedEvidenceDisplayText;

  return { purpose: "用途：補充線索", summary: item.summary, title: item.title };
}

function evidenceDisplayPriority(item: EvidencePreview & { source_id?: string | null }) {
  if (isHistoricalNewsEvidence(item)) return 99;
  if (item.source_type === "official" && isRealtimeEvidence(item)) return 0;
  if (item.source_type === "official") return 1;
  if (item.source_type === "derived") return 2;
  if (item.source_type === "user_report") return 3;
  return 4;
}

export function publicEvidenceDisplayItems<T extends EvidencePreview & { source_id?: string | null }>(
  items: T[],
  limit = 3,
) {
  return [...items]
    .filter((item) => !isHistoricalNewsEvidence(item))
    .sort((left, right) => {
      const priorityDelta = evidenceDisplayPriority(left) - evidenceDisplayPriority(right);
      if (priorityDelta !== 0) return priorityDelta;
      return evidenceSortTime(right) - evidenceSortTime(left);
    })
    .slice(0, Math.max(0, limit));
}

export function publicDataFreshnessItems(items: DataFreshnessItem[]) {
  return items.filter((item) => !isHistoricalNewsFreshness(item));
}

export function sourceHealthSummaryState(
  layerDisplayState: LayerDisplayState,
): SourceHealthSummary {
  const counts = layerDisplayState.items.reduce(
    (summary, item) => {
      if (item.availability === "available") summary.available += 1;
      if (item.availability === "limited") summary.limited += 1;
      if (item.availability === "unavailable") summary.unavailable += 1;
      if (item.availability === "empty" || item.availability === "pending") {
        summary.empty += 1;
      }
      return summary;
    },
    { available: 0, empty: 0, limited: 0, unavailable: 0 },
  );

  const title =
    layerDisplayState.status === "ready"
      ? "來源摘要：可用"
      : layerDisplayState.status === "limited"
        ? "來源摘要：部分受限"
        : layerDisplayState.status === "empty"
          ? "來源摘要：本次無資料"
          : "來源摘要：等待查詢";

  const note = layerDisplayState.hasTileContract
    ? "以本次回傳的地圖圖層契約為主，細節可在下方展開核對。"
    : "以可公開顯示的來源狀態與資料線索推估；歷史新聞已先隱藏。";

  return {
    items: [
      { count: counts.available, key: "available", label: "可用" },
      { count: counts.limited, key: "limited", label: "受限" },
      { count: counts.empty, key: "empty", label: "無資料" },
      { count: counts.unavailable, key: "unavailable", label: "不可用" },
    ],
    note,
    title,
    tone:
      layerDisplayState.status === "ready"
        ? "ready"
        : layerDisplayState.status === "limited"
          ? "limited"
          : "empty",
  };
}

export function hiddenHistoricalNewsCount(
  items: Array<EvidencePreview & { source_id?: string | null }>,
) {
  return items.filter(isHistoricalNewsEvidence).length;
}

const realtimeEventLabels: Record<string, string> = {
  flood_depth: "淹水深度",
  flood_warning: "官方警戒",
  rainfall: "雨量",
  sewer_water_level: "下水道水位",
  water_level: "水位",
};

const requiredRealtimeSignals = ["rainfall", "water_level"] as const;

const coverageLevelLabels: Record<NearbyCoverageLevel, string> = {
  high: "高",
  low: "低",
  medium: "中",
  no_local_sensor: "低",
  unavailable: "暫不可判斷",
};

function isRealtimeEvidence(item: EvidencePreview) {
  return Object.prototype.hasOwnProperty.call(realtimeEventLabels, item.event_type);
}

function coverageTone(level: NearbyCoverageLevel): NearbySensingState["tone"] {
  if (level === "high") return "good";
  if (level === "medium") return "warn";
  if (level === "low" || level === "no_local_sensor") return "poor";
  return "muted";
}

function nearbyCoverageBadge(level: NearbyCoverageLevel) {
  if (level === "unavailable") return "附近觀測暫不可判斷";
  if (level === "no_local_sensor") return "附近觀測：低";
  return `附近觀測：${coverageLevelLabels[level]}`;
}

function nearbySignalLabel(value: string) {
  return realtimeEventLabels[value] ?? value;
}

function nearbySensingCoverageSummary(coverage: NearbyRealtimeCoverage) {
  const signals = coverage.signal_breakdown.filter(
    (signal) =>
      signal.nearest_distance_m !== null ||
      signal.fresh_count > 0 ||
      signal.status_only_count > 0,
  );
  const labels = Array.from(
    new Set(signals.map((signal) => nearbySignalLabel(signal.signal_type))),
  ).slice(0, 3);
  const gaps = coverage.missing_signal_types.map(nearbySignalLabel).slice(0, 3);
  const nearestDistances = signals
    .map((signal) => signal.nearest_distance_m)
    .filter((distance): distance is number => distance !== null);
  const nearestText = nearestDistances.length
    ? `，最近 ${formatDistance(Math.min(...nearestDistances))}`
    : "";

  if (coverage.overall_level === "unavailable") {
    return "本次無法判讀附近即時感測覆蓋，請改看風險摘要與重點資料線索。";
  }

  if (!signals.length) {
    return "本次沒有可列出的近距即時觀測；即時風險需要搭配其他資料判讀。";
  }

  const signalText = labels.length ? labels.join("、") : "即時感測";
  const gapText = gaps.length ? `；仍缺 ${gaps.join("、")}。` : "。";
  return `附近有 ${signalText} ${signals.length} 類觀測${nearestText}${gapText}`;
}

function nearbyCoverageNote(coverage: NearbyRealtimeCoverage) {
  if (coverage.overall_level === "unavailable") {
    return "附近感測資料暫不可用；不要只用此區塊判斷現地安全。";
  }

  if (coverage.missing_signal_types.length) {
    return "缺口代表本次查詢範圍內沒有取得該類近距觀測，不等於現地安全。";
  }

  return "附近觀測只描述感測覆蓋與新鮮度，不會單獨改變綜合風險。";
}

export function nearbySensingState(input: {
  assessment?: {
    nearby_realtime_coverage?: NearbyRealtimeCoverage | null;
  } | null;
  evidenceItems?: Array<EvidencePreview & { source_id?: string | null }> | null;
}): NearbySensingState {
  const coverage = input.assessment?.nearby_realtime_coverage ?? null;
  if (coverage) {
    return {
      badge: nearbyCoverageBadge(coverage.overall_level),
      gaps: coverage.missing_signal_types.map(nearbySignalLabel).slice(0, 3),
      items: coverage.signal_breakdown.slice(0, 4).map((signal) => ({
        detail:
          signal.nearest_distance_m === null
            ? "未取得近距觀測"
            : `${formatDistance(signal.nearest_distance_m)}；${nearbyCoverageBadge(signal.coverage_level).replace("附近觀測：", "覆蓋")}`,
        id: signal.signal_type,
        label: nearbySignalLabel(signal.signal_type),
      })),
      note: nearbyCoverageNote(coverage),
      summary: nearbySensingCoverageSummary(coverage),
      tone: coverageTone(coverage.overall_level),
    };
  }

  const realtimeItems = (input.evidenceItems ?? [])
    .filter((item) => !isHistoricalNewsEvidence(item) && isRealtimeEvidence(item))
    .sort((left, right) => {
      const leftDistance = left.distance_to_query_m ?? Number.POSITIVE_INFINITY;
      const rightDistance = right.distance_to_query_m ?? Number.POSITIVE_INFINITY;
      return leftDistance - rightDistance;
    });

  if (!input.assessment) {
    return {
      badge: "附近觀測：尚未查詢",
      gaps: [],
      items: [],
      note: "查詢後會獨立整理附近雨量、水位與警戒觀測。",
      summary: "尚未查詢附近即時感測資料。",
      tone: "muted",
    };
  }

  if (realtimeItems.length === 0) {
    return {
      badge: "附近觀測：低",
      gaps: ["雨量", "水位"],
      items: [],
      note: "低代表本次回應沒有可列出的近距即時感測；不等於現地安全。",
      summary: "本次沒有可列出的雨量、水位或警戒觀測；即時風險若偏低，仍可能受到資料覆蓋限制。",
      tone: "poor",
    };
  }

  const nearestDistance = realtimeItems[0].distance_to_query_m;
  const signalTypes = new Set(realtimeItems.map((item) => item.event_type));
  const gaps = requiredRealtimeSignals
    .filter((signalType) => !signalTypes.has(signalType))
    .map(nearbySignalLabel);
  const level: NearbyCoverageLevel =
    signalTypes.size >= 2 && nearestDistance !== null && nearestDistance <= 500
      ? "high"
      : nearestDistance !== null && nearestDistance <= 1000
        ? "medium"
        : "low";

  return {
    badge: nearbyCoverageBadge(level),
    gaps,
    items: realtimeItems.slice(0, 4).map((item) => ({
      detail: `${formatDistance(item.distance_to_query_m)}；${formatDateTime(item.observed_at)}`,
      id: item.id,
      label: item.title || realtimeEventLabels[item.event_type] || "即時觀測",
    })),
    note: "這是依目前證據列表整理的附近感測摘要；正式 coverage 欄位接上後會改用後端計算。",
    summary:
      level === "high"
        ? "附近已有多種即時水情訊號，可輔助判讀當下狀況。"
        : level === "medium"
          ? "附近有可用即時觀測，但訊號種類或距離仍有限。"
          : "本次只有較少或較遠的即時觀測，請把它視為低覆蓋而非低風險。",
    tone: coverageTone(level),
  };
}

function evidenceSortTime(item: EvidencePreview) {
  const time = evidencePublishedAt(item) ?? item.observed_at ?? item.ingested_at;
  if (!time) return 0;
  const parsed = Date.parse(time);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function selectEvidenceItems<T extends EvidencePreview>(
  previewItems: T[],
  fullListItems: T[],
  status: EvidenceStatus,
) {
  if (status === "ready") return fullListItems;
  return fullListItems.length ? fullListItems : previewItems;
}

export function getEvidenceDisplayState(status: EvidenceStatus, itemCount: number) {
  return {
    showEmpty: itemCount === 0 && status !== "loading",
    showError: status === "error",
    showList: itemCount > 0,
    showLoading: status === "loading",
  };
}

export function shouldFetchEvidenceList(assessmentId: string | null | undefined) {
  return Boolean(assessmentId);
}

export function getProfilePreviewState(input: {
  data_freshness?: DataFreshnessItem[] | null;
  explanation?: {
    summary?: string | null;
  } | null;
} | null | undefined): ProfilePreviewState {
  const profileFreshness = input?.data_freshness?.find(
    (item) => item.source_id === "precomputed-risk-profile",
  );
  if (!profileFreshness) {
    return {
      isProfilePreview: false,
      label: null,
      message: null,
    };
  }

  return {
    isProfilePreview: true,
    label: "區域 profile 初步結果",
    message:
      profileFreshness.message ??
      input?.explanation?.summary ??
      "本次結果先使用預先計算的區域風險 profile，精準半徑資料會由背景工作更新。",
  };
}

export function getProfileBasisText(input: {
  data_freshness?: DataFreshnessItem[] | null;
  explanation?: {
    main_reasons?: string[] | null;
  } | null;
  evidence?: EvidencePreview[] | null;
} | null | undefined): ProfileBasisText {
  const profileFreshness = input?.data_freshness?.find(
    (item) => item.source_id === "precomputed-risk-profile",
  );
  if (!profileFreshness) {
    return {
      historicalNote: null,
      confidenceNote: null,
      limitationLead: null,
    };
  }

  const reasons = input?.explanation?.main_reasons ?? [];
  const evidenceCount = input?.evidence?.length ?? 0;
  const evidenceReason =
    reasons.find((reason) => reason.includes("歷史參考來自 profile")) ??
    reasons.find((reason) => reason.includes("profile 彙整")) ??
    null;

  return {
    historicalNote:
      evidenceReason ??
      (evidenceCount > 0
        ? `profile 已提供 ${evidenceCount} 筆摘要證據。`
        : "profile 尚未列出逐筆摘要證據。"),
    confidenceNote: "由 profile 的來源類型、資料筆數、時間新鮮度與覆蓋缺口推估。",
    limitationLead:
      "這不是系統錯誤，而是本次 profile 未納入的資料來源；即時雨量或水位缺口會限制即時判斷。",
  };
}

export function buildRiskAssessmentPayload(
  coordinate: Coordinate,
  radius: number,
  locationText: string | null,
) {
  return {
    point: {
      lat: coordinate.lat,
      lng: coordinate.lng,
    },
    radius_m: radius,
    time_context: "now",
    location_text: locationText,
  };
}

export function buildUserReportPayload(
  coordinate: Coordinate,
  summary: string,
): UserReportPayloadState {
  const trimmedSummary = summary.trim();
  if (!trimmedSummary) {
    return {
      isValid: false,
      payload: null,
      summary: trimmedSummary,
      validationMessage: "summary_required",
    };
  }

  return {
    isValid: true,
    payload: {
      point: {
        lat: coordinate.lat,
        lng: coordinate.lng,
      },
      summary: trimmedSummary,
    },
    summary: trimmedSummary,
    validationMessage: null,
  };
}

export function getUserReportSubmissionDisplayState(
  status: UserReportSubmissionStatus,
): UserReportSubmissionDisplayState {
  if (status === "loading") {
    return {
      kind: "loading",
      message: "正在送出通報。",
      submitLabel: "送出中",
    };
  }

  if (status === "success") {
    return {
      kind: "success",
      message: "通報已收到，等待審核。",
      submitLabel: "送出通報",
    };
  }

  if (status === "feature_disabled") {
    return {
      kind: "warning",
      message: "此環境目前停用民眾通報功能。",
      submitLabel: "送出通報",
    };
  }

  if (status === "repository_unavailable") {
    return {
      kind: "error",
      message: "通報收件暫時無法使用。",
      submitLabel: "送出通報",
    };
  }

  if (status === "rate_limited") {
    return {
      kind: "warning",
      message: "通報送出太頻繁，請稍後再試。",
      submitLabel: "送出通報",
    };
  }

  if (status === "error") {
    return {
      kind: "error",
      message: "通報送出失敗。",
      submitLabel: "送出通報",
    };
  }

  return {
    kind: "neutral",
    message: null,
    submitLabel: "送出通報",
  };
}

function normalizeLayerAvailability(
  item: Pick<LayerContractItem, "availability" | "coverage_percent" | "feature_count" | "health_status" | "status">,
): LayerDisplayItem["availability"] {
  const explicit = item.availability?.toLowerCase();
  if (
    explicit === "available" ||
    explicit === "limited" ||
    explicit === "empty" ||
    explicit === "unavailable" ||
    explicit === "pending"
  ) {
    return explicit;
  }

  const status = item.status?.toLowerCase() ?? item.health_status?.toLowerCase() ?? "unknown";
  if (item.feature_count === 0) return "empty";
  if (status === "failed" || status === "disabled" || status === "unavailable") {
    return "unavailable";
  }
  if (
    status === "degraded" ||
    status === "limited" ||
    (typeof item.coverage_percent === "number" && item.coverage_percent < 50)
  ) {
    return "limited";
  }
  if (status === "pending") return "pending";
  return "available";
}

function layerId(item: LayerContractItem, index: number) {
  return item.id ?? item.layer_id ?? item.source_id ?? `layer-${index + 1}`;
}

function layerKindLabel(value: string | null | undefined) {
  const normalized = value?.toLowerCase();
  if (!normalized) return "圖層";
  if (normalized === "raster-tile" || normalized === "raster") return "點陣圖磚";
  if (normalized === "vector-tile" || normalized === "vector" || normalized === "tile") {
    return "向量圖磚";
  }
  if (normalized === "evidence") return "資料";
  return "圖層";
}

function evidenceCountForSource(evidenceItems: EvidenceItem[], sourceId: string): number | null {
  if (sourceId === "on-demand-public-news") {
    return evidenceItems.filter((item) =>
      Boolean(
        item.source_id?.startsWith("public-news-rss:") ||
          item.source_id?.startsWith("public-wiki:") ||
          item.source_id?.startsWith("gdelt-on-demand:"),
      ),
    ).length;
  }

  const matchingCount = evidenceItems.filter((item) => item.source_id === sourceId).length;
  return matchingCount > 0 ? matchingCount : null;
}

export function buildLayerDisplayState(input: {
  layers?: LayerContractItem[] | null;
  dataFreshness?: DataFreshnessItem[] | null;
  evidenceItems?: EvidenceItem[] | null;
}): LayerDisplayState {
  const layers = input.layers ?? [];
  const dataFreshness = input.dataFreshness ?? [];
  const evidenceItems = input.evidenceItems ?? [];

  const items: LayerDisplayItem[] = layers.length
    ? layers.map((item, index) => ({
        availability: normalizeLayerAvailability(item),
        featureCount: item.feature_count ?? null,
        freshnessAt: item.observed_at ?? item.updated_at ?? item.ingested_at ?? null,
        id: layerId(item, index),
        kind: layerKindLabel(item.kind ?? item.type),
        message: item.message ?? null,
        name: item.name,
        status: item.status ?? item.health_status ?? "unknown",
        tileUrl: item.tile_url ?? null,
      }))
    : dataFreshness.map((item) => ({
        availability: normalizeLayerAvailability(item),
        featureCount: item.feature_count ?? evidenceCountForSource(evidenceItems, item.source_id),
        freshnessAt: item.observed_at ?? item.ingested_at,
        id: item.source_id,
        kind: "資料",
        message: item.message,
        name: item.name,
        status: item.health_status,
        tileUrl: null,
      }));

  if (!items.length) {
    return {
      hasTileContract: false,
      items: [],
      status: evidenceItems.length ? "limited" : "empty",
    };
  }

  const hasLimited = items.some(
    (item) => item.availability === "limited" || item.availability === "unavailable",
  );
  const hasOnlyEmpty = items.every((item) => item.availability === "empty");

  return {
    hasTileContract: layers.length > 0,
    items,
    status: hasOnlyEmpty ? "empty" : hasLimited ? "limited" : "ready",
  };
}
