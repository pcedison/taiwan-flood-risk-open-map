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
  | "repository_unavailable"
  | "error";

export type UserReportSubmissionDisplayState = {
  kind: "neutral" | "loading" | "success" | "warning" | "error";
  message: string | null;
  submitLabel: string;
};

export function formatCoordinate(value: number) {
  return value.toFixed(5);
}

export function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function formatDistance(value: number | null) {
  return value === null ? "未提供" : `${Math.round(value).toLocaleString("zh-TW")} 公尺`;
}

export function formatDateTime(value: string | null, options?: { timeZone?: string }) {
  if (!value) return "未提供";
  return new Intl.DateTimeFormat("zh-TW", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
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
