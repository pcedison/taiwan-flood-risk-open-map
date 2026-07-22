import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type {
  NearbyRealtimeCoverage,
  PublicRealtimeSourceHealth,
} from "../../app/lib/page-types";
import type { EvidenceItem, EvidencePreview } from "../../app/lib/risk-display";

type CoverageSignalType =
  NearbyRealtimeCoverage["signal_breakdown"][number]["signal_type"];

const riskDisplayModulePath = "../../app/lib/risk-display.ts";
const {
  buildRiskAssessmentPayload,
  buildLayerDisplayState,
  buildUserReportPayload,
  combinedRiskLevel,
  evidenceDisplayText,
  evidencePublishedAt,
  evidenceSourceUrl,
  formatConfidence,
  isSafeLinkUrl,
  formatCoordinate,
  formatDateTime,
  formatDistance,
  formatDistanceMeters,
  getEvidenceDisplayState,
  getProfileBasisText,
  getProfilePreviewState,
  getUserReportSubmissionDisplayState,
  hiddenHistoricalNewsCount,
  layerAvailabilityDisplayLabel,
  latestNewsEvidenceLinks,
  latestNewsLinksFreshnessSourceId,
  nearbyCoverageLevelLabel,
  nearbyCoverageSummary,
  nearbySensingState,
  normalizeRiskLevel,
  publicDataFreshnessItems,
  publicEvidenceDisplayItems,
  riskDecisionSummary,
  riskOverlayPresentation,
  riskSummaryDecisionText,
  riskSummaryBasis,
  riskSummaryTitle,
  selectEvidenceItems,
  shouldFetchEvidenceList,
  sourceHealthSummaryState,
} = (await import(riskDisplayModulePath)) as typeof import("../../app/lib/risk-display");
const uiTextSource = readFileSync(new URL("../../app/lib/ui-text.ts", import.meta.url), "utf8");

const previewEvidence: EvidencePreview = {
  confidence: 0.812,
  distance_to_query_m: 1234.49,
  event_type: "flood",
  id: "preview-1",
  ingested_at: "2026-04-30T02:00:00+08:00",
  observed_at: "2026-04-30T01:30:00+08:00",
  occurred_at: "2026-04-30T01:00:00+08:00",
  source_type: "official",
  source_url: "https://example.test/source",
  summary: "Preview summary",
  title: "Preview evidence",
};

const fullEvidence: EvidenceItem = {
  ...previewEvidence,
  id: "full-1",
  published_at: "2026-04-30T01:45:00+08:00",
  source_id: "rain-gauge",
  url: "https://example.test/full",
};

function missingRainfallCoverage(input: {
  availabilityState:
    | "no_station"
    | "source_unavailable"
    | "source_status_unknown";
  missingCause:
    | "no_station_in_range"
    | "source_degraded"
    | "source_failed"
    | "update_pipeline_stalled"
    | "source_not_configured"
    | "inventory_unverified"
    | "health_unknown";
  sourceHealth?: PublicRealtimeSourceHealth;
  sourceHealthChecked?: boolean;
  jurisdictionVerified?: boolean;
}): NearbyRealtimeCoverage {
  const jurisdictionVerified = input.jurisdictionVerified ?? true;
  return {
    county_level_note: "縣市資料源不代表近距觀測。",
    evaluated_at: "2026-07-18T08:00:00Z",
    limitations: [],
    missing_signal_types: ["rainfall"],
    overall_level: "no_local_sensor",
    jurisdiction_status: jurisdictionVerified ? "verified" : "boundary_unverified",
    jurisdiction_checked: jurisdictionVerified,
    jurisdiction_catalog_complete: jurisdictionVerified,
    home_jurisdiction: jurisdictionVerified ? "臺北市" : null,
    considered_jurisdictions: jurisdictionVerified ? ["臺北市", "新北市"] : [],
    jurisdiction_mapping_revisions: jurisdictionVerified
      ? ["official-source-catalog-v1"]
      : [],
    jurisdiction_unverified_signal_types: jurisdictionVerified ? [] : ["rainfall"],
    query_radius_m: 500,
    radius_buckets_m: [500, 1000, 3000, 5000, 10000, 15000],
    signal_breakdown: [
      {
        availability_state: input.availabilityState,
        counts_by_radius_m: { "500": 0, "15000": 0 },
        coverage_level: "no_local_sensor",
        degraded_count: 0,
        failed_source_count:
          input.sourceHealth?.health_status === "failed" ? 1 : 0,
        fresh_count: 0,
        label: "雨量",
        missing_cause: input.missingCause,
        missing_reason: "公開安全的缺口說明。",
        nearest_distance_m: null,
        nearest_freshness_state: null,
        nearest_observed_at: null,
        nearest_source_id: null,
        signal_type: "rainfall",
        source_count: input.sourceHealth ? 1 : 0,
        source_health_status: input.sourceHealth?.health_status ?? "unknown",
        stale_count: 0,
        status_only_count: 0,
      },
    ],
    source_health: input.sourceHealth ? [input.sourceHealth] : [],
    source_health_checked: input.sourceHealthChecked ?? true,
    source_health_status: input.sourceHealth?.health_status ?? "unknown",
    summary: "後端覆蓋摘要。",
  };
}

function realtimeSourceHealth(
  overrides: Partial<PublicRealtimeSourceHealth> = {},
): PublicRealtimeSourceHealth {
  return {
    checked_at: "2026-07-18T08:00:00Z",
    coverage_scope: "national",
    health_status: "healthy",
    message: "來源運作正常。",
    name: "公開雨量來源",
    observed_at: "2026-07-18T07:55:00Z",
    reason_code: "operational",
    signal_types: ["rainfall"],
    source_id: "internal-source-id-must-not-render",
    station_count: 42,
    inventory_complete: true,
    ...overrides,
  };
}

