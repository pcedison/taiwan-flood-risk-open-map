"use client";

import type { RiskAssessmentResponse } from "../lib/page-types";
import type { EvidenceItem } from "../lib/risk-display";
import { nearbySensingState } from "../lib/risk-display";
import { text } from "../lib/ui-text";

type NearbySensingSectionProps = {
  assessment: RiskAssessmentResponse | null;
  evidenceItems: EvidenceItem[];
};

export function NearbySensingSection({
  assessment,
  evidenceItems,
}: NearbySensingSectionProps) {
  const state = nearbySensingState({ assessment, evidenceItems });
  const coverage = assessment?.nearby_realtime_coverage;
  const searchRadiusM = coverage
    ? Math.max(...coverage.radius_buckets_m, coverage.query_radius_m)
    : null;

  return (
    <section
      className={`panel-section nearby-sensing nearby-sensing-${state.tone}`}
      data-testid="nearby-sensing"
    >
      <div className="section-heading">
        <span className="section-kicker">{text.nearbySensingKicker}</span>
        <h2>{state.badge}</h2>
      </div>
      <p>{state.summary}</p>
      {state.availability.total > 0 ? (
        <div className="sensing-availability" data-testid="sensing-availability">
          <div className="sensing-availability-heading">
            <span>{text.nearbySensingAvailability}</span>
            <strong>
              {state.availability.available} / {state.availability.total} 類
            </strong>
          </div>
          <progress
            className="sensing-availability-track"
            aria-label={text.nearbySensingAvailability}
            max={state.availability.total}
            value={state.availability.available}
          />
          <div className="sensing-availability-legend" aria-label="觀測新鮮度摘要">
            <span>新鮮 {state.availability.fresh}</span>
            <span>較慢 {state.availability.delayed}</span>
            <span>區域參考 {state.availability.regional}</span>
            <span>過期 {state.availability.stale}</span>
          </div>
        </div>
      ) : null}
      {state.gaps.length ? (
        <div className="nearby-sensing-gaps" aria-label={text.nearbySensingGaps}>
          <span>{text.nearbySensingGaps}</span>
          {state.gaps.map((gap) => (
            <strong key={gap}>{gap}</strong>
          ))}
        </div>
      ) : null}
      {state.items.length ? (
        <ul className="nearby-sensing-list">
          {state.items.map((item) => (
            <li key={item.id} className={`nearby-sensing-item-${item.statusTone}`}>
              <div className="nearby-sensing-item-heading">
                <strong>{item.label}</strong>
                <span>{item.status}</span>
              </div>
              <div className="nearby-sensing-reading">
                {item.value !== null ? (
                  <p>
                    <strong>{item.value}</strong>
                    <span>{item.unit}</span>
                  </p>
                ) : (
                  <p className="nearby-sensing-reading-empty">未提供讀值</p>
                )}
                <p>{item.insight}</p>
              </div>
              <span className="nearby-sensing-item-meta">{item.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <details className="nearby-sensing-details">
        <summary>{text.nearbySensingDetails}</summary>
        {coverage && searchRadiusM !== null ? (
          <p>
            風險圈 {Math.round(assessment.radius_m ?? coverage.query_radius_m)} 公尺；感測站搜尋至{" "}
            {searchRadiusM >= 1000
              ? `${Math.round(searchRadiusM / 1000)} 公里`
              : `${Math.round(searchRadiusM)} 公尺`}
            {searchRadiusM > 5000 ? "，5 公里外僅供區域參考。" : "。"}
          </p>
        ) : null}
        <p>{state.note}</p>
      </details>
    </section>
  );
}
