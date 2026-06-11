"use client";

import type { Coordinate, RiskAssessmentResponse } from "../lib/page-types";
import type { buildLayerDisplayState, latestNewsEvidenceLinks } from "../lib/risk-display";
import {
  formatCoordinate,
  formatDateTime,
  layerAvailabilityDisplayLabel,
} from "../lib/risk-display";
import { healthLabel, text } from "../lib/ui-text";

type DiagnosticsSectionProps = {
  assessment: RiskAssessmentResponse | null;
  coordinate: Coordinate;
  radius: number;
  currentSummary: string;
  layerDisplayState: ReturnType<typeof buildLayerDisplayState>;
  latestNewsLinks: ReturnType<typeof latestNewsEvidenceLinks>;
  latestNewsLinkSourceId: string | null;
};

export function DiagnosticsSection({
  assessment,
  coordinate,
  radius,
  currentSummary,
  layerDisplayState,
  latestNewsLinks,
  latestNewsLinkSourceId,
}: DiagnosticsSectionProps) {
  return (
    <section className="panel-section diagnostics-panel" data-testid="diagnostics-panel">
      <details className="diagnostics-drawer" data-testid="diagnostics-drawer">
        <summary data-testid="diagnostics-summary">
          <span className="section-kicker">{text.diagnosticsKicker}</span>
          <strong>{text.diagnosticsTitle}</strong>
          <span>{assessment ? text.diagnosticsReady : text.diagnosticsPending}</span>
        </summary>
        <div className="diagnostics-body">
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
            {assessment ? (
              <ul className="freshness-list">
                {assessment.data_freshness.map((item) => {
                  const showLatestNewsLinks =
                    latestNewsLinks.length > 0 && item.source_id === latestNewsLinkSourceId;

                  return (
                    <li key={item.source_id}>
                      <strong>{`${item.name}：${healthLabel(item.health_status)}`}</strong>
                      {item.message ? <span>{item.message}</span> : null}
                      {showLatestNewsLinks ? (
                        <div className="freshness-source-links">
                          <span>{text.latestNewsSources}</span>
                          <ol>
                            {latestNewsLinks.map((link) => (
                              <li key={link.id}>
                                <a href={link.url} target="_blank" rel="noreferrer">
                                  {link.title}
                                </a>
                                <small>{formatDateTime(link.time)}</small>
                              </li>
                            ))}
                          </ol>
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
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