test("buildRiskAssessmentPayload shapes the risk API request", () => {
  assert.deepEqual(
    buildRiskAssessmentPayload({ lat: 25.04776, lng: 121.51706 }, 500, "台北車站"),
    {
      location_text: "台北車站",
      point: {
        lat: 25.04776,
        lng: 121.51706,
      },
      radius_m: 500,
      time_context: "now",
    },
  );
});

test("buildUserReportPayload trims summary and shapes the public report request", () => {
  assert.deepEqual(buildUserReportPayload({ lat: 25.033, lng: 121.5654 }, "  Water over curb.  "), {
    isValid: true,
    payload: {
      point: {
        lat: 25.033,
        lng: 121.5654,
      },
      summary: "Water over curb.",
    },
    summary: "Water over curb.",
    validationMessage: null,
  });
});

test("buildUserReportPayload marks blank summaries invalid", () => {
  assert.deepEqual(buildUserReportPayload({ lat: 25.033, lng: 121.5654 }, "   "), {
    isValid: false,
    payload: null,
    summary: "",
    validationMessage: "summary_required",
  });
});

test("user report display state covers success and disabled/error gates", () => {
  assert.deepEqual(getUserReportSubmissionDisplayState("success"), {
    kind: "success",
    message: "通報已收到，等待審核。",
    submitLabel: "送出通報",
  });

  assert.deepEqual(getUserReportSubmissionDisplayState("feature_disabled"), {
    kind: "warning",
    message: "此環境目前停用民眾通報功能。",
    submitLabel: "送出通報",
  });

  assert.deepEqual(getUserReportSubmissionDisplayState("repository_unavailable"), {
    kind: "error",
    message: "通報收件暫時無法使用。",
    submitLabel: "送出通報",
  });

  assert.deepEqual(getUserReportSubmissionDisplayState("rate_limited"), {
    kind: "warning",
    message: "通報送出太頻繁，請稍後再試。",
    submitLabel: "送出通報",
  });

  assert.deepEqual(getUserReportSubmissionDisplayState("error"), {
    kind: "error",
    message: "通報送出失敗。",
    submitLabel: "送出通報",
  });
});

test("evidence URL and published-at shaping prefer full-list fields", () => {
  assert.equal(evidenceSourceUrl(fullEvidence), "https://example.test/full");
  assert.equal(evidencePublishedAt(fullEvidence), "2026-04-30T01:45:00+08:00");

  assert.equal(evidenceSourceUrl(previewEvidence), "https://example.test/source");
  assert.equal(evidencePublishedAt(previewEvidence), "2026-04-30T01:00:00+08:00");
});

test("evidenceSourceUrl rejects unsafe href schemes so no anchor is rendered", () => {
  const javascriptSchemeEvidence: EvidenceItem = {
    ...fullEvidence,
    id: "unsafe-1",
    url: "javascript:alert(1)",
  };
  const dataSchemeEvidence: EvidenceItem = {
    ...fullEvidence,
    id: "unsafe-2",
    url: "data:text/html,<script>alert(1)</script>",
  };

  assert.equal(evidenceSourceUrl(javascriptSchemeEvidence), null);
  assert.equal(evidenceSourceUrl(dataSchemeEvidence), null);

  assert.equal(isSafeLinkUrl("javascript:alert(1)"), false);
  assert.equal(isSafeLinkUrl("data:text/html,evil"), false);
  assert.equal(isSafeLinkUrl("https://example.test/safe"), true);
  assert.equal(isSafeLinkUrl("http://example.test/safe"), true);
  assert.equal(isSafeLinkUrl(null), false);
});

test("latestNewsEvidenceLinks returns newest linked news first", () => {
  const oldLinkedNews: EvidencePreview = {
    ...previewEvidence,
    id: "news-old",
    occurred_at: "2024-07-25T10:00:00+08:00",
    source_type: "news",
    source_url: "https://example.test/old-news",
    title: "Old flood news",
  };
  const newLinkedNews: EvidencePreview = {
    ...previewEvidence,
    id: "news-new",
    occurred_at: "2025-08-02T08:00:00+08:00",
    source_type: "news",
    source_url: "https://example.test/new-news",
    title: "New flood news",
  };
  const unlinkedNews: EvidencePreview = {
    ...previewEvidence,
    id: "news-missing-url",
    occurred_at: "2026-01-01T08:00:00+08:00",
    source_type: "news",
    source_url: null,
    title: "Unlinked flood news",
  };

  assert.deepEqual(latestNewsEvidenceLinks([oldLinkedNews, previewEvidence, unlinkedNews, newLinkedNews], 2), [
    {
      id: "news-new",
      time: "2025-08-02T08:00:00+08:00",
      title: "New flood news",
      url: "https://example.test/new-news",
    },
    {
      id: "news-old",
      time: "2024-07-25T10:00:00+08:00",
      title: "Old flood news",
      url: "https://example.test/old-news",
    },
  ]);
});

test("evidence full-list selection falls back to preview items", () => {
  assert.deepEqual(selectEvidenceItems([previewEvidence], [], "loading"), [previewEvidence]);
  assert.deepEqual(selectEvidenceItems([previewEvidence], [], "error"), [previewEvidence]);
  assert.deepEqual(selectEvidenceItems([previewEvidence], [], "ready"), []);
  assert.deepEqual(selectEvidenceItems([previewEvidence], [fullEvidence], "ready"), [fullEvidence]);
  assert.equal(shouldFetchEvidenceList("assessment-123"), true);
  assert.equal(shouldFetchEvidenceList(""), false);
  assert.equal(shouldFetchEvidenceList(null), false);
});

test("evidence display state distinguishes loading, error, list, and empty states", () => {
  assert.deepEqual(getEvidenceDisplayState("loading", 0), {
    showEmpty: false,
    showError: false,
    showList: false,
    showLoading: true,
  });

  assert.deepEqual(getEvidenceDisplayState("error", 1), {
    showEmpty: false,
    showError: true,
    showList: true,
    showLoading: false,
  });

  assert.deepEqual(getEvidenceDisplayState("ready", 0), {
    showEmpty: true,
    showError: false,
    showList: false,
    showLoading: false,
  });
});

