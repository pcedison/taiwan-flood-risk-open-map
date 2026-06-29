"use client";

import type { Coordinate, RiskAssessmentResponse } from "../lib/page-types";
import type { buildLayerDisplayState } from "../lib/risk-display";
import {
  formatCoordinate,
  formatDateTime,
  formatDistanceMeters,
  layerAvailabilityDisplayLabel,
  nearbyCoverageLevelLabel,
  publicDataFreshnessItems,
  sourceHealthSummaryState,
} from "../lib/risk-display";
import { healthLabel, text } from "../lib/ui-text";

type CoverageSignal =
  RiskAssessmentResponse["nearby_realtime_coverage"]["signal_breakdown"][number];

type DiagnosticsSectionProps = {
  assessment: RiskAssessmentResponse | null;
  coordinate: Coordinate;
  radius: number;
  currentSummary: string;
  layerDisplayState: ReturnType<typeof buildLayerDisplayState>;
};

export function DiagnosticsSection({
  assessment,
  coordinate,
  radius,
  currentSummary,
  layerDisplayState,
}: DiagnosticsSectionProps) {
  const coverage = assessment?.nearby_realtime_coverage ?? null;
  const visibleFreshness = assessment
    ? publicDataFreshnessItems(assessment.data_freshness)
    : [];
  const sourceSummary = sourceHealthSummaryState(layerDisplayState);

  return (
    <section className="panel-section diagnostics-panel" data-testid="diagnostics-panel">
      <details className="diagnostics-drawer" data-testid="diagnostics-drawer">
        <summary data-testid="diagnostics-summary">
          <span className="section-kicker">{text.diagnosticsKicker}</span>
          <strong>{text.diagnosticsTitle}</strong>
          <span>{assessment ? text.diagnosticsReady : text.diagnosticsPending}</span>
        </summary>
        <div className="diagnostics-body">
          <section
            className={`diagnostics-section source-health-summary source-health-${sourceSummary.tone}`}
            aria-label="來源摘要"
          >
            <div>
              <span className="section-kicker">來源摘要</span>
              <strong>{sourceSummary.title}</strong>
              <p>{sourceSummary.note}</p>
            </div>
            <dl>
              {sourceSummary.items.map((item) => (
                <div key={item.key} className={`source-health-chip source-health-chip-${item.key}`}>
                  <dt>{item.label}</dt>
                  <dd>{item.count.toLocaleString("zh-TW")}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="diagnostics-section coordinate-panel" aria-label={text.currentCoordinate}>
            <div>
              <span className="section-kicker">{text.currentCoordinate}</span>
              <strong>{currentSummary}</strong>
            </div>
            <dl>
              <div>
                <dt>{text.latitude}</dt>
                <dd>{formatCoordinate(coordinate.lat)}</dd>
              </div>
              <div>
                <dt>{text.longitude}</dt>
                <dd>{formatCoordinate(coordinate.lng)}</dd>
              </div>
              <div>
                <dt>{text.radius}</dt>
                <dd>{radius.toLocaleString("zh-TW")} 公尺</dd>
              </div>
            </dl>
          </section>

          <section className="diagnostics-section coverage-detail-panel" aria-label={text.diagnosticsCoverageTitle}>
            <div className="section-heading">
              <span className="section-kicker">{text.nearbyCoverageKicker}</span>
              <strong>
                {coverage
                  ? nearbyCoverageLevelLabel(coverage.overall_level)
                  : text.diagnosticsPending}
              </strong>
            </div>
            <p>{coverage ? coverage.summary : text.nearbyCoveragePending}</p>
            {coverage ? (
              <>
                <p className="coverage-boundary-note">
                  {coverage.county_level_note || text.diagnosticsCoverageLocalBoundary}
                </p>
                {coverage.signal_breakdown.length ? (
                  <ul className="coverage-detail-list">
                    {coverage.signal_breakdown.map((signal) => (
                      <li key={signal.signal_type}>
                        <div className="coverage-detail-heading">
                          <strong>{signal.label}</strong>
                          <span>{nearbyCoverageLevelLabel(signal.coverage_level)}</span>
                        </div>
                        <dl>
                          <div>
                            <dt>{text.nearbyCoverageNearest}</dt>
                            <dd>{formatDistanceMeters(signal.nearest_distance_m)}</dd>
                          </div>
                          <div>
                            <dt>{text.diagnosticsCoverageBuckets}</dt>
                            <dd>{formatCoverageBucketCounts(signal, coverage.radius_buckets_m)}</dd>
                          </div>
                          <div>
                            <dt>{text.diagnosticsCoverageFreshness}</dt>
                            <dd>
                              {signal.fresh_count} / {signal.stale_count} /{" "}
                              {signal.status_only_count}
                            </dd>
                          </div>
                          <div>
                            <dt>{text.nearbyCoverageObservedAt}</dt>
                            <dd>{formatDateTime(signal.nearest_observed_at)}</dd>
                          </div>
                        </dl>
                        {signal.missing_reason ? (
                          <p>
                            <strong>{text.diagnosticsCoverageMissingReason}</strong>
                            <span>{signal.missing_reason}</span>
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>{text.diagnosticsCoverageNoSignals}</p>
                )}
                {coverage.limitations.length ? (
                  <ul className="coverage-limitations">
                    {coverage.limitations.map((limitation) => (
                      <li key={limitation}>{limitation}</li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : null}
          </section>

          <section className="diagnostics-section layer-panel" aria-label={text.layers}>
            <div className="section-heading">
              <span className="section-kicker">{text.layers}</span>
              <strong>
                {layerDisplayState.status === "ready"
                  ? text.layerReady
                  : layerDisplayState.status === "limited"
                    ? text.layerLimited
                    : layerDisplayState.status === "empty"
                      ? text.layerEmpty
                      : text.layerPending}
              </strong>
            </div>
            <div className="layer-contract-status">
              {layerDisplayState.hasTileContract ? text.layerContract : text.layerFallback}
            </div>
            {layerDisplayState.items.length ? (
              <ul className="layer-list">
                {layerDisplayState.items.map((item) => (
                  <li key={item.id}>
                    <div>
                      <strong>{item.name}</strong>
                      <span>{`${item.kind}：${layerAvailabilityDisplayLabel(item)}`}</span>
                    </div>
                    <dl>
                      <div>
                        <dt>{text.freshness}</dt>
                        <dd>{formatDateTime(item.freshnessAt)}</dd>
                      </div>
                      <div>
                        <dt>{text.layerFeatureCount}</dt>
                        <dd>{item.featureCount ?? "--"}</dd>
                      </div>
                      <div>
                        <dt>{text.mapStatus}</dt>
                        <dd>{healthLabel(item.status)}</dd>
                      </div>
                      <div>
                        <dt>{text.tileLabel}</dt>
                        <dd>{item.tileUrl ? text.provided : text.layerNoTile}</dd>
                      </div>
                    </dl>
                    {item.message ? <p>{item.message}</p> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p>{assessment ? text.layerNoData : text.freshnessNote}</p>
            )}
          </section>

          <section className="diagnostics-section freshness-panel" aria-label={text.freshness}>
            <div>
              <span className="section-kicker">{text.freshness}</span>
              <strong>{assessment ? text.online : text.offline}</strong>
            </div>
            {assessment && visibleFreshness.length ? (
              <ul className="freshness-list">
                {visibleFreshness.map((item) => (
                  <li key={item.source_id}>
                    <strong>{`${item.name}：${healthLabel(item.health_status)}`}</strong>
                    {item.message ? <span>{item.message}</span> : null}
                  </li>
                ))}
              </ul>
            ) : assessment ? (
              <p>歷史新聞已暫時隱藏；本次沒有其他可公開顯示的來源狀態。</p>
            ) : (
              <p>{text.lastSync}</p>
            )}
            <p>
              {assessment
                ? `查詢關注度：${assessment.query_heat.attention_level}`
                : text.freshnessNote}
            </p>
          </section>
        </div>
      </details>
    </section>
  );
}

function formatCoverageBucketCounts(signal: CoverageSignal, buckets: number[]) {
  return buckets
    .map((bucket) => {
      const label = bucket >= 1000 ? `${bucket / 1000}km` : `${bucket}m`;
      return `${label}: ${signal.counts_by_radius_m[String(bucket)] ?? 0}`;
    })
    .join(" / ");
}
