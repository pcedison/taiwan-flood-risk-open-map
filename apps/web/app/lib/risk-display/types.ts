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

export type NearbyCoverageSummaryState = {
  badge: string;
  tone: "good" | "warn" | "poor" | "muted";
  summary: string;
};

export type NewsEvidenceLink = {
  id: string;
  title: string;
  url: string;
  time: string | null;
};

export type EvidenceDisplayText = {
  purpose: string;
  title: string;
  summary: string;
};