test("profile preview state labels precomputed profile responses", () => {
  const state = getProfilePreviewState({
    data_freshness: [
      {
        health_status: "healthy",
        ingested_at: "2026-05-08T03:00:00Z",
        message: "已使用預先計算的 risk_grid:h3:8 profile。",
        name: "預先計算區域風險 profile",
        observed_at: null,
        source_id: "precomputed-risk-profile",
      },
    ],
    explanation: {
      summary: "此結果先使用預先計算的區域風險 profile 回應。",
    },
  });

  assert.equal(state.isProfilePreview, true);
  assert.equal(state.label, "區域概略估計");
  assert.match(state.message ?? "", /risk_grid:h3:8/);

  assert.deepEqual(getProfilePreviewState({ data_freshness: [] }), {
    isProfilePreview: false,
    label: null,
    message: null,
  });
});

test("profile basis text explains historical and confidence cards", () => {
  const state = getProfileBasisText({
    data_freshness: [
      {
        health_status: "healthy",
        ingested_at: "2026-05-08T03:00:00Z",
        message: "profile freshness",
        name: "預先計算區域風險 profile",
        observed_at: null,
        source_id: "precomputed-risk-profile",
      },
    ],
    evidence: [previewEvidence],
    explanation: {
      main_reasons: ["歷史參考來自 profile 彙整的 3 筆公開資料：官方淹水潛勢資料 1 筆、新聞淹水事件資料 2 筆"],
    },
  });

  assert.match(state.historicalNote ?? "", /3 筆公開資料/);
  assert.doesNotMatch((state.historicalNote ?? "").toLowerCase(), /profile/);
  assert.match(state.confidenceNote ?? "", /來源類型/);
  assert.match(state.confidenceNote ?? "", /不代表淹水機率/);
  assert.match(state.limitationLead ?? "", /不是系統錯誤/);

  assert.deepEqual(getProfileBasisText({ data_freshness: [] }), {
    confidenceNote: null,
    historicalNote: null,
    limitationLead: null,
  });
});

test("combined risk display separates summary from source basis", () => {
  assert.equal(combinedRiskLevel("未知", "高"), "高");
  assert.equal(riskSummaryTitle("未知", "高"), "綜合風險：高");
  assert.equal(riskSummaryBasis("未知", "高"), "即時：未知；歷史參考：高");
  assert.equal(normalizeRiskLevel("low"), "低");
  assert.equal(normalizeRiskLevel("medium"), "中");
  assert.equal(normalizeRiskLevel("very_high"), "極高");
  assert.equal(combinedRiskLevel("low", "medium"), "中");
  assert.equal(riskSummaryTitle("low", "medium"), "綜合風險：中");
  assert.equal(riskSummaryBasis("low", "medium"), "即時：低；歷史參考：中");
  assert.match(
    riskSummaryDecisionText({
      confidenceLevel: "中",
      historicalLevel: "高",
      realtimeLevel: "未知",
    }),
    /由歷史事件或淹水潛勢參考主導/,
  );
  assert.deepEqual(
    riskDecisionSummary({
      confidenceLevel: "中",
      historicalLevel: "高",
      realtimeLevel: "未知",
    }),
    {
      confidence: "資料可信度：中",
      driver: "主導：歷史參考",
      method: "取即時/歷史較高",
      narrative: "本次採歷史參考，因歷史參考（高）高於即時（未知）。",
    },
  );

  const highOverlay = riskOverlayPresentation("高", true);
  assert.equal(highOverlay.colorName, "紅色");
  assert.equal(highOverlay.fillOpacity, 0.85);

  const englishHighOverlay = riskOverlayPresentation("high", true);
  assert.equal(englishHighOverlay.level, "高");
  assert.equal(englishHighOverlay.colorName, "紅色");

  const idleOverlay = riskOverlayPresentation(null, false);
  assert.equal(idleOverlay.level, "未知");
  assert.equal(idleOverlay.fillOpacity, 0.18);
});

test("risk decision copy explains realtime is not only current rainfall", () => {
  const decision = riskDecisionSummary({
    confidenceLevel: "high",
    historicalLevel: "low",
    realtimeLevel: "very_high",
  });

  assert.equal(decision.driver, "主導：即時主導");
  assert.equal(decision.confidence, "資料可信度：高");
  assert.match(decision.narrative, /即時不是只代表正在下雨/);

  const methodText = riskSummaryDecisionText({
    confidenceLevel: "high",
    historicalLevel: "low",
    realtimeLevel: "very_high",
  });
  assert.match(methodText, /近期雨量、水位、官方警戒、通報或區域即時 profile/);
  assert.match(methodText, /資料可信度（高）只描述證據可靠度，不代表淹水機率/);
});

test("public evidence display hides historical news and keeps official signals first", () => {
  const newsEvidence: EvidenceItem = {
    ...fullEvidence,
    id: "news-hidden",
    source_id: "news:stored",
    source_type: "news",
    title: "歷史新聞",
  };
  const rainfallEvidence: EvidenceItem = {
    ...fullEvidence,
    event_type: "rainfall",
    id: "rainfall",
    source_id: "cwa-rainfall",
    source_type: "official",
    title: "CWA 雨量站",
  };

  assert.deepEqual(publicEvidenceDisplayItems([newsEvidence, fullEvidence, rainfallEvidence]), [
    rainfallEvidence,
    fullEvidence,
  ]);
  assert.equal(hiddenHistoricalNewsCount([newsEvidence, rainfallEvidence]), 1);
  assert.deepEqual(
    publicDataFreshnessItems([
      {
        health_status: "healthy",
        ingested_at: "2026-05-13T03:50:00Z",
        message: "已從公開新聞/百科索引補查並整理 2 筆候選淹水事件。",
        name: "公開新聞即時補查",
        observed_at: "2026-04-23T02:28:00Z",
        source_id: "on-demand-public-news",
      },
      {
        health_status: "healthy",
        ingested_at: "2026-05-13T04:20:00Z",
        message: "來源可用。",
        name: "中央氣象署即時雨量",
        observed_at: "2026-05-13T04:20:00Z",
        source_id: "cwa-rainfall",
      },
    ]).map((item) => item.source_id),
    ["cwa-rainfall"],
  );
});

