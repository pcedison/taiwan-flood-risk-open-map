"use client";

import type { FormEvent } from "react";
import type { Coordinate } from "../lib/page-types";
import type { UserReportSubmissionStatus, getUserReportSubmissionDisplayState } from "../lib/risk-display";
import { formatCoordinate } from "../lib/risk-display";
import { text } from "../lib/ui-text";

type UserReportSectionProps = {
  enabled: boolean;
  coordinate: Coordinate;
  reportSummary: string;
  reportStatus: UserReportSubmissionStatus;
  reportDisplayState: ReturnType<typeof getUserReportSubmissionDisplayState>;
  isReportValid: boolean;
  isReportLoading: boolean;
  onSummaryChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function UserReportSection({
  enabled,
  coordinate,
  reportSummary,
  reportDisplayState,
  isReportValid,
  isReportLoading,
  onSummaryChange,
  onSubmit,
}: UserReportSectionProps) {
  if (!enabled) {
    return (
      <section className="panel-section user-report-panel" data-testid="user-report-panel" aria-label={text.reportDisabledTitle}>
        <details className="report-disabled-drawer">
          <summary>
            <span className="section-kicker">{text.publicReportKicker}</span>
            <strong>{text.reportDisabledTitle}</strong>
            <small>{text.reportDisabledAction}</small>
          </summary>
          <p>{text.reportDisabledMessage}</p>
        </details>
      </section>
    );
  }

  return (
    <form className="panel-section user-report-panel" data-testid="user-report-panel" onSubmit={onSubmit}>
      <div className="section-heading">
        <span className="section-kicker">{text.publicReportKicker}</span>
        <strong>{text.publicReportTitle}</strong>
      </div>
      <div className="report-location">
        <span>{text.reportLocation}</span>
        <strong>
          {formatCoordinate(coordinate.lat)}, {formatCoordinate(coordinate.lng)}
        </strong>
      </div>
      <label className="field">
        <span>{text.reportObservation}</span>
        <textarea
          value={reportSummary}
          onChange={(event) => onSummaryChange(event.target.value)}
          placeholder={text.reportPlaceholder}
          maxLength={500}
          rows={4}
        />
      </label>
      {!isReportValid && reportSummary.length > 0 ? (
        <p className="form-error">{text.reportValidation}</p>
      ) : null}
      <button
        className="primary-action"
        type="submit"
        disabled={isReportLoading || !isReportValid}
      >
        {isReportLoading ? reportDisplayState.submitLabel : text.reportSubmit}
      </button>
      {reportDisplayState.message ? (
        <p className={`report-state report-state-${reportDisplayState.kind}`} role="status">
          {reportDisplayState.message}
        </p>
      ) : null}
    </form>
  );
}
