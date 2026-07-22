"use client";

import type { RiskAssessmentResponse } from "../lib/page-types";
import type {
  getProfileBasisText,
  getProfilePreviewState,
  riskOverlayPresentation,
} from "../lib/risk-display";
import {
  normalizeRiskLevel,
  riskDecisionSummary,
  riskLevelTextColor,
  riskSummaryDecisionText,
} from "../lib/risk-display";
import { emergencyGuidance, riskMeterPosition, text } from "../lib/ui-text";

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
  const realtimeLevel = normalizeRiskLevel(assessment?.realtime.level);
  const historicalLevel = normalizeRiskLevel(assessment?.historical.level);
  const confidenceLevel = normalizeRiskLevel(assessment?.confidence.level);
  const decisionSummary = assessment
    ? riskDecisionSummary({
        confidenceLevel,
        historicalLevel,
        realtimeLevel,
      })
    : null;

  return (
    <section className="panel-section risk-summary" data-testid="risk-summary">
      <div className="section-heading">
        <span className="section-kicker">{text.riskSummary}</span>
        <h2>{riskSummaryHeading}</h2>
      </div>
      <p className="risk-emergency-notice" role="note">
        {emergencyGuidance.notice} {emergencyGuidance.callToAction}
        {" "}
        <a href={emergencyGuidance.officialLinkUrl} target="_blank" rel="noopener noreferrer">
          {emergencyGuidance.officialLinkLabel}
        </a>
        。
      </p>
      <p className="section-question">{text.riskQuestion}</p>
      <div className="risk-meter" aria-label={text.riskMeter}>
        <span style={{ left: riskMeterPosition(combinedRisk ?? undefined) }} />
      </div>
      {riskSummaryBasisLine ? (
        <p className="risk-summary-basis">{riskSummaryBasisLine}</p>
      ) : null}
      {decisionSummary ? (
        <div className="risk-verdict-strip" aria-label={text.riskDecisionSummary}>
          <span>{decisionSummary.driver}</span>
          <span>{decisionSummary.method}</span>
          <span>{decisionSummary.confidence}</span>
        </div>
      ) : null}
      {decisionSummary ? <p className="risk-decision-line">{decisionSummary.narrative}</p> : null}
      {assessment ? (
        <dl className="risk-levels">
          <div>
            <dt>{text.realtime}</dt>
            <dd style={{ color: riskLevelTextColor(realtimeLevel) }}>{realtimeLevel}</dd>
          </div>
          <div>
            <dt>{text.historical}</dt>
            <dd style={{ color: riskLevelTextColor(historicalLevel) }}>{historicalLevel}</dd>
          </div>
          <div className="risk-confidence-card">
            <dt>{text.confidence}</dt>
            <dd style={{ color: riskLevelTextColor(confidenceLevel) }}>{confidenceLevel}</dd>
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
      {assessment ? (
        <details className="risk-method-drawer" data-testid="risk-method-drawer">
          <summary>{text.riskMethodSummary}</summary>
          <p>
            {riskSummaryDecisionText({
              confidenceLevel,
              historicalLevel,
              realtimeLevel,
            })}
          </p>
          <dl className="risk-method-list">
            <div>
              <dt>{text.realtime}</dt>
              <dd>近 6 小時雨量、水位、官方警戒、通報或區域即時 profile；不是只看現在是否下雨。</dd>
            </div>
            <div>
              <dt>{text.historical}</dt>
              <dd>{profileBasisText.historicalNote ?? "淹水潛勢、災點與已審核事件；不是即時災情。"}</dd>
            </div>
            <div>
              <dt>{text.confidence}</dt>
              <dd>
                {profileBasisText.confidenceNote ??
                  "看來源可信度、資料筆數、時間新鮮度與覆蓋缺口；不是淹水機率。"}
              </dd>
            </div>
          </dl>
          {assessment.explanation.main_reasons.length ? (
            <ul className="risk-reasons">
              {assessment.explanation.main_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          <p className="risk-overlay-note">
            地圖罩色：{riskOverlay.level}（{riskOverlay.colorName}，透明度 85%）
          </p>
        </details>
      ) : null}
    </section>
  );
}