test("evidence display text normalizes official realtime raw titles", () => {
  const rainfallEvidence: EvidenceItem = {
    ...fullEvidence,
    event_type: "rainfall",
    source_id: "cwa-rainfall",
    source_type: "official",
    summary: "Raw CWA rainfall summary from backend.",
    title: "Raw CWA rainfall station title",
  };
  const forumEvidence: EvidenceItem = {
    ...fullEvidence,
    event_type: "discussion",
    source_id: "community-report",
    source_type: "forum",
    summary: "Community report summary",
    title: "公開討論淹水線索",
  };

  assert.deepEqual(evidenceDisplayText(rainfallEvidence), {
    purpose: "用途：即時雨量",
    summary: "附近即時雨量觀測可輔助判讀當下降雨壓力。",
    title: "雨量觀測",
  });
  assert.doesNotMatch(evidenceDisplayText(rainfallEvidence).title, /Raw|CWA|backend/i);
  assert.doesNotMatch(evidenceDisplayText(rainfallEvidence).summary, /Raw|backend/i);
  assert.deepEqual(evidenceDisplayText(forumEvidence), {
    purpose: "用途：補充線索",
    summary: "Community report summary",
    title: "公開討論淹水線索",
  });
});

test("nearby sensing state prefers backend coverage and falls back to realtime evidence", () => {
  const fromCoverage = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: {
        county_level_note: "縣市級 coverage catalog 只作背景。",
        evaluated_at: "2026-06-29T12:00:00Z",
        limitations: ["Backend technical coverage limitation."],
        missing_signal_types: ["flood_depth"],
        overall_level: "medium",
        query_radius_m: 500,
        radius_buckets_m: [500, 1000, 3000, 5000],
        signal_breakdown: [
          {
            counts_by_radius_m: { "500": 0, "1000": 1 },
            coverage_level: "medium",
            fresh_count: 1,
            label: "Rainfall sensor",
            missing_reason: null,
            nearest_distance_m: 820,
            nearest_observed_at: "2026-06-29T11:55:00Z",
            nearest_source_id: "cwa-rainfall:001",
            signal_type: "rainfall",
            stale_count: 0,
            status_only_count: 0,
          },
        ],
        summary: "Backend raw English summary.",
      },
    },
    evidenceItems: [],
  });
  assert.equal(fromCoverage.badge, "附近觀測：中");
  assert.deepEqual(fromCoverage.gaps, ["淹水深度"]);
  assert.equal(fromCoverage.items[0].label, "雨量");
  assert.equal(
    fromCoverage.summary,
    "附近有 雨量 1 類觀測；最近觀測距查詢點 820 公尺；仍缺 淹水深度。",
  );
  assert.match(fromCoverage.items[0].detail, /^距查詢點 820 公尺；新鮮/);
  assert.equal(
    fromCoverage.note,
    "缺口代表本次查詢範圍內沒有取得該類近距觀測，不等於現地安全。",
  );
  assert.doesNotMatch(fromCoverage.summary, /Backend|English/);
  assert.doesNotMatch(fromCoverage.note, /Backend|technical/);

  const fromEvidence = nearbySensingState({
    assessment: {},
    evidenceItems: [
      {
        ...fullEvidence,
        distance_to_query_m: 260,
        event_type: "rainfall",
        source_id: "cwa-rainfall",
        source_type: "official",
        title: "CWA 雨量站",
      },
    ],
  });
  assert.equal(fromEvidence.badge, "附近觀測：中");
  assert.deepEqual(fromEvidence.gaps, ["水位"]);
  assert.match(fromEvidence.summary, /可用即時觀測/);
  assert.match(fromEvidence.items[0].detail, /^距查詢點 260 公尺；觀測 /);
});

test("right panel labels distinguish distance and source confidence", () => {
  assert.match(uiTextSource, /evidenceDistance:\s*"距查詢點"/);
  assert.match(uiTextSource, /evidenceConfidence:\s*"來源可信度"/);
  assert.match(uiTextSource, /evidenceScopeNote:[\s\S]*不是淹水機率/);
  assert.match(uiTextSource, /nearbySensingQuestion:.*距離是感測器到查詢點/);
});

test("nearby sensing state never presents missing observations as low", () => {
  const signal = (signal_type: "rainfall" | "water_level" | "flood_depth" | "sewer_water_level", label: string) => ({
    availability_state: "no_station" as const,
    counts_by_radius_m: { "500": 0, "5000": 0, "15000": 0 },
    coverage_level: "no_local_sensor" as const,
    degraded_count: 0,
    fresh_count: 0,
    label,
    missing_reason: `15 公里內沒有${label}`,
    nearest_distance_m: null,
    nearest_freshness_state: null,
    nearest_observed_at: null,
    nearest_source_id: null,
    signal_type,
    stale_count: 0,
    status_only_count: 0,
  });
  const state = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: {
        county_level_note: "縣市資料源不代表近距觀測。",
        evaluated_at: "2026-07-18T07:22:00Z",
        limitations: [],
        missing_signal_types: [
          "rainfall",
          "water_level",
          "flood_depth",
          "sewer_water_level",
        ],
        overall_level: "no_local_sensor",
        query_radius_m: 500,
        radius_buckets_m: [500, 1000, 3000, 5000, 10000, 15000],
        signal_breakdown: [
          signal("rainfall", "雨量"),
          signal("water_level", "水位"),
          signal("flood_depth", "淹水深度"),
          signal("sewer_water_level", "下水道水位"),
        ],
        summary: "目前沒有可用的近距離即時感測資料。",
      },
    },
    evidenceItems: [],
  });

  assert.equal(state.badge, "附近觀測：資料不足");
  assert.doesNotMatch(state.badge, /低/);
  assert.deepEqual(state.gaps, ["雨量", "水位", "淹水深度", "下水道水位"]);
  assert.equal(state.items[0].detail, "15 公里內未取得觀測");
});

