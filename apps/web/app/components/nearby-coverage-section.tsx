"use client";

import type { NearbyRealtimeCoverage } from "../lib/page-types";
import {
  formatDistanceMeters,
  nearbyCoverageLevelLabel,
  nearbyCoverageSummary,
} from "../lib/risk-display";
import { text } from "../lib/ui-text";

export function NearbyCoverageSection({
  coverage,
}: {
  coverage: NearbyRealtimeCoverage | null;
}) {
  const summary = nearbyCoverageSummary(coverage);
  const signals = coverage?.signal_breakdown.slice(0, 4) ?? [];

  return (
    <section
      className={`panel-section nearby-coverage nearby-coverage-tone-${summary.tone}`}
      data-testid="nearby-coverage"
    >
      <div className="section-heading">
        <span className="section-kicker">{text.nearbyCoverageKicker}</span>
        <strong>{summary.badge}</strong>
      </div>
      <p>{summary.summary}</p>
      {coverage?.county_level_note ? (
        <p className="nearby-coverage-note">
          <strong>{text.nearbyCoverageCountyNote}</strong>
          <span>{coverage.county_level_note}</span>
        </p>
      ) : null}
      {signals.length ? (
        <ul className="nearby-coverage-list">
          {signals.map((signal) => (
            <li key={signal.signal_type}>
              <div>
                <strong>{signal.label}</strong>
                <span>{nearbyCoverageLevelLabel(signal.coverage_level)}</span>
              </div>
              <span>{formatDistanceMeters(signal.nearest_distance_m)}</span>
            </li>
          ))}
        </ul>
      ) : coverage ? (
        <p className="nearby-coverage-note">{text.nearbyCoverageEmpty}</p>
      ) : null}
    </section>
  );
}
