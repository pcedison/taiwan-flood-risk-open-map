import assert from "node:assert/strict";
import test from "node:test";

import type { EvidenceItem, EvidencePreview } from "../../app/lib/risk-display";

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
  assert.match(state.confidenceNote ?? "", /來源類型/);
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
      confidence: "信心：中",
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
  assert.equal(fromCoverage.summary, "附近有 雨量 1 類觀測，最近 820 公尺；仍缺 淹水深度。");
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
      badge: "半徑內無新鮮在地感測",
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
  assert.equal(nearbyCoverageLevelLabel("low"), "附近即時感測偏少");
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
