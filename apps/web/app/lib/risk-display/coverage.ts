import type { NearbyCoverageLevel, NearbyRealtimeCoverage } from "../page-types.ts";
import { isHistoricalNewsEvidence, isRealtimeEvidence, realtimeEventLabels } from "./evidence.ts";
import { formatDateTime, formatDistance } from "./format.ts";
import type { EvidencePreview, NearbyCoverageSummaryState, NearbySensingState } from "./types.ts";

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

const requiredRealtimeSignals = ["rainfall", "water_level"] as const;

const coverageLevelLabels: Record<NearbyCoverageLevel, string> = {
  high: "高",
  low: "低",
  medium: "中",
  no_local_sensor: "低",
  unavailable: "暫不可判斷",
};

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