test("nearby sensing state prioritizes regional reference over stale observations", () => {
  const state = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: {
        county_level_note: "縣市資料源不代表近距觀測。",
        evaluated_at: "2026-07-18T07:22:00Z",
        limitations: [],
        missing_signal_types: ["rainfall", "water_level"],
        overall_level: "no_local_sensor",
        query_radius_m: 500,
        radius_buckets_m: [500, 1000, 3000, 5000, 10000, 15000],
        signal_breakdown: [
          {
            availability_state: "regional_reference",
            counts_by_radius_m: { "5000": 0, "10000": 1 },
            coverage_level: "no_local_sensor",
            degraded_count: 0,
            fresh_count: 1,
            label: "雨量",
            missing_reason: "最近站僅供區域參考",
            nearest_distance_m: 7200,
            nearest_freshness_state: "fresh",
            nearest_observed_at: "2026-07-18T07:20:00Z",
            nearest_source_id: "cwa-rainfall:regional",
            signal_type: "rainfall",
            stale_count: 0,
            status_only_count: 0,
          },
          {
            availability_state: "stale_observation",
            counts_by_radius_m: { "1000": 1 },
            coverage_level: "no_local_sensor",
            degraded_count: 0,
            fresh_count: 0,
            label: "水位",
            missing_reason: "只有過期資料",
            nearest_distance_m: 900,
            nearest_freshness_state: "stale",
            nearest_observed_at: "2026-07-17T07:20:00Z",
            nearest_source_id: "wra-water-level:stale",
            signal_type: "water_level",
            stale_count: 1,
            status_only_count: 0,
          },
        ],
        summary: "5 公里內缺少直接水情觀測；15 公里內有較遠測站可作區域參考。",
      },
    },
    evidenceItems: [],
  });

  assert.equal(state.badge, "附近觀測：僅區域參考");
  assert.match(state.items[0].detail, /7.2 公里；僅供區域參考/);
  assert.match(state.items[1].detail, /900 公尺；已過期/);
});

test("contradictory no-station payload is downgraded when complementary sources fail", () => {
  const healthyNational = realtimeSourceHealth({
    name: "中央氣象署即時雨量",
  });
  const coverage = missingRainfallCoverage({
    availabilityState: "no_station",
    missingCause: "no_station_in_range",
    sourceHealth: healthyNational,
  });
  coverage.source_health = [
    healthyNational,
    realtimeSourceHealth({
      health_status: "disabled",
      name: "未啟用的全國備援來源",
      reason_code: "disabled",
      source_id: "disabled-national-source",
      station_count: null,
    }),
    realtimeSourceHealth({
      coverage_scope: "local",
      health_status: "failed",
      name: "地方實驗來源",
      reason_code: "pipeline_unavailable",
      source_id: "failed-local-source",
      station_count: null,
    }),
  ];
  coverage.source_health_status = "failed";

  const state = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: coverage,
    },
    evidenceItems: [],
  });

  assert.equal(state.badge, "附近觀測：來源異常");
  assert.equal(state.items[0].detail, "來源或更新管線異常，無法確認附近測站");
  assert.match(state.summary, /無法確認附近是否真的沒有測站/);
  assert.doesNotMatch(state.badge, /範圍內無站/);
  assert.doesNotMatch(state.summary, /來源運作正常/);
  assert.match(state.note, /不代表現地安全/);
  assert.doesNotMatch(JSON.stringify(state), /internal-source-id-must-not-render/);

  const observedCoverage: NearbyRealtimeCoverage = {
    ...coverage,
    missing_signal_types: [],
    overall_level: "high",
    signal_breakdown: [
      {
        ...coverage.signal_breakdown[0],
        availability_state: "fresh_nearby",
        counts_by_radius_m: { "500": 1 },
        coverage_level: "high",
        fresh_count: 1,
        missing_cause: "none",
        missing_reason: null,
        nearest_distance_m: 280,
        nearest_freshness_state: "fresh",
        nearest_observed_at: "2026-07-18T07:58:00Z",
      },
    ],
  };
  const observedState = nearbySensingState({
    assessment: { nearby_realtime_coverage: observedCoverage },
  });
  assert.equal(observedState.badge, "附近觀測：部分來源異常");
  assert.equal(observedState.tone, "warn");
});

test("partial required-signal contract cannot claim overall confirmed no-station", () => {
  const coverage = missingRainfallCoverage({
    availabilityState: "no_station",
    missingCause: "no_station_in_range",
    sourceHealth: realtimeSourceHealth(),
  });

  const state = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });

  assert.equal(state.badge, "附近觀測：資料不足");
  assert.doesNotMatch(state.badge, /範圍內無站/);
  assert.doesNotMatch(state.summary, /來源運作正常/);
});

test("unverified jurisdiction contracts prevent a confirmed no-station badge", () => {
  const coverage = missingRainfallCoverage({
    availabilityState: "no_station",
    jurisdictionVerified: false,
    missingCause: "no_station_in_range",
    sourceHealth: realtimeSourceHealth(),
  });

  const state = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });

  assert.equal(state.badge, "附近觀測：管轄來源待驗證");
  assert.doesNotMatch(state.badge, /範圍內無站/);
  assert.match(state.summary, /縣市邊界或管轄來源清單尚未完成審核/);
});

