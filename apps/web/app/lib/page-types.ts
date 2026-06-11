import type { EvidenceItem, EvidencePreview, LayerContractItem } from "./risk-display";

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
    message: string | null;
  }>;
  query_heat: {
    attention_level: string;
    updated_at: string;
  };
  layers?: LayerContractItem[];
  map_layers?: LayerContractItem[];
};
