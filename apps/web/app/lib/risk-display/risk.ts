import type { RiskDecisionSummary, RiskOverlayPresentation } from "./types";

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
        ? "目前由即時訊號主導；即時可能包含近期雨量、水位、官方警戒、通報或區域即時 profile，不等於現在正在下雨。"
        : historicalRank > realtimeRank
          ? "目前由歷史事件或淹水潛勢參考主導。"
          : "即時與歷史參考落在相同等級。";

  return `綜合風險取即時與歷史參考中較高的等級；資料可信度（${confidenceLevel}）只描述證據可靠度，不代表淹水機率，也不會單獨拉高風險。${driver}`;
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
        ? `本次採即時風險，因即時（${realtimeLevel}）高於歷史參考（${historicalLevel}）。即時不是只代表正在下雨，也可能來自水位、官方警戒、通報或區域即時 profile。`
        : historicalRank > realtimeRank
          ? `本次採歷史參考，因歷史參考（${historicalLevel}）高於即時（${realtimeLevel}）。`
          : `即時與歷史參考同為${realtimeLevel}，綜合維持${realtimeLevel}。`;

  return {
    confidence: `資料可信度：${confidenceLevel}`,
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
