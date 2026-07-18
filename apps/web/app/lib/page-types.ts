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

export type PublicRealtimeSourceHealth = {
  source_id: string;
  name: string;
  signal_types: NearbyCoverageSignalType[];
  coverage_scope: "national" | "local";
  health_status: "healthy" | "degraded" | "failed" | "disabled" | "unknown";
  reason_code:
    | "operational"
    | "delayed"
    | "upstream_unavailable"
    | "pipeline_unavailable"
    | "pipeline_stalled"
    | "disabled"
    | "not_yet_observed";
  observed_at: string | null;
  checked_at: string | null;
  station_count: number | null;
  upstream_station_count?: number | null;
  pages_fetched?: number | null;
  pagination_complete?: boolean | null;
  inventory_manifest_sha256?: string | null;
  inventory_proof_status?:
    | "missing"
    | "incomplete"
    | "awaiting_review"
    | "checksum_mismatch"
    | "approved";
  inventory_complete?: boolean;
  jurisdictions?: string[];
  required_for_absence?: boolean;
  message: string;
};

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
    availability_state?:
      | "fresh_nearby"
      | "degraded_nearby"
      | "regional_reference"
      | "stale_observation"
      | "source_unavailable"
      | "source_status_unknown"
      | "no_station";
    nearest_distance_m: number | null;
    nearest_source_id: string | null;
    nearest_observed_at: string | null;
    counts_by_radius_m: Record<string, number>;
    fresh_count: number;
    degraded_count?: number;
    stale_count: number;
    status_only_count: number;
    nearest_freshness_state?: "fresh" | "degraded" | "stale" | null;
    source_health_status?: "healthy" | "degraded" | "failed" | "disabled" | "unknown";
    source_count?: number;
    failed_source_count?: number;
    missing_cause?:
      | "none"
      | "no_station_in_range"
      | "inventory_unverified"
      | "stale_observation"
      | "source_degraded"
      | "source_failed"
      | "update_pipeline_stalled"
      | "source_not_configured"
      | "jurisdiction_unverified"
      | "health_unknown";
    missing_reason: string | null;
  }>;
  missing_signal_types: NearbyCoverageSignalType[];
  limitations: string[];
  source_health?: PublicRealtimeSourceHealth[];
  source_health_status?: "healthy" | "degraded" | "failed" | "disabled" | "unknown";
  source_health_checked?: boolean;
  jurisdiction_status?:
    | "verified"
    | "boundary_unverified"
    | "outside_coverage"
    | "ambiguous"
    | "unavailable";
  jurisdiction_checked?: boolean;
  jurisdiction_catalog_complete?: boolean;
  home_jurisdiction?: string | null;
  considered_jurisdictions?: string[];
  jurisdiction_mapping_revisions?: string[];
  jurisdiction_unverified_signal_types?: NearbyCoverageSignalType[];
  county_level_note: string;
};

export type RiskAssessmentResponse = {
  assessment_id: string;
  radius_m: number;
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
