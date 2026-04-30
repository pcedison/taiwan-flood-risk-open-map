import assert from "node:assert/strict";
import test from "node:test";

import type { EvidenceItem, EvidencePreview } from "../../app/lib/risk-display";

const riskDisplayModulePath = "../../app/lib/risk-display.ts";
const {
  buildRiskAssessmentPayload,
  buildLayerDisplayState,
  evidencePublishedAt,
  evidenceSourceUrl,
  formatConfidence,
  formatCoordinate,
  formatDateTime,
  formatDistance,
  getEvidenceDisplayState,
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
    kind: "raster-tile",
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
  assert.equal(formatDistance(1234.49), "1,234 m");
  assert.equal(formatDistance(null), "未提供");
  assert.match(formatDateTime("2026-04-30T01:30:00+08:00", { timeZone: "Asia/Taipei" }), /04\/30/);
  assert.equal(formatDateTime(null), "未提供");
});
