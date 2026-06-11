"use client";

import type { RiskAssessmentResponse } from "../lib/page-types";
import type {
  getProfileBasisText,
  getProfilePreviewState,
  riskOverlayPresentation,
} from "../lib/risk-display";
import { riskMeterPosition, text } from "../lib/ui-text";

type RiskSummarySectionProps = {
  assessment: RiskAssessmentResponse | null;
  combinedRisk: string | null;
  riskOverlay: ReturnType<typeof riskOverlayPresentation>;
  riskSummaryHeading: string;
  riskSummaryBasisLine: string | null;
  profileBasisText: ReturnType<typeof getProfileBasisText>;
  profilePreviewState: ReturnType<typeof getProfilePreviewState>;
};

export function RiskSummarySection({
  assessment,
  combinedRisk,
  riskOverlay,
  riskSummaryHeading,
  riskSummaryBasisLine,
  profileBasisText,
  profilePreviewState,
}: RiskSummarySectionProps) {
  return (
    <section className="panel-section risk-summary" data-testid="risk-summary">
      <div className="section-heading">
        <span className="section-kicker">{text.riskSummary}</span>
        <strong>{riskSummaryHeading}</strong>
      </div>
      <div className="risk-meter" aria-label={text.riskMeter}>
        <span style={{ left: riskMeterPosition(combinedRisk ?? undefined) }} />
      </div>
      {riskSummaryBasisLine ? (
        <p className="risk-summary-basis">{riskSummaryBasisLine}</p>
      ) : null}
      {assessment ? (
        <p className="risk-overlay-note">
          地圖罩色：{riskOverlay.level}（{riskOverlay.colorName}，透明度 85%）
        </p>
      ) : null}
      {assessment ? (
        <dl className="risk-levels">
          <div className="risk-confidence-card">
            <dt>{text.confidence}</dt>
            <dd>{assessment.confidence.level}</dd>
            {profileBasisText.confidenceNote ? (
              <small className="risk-card-note">{profileBasisText.confidenceNote}</small>
            ) : null}
          </div>
          <div>
            <dt>{text.realtime}</dt>
            <dd>{assessment.realtime.level}</dd>
          </div>
          <div>
            <dt>{text.historical}</dt>
            <dd>{assessment.historical.level}</dd>
            {profileBasisText.historicalNote ? (
              <small className="risk-card-note">{profileBasisText.historicalNote}</small>
            ) : null}
          </div>
        </dl>
      ) : null}
      {profilePreviewState.isProfilePreview ? (
        <div className="profile-preview-banner" role="status">
          <strong>{profilePreviewState.label}</strong>
          <span>{profilePreviewState.message}</span>
        </div>
      ) : null}
      <p className="risk-explanation">{assessment ? assessment.explanation.summary : text.riskPlaceholder}</p>
      {assessment?.explanation.main_reasons.length ? (
        <ul className="risk-reasons">
          {assessment.explanation.main_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
