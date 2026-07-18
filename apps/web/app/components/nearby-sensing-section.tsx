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
      <p className="section-question">{text.nearbySensingQuestion}</p>
      {coverage && searchRadiusM !== null ? (
        <p className="nearby-sensing-scope">
          紅圈是 {Math.round(assessment.radius_m ?? coverage.query_radius_m)} 公尺風險分析範圍；感測站另搜尋至{" "}
          {searchRadiusM >= 1000
            ? `${Math.round(searchRadiusM / 1000)} 公里`
            : `${Math.round(searchRadiusM)} 公尺`}
          {searchRadiusM > 5000 ? "，5 公里外僅供區域參考。" : "。"}
        </p>
      ) : null}
      <p>{state.summary}</p>
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
            <li key={item.id}>
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="nearby-sensing-note">{state.note}</p>
    </section>
  );
}
