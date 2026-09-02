"use client";

import type { HistoricalCoverageResponse, RiskAssessmentResponse } from "../lib/page-types";
import type {
  EvidenceItem,
  EvidenceStatus,
  HistoricalCoverageStatus,
  getEvidenceDisplayState,
  getProfileBasisText,
  getProfilePreviewState,
} from "../lib/risk-display";
import {
  evidenceDisplayText,
  evidenceSourceUrl,
  evidenceTimeSummary,
  historicalEvidenceVintage,
  formatConfidence,
  formatDistance,
  publicHistoricalEvidenceItems,
} from "../lib/risk-display";
import { sourceTypeLabel, text } from "../lib/ui-text";

type EvidenceSectionProps = {
  assessment: RiskAssessmentResponse | null;
  displayedEvidence: EvidenceItem[];
  evidenceDisplayState: ReturnType<typeof getEvidenceDisplayState>;
  hiddenHistoricalNewsCount: number;
  historicalItems: EvidenceItem[];
  historicalNextCursor: string | null;
  historicalStatus: EvidenceStatus;
  historicalErrorMessage: string | null;
  historicalCanRetry: boolean;
  historyCoverage: HistoricalCoverageResponse | null;
  historyCoverageStatus: HistoricalCoverageStatus;
  profileBasisText: ReturnType<typeof getProfileBasisText>;
  profilePreviewState: ReturnType<typeof getProfilePreviewState>;
  onExpandHistory: () => void;
  onLoadMoreHistory: () => void;
  onRetryHistory: () => void;
};

