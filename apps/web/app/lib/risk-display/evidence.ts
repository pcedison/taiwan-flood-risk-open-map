import { formatDateTime } from "./format.ts";
import type {
  DataFreshnessItem,
  EvidenceDisplayText,
  EvidencePreview,
  EvidenceStatus,
  NewsEvidenceLink,
} from "./types.ts";

const SAFE_LINK_SCHEMES = new Set(["http:", "https:"]);

/**
 * Guards against unsafe href schemes (e.g. `javascript:`, `data:`) before a
 * value is used to render an anchor. Evidence source URLs originate from
 * external feeds (news RSS, etc.) and must never be trusted blindly.
 */
export function isSafeLinkUrl(value: string | null | undefined): value is string {
  if (!value) return false;
  try {
    return SAFE_LINK_SCHEMES.has(new URL(value).protocol);
  } catch {
    return false;
  }
}

export function evidenceSourceUrl(item: EvidencePreview) {
  const candidate = item.url ?? item.source_url ?? null;
  return isSafeLinkUrl(candidate) ? candidate : null;
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
  summary: "系統整理後的公開資料線索，請搭配來源時間與來源可信度判讀。",
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

export function hiddenHistoricalNewsCount(
  items: Array<EvidencePreview & { source_id?: string | null }>,
) {
  return items.filter(isHistoricalNewsEvidence).length;
}

/**
 * Event types that represent live sensing signals (rainfall, water level,
 * etc.). Exported so the nearby-coverage module can reuse the same
 * "is this a realtime signal" classification.
 */
export const realtimeEventLabels: Record<string, string> = {
  flood_depth: "淹水深度",
  flood_warning: "官方警戒",
  pump_or_gate_status: "抽水站／水門狀態",
  rainfall: "雨量",
  sewer_water_level: "下水道水位",
  status_only: "狀態線索",
  water_level: "水位",
};

export function isRealtimeEvidence(item: EvidencePreview) {
  return Object.prototype.hasOwnProperty.call(realtimeEventLabels, item.event_type);
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
