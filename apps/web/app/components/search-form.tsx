"use client";

import type { FormEvent } from "react";
import type { GeocodeCandidate } from "../lib/page-types";
import { geocodePrecisionLabel, radiusOptions, text } from "../lib/ui-text";

type SearchFormProps = {
  query: string;
  radius: number;
  isLoading: boolean;
  errorMessage: string | null;
  geocodeNotice: string | null;
  geocodeCandidates: GeocodeCandidate[];
  onQueryChange: (value: string) => void;
  onRadiusChange: (value: number) => void;
  onSelectGeocodeCandidate: (candidate: GeocodeCandidate) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function SearchForm({
  query,
  radius,
  isLoading,
  errorMessage,
  geocodeNotice,
  geocodeCandidates,
  onQueryChange,
  onRadiusChange,
  onSelectGeocodeCandidate,
  onSubmit,
}: SearchFormProps) {
  return (
    <form className="panel-section query-panel" onSubmit={onSubmit}>
      <details className="beta-limit-notice" role="note" open>
        <summary>
          <strong>{text.betaLimitTitle}</strong>
          <span>{text.betaLimitAction}</span>
        </summary>
        <p>{text.betaLimitMessage}</p>
      </details>

      <label className="field">
        <span>{text.searchPlace}</span>
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={text.searchPlaceholder}
        />
      </label>

      <fieldset className="radius-control">
        <legend>{text.radius}</legend>
        <div className="radius-options">
          {radiusOptions.map((option) => (
            <label key={option}>
              <input
                type="radio"
                name="radius"
                value={option}
                checked={radius === option}
                onChange={() => onRadiusChange(option)}
              />
              <span>{option >= 1000 ? `${option / 1000} 公里` : `${option} 公尺`}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <button className="primary-action" type="submit" disabled={isLoading}>
        {isLoading ? text.loading : text.assessRisk}
      </button>
      {isLoading ? (
        <p className="form-loading-hint" role="status">
          {text.queryLoadingHint}
        </p>
      ) : null}
      {errorMessage ? (
        <p className="form-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {geocodeNotice ? (
        <p className="form-notice" role="status">
          {geocodeNotice}
        </p>
      ) : null}
      {geocodeCandidates.length > 0 ? (
        <div className="geocode-candidates" role="group" aria-label={text.geocodeCandidatesLabel}>
          {geocodeCandidates.map((candidate, index) => (
            <button
              key={`${candidate.name}-${index}`}
              type="button"
              className="geocode-candidate"
              onClick={() => onSelectGeocodeCandidate(candidate)}
            >
              <span>{candidate.name}</span>
              <span>{geocodePrecisionLabel(candidate.precision)}</span>
            </button>
          ))}
        </div>
      ) : null}
    </form>
  );
}