export function EvidenceSection({
  assessment,
  displayedEvidence,
  evidenceDisplayState,
  hiddenHistoricalNewsCount,
  historicalItems,
  historicalNextCursor,
  historicalStatus,
  historicalErrorMessage,
  historicalCanRetry,
  historyCoverage,
  historyCoverageStatus,
  profileBasisText,
  profilePreviewState,
  onExpandHistory,
  onLoadMoreHistory,
  onRetryHistory,
}: EvidenceSectionProps) {
  const currentOrContextEvidence = displayedEvidence.filter(
    (item) => item.evidence_scope !== "historical",
  );
  const previewHistoricalEvidence = displayedEvidence.filter(
    (item) => item.evidence_scope === "historical",
  );
  const historicalEvidenceById = new Map<string, EvidenceItem>();
  for (const item of [...previewHistoricalEvidence, ...historicalItems]) {
    historicalEvidenceById.set(item.id, item);
  }
  const [latestHistoricalEvidence, ...olderHistoricalEvidence] =
    publicHistoricalEvidenceItems([...historicalEvidenceById.values()]);
  const displayedEvidenceCount =
    currentOrContextEvidence.length +
    (latestHistoricalEvidence ? 1 : 0) +
    olderHistoricalEvidence.length;

  return (
    <section className="panel-section evidence-panel" data-testid="evidence-panel">
      <details className="evidence-drawer" data-testid="evidence-drawer">
        <summary>
          <span className="section-kicker">{text.evidenceKicker}</span>
          <strong>{text.evidenceTitle}</strong>
          {assessment ? (
            <span>
              {displayedEvidenceCount} {text.evidenceCountSuffix}
            </span>
          ) : null}
        </summary>
        {assessment ? (
          <div className="evidence-drawer-body">
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
              <>
                {currentOrContextEvidence.length ? (
                  <EvidenceList items={currentOrContextEvidence} />
                ) : null}
              </>
            ) : evidenceDisplayState.showEmpty ? (
              <div className="evidence-empty">
                {profilePreviewState.isProfilePreview ? text.profileEvidenceEmpty : text.evidenceEmpty}
              </div>
            ) : null}

            <section className="historical-evidence" data-testid="historical-evidence">
              <header>
                <strong>{text.evidenceHistoryTitle}</strong>
                <span>{text.evidenceHistoryOrder}</span>
              </header>
              <HistoryCoverageSummary
                coverage={historyCoverage}
                status={historyCoverageStatus}
              />
              {latestHistoricalEvidence ? (
                <EvidenceList items={[latestHistoricalEvidence]} />
              ) : (
                <p className="historical-evidence-empty">{text.evidenceHistoryPreviewEmpty}</p>
              )}
              <details
                className="historical-evidence-more"
                data-testid="historical-evidence-more"
                onToggle={(event) => {
                  if (event.currentTarget.open) onExpandHistory();
                }}
              >
                <summary>
                  {latestHistoricalEvidence
                    ? text.evidenceHistoryExpand
                    : text.evidenceHistoryOpen}
                </summary>
                <div className="historical-evidence-more-body" aria-live="polite">
                  {olderHistoricalEvidence.length ? (
                    <EvidenceList items={olderHistoricalEvidence} />
                  ) : null}
                  {historicalStatus === "loading" ? (
                    <p className="historical-evidence-state" role="status">
                      {text.evidenceHistoryLoading}
                    </p>
                  ) : null}
                  {historicalStatus === "error" ? (
                    <div className="historical-evidence-state is-error" role="alert">
                      <span>{historicalErrorMessage ?? text.evidenceHistoryError}</span>
                      {historicalCanRetry ? (
                        <button type="button" onClick={onRetryHistory}>
                          {text.evidenceHistoryRetry}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  {historicalStatus === "ready" && !olderHistoricalEvidence.length ? (
                    <p className="historical-evidence-state">
                      {text.evidenceHistoryNoMore}
                    </p>
                  ) : null}
                  {historicalStatus === "ready" && historicalNextCursor ? (
                    <button
                      type="button"
                      className="historical-evidence-load-more"
                      onClick={onLoadMoreHistory}
                    >
                      {text.evidenceHistoryLoadMore}
                    </button>
                  ) : null}
                </div>
              </details>
            </section>

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
        ) : null}
      </details>
    </section>
  );
}

function HistoryCoverageSummary({
  coverage,
  status,
}: {
  coverage: HistoricalCoverageResponse | null;
  status: HistoricalCoverageStatus;
}) {
  if (status === "loading") {
    return (
      <div className="history-coverage-summary is-loading" role="status">
        {text.evidenceHistoryCoverageLoading}
      </div>
    );
  }

  if (status === "error" || status === "unavailable" || !coverage) {
    return (
      <div className="history-coverage-summary is-incomplete" role="status">
        <strong>{text.evidenceHistoryCoverageUnavailable}</strong>
        <span>{text.evidenceHistoryAbsenceWarning}</span>
      </div>
    );
  }

  const summary = coverage.summary;
  const expected = summary.expected_cell_count || summary.lookback_years || 15;
  const knownGapCount =
    summary.known_gap_cell_count ??
    coverage.cells.filter((cell) =>
      ["failed", "not_published", "partial", "stale"].includes(cell.status),
    ).length;
  const auditComplete =
    summary.audit_complete ??
    (summary.unresolved_cell_count === 0 && summary.missing_persisted_cell_count === 0);
  // The legacy `coverage_complete` only means every cell was audited and may
  // still be true when every source says `not_published`.  Fail closed unless
  // the newer data-completeness field is explicitly true.
  const dataCoverageComplete = summary.data_coverage_complete ?? false;
  const complete = auditComplete && dataCoverageComplete && knownGapCount === 0;

  return (
    <div
      className={`history-coverage-summary ${complete ? "is-complete" : "is-incomplete"}`}
      data-testid="history-coverage-summary"
      role="status"
    >
      <strong>
        {complete
          ? text.evidenceHistoryCoverageComplete
          : text.evidenceHistoryCoverageIncomplete}
      </strong>
      <span>
        已查核 {summary.resolved_cell_count} / {expected} 格
        {!complete
          ? `；已知缺口 ${knownGapCount} 格；待查核 ${summary.unresolved_cell_count} 格`
          : ""}
      </span>
      <small>
        {summary.start_year}–{summary.end_year} · {text.evidenceHistoryAbsenceWarning}
      </small>
    </div>
  );
}

function EvidenceList({ items }: { items: EvidenceItem[] }) {
  return (
    <ul className="evidence-list">
      {items.map((item) => (
        <EvidenceCard key={item.id} item={item} />
      ))}
    </ul>
  );
}

function EvidenceCard({ item }: { item: EvidenceItem }) {
  const displayText = evidenceDisplayText(item);
  const sourceUrl = evidenceSourceUrl(item);
  const historicalVintage = historicalEvidenceVintage(item);

  return (
    <li className="evidence-card">
      <div className="evidence-card-header">
        <div>
          <span>{sourceTypeLabel(item.source_type)}</span>
          <strong>{displayText.title}</strong>
          {historicalVintage ? (
            <small
              className={
                historicalVintage.isOld ? "evidence-vintage is-old" : "evidence-vintage"
              }
            >
              {historicalVintage.label}
            </small>
          ) : null}
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
      <dl className="evidence-meta">
        <div>
          <dt>{text.evidenceDistance}</dt>
          <dd>{formatDistance(item.distance_to_query_m)}</dd>
        </div>
        <div>
          <dt>
            {item.evidence_scope === "historical"
              ? text.evidenceHistoricalTime
              : text.evidenceTime}
          </dt>
          <dd>{evidenceTimeSummary(item)}</dd>
        </div>
        <div>
          <dt>
            {item.evidence_scope === "historical"
              ? text.evidenceHistoricalConfidence
              : text.evidenceConfidence}
          </dt>
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
      <details className="evidence-card-detail">
        <summary>{text.evidenceUsage}</summary>
        <p>{displayText.summary}</p>
        <span className="evidence-card-purpose">{displayText.purpose}</span>
      </details>
    </li>
  );
}
