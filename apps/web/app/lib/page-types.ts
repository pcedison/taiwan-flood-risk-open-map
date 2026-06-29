import type {
  EvidenceItem,
  EvidencePreview,
  LayerContractItem,
} from "./risk-display";

export type CoordinateSource = "default" | "map" | "search";
export type QueryMode = "map" | "search";

export type Coordinate = {
  lat: number;
  lng: number;
  source: CoordinateSource;
};

export type GeocodeResponse = {
  candidates: Array<{
    confidence: number;
    limitations?: string[];
    matched_query?: string | null;
    name: string;
    point: {
      lat: number;
      lng: number;
    };
    precision?: "exact_address" | "road_or_lane" | "poi" | "admin_area" | "map_click" | "unknown";
    requires_confirmation?: boolean;
    source: string;
  }>;
};

export type GeocodeCandidate = GeocodeResponse["candidates"][number];

export type EvidenceListResponse = {
  assessment_id: string;
  items: EvidenceItem[];
  next_cursor: string | null;
};

export type NearbyCoverageLevel =
  | "high"
  | "medium"
  | "low"
  | "no_local_sensor"
  | "unavailable";

export type NearbyCoverageSignalType =
  | "rainfall"
  | "water_level"
  | "flood_depth"
  | "sewer_water_level"
  | "pump_or_gate_status"
  | "flood_warning"
  | "status_only";

export type NearbyRealtimeCoverage = {
  overall_level: NearbyCoverageLevel;
  evaluated_at: string;
  query_radius_m: number;
  radius_buckets_m: number[];
  summary: string;
  signal_breakdown: Array<{
    signal_type: NearbyCoverageSignalType;
    label: string;
    coverage_level: NearbyCoverageLevel;
    nearest_distance_m: number | null;
    nearest_source_id: string | null;
    nearest_observed_at: string | null;
    counts_by_radius_m: Record<string, number>;
    fresh_count: number;
    stale_count: number;
    status_only_count: number;
    missing_reason: string | null;
  }>;
  missing_signal_types: NearbyCoverageSignalType[];
  limitations: string[];
  county_level_note: string;
};

export type RiskAssessmentResponse = {
  assessment_id: string;
  realtime: {
    level: string;
  };
  historical: {
    level: string;
  };
  confidence: {
    level: string;
  };
  explanation: {
    summary: string;
    main_reasons: string[];
    missing_sources: string[];
  };
  evidence: EvidencePreview[];
  data_freshness: Array<{
    source_id: string;
    name: string;
    health_status: string;
    observed_at: string | null;
    ingested_at: string | null;
    feature_count?: number | null;
    message: string | null;
  }>;
  query_heat: {
    attention_level: string;
    updated_at: string;
  };
  nearby_realtime_coverage: NearbyRealtimeCoverage;
  layers?: LayerContractItem[];
  map_layers?: LayerContractItem[];
};
