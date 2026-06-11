"use client";

import type { RiskAssessmentResponse } from "../lib/page-types";
import type { EvidenceItem, getEvidenceDisplayState, getProfileBasisText, getProfilePreviewState } from "../lib/risk-display";
import {
  evidenceSourceUrl,
  evidenceTimeSummary,
  formatConfidence,
  formatDistance,
} from "../lib/risk-display";
import { sourceTypeLabel, text } from "../lib/ui-text";

type EvidenceSectionProps = {
  assessment: RiskAssessmentResponse | null;
  displayedEvidence: EvidenceItem[];
  evidenceDisplayState: ReturnType<typeof getEvidenceDisplayState>;
  profileBasisText: ReturnType<typeof getProfileBasisText>;
  profilePreviewState: ReturnType<typeof getProfilePreviewState>;
};

export function EvidenceSection({
  assessment,
  displayedEvidence,
  evidenceDisplayState,
  profileBasisText,
  profilePreviewState,
}: EvidenceSectionProps) {
  return (
    <section className="panel-section evidence-panel" data-testid="evidence-panel">
      <details className="evidence-drawer" open>
        <summary>
          <span className="section-kicker">{text.evidenceKicker}</span>
          <strong>{text.evidenceTitle}</strong>
          {assessment ? (
            <span>
              {displayedEvidence.length} {text.evidenceCountSuffix}
            </span>
          ) : null}
        </summary>
        {assessment ? (
          <div className="evidence-drawer-body">
            {evidenceDisplayState.showLoading ? (
              <div className="evidence-state" role="status">
                {text.evidenceLoading}
              </div>
            ) : null}

            {evidenceDisplayState.showError ? (
              <div className="evidence-state evidence-state-error" role="alert">
                {text.evidenceError}
              </div>
            ) : null}

            {evidenceDisplayState.showList ? (
              <ul className="evidence-list">
                {displayedEvidence.map((item) => {
                  const sourceUrl = evidenceSourceUrl(item);

                  return (
                    <li key={item.id} className="evidence-card">
                      <div className="evidence-card-header">
                        <span>{sourceTypeLabel(item.source_type)}</span>
                        <strong>{item.title}</strong>
                      </div>
                      <p>{item.summary}</p>
                      <dl className="evidence-meta">
                        <div>
                          <dt>{text.evidenceDistance}</dt>
                          <dd>{formatDistance(item.distance_to_query_m)}</dd>
                        </div>
                        <div>
                          <dt>{text.evidenceTime}</dt>
                          <dd>{evidenceTimeSummary(item)}</dd>
                        </div>
                        <div>
                          <dt>{text.evidenceConfidence}</dt>
                          <dd>{formatConfidence(item.confidence)}</dd>
                        </div>
                        <div>
                          <dt>{text.evidenceUrl}</dt>
                          <dd>
                            {sourceUrl ? (
                              <a href={sourceUrl} target="_blank" rel="noreferrer">
                                {text.evidenceOpenSource}
                              </a>
                            ) : (
                              <span className="missing-source">{text.evidenceMissingUrl}</span>
                            )}
                          </dd>
                        </div>
                      </dl>
                    </li>
                  );
                })}
              </ul>
            ) : evidenceDisplayState.showEmpty ? (
              <div className="evidence-empty">
                {profilePreviewState.isProfilePreview ? text.profileEvidenceEmpty : text.evidenceEmpty}
              </div>
            ) : null}

            {assessment.explanation.missing_sources.length ? (
              <div className="evidence-warning" data-testid="evidence-limitations" role="status">
                <strong>{text.limitations}</strong>
                {profileBasisText.limitationLead ? (
                  <span className="evidence-warning-note">{profileBasisText.limitationLead}</span>
                ) : null}
                <ul>
                  {assessment.explanation.missing_sources.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : (
          <ul className="evidence-placeholder-list">
            <li>{text.evidenceFlood}</li>
            <li>{text.evidenceRain}</li>
            <li>{text.evidenceTerrain}</li>
          </ul>
        )}
      </details>
    </section>
  );
}