test("a failed required depth source prevents a confirmed no-station badge", () => {
  const healthyRainfall = realtimeSourceHealth({
    health_status: "healthy",
    reason_code: "operational",
    signal_types: ["rainfall"],
    station_count: 42,
  });
  const failedFloodDepth = realtimeSourceHealth({
    health_status: "failed",
    name: "水利署淹水深度觀測",
    reason_code: "pipeline_unavailable",
    signal_types: ["flood_depth"],
    source_id: "failed-flood-depth-source",
    station_count: null,
  });
  const coverage = missingRainfallCoverage({
    availabilityState: "no_station",
    missingCause: "no_station_in_range",
    sourceHealth: healthyRainfall,
  });
  const noStationSignal = coverage.signal_breakdown[0];
  coverage.signal_breakdown = [
    noStationSignal,
    { ...noStationSignal, label: "水位", signal_type: "water_level" },
    {
      ...noStationSignal,
      availability_state: "source_unavailable",
      failed_source_count: 1,
      label: "淹水深度",
      missing_cause: "source_failed",
      missing_reason: "來源或更新管線目前異常。",
      signal_type: "flood_depth",
      source_health_status: "failed",
    },
    { ...noStationSignal, label: "下水道水位", signal_type: "sewer_water_level" },
  ];
  coverage.missing_signal_types = [
    "rainfall",
    "water_level",
    "flood_depth",
    "sewer_water_level",
  ];
  coverage.source_health = [healthyRainfall, failedFloodDepth];
  coverage.source_health_status = "degraded";

  const state = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });

  assert.equal(state.badge, "附近觀測：來源異常");
  assert.doesNotMatch(state.badge, /範圍內無站/);
  assert.match(state.summary, /無法確認附近是否真的沒有測站/);
});

test("optional unavailable sources never displace the four required measurements", () => {
  const coverage = missingRainfallCoverage({
    availabilityState: "no_station",
    missingCause: "no_station_in_range",
    sourceHealth: realtimeSourceHealth(),
  });
  const requiredSignal = coverage.signal_breakdown[0];
  const optionalUnavailable = (signalType: CoverageSignalType, label: string) => ({
    ...requiredSignal,
    availability_state: "source_unavailable" as const,
    label,
    missing_cause: "source_not_configured" as const,
    signal_type: signalType,
    source_health_status: "disabled" as const,
  });
  coverage.signal_breakdown = [
    optionalUnavailable("pump_or_gate_status", "抽水站狀態"),
    optionalUnavailable("flood_warning", "淹水警戒"),
    optionalUnavailable("status_only", "狀態觀測"),
    requiredSignal,
    { ...requiredSignal, label: "水位", signal_type: "water_level" },
    { ...requiredSignal, label: "淹水深度", signal_type: "flood_depth" },
    { ...requiredSignal, label: "下水道水位", signal_type: "sewer_water_level" },
  ];

  const state = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });

  assert.deepEqual(
    state.items.map((item) => item.id),
    ["rainfall", "water_level", "flood_depth", "sewer_water_level"],
  );

  const observedOptional = {
    ...optionalUnavailable("pump_or_gate_status", "抽水站狀態"),
    availability_state: "fresh_nearby" as const,
    coverage_level: "high" as const,
    fresh_count: 1,
    missing_cause: "none" as const,
    nearest_distance_m: 450,
    nearest_freshness_state: "fresh" as const,
    source_health_status: "healthy" as const,
  };
  const legacyCoverage = {
    ...coverage,
    signal_breakdown: [requiredSignal, observedOptional],
  };
  const legacyState = nearbySensingState({
    assessment: { nearby_realtime_coverage: legacyCoverage },
  });
  assert.deepEqual(
    legacyState.items.map((item) => item.id),
    ["rainfall", "pump_or_gate_status"],
  );
});

test("nearby sensing state distinguishes source failure, stalled pipeline, and unknown health", () => {
  const failed = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: missingRainfallCoverage({
        availabilityState: "source_unavailable",
        missingCause: "source_failed",
        sourceHealth: realtimeSourceHealth({
          health_status: "failed",
          message: "來源或背景更新目前異常。",
          reason_code: "pipeline_unavailable",
          station_count: null,
        }),
      }),
    },
  });
  assert.equal(failed.badge, "附近觀測：來源異常");
  assert.equal(failed.items[0].detail, "來源或更新管線異常，無法確認附近測站");
  assert.match(failed.summary, /無法確認附近是否真的沒有測站/);
  assert.equal(failed.tone, "warn");

  const stalled = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: missingRainfallCoverage({
        availabilityState: "source_unavailable",
        missingCause: "update_pipeline_stalled",
        sourceHealth: realtimeSourceHealth({
          health_status: "failed",
          message: "背景更新近期沒有活動。",
          reason_code: "pipeline_stalled",
        }),
      }),
    },
  });
  assert.equal(stalled.badge, "附近觀測：更新管線停滯");
  assert.equal(stalled.items[0].detail, "背景更新管線停滯，無法確認附近測站");
  assert.match(stalled.note, /更新管線停滯/);

  const unknown = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: missingRainfallCoverage({
        availabilityState: "source_status_unknown",
        missingCause: "health_unknown",
        sourceHealthChecked: false,
      }),
    },
  });
  assert.equal(unknown.badge, "附近觀測：來源狀態不明");
  assert.equal(unknown.items[0].detail, "來源健康狀態不明，無法確認附近測站");
  assert.equal(unknown.tone, "muted");

  const unverifiedInventory = nearbySensingState({
    assessment: {
      nearby_realtime_coverage: missingRainfallCoverage({
        availabilityState: "source_status_unknown",
        missingCause: "inventory_unverified",
        sourceHealth: realtimeSourceHealth({ inventory_complete: false }),
      }),
    },
  });
  assert.equal(unverifiedInventory.badge, "附近觀測：站點清冊待驗證");
  assert.equal(
    unverifiedInventory.items[0].detail,
    "來源正常，但站點清冊完整性尚未驗證",
  );
  assert.match(unverifiedInventory.note, /不等於附近真的沒有測站/);
  assert.equal(unverifiedInventory.tone, "muted");
});

