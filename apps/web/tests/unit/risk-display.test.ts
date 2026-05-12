import assert from "node:assert/strict";
import test from "node:test";

import type { EvidenceItem, EvidencePreview } from "../../app/lib/risk-display";

const riskDisplayModulePath = "../../app/lib/risk-display.ts";
const {
  buildRiskAssessmentPayload,
  buildLayerDisplayState,
  buildUserReportPayload,
  evidencePublishedAt,
  evidenceSourceUrl,
  formatConfidence,
  formatCoordinate,
  formatDateTime,
  formatDistance,
  getEvidenceDisplayState,
  getProfileBasisText,
  getProfilePreviewState,
  getUserReportSubmissionDisplayState,
  selectEvidenceItems,
  shouldFetchEvidenceList,
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
  assert.equal(state.label, "區域 profile 初步結果");
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

test("layer display state exposes an empty state when no layer inputs exist", () => {
  assert.deepEqual(buildLayerDisplayState({}), {
    hasTileContract: false,
    items: [],
    status: "empty",
  });
});

test("risk and evidence formatting helpers produce display-ready strings", () => {
  assert.equal(formatCoordinate(25.047761), "25.04776");
  assert.equal(formatConfidence(0.812), "81%");
  assert.equal(formatDistance(1234.49), "1,234 公尺");
  assert.equal(formatDistance(null), "未提供");
  assert.match(formatDateTime("2026-04-30T01:30:00+08:00", { timeZone: "Asia/Taipei" }), /04\/30/);
  assert.equal(formatDateTime(null), "未提供");
});
