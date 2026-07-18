import type {
  DataFreshnessItem,
  EvidenceItem,
  LayerContractItem,
  LayerDisplayItem,
  LayerDisplayState,
  SourceHealthSummary,
} from "./types";

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