test("nearby sensing state reports partial failure without hiding useful observations", () => {
  const coverage = missingRainfallCoverage({
    availabilityState: "source_unavailable",
    missingCause: "source_failed",
    sourceHealth: realtimeSourceHealth({
      coverage_scope: "local",
      health_status: "failed",
      jurisdictions: ["臺北市"],
      reason_code: "upstream_unavailable",
      required_for_absence: true,
      signal_types: ["rainfall"],
    }),
  });
  coverage.missing_signal_types = [];
  coverage.overall_level = "high";
  coverage.signal_breakdown = [
    {
      availability_state: "fresh_nearby",
      counts_by_radius_m: { "500": 1 },
      coverage_level: "high",
      degraded_count: 0,
      failed_source_count: 0,
      fresh_count: 1,
      label: "雨量",
      missing_cause: "none",
      missing_reason: null,
      nearest_distance_m: 320,
      nearest_freshness_state: "fresh",
      nearest_observed_at: "2026-07-18T07:58:00Z",
      nearest_source_id: "public-evidence-id-not-used-as-source-health-id",
      signal_type: "rainfall",
      source_count: 1,
      source_health_status: "healthy",
      stale_count: 0,
      status_only_count: 0,
    },
  ];

  const state = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });

  assert.equal(state.badge, "附近觀測：部分來源異常");
  assert.match(state.summary, /部分即時觀測/);
  assert.match(state.items[0].detail, /320 公尺；新鮮/);
  assert.match(state.note, /不代表現地安全/);

  coverage.source_health = coverage.source_health?.map((source) => ({
    ...source,
    required_for_absence: false,
  }));
  const redundantFailureState = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });
  assert.equal(redundantFailureState.badge, "附近觀測：高");

  coverage.source_health = [];
  coverage.source_health_checked = false;
  coverage.source_health_status = "unknown";
  const uncheckedState = nearbySensingState({
    assessment: { nearby_realtime_coverage: coverage },
  });
  assert.equal(uncheckedState.badge, "附近觀測：部分來源狀態不明");
  assert.equal(uncheckedState.tone, "muted");
});

test("layer display state prefers explicit tile contract fields", () => {
  const state = buildLayerDisplayState({
    layers: [
      {
        availability: "available",
        feature_count: 42,
        health_status: "healthy",
        kind: "raster-tile",
        layer_id: "rainfall-now",
        name: "Rainfall now",
        observed_at: "2026-04-30T01:30:00+08:00",
        tile_url: "/v1/tiles/rainfall/{z}/{x}/{y}.png",
      },
    ],
  });

  assert.equal(state.status, "ready");
  assert.equal(state.hasTileContract, true);
  assert.deepEqual(state.items[0], {
    availability: "available",
    featureCount: 42,
    freshnessAt: "2026-04-30T01:30:00+08:00",
    id: "rainfall-now",
    kind: "點陣圖磚",
    message: null,
    name: "Rainfall now",
    status: "healthy",
    tileUrl: "/v1/tiles/rainfall/{z}/{x}/{y}.png",
  });
});

test("source health summary condenses layer availability counts", () => {
  const state = buildLayerDisplayState({
    layers: [
      {
        availability: "available",
        health_status: "healthy",
        layer_id: "ready-layer",
        name: "Ready layer",
      },
      {
        availability: "limited",
        health_status: "degraded",
        layer_id: "limited-layer",
        name: "Limited layer",
      },
      {
        availability: "empty",
        health_status: "healthy",
        layer_id: "empty-layer",
        name: "Empty layer",
      },
      {
        availability: "unavailable",
        health_status: "failed",
        layer_id: "failed-layer",
        name: "Failed layer",
      },
    ],
  });

  const summary = sourceHealthSummaryState(state);

  assert.equal(summary.tone, "limited");
  assert.match(summary.title, /部分受限/);
  assert.match(summary.note, /地圖圖層契約/);
  assert.deepEqual(
    summary.items.map((item) => [item.key, item.count]),
    [
      ["available", 1],
      ["limited", 1],
      ["empty", 1],
      ["unavailable", 1],
    ],
  );
});

test("layer display state derives a limited fallback from freshness and evidence", () => {
  const state = buildLayerDisplayState({
    dataFreshness: [
      {
        health_status: "degraded",
        ingested_at: "2026-04-30T01:40:00+08:00",
        message: "Source is delayed",
        name: "Rain gauge",
        observed_at: null,
        source_id: "rain-gauge",
      },
    ],
    evidenceItems: [fullEvidence],
  });

  assert.equal(state.status, "limited");
  assert.equal(state.hasTileContract, false);
  assert.equal(state.items[0].availability, "limited");
  assert.equal(state.items[0].featureCount, 1);
  assert.equal(state.items[0].freshnessAt, "2026-04-30T01:40:00+08:00");
});

test("layer display state uses freshness feature counts for on-demand public news", () => {
  const state = buildLayerDisplayState({
    dataFreshness: [
      {
        feature_count: 5,
        health_status: "healthy",
        ingested_at: "2026-05-13T03:50:00Z",
        message: "已從公開新聞/百科索引補查並整理 5 筆候選淹水事件。",
        name: "公開新聞即時補查",
        observed_at: "2026-04-23T02:28:00Z",
        source_id: "on-demand-public-news",
      },
    ],
    evidenceItems: [],
  });

  assert.equal(state.items[0].featureCount, 5);
  assert.equal(state.items[0].availability, "available");
  assert.equal(layerAvailabilityDisplayLabel(state.items[0]), "來源可用");
});

