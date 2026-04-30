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

export function formatCoordinate(value: number) {
  return value.toFixed(5);
}

export function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function formatDistance(value: number | null) {
  return value === null ? "未提供" : `${Math.round(value).toLocaleString("zh-TW")} m`;
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

export function buildRiskAssessmentPayload(
  coordinate: Coordinate,
  radius: number,
  locationText: string,
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

function evidenceCountForSource(evidenceItems: EvidenceItem[], sourceId: string) {
  return evidenceItems.filter((item) => item.source_id === sourceId).length;
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
        kind: item.kind ?? item.type ?? "tile",
        message: item.message ?? null,
        name: item.name,
        status: item.status ?? item.health_status ?? "unknown",
        tileUrl: item.tile_url ?? null,
      }))
    : dataFreshness.map((item) => ({
        availability: normalizeLayerAvailability(item),
        featureCount: evidenceCountForSource(evidenceItems, item.source_id),
        freshnessAt: item.observed_at ?? item.ingested_at,
        id: item.source_id,
        kind: "evidence",
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
