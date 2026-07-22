"use client";

import type { RiskAssessmentResponse } from "../lib/page-types";
import type { EvidenceItem, getEvidenceDisplayState, getProfileBasisText, getProfilePreviewState } from "../lib/risk-display";
import {
  evidenceDisplayText,
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
  hiddenHistoricalNewsCount: number;
  profileBasisText: ReturnType<typeof getProfileBasisText>;
  profilePreviewState: ReturnType<typeof getProfilePreviewState>;
};

export function EvidenceSection({
  assessment,
  displayedEvidence,
  evidenceDisplayState,
  hiddenHistoricalNewsCount,
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
            <p className="section-question">{text.evidenceQuestion}</p>
            <div className="evidence-scope-note" role="status">
              <span>{text.evidenceScopeNote}</span>
              {hiddenHistoricalNewsCount > 0 ? (
                <strong>
                  {text.hiddenNewsEvidence} {hiddenHistoricalNewsCount} 筆
                </strong>
              ) : null}
            </div>

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
                  const displayText = evidenceDisplayText(item);
                  const sourceUrl = evidenceSourceUrl(item);

                  return (
                    <li key={item.id} className="evidence-card">
                      <div className="evidence-card-header">
                        <div>
                          <span>{sourceTypeLabel(item.source_type)}</span>
                          <strong>{displayText.title}</strong>
                        </div>
                        {sourceUrl ? (
                          <a
                            className="evidence-card-link"
                            href={sourceUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {text.evidenceOpenSource}
                          </a>
                        ) : null}
                      </div>
                      <p>{displayText.summary}</p>
                      <span className="evidence-card-purpose">{displayText.purpose}</span>
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
                        {!sourceUrl ? (
                          <div>
                            <dt>{text.evidenceUrl}</dt>
                            <dd>
                              <span className="missing-source">{text.evidenceMissingUrl}</span>
                            </dd>
                          </div>
                        ) : null}
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
              <details className="evidence-warning" data-testid="evidence-limitations">
                <summary>
                  <span>
                    <strong>{text.limitations}</strong>
                    <small>
                      {assessment.explanation.missing_sources.length} 項需要留意
                    </small>
                  </span>
                  <span>查看限制</span>
                </summary>
                <div className="evidence-warning-body" role="status">
                  {profileBasisText.limitationLead ? (
                    <span className="evidence-warning-note">{profileBasisText.limitationLead}</span>
                  ) : null}
                  <ul>
                    {assessment.explanation.missing_sources.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </details>
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