test("latest news links are attached to one freshness source only", () => {
  const dataFreshness = [
    {
      feature_count: 12,
      health_status: "healthy",
      ingested_at: "2026-05-13T03:50:00Z",
      message: "查詢半徑內找到 12 筆已審核歷史資料。",
      name: "歷史淹水紀錄與公開新聞",
      observed_at: "2026-04-23T02:28:00Z",
      source_id: "db-evidence",
    },
    {
      feature_count: 2,
      health_status: "healthy",
      ingested_at: "2026-05-13T03:50:00Z",
      message: "已從公開新聞/百科索引補查並整理 2 筆候選淹水事件。",
      name: "公開新聞／Wiki 即時補查",
      observed_at: "2026-04-23T02:28:00Z",
      source_id: "on-demand-public-news",
    },
  ];

  assert.equal(
    latestNewsLinksFreshnessSourceId(dataFreshness, [
      {
        ...fullEvidence,
        id: "rss-news",
        source_id: "public-news-rss:abc",
        source_type: "news",
      },
    ]),
    "on-demand-public-news",
  );

  assert.equal(
    latestNewsLinksFreshnessSourceId([dataFreshness[0]], [
      {
        ...fullEvidence,
        id: "db-news",
        source_id: "news:stored",
        source_type: "news",
      },
    ]),
    "db-evidence",
  );
});

test("data-source availability labels distinguish zero hits from missing map layers", () => {
  assert.equal(layerAvailabilityDisplayLabel({ availability: "empty", kind: "資料" }), "本來源 0 命中");
  assert.equal(layerAvailabilityDisplayLabel({ availability: "empty", kind: "點陣圖磚" }), "無圖層資料");
});

test("layer display state leaves non-evidence source counts unknown instead of zero", () => {
  const state = buildLayerDisplayState({
    dataFreshness: [
      {
        health_status: "healthy",
        ingested_at: "2026-05-13T04:20:00Z",
        message: "來源可用，但沒有逐筆證據計數。",
        name: "中央氣象署即時雨量",
        observed_at: "2026-05-13T04:20:00Z",
        source_id: "cwa-rainfall",
      },
    ],
    evidenceItems: [],
  });

  assert.equal(state.items[0].availability, "available");
  assert.equal(state.items[0].featureCount, null);
  assert.equal(layerAvailabilityDisplayLabel(state.items[0]), "來源可用");
});

test("layer display state falls back to on-demand public news source prefixes", () => {
  const state = buildLayerDisplayState({
    dataFreshness: [
      {
        health_status: "healthy",
        ingested_at: "2026-05-13T03:50:00Z",
        message: "已從公開新聞/百科索引補查並整理 2 筆候選淹水事件。",
        name: "公開新聞即時補查",
        observed_at: "2026-04-23T02:28:00Z",
        source_id: "on-demand-public-news",
      },
    ],
    evidenceItems: [
      {
        ...fullEvidence,
        id: "rss-news",
        source_id: "public-news-rss:abc",
        source_type: "news",
      },
      {
        ...fullEvidence,
        id: "wiki-news",
        source_id: "public-wiki:def",
        source_type: "news",
      },
    ],
  });

  assert.equal(state.items[0].featureCount, 2);
});

test("layer display state exposes an empty state when no layer inputs exist", () => {
  assert.deepEqual(buildLayerDisplayState({}), {
    hasTileContract: false,
    items: [],
    status: "empty",
  });
});

test("nearbyCoverageSummary labels nearby sensor availability", () => {
  const state = nearbyCoverageSummary({
    county_level_note:
      "縣市資料源目錄顯示可能有資料，但附近覆蓋仍以查詢點半徑內感測器為準。",
    evaluated_at: "2026-06-29T12:00:00Z",
    limitations: [],
    missing_signal_types: ["flood_depth"],
    overall_level: "medium",
    query_radius_m: 500,
    radius_buckets_m: [500, 1000, 3000, 5000],
    signal_breakdown: [],
    summary: "查詢點 1 公里內有雨量或水位即時資料，但感測密度仍有限。",
  });

  assert.deepEqual(state, {
    badge: "附近即時感測中等",
    summary: "查詢點 1 公里內有雨量或水位即時資料，但感測密度仍有限。",
    tone: "warn",
  });
});

test("nearbyCoverageSummary distinguishes no local sensor from unavailable coverage", () => {
  assert.deepEqual(
    nearbyCoverageSummary({
      county_level_note:
        "縣市資料源目錄顯示可能有資料，但查詢點半徑附近沒有新鮮在地感測資料。",
      evaluated_at: "2026-06-29T12:00:00Z",
      limitations: ["半徑內沒有 fresh local sensor，不能代表縣市沒有感測器。"],
      missing_signal_types: ["rainfall", "water_level"],
      overall_level: "no_local_sensor",
      query_radius_m: 500,
      radius_buckets_m: [500, 1000, 3000, 5000],
      signal_breakdown: [],
      summary: "查詢點半徑內沒有新鮮在地感測資料；縣市或資料源仍可能有資料。",
    }),
    {
      badge: "附近即時資料不足",
      summary: "查詢點半徑內沒有新鮮在地感測資料；縣市或資料源仍可能有資料。",
      tone: "poor",
    },
  );

  assert.deepEqual(nearbyCoverageSummary(null), {
    badge: "即時覆蓋暫時無法評估",
    summary: "即時感測覆蓋尚未回傳，無法判斷附近是否有感測器。",
    tone: "muted",
  });
});

test("nearby coverage labels and distance formatting are explicit", () => {
  assert.equal(nearbyCoverageLevelLabel("high"), "附近即時感測充足");
  assert.equal(nearbyCoverageLevelLabel("low"), "附近即時觀測有限");
  assert.equal(nearbyCoverageLevelLabel("unavailable"), "即時覆蓋暫時無法評估");
  assert.equal(formatDistanceMeters(230.4), "230 公尺");
  assert.equal(formatDistanceMeters(1234.4), "1.2 公里");
  assert.equal(formatDistanceMeters(null), "半徑內無新鮮感測");
});

test("risk and evidence formatting helpers produce display-ready strings", () => {
  assert.equal(formatCoordinate(25.047761), "25.04776");
  assert.equal(formatConfidence(0.812), "81%");
  assert.equal(formatDistance(1234.49), "1,234 公尺");
  assert.equal(formatDistance(null), "未提供");
  assert.match(formatDateTime("2026-04-30T01:30:00+08:00", { timeZone: "Asia/Taipei" }), /04\/30/);
  assert.equal(formatDateTime(null), "未提供");
});
