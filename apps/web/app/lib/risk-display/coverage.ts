import type { NearbyCoverageLevel, NearbyRealtimeCoverage } from "../page-types.ts";
import { isHistoricalNewsEvidence, isRealtimeEvidence, realtimeEventLabels } from "./evidence.ts";
import { formatDateTime, formatDistance, formatDistanceMeters } from "./format.ts";
import type { EvidencePreview, NearbyCoverageSummaryState, NearbySensingState } from "./types.ts";

const nearbyCoverageLabels: Record<NearbyCoverageLevel, string> = {
  high: "附近即時感測充足",
  low: "附近即時觀測有限",
  medium: "附近即時感測中等",
  no_local_sensor: "附近即時資料不足",
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
const requiredCoverageSignals = [
  "rainfall",
  "water_level",
  "flood_depth",
  "sewer_water_level",
] as const;
const requiredCoverageSignalSet = new Set<string>(requiredCoverageSignals);
const measurementSignalSet = new Set<string>([
  "rainfall",
  "water_level",
  "flood_depth",
  "sewer_water_level",
]);

type CoverageSignal = NearbyRealtimeCoverage["signal_breakdown"][number];
type SignalAvailability = NonNullable<CoverageSignal["availability_state"]>;
type MissingCause = NonNullable<CoverageSignal["missing_cause"]>;
type SourceIssueCause = Extract<
  MissingCause,
  | "source_degraded"
  | "source_failed"
  | "update_pipeline_stalled"
  | "source_not_configured"
  | "inventory_unverified"
  | "jurisdiction_unverified"
  | "health_unknown"
>;

type CoverageDiagnosis = {
  confirmedNoStation: boolean;
  hasRegionalReference: boolean;
  hasUsableObservation: boolean;
  isPartial: boolean;
  sourceIssue: SourceIssueCause | null;
};

const coverageLevelLabels: Record<NearbyCoverageLevel, string> = {
  high: "高",
  low: "有限",
  medium: "中",
  no_local_sensor: "不足",
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
  if (level === "no_local_sensor") return "附近觀測：資料不足";
  return `附近觀測：${coverageLevelLabels[level]}`;
}

function nearbySignalLabel(value: string) {
  return realtimeEventLabels[value] ?? value;
}

function nearbySensingCoverageSummary(
  coverage: NearbyRealtimeCoverage,
  diagnosis: CoverageDiagnosis,
) {
  const signals = coverage.signal_breakdown.filter(
    (signal) =>
      signal.nearest_distance_m !== null ||
      signal.fresh_count > 0 ||
      (signal.degraded_count ?? 0) > 0 ||
      signal.stale_count > 0 ||
      signal.status_only_count > 0,
  );
  const labels = Array.from(
    new Set(signals.map((signal) => nearbySignalLabel(signal.signal_type))),
  ).slice(0, 3);
  const gaps = coverage.missing_signal_types.map(nearbySignalLabel);
  const nearestDistances = signals
    .map((signal) => signal.nearest_distance_m)
    .filter((distance): distance is number => distance !== null);
  const nearestText = nearestDistances.length
    ? `；最近觀測距查詢點 ${formatDistance(Math.min(...nearestDistances))}`
    : "";

  if (coverage.overall_level === "unavailable") {
    return "本次無法判讀附近即時感測覆蓋，請改看風險摘要與判讀依據。";
  }

  if (diagnosis.sourceIssue) {
    if (diagnosis.isPartial) {
      if (diagnosis.sourceIssue === "jurisdiction_unverified") {
        return "附近仍有部分即時觀測，但縣市邊界或管轄來源清單尚未完成審核。";
      }
      if (diagnosis.sourceIssue === "inventory_unverified") {
        return "附近仍有部分即時觀測，但另有來源的站點清冊完整性尚未驗證。";
      }
      return diagnosis.sourceIssue === "update_pipeline_stalled"
        ? "附近仍有部分即時觀測，但另有來源的背景更新已停滯，覆蓋並不完整。"
        : "附近仍有部分即時觀測，但另有來源異常或狀態受限，覆蓋並不完整。";
    }
    if (diagnosis.sourceIssue === "update_pipeline_stalled") {
      return "即時來源的背景更新已停滯，目前無法確認附近是否真的沒有測站。";
    }
    if (diagnosis.sourceIssue === "source_failed") {
      return "即時資料來源或更新管線異常，目前無法確認附近是否真的沒有測站。";
    }
    if (diagnosis.sourceIssue === "source_degraded") {
      return "即時資料來源目前僅部分可用或有所延遲，無法確認附近是否真的沒有測站。";
    }
    if (diagnosis.sourceIssue === "source_not_configured") {
      return "必要的即時資料來源尚未啟用，無法確認附近是否真的沒有測站。";
    }
    if (diagnosis.sourceIssue === "jurisdiction_unverified") {
      return "縣市邊界或管轄來源清單尚未完成審核，不能確認附近真的沒有測站。";
    }
    if (diagnosis.sourceIssue === "inventory_unverified") {
      return "來源目前可運作，但站點清冊完整性尚未驗證，不能確認附近真的沒有測站。";
    }
    return "目前無法取得完整的即時來源健康狀態，不能確認附近是否真的沒有測站。";
  }

  if (diagnosis.confirmedNoStation) {
    return "來源運作正常，且站點清冊顯示感測搜尋範圍內沒有測站。";
  }

  if (!signals.length) {
    return coverage.summary.trim() || "本次沒有可列出的即時觀測；即時風險需要搭配其他資料判讀。";
  }

  const hasRegionalReference = signals.some(
    (signal) =>
      signal.coverage_level === "no_local_sensor" &&
      signal.nearest_distance_m !== null &&
      signal.fresh_count + (signal.degraded_count ?? 0) > 0,
  );
  const hasOnlyStale = signals.every(
    (signal) => signal.fresh_count + (signal.degraded_count ?? 0) === 0,
  );
  if (hasRegionalReference && coverage.overall_level === "no_local_sensor") {
    return coverage.summary.trim() || "近距觀測不足；較遠測站僅能作區域參考。";
  }
  if (hasOnlyStale && coverage.overall_level === "no_local_sensor") {
    return coverage.summary.trim() || "最近觀測已過期，不能代表當下狀況。";
  }

  const signalText = labels.length ? labels.join("、") : "即時感測";
  const gapText = gaps.length ? `；仍缺 ${gaps.join("、")}。` : "。";
  return `附近有 ${signalText} ${signals.length} 類觀測${nearestText}${gapText}`;
}

function nearbyCoverageNote(
  coverage: NearbyRealtimeCoverage,
  diagnosis: CoverageDiagnosis,
) {
  if (coverage.overall_level === "unavailable") {
    return "附近感測資料暫不可用；不要只用此區塊判斷現地安全。";
  }

  if (diagnosis.sourceIssue === "update_pipeline_stalled") {
    return "更新管線停滯是資料缺口，不代表現地安全；請搭配其他官方資訊判讀。";
  }
  if (diagnosis.sourceIssue === "source_failed") {
    return "來源或更新管線異常是資料缺口，不代表現地安全；請搭配其他官方資訊判讀。";
  }
  if (diagnosis.sourceIssue === "source_degraded") {
    return "來源目前部分可用或更新延遲，缺少觀測不代表現地安全。";
  }
  if (diagnosis.sourceIssue === "source_not_configured") {
    return "必要來源尚未啟用；這是系統覆蓋缺口，不代表現地安全。";
  }
  if (diagnosis.sourceIssue === "jurisdiction_unverified") {
    return "縣市邊界或管轄來源清單尚未驗證；目前沒找到觀測不等於附近真的沒有測站。";
  }
  if (diagnosis.sourceIssue === "inventory_unverified") {
    return "站點清冊完整性尚未驗證；目前沒找到觀測不等於附近真的沒有測站。";
  }
  if (diagnosis.sourceIssue === "health_unknown") {
    return "來源健康狀態目前不明；無法把缺少觀測解讀為附近沒有測站。";
  }

  if (diagnosis.confirmedNoStation) {
    return "範圍內沒有測站只代表感測覆蓋缺口，不代表現地安全。";
  }

  if (coverage.missing_signal_types.length) {
    return "缺口代表本次查詢範圍內沒有取得該類近距觀測，不等於現地安全。";
  }

  return "附近觀測只描述感測覆蓋與新鮮度，不會單獨改變綜合風險。";
}

function hasSignalObservation(
  signal: NearbyRealtimeCoverage["signal_breakdown"][number],
) {
  return (
    signal.nearest_distance_m !== null ||
    signal.fresh_count > 0 ||
    (signal.degraded_count ?? 0) > 0 ||
    signal.stale_count > 0 ||
    signal.status_only_count > 0
  );
}

function signalAvailability(
  signal: CoverageSignal,
): SignalAvailability {
  if (signal.availability_state) return signal.availability_state;
  if (!hasSignalObservation(signal)) return "no_station";
  if (signal.fresh_count + (signal.degraded_count ?? 0) === 0) {
    return "stale_observation";
  }
  if (signal.coverage_level === "no_local_sensor") return "regional_reference";
  return signal.nearest_freshness_state === "degraded"
    ? "degraded_nearby"
    : "fresh_nearby";
}

function primaryMeasurementSignals(coverage: NearbyRealtimeCoverage) {
  const requiredSignals = requiredCoverageSignals.flatMap((signalType) => {
    const signal = coverage.signal_breakdown.find(
      (candidate) => candidate.signal_type === signalType,
    );
    return signal ? [signal] : [];
  });
  if (requiredSignals.length) return requiredSignals;
  return coverage.signal_breakdown.filter((signal) =>
    measurementSignalSet.has(signal.signal_type),
  );
}

function displayMeasurementSignals(coverage: NearbyRealtimeCoverage) {
  const requiredSignals = primaryMeasurementSignals(coverage);
  const optionalObservedSignals = coverage.signal_breakdown
    .filter(
      (signal) =>
        !requiredCoverageSignalSet.has(signal.signal_type) &&
        hasSignalObservation(signal),
    )
    .sort(
      (left, right) =>
        availabilityRank[signalAvailability(right)] -
        availabilityRank[signalAvailability(left)],
    );

  return [...requiredSignals, ...optionalObservedSignals].slice(0, 4);
}

function effectiveMissingCause(signal: CoverageSignal): MissingCause {
  if (signal.missing_cause) return signal.missing_cause;
  const availability = signalAvailability(signal);
  if (availability === "stale_observation") return "stale_observation";
  if (availability === "source_unavailable") return "source_failed";
  if (availability === "source_status_unknown") return "health_unknown";
  if (availability === "no_station") return "no_station_in_range";
  return "none";
}

function sourceHealthIssue(
  source: NonNullable<NearbyRealtimeCoverage["source_health"]>[number],
): SourceIssueCause | null {
  if (source.health_status === "failed") {
    return source.reason_code === "pipeline_stalled"
      ? "update_pipeline_stalled"
      : "source_failed";
  }
  if (source.health_status === "degraded") return "source_degraded";
  if (source.health_status === "disabled") return "source_not_configured";
  if (source.health_status === "unknown") return "health_unknown";
  return null;
}

function strongestSourceIssue(causes: SourceIssueCause[]): SourceIssueCause | null {
  if (!causes.length) return null;
  if (causes.every((cause) => cause === "update_pipeline_stalled")) {
    return "update_pipeline_stalled";
  }
  if (
    causes.some(
      (cause) => cause === "source_failed" || cause === "update_pipeline_stalled",
    )
  ) {
    return "source_failed";
  }
  if (causes.includes("source_degraded")) return "source_degraded";
  if (causes.includes("source_not_configured")) return "source_not_configured";
  if (causes.includes("jurisdiction_unverified")) return "jurisdiction_unverified";
  if (causes.includes("inventory_unverified")) return "inventory_unverified";
  return "health_unknown";
}

function noStationProofIssue(
  coverage: NearbyRealtimeCoverage,
  signal: CoverageSignal,
): SourceIssueCause | null {
  // Legacy payloads only exposed availability_state.  Keep their deliberately
  // generic "data missing" presentation; the stronger proof check applies to
  // the explicit public-health contract.
  if (signal.missing_cause !== "no_station_in_range") return null;
  if (coverage.source_health_checked !== true) return "health_unknown";
  if (
    coverage.jurisdiction_checked !== true ||
    coverage.jurisdiction_catalog_complete !== true ||
    coverage.jurisdiction_unverified_signal_types?.includes(signal.signal_type)
  ) {
    return "jurisdiction_unverified";
  }

  const relevantSources = (coverage.source_health ?? []).filter(
    (source) =>
      source.signal_types.includes(signal.signal_type) &&
      source.required_for_absence !== false,
  );
  if (!relevantSources.length) return "health_unknown";

  const runtimeIssue = strongestSourceIssue(
    relevantSources
      .map(sourceHealthIssue)
      .filter((cause): cause is SourceIssueCause => cause !== null),
  );
  if (runtimeIssue) return runtimeIssue;

  const hasAuditedApplicableInventory = relevantSources.every(
    (source) =>
      source.health_status === "healthy" &&
      source.reason_code === "operational" &&
      source.inventory_complete === true &&
      source.station_count !== null &&
      source.station_count > 0,
  );
  return hasAuditedApplicableInventory ? null : "inventory_unverified";
}

function diagnoseCoverage(coverage: NearbyRealtimeCoverage): CoverageDiagnosis {
  const primarySignals = primaryMeasurementSignals(coverage);
  const states = primarySignals.map(signalAvailability);
  const primarySignalTypes = new Set(primarySignals.map((signal) => signal.signal_type));
  const hasUsableObservation = states.some(
    (state) => state === "fresh_nearby" || state === "degraded_nearby",
  );
  const hasRegionalReference = states.includes("regional_reference");
  const signalIssues = primarySignals
    .map(effectiveMissingCause)
    .filter((cause): cause is SourceIssueCause =>
      [
        "source_degraded",
        "source_failed",
        "update_pipeline_stalled",
        "source_not_configured",
        "jurisdiction_unverified",
        "inventory_unverified",
        "health_unknown",
      ].includes(cause),
    );
  const noStationProofIssues = primarySignals
    .map((signal) => noStationProofIssue(coverage, signal))
    .filter((cause): cause is SourceIssueCause => cause !== null);
  const sourceIssues =
    hasUsableObservation || hasRegionalReference
      ? (coverage.source_health ?? [])
          .filter(
            (source) =>
              source.required_for_absence !== false &&
              source.signal_types.some((signalType) =>
                primarySignalTypes.has(signalType),
              ),
          )
          .map(sourceHealthIssue)
          .filter((cause): cause is SourceIssueCause => cause !== null)
      : [];
  const healthCheckIssue: SourceIssueCause | null =
    (hasUsableObservation || hasRegionalReference) &&
    coverage.source_health_checked !== undefined &&
    (coverage.source_health_checked === false ||
      (coverage.source_health_checked === true &&
        (coverage.source_health ?? []).length === 0))
      ? "health_unknown"
      : null;
  const sourceIssue =
    strongestSourceIssue([...signalIssues, ...noStationProofIssues]) ??
    strongestSourceIssue([
      ...sourceIssues,
      ...(healthCheckIssue ? [healthCheckIssue] : []),
    ]);
  const confirmedNoStation =
    coverage.source_health_checked === true &&
    requiredCoverageSignals.every((signalType) =>
      primarySignalTypes.has(signalType),
    ) &&
    primarySignals.every(
      (signal) =>
        signal.missing_cause === "no_station_in_range" &&
        noStationProofIssue(coverage, signal) === null,
    );

  return {
    confirmedNoStation,
    hasRegionalReference,
    hasUsableObservation,
    isPartial: sourceIssue !== null && (hasUsableObservation || hasRegionalReference),
    sourceIssue,
  };
}

function coverageBadge(
  coverage: NearbyRealtimeCoverage,
  diagnosis: CoverageDiagnosis,
) {
  if (coverage.overall_level === "unavailable") {
    return nearbyCoverageBadge(coverage.overall_level);
  }
  if (diagnosis.sourceIssue) {
    if (diagnosis.isPartial) {
      if (diagnosis.sourceIssue === "source_degraded") {
        return "附近觀測：部分來源受限";
      }
      if (diagnosis.sourceIssue === "health_unknown") {
        return "附近觀測：部分來源狀態不明";
      }
      if (diagnosis.sourceIssue === "jurisdiction_unverified") {
        return "附近觀測：部分管轄待驗證";
      }
      if (diagnosis.sourceIssue === "inventory_unverified") {
        return "附近觀測：部分清冊待驗證";
      }
      return "附近觀測：部分來源異常";
    }
    if (diagnosis.sourceIssue === "update_pipeline_stalled") {
      return "附近觀測：更新管線停滯";
    }
    if (diagnosis.sourceIssue === "source_degraded") {
      return "附近觀測：來源受限";
    }
    if (diagnosis.sourceIssue === "source_not_configured") {
      return "附近觀測：來源未啟用";
    }
    if (diagnosis.sourceIssue === "jurisdiction_unverified") {
      return "附近觀測：管轄來源待驗證";
    }
    if (diagnosis.sourceIssue === "inventory_unverified") {
      return "附近觀測：站點清冊待驗證";
    }
    if (diagnosis.sourceIssue === "health_unknown") {
      return "附近觀測：來源狀態不明";
    }
    return "附近觀測：來源異常";
  }
  if (diagnosis.confirmedNoStation) return "附近觀測：範圍內無站";

  const measurementSignals = primaryMeasurementSignals(coverage);
  const states = new Set(measurementSignals.map(signalAvailability));
  if (states.has("fresh_nearby") || states.has("degraded_nearby")) {
    return nearbyCoverageBadge(coverage.overall_level);
  }
  if (states.has("regional_reference")) return "附近觀測：僅區域參考";
  if (states.has("stale_observation")) return "附近觀測：已過期";
  return "附近觀測：資料不足";
}

const availabilityRank = {
  fresh_nearby: 7,
  degraded_nearby: 6,
  regional_reference: 5,
  stale_observation: 4,
  source_unavailable: 3,
  source_status_unknown: 2,
  no_station: 1,
} satisfies Record<SignalAvailability, number>;

function missingSignalDetail(
  coverage: NearbyRealtimeCoverage,
  signal: CoverageSignal,
  searchRadiusM: number,
) {
  const missingCause = signal.missing_cause
    ? (noStationProofIssue(coverage, signal) ?? effectiveMissingCause(signal))
    : null;
  if (missingCause === "no_station_in_range") {
    return `${formatDistanceMeters(searchRadiusM)}內確認沒有測站`;
  }
  if (missingCause === "update_pipeline_stalled") {
    return "背景更新管線停滯，無法確認附近測站";
  }
  if (missingCause === "source_failed") {
    return "來源或更新管線異常，無法確認附近測站";
  }
  if (missingCause === "source_degraded") {
    return "來源部分可用或更新延遲，無法確認附近測站";
  }
  if (missingCause === "source_not_configured") {
    return "來源尚未啟用，無法確認附近測站";
  }
  if (missingCause === "inventory_unverified") {
    return "來源正常，但站點清冊完整性尚未驗證";
  }
  if (missingCause === "jurisdiction_unverified") {
    return "縣市邊界或管轄來源清單尚未驗證";
  }
  if (missingCause === "health_unknown") {
    return "來源健康狀態不明，無法確認附近測站";
  }
  if (signal.availability_state === "source_unavailable") {
    return "來源或更新管線異常，無法確認附近測站";
  }
  if (signal.availability_state === "source_status_unknown") {
    return "來源健康狀態不明，無法確認附近測站";
  }
  return `${formatDistanceMeters(searchRadiusM)}內未取得觀測`;
}

function signalDetail(
  coverage: NearbyRealtimeCoverage,
  signal: CoverageSignal,
  searchRadiusM: number,
) {
  if (signal.nearest_distance_m === null) {
    return missingSignalDetail(coverage, signal, searchRadiusM);
  }

  const availability = signalAvailability(signal);
  const status =
    availability === "regional_reference"
      ? "僅供區域參考"
      : availability === "fresh_nearby"
        ? "新鮮"
        : availability === "degraded_nearby"
          ? "更新較慢"
          : "已過期";
  const sourceStatus =
    signal.missing_cause === "update_pipeline_stalled"
      ? "；更新管線停滯"
      : signal.missing_cause === "source_failed"
        ? "；來源異常"
        : signal.missing_cause === "source_degraded"
          ? "；來源受限"
          : signal.missing_cause === "health_unknown"
            ? "；來源狀態不明"
            : signal.missing_cause === "jurisdiction_unverified"
              ? "；管轄來源待驗證"
            : signal.missing_cause === "inventory_unverified"
              ? "；站點清冊待驗證"
            : "";
  const observedAt = signal.nearest_observed_at
    ? `；${formatDateTime(signal.nearest_observed_at)}`
    : "";
  return `距查詢點 ${formatDistanceMeters(signal.nearest_distance_m)}；${status}${sourceStatus}${observedAt}`;
}

function legacySourceAvailabilityNote(input: {
  data_freshness?: Array<{ source_id: string; health_status: string }> | null;
}) {
  const sources = input.data_freshness ?? [];
  if (
    sources.length > 0 &&
    sources.every((item) =>
      ["failed", "disabled", "unknown"].includes(item.health_status),
    )
  ) {
    return "本次資料來源均未提供可用狀態；這是資料缺口，不代表現地安全。";
  }
  return null;
}

export function nearbySensingState(input: {
  assessment?: {
    nearby_realtime_coverage?: NearbyRealtimeCoverage | null;
    data_freshness?: Array<{ source_id: string; health_status: string }> | null;
  } | null;
  evidenceItems?: Array<EvidencePreview & { source_id?: string | null }> | null;
}): NearbySensingState {
  const coverage = input.assessment?.nearby_realtime_coverage ?? null;
  if (coverage) {
    const searchRadiusM = Math.max(...coverage.radius_buckets_m, coverage.query_radius_m);
    const diagnosis = diagnoseCoverage(coverage);
    const sourceNote =
      coverage.source_health !== undefined ||
      coverage.source_health_checked !== undefined
        ? null
        : legacySourceAvailabilityNote(input.assessment ?? {});
    const orderedSignals = displayMeasurementSignals(coverage);
    return {
      badge: coverageBadge(coverage, diagnosis),
      gaps: coverage.missing_signal_types.map(nearbySignalLabel),
      items: orderedSignals.map((signal) => ({
        detail: signalDetail(coverage, signal, searchRadiusM),
        id: signal.signal_type,
        label: nearbySignalLabel(signal.signal_type),
      })),
      note: sourceNote ?? nearbyCoverageNote(coverage, diagnosis),
      summary: nearbySensingCoverageSummary(coverage, diagnosis),
      tone:
        diagnosis.sourceIssue === "health_unknown" ||
        diagnosis.sourceIssue === "inventory_unverified" ||
        diagnosis.sourceIssue === "jurisdiction_unverified"
          ? "muted"
          : diagnosis.sourceIssue
            ? "warn"
            : coverageTone(coverage.overall_level),
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
      badge: "附近觀測：資料不足",
      gaps: ["雨量", "水位"],
      items: [],
      note: "資料不足代表本次回應沒有可列出的近距即時感測；不等於現地安全。",
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
      detail: `距查詢點 ${formatDistance(item.distance_to_query_m)}；觀測 ${formatDateTime(item.observed_at)}`,
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
