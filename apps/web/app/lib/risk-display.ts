// This module is a barrel re-export. The implementation lives in
// ./risk-display/* split by concern (types, formatting, risk levels,
// evidence, nearby coverage, map layers, profile previews, report payloads).
// Keep this file's public surface identical to the pre-split module: every
// name below was previously exported directly from this file.

export type {
  Coordinate,
  DataFreshnessItem,
  EvidenceDisplayText,
  EvidenceItem,
  EvidencePreview,
  EvidenceStatus,
  LayerContractItem,
  LayerDisplayItem,
  LayerDisplayState,
  NearbyCoverageSummaryState,
  NearbySensingState,
  NewsEvidenceLink,
  ProfileBasisText,
  ProfilePreviewState,
  RiskDecisionSummary,
  RiskOverlayPresentation,
  SourceHealthSummary,
  UserReportPayload,
  UserReportPayloadState,
  UserReportSubmissionDisplayState,
  UserReportSubmissionStatus,
} from "./risk-display/types.ts";

export {
  formatConfidence,
  formatCoordinate,
  formatDateTime,
  formatDistance,
  formatDistanceMeters,
} from "./risk-display/format.ts";

export {
  UNKNOWN_RISK_LEVEL,
  combinedRiskLevel,
  normalizeRiskLevel,
  riskDecisionSummary,
  riskLevelRank,
  riskLevelTextColor,
  riskOverlayPresentation,
  riskSummaryBasis,
  riskSummaryDecisionText,
  riskSummaryTitle,
} from "./risk-display/risk.ts";

export {
  evidenceDisplayText,
  evidencePublishedAt,
  evidenceSourceUrl,
  evidenceTimeSummary,
  getEvidenceDisplayState,
  hiddenHistoricalNewsCount,
  isHistoricalNewsEvidence,
  isHistoricalNewsFreshness,
  isSafeLinkUrl,
  latestNewsEvidenceLinks,
  latestNewsLinksFreshnessSourceId,
  publicDataFreshnessItems,
  publicEvidenceDisplayItems,
  selectEvidenceItems,
  shouldFetchEvidenceList,
} from "./risk-display/evidence.ts";

export {
  nearbyCoverageLevelLabel,
  nearbyCoverageSummary,
  nearbySensingState,
} from "./risk-display/coverage.ts";

export {
  buildLayerDisplayState,
  layerAvailabilityDisplayLabel,
  sourceHealthSummaryState,
} from "./risk-display/layers.ts";

export { getProfileBasisText, getProfilePreviewState } from "./risk-display/profile.ts";

export {
  buildRiskAssessmentPayload,
  buildUserReportPayload,
  getUserReportSubmissionDisplayState,
} from "./risk-display/reports.ts";
