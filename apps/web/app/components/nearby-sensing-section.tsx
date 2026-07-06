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
