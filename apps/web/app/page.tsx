"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { DiagnosticsSection } from "./components/diagnostics-section";
import { EvidenceSection } from "./components/evidence-section";
import { RiskSummarySection } from "./components/risk-summary-section";
import { SearchForm } from "./components/search-form";
import { UserReportSection } from "./components/user-report-section";
import { useFloodMap } from "./components/use-flood-map";
import { apiBaseUrl, getJson, postJson, publicApiErrorMessage } from "./lib/api-client";
import { INITIAL_COORDINATE, INITIAL_RADIUS, targetZoom } from "./lib/map-setup";
import type {
  Coordinate,
  EvidenceListResponse,
  GeocodeResponse,
  QueryMode,
  RiskAssessmentResponse,
} from "./lib/page-types";
import {
  buildRiskAssessmentPayload,
  buildLayerDisplayState,
  buildUserReportPayload,
  combinedRiskLevel,
  formatCoordinate,
  getEvidenceDisplayState,
  getProfileBasisText,
  getProfilePreviewState,
  getUserReportSubmissionDisplayState,
  latestNewsEvidenceLinks,
  latestNewsLinksFreshnessSourceId,
  riskOverlayPresentation,
  riskSummaryBasis,
  riskSummaryTitle,
  selectEvidenceItems,
  shouldFetchEvidenceList,
} from "./lib/risk-display";
import type { EvidenceItem, EvidenceStatus, UserReportSubmissionStatus } from "./lib/risk-display";
import {
  coordinateSummary,
  geocodeCandidateNotice,
  hasInsufficientRiskData,
  text,
} from "./lib/ui-text";
import { postUserReport, UserReportSubmitError } from "./lib/user-reports";

const API_BASE_URL = apiBaseUrl;
const IDLE_RISK_OVERLAY = riskOverlayPresentation(null, false);
const USER_REPORTS_PUBLIC_ENABLED = process.env.NEXT_PUBLIC_USER_REPORTS_ENABLED === "true";
const MIN_GEOCODE_CONFIDENCE = 0.65;

export default function HomePage() {
  const requestIdRef = useRef(0);
  const searchAbortRef = useRef<AbortController | null>(null);
  const [query, setQuery] = useState(text.taipeiMainStation);
  const [radius, setRadius] = useState(INITIAL_RADIUS);
  const [coordinate, setCoordinate] = useState<Coordinate>(INITIAL_COORDINATE);
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);
  const [evidenceStatus, setEvidenceStatus] = useState<EvidenceStatus>("idle");
  const [isLoading, setIsLoading] = useState(false);
  const [queryMode, setQueryMode] = useState<QueryMode>("search");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [geocodeNotice, setGeocodeNotice] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState(text.taipeiMainStation);
  const [reportSummary, setReportSummary] = useState("");
  const [reportStatus, setReportStatus] = useState<UserReportSubmissionStatus>("idle");

  const displayedEvidence = useMemo(
    () =>
      assessment
        ? selectEvidenceItems(assessment.evidence, evidenceItems, evidenceStatus)
        : [],
    [assessment, evidenceItems, evidenceStatus],
  );
  const latestNewsLinks = useMemo(
    () => latestNewsEvidenceLinks(displayedEvidence, 3),
    [displayedEvidence],
  );
  const latestNewsLinkSourceId = useMemo(
    () => latestNewsLinksFreshnessSourceId(assessment?.data_freshness ?? [], displayedEvidence),
    [assessment?.data_freshness, displayedEvidence],
  );
  const evidenceDisplayState = getEvidenceDisplayState(
    evidenceStatus,
    displayedEvidence.length,
  );
  const layerDisplayState = assessment
    ? buildLayerDisplayState({
        dataFreshness: assessment.data_freshness,
        evidenceItems,
        layers: assessment.map_layers ?? assessment.layers,
      })
    : { hasTileContract: false, items: [], status: "pending" as const };
  const profilePreviewState = getProfilePreviewState(assessment);
  const profileBasisText = getProfileBasisText(assessment);
  const hasAssessment = Boolean(assessment);
  const realtimeRiskLevel = assessment?.realtime.level ?? null;
  const historicalRiskLevel = assessment?.historical.level ?? null;
  const combinedRisk = useMemo(
    () =>
      hasAssessment
        ? combinedRiskLevel(realtimeRiskLevel, historicalRiskLevel)
        : null,
    [hasAssessment, historicalRiskLevel, realtimeRiskLevel],
  );
  const riskOverlay = useMemo(
    () => riskOverlayPresentation(combinedRisk, hasAssessment),
    [combinedRisk, hasAssessment],
  );
  const riskSummaryHeading = assessment
    ? hasInsufficientRiskData(assessment)
      ? text.insufficientData
      : riskSummaryTitle(realtimeRiskLevel, historicalRiskLevel)
    : text.pendingData;
  const riskSummaryBasisLine = assessment
    ? riskSummaryBasis(realtimeRiskLevel, historicalRiskLevel)
    : null;
  const currentSummary = useMemo(
    () => coordinateSummary(coordinate, locationLabel),
    [coordinate, locationLabel],
  );
  const userReportPayload = useMemo(
    () => buildUserReportPayload(coordinate, reportSummary),
    [coordinate, reportSummary],
  );
  const reportDisplayState = getUserReportSubmissionDisplayState(reportStatus);
  const isReportLoading = reportStatus === "loading";

  const { mapContainerRef, mapRef, isMapReady } = useFloodMap({
    coordinate,
    radius,
    riskOverlay,
    idleRiskOverlay: IDLE_RISK_OVERLAY,
    onMapClick: (point) => {
      searchAbortRef.current?.abort();
      searchAbortRef.current = null;
      setCoordinate({
        lat: point.lat,
        lng: point.lng,
        source: "map",
      });
      setQuery("");
      setQueryMode("map");
      setLocationLabel(text.mapSource);
      requestIdRef.current += 1;
      setAssessment(null);
      setEvidenceItems([]);
      setEvidenceStatus("idle");
      setIsLoading(false);
      setErrorMessage(null);
      setGeocodeNotice(null);
    },
  });
  const statusText = isMapReady ? text.mapStatusReady : text.mapStatusLoading;

  useEffect(() => {
    return () => {
      searchAbortRef.current?.abort();
      searchAbortRef.current = null;
    };
  }, []);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchAbortRef.current?.abort();
    const requestController = new AbortController();
    searchAbortRef.current = requestController;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setIsLoading(true);
    setErrorMessage(null);
    setGeocodeNotice(null);

    const normalized = query.trim();
    const shouldResolveSearchQuery = queryMode === "search" && normalized.length > 0;
    let target = coordinate;
    let resolvedLocationText: string | null = shouldResolveSearchQuery ? normalized : null;

    try {
      if (shouldResolveSearchQuery) {
        const geocode = await postJson<GeocodeResponse>("/v1/geocode", {
          input_type: "address",
          limit: 1,
          query: normalized,
        }, {
          signal: requestController.signal,
        });
        const candidate = geocode.candidates[0];
        if (!candidate || candidate.confidence < MIN_GEOCODE_CONFIDENCE) {
          setAssessment(null);
          setEvidenceItems([]);
          setEvidenceStatus("idle");
          setErrorMessage(text.noGeocodeResult);
          return;
        }

        target = {
          lat: candidate.point.lat,
          lng: candidate.point.lng,
          source: "search",
        };
        setCoordinate(target);
        setLocationLabel(candidate.name);
        setGeocodeNotice(geocodeCandidateNotice(candidate));
        resolvedLocationText =
          normalized === candidate.name ? candidate.name : `${normalized}｜${candidate.name}`;
        mapRef.current?.resize();
        mapRef.current?.flyTo({
          center: [target.lng, target.lat],
          duration: 900,
          essential: true,
          zoom: targetZoom(target, radius),
        });

        if (candidate.requires_confirmation) {
          setGeocodeNotice(`${geocodeCandidateNotice(candidate)}。${text.geocodeNeedsConfirmation}`);
        }
      }

      const risk = await postJson<RiskAssessmentResponse>(
        "/v1/risk/assess",
        buildRiskAssessmentPayload(target, radius, resolvedLocationText),
        {
          signal: requestController.signal,
        },
      );
      if (requestIdRef.current !== requestId) return;
      setAssessment(risk);
      setEvidenceItems(risk.evidence);
      setIsLoading(false);

      if (shouldFetchEvidenceList(risk.assessment_id)) {
        setEvidenceStatus("loading");
        try {
          const evidence = await getJson<EvidenceListResponse>(
            `/v1/evidence/${encodeURIComponent(risk.assessment_id)}?page_size=100`,
            {
              signal: requestController.signal,
            },
          );
          if (requestIdRef.current !== requestId) return;
          setEvidenceItems(evidence.items);
          setEvidenceStatus("ready");
        } catch {
          if (requestIdRef.current !== requestId) return;
          setEvidenceStatus("error");
        }
      } else {
        setEvidenceStatus("ready");
      }
    } catch (error) {
      if (!requestController.signal.aborted && requestIdRef.current === requestId) {
        setErrorMessage(
          publicApiErrorMessage(error, {
            fallback: text.queryFailed,
            notFoundMessage: text.noGeocodeResult,
          }),
        );
      }
    } finally {
      if (searchAbortRef.current === requestController) {
        searchAbortRef.current = null;
      }
      if (requestIdRef.current === requestId) {
        setIsLoading(false);
      }
    }
  }

  async function handleUserReportSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const report = buildUserReportPayload(coordinate, reportSummary);
    if (!report.isValid) {
      setReportStatus("idle");
      return;
    }

    setReportStatus("loading");
    try {
      const response = await postUserReport(API_BASE_URL, report.payload);
      if (response.status === "pending") {
        setReportStatus("success");
        setReportSummary("");
      } else {
        setReportStatus("error");
      }
    } catch (error) {
      if (error instanceof UserReportSubmitError && error.code === "feature_disabled") {
        setReportStatus("feature_disabled");
      } else if (error instanceof UserReportSubmitError && error.code === "rate_limited") {
        setReportStatus("rate_limited");
      } else if (error instanceof UserReportSubmitError && error.code === "repository_unavailable") {
        setReportStatus("repository_unavailable");
      } else {
        setReportStatus("error");
      }
    }
  }

  return (
    <main className="app-shell">
      <section className="map-workspace" aria-label={text.appLabel}>
        <header className="top-bar">
          <div>
            <p className="eyebrow">{text.eyebrow}</p>
            <h1>{text.title}</h1>
          </div>
          <div className="status-pill" aria-label={text.mapStatus}>
            {statusText}
          </div>
        </header>

        <div className="map-shell" aria-label={text.mapLabel}>
          <div ref={mapContainerRef} className="map-canvas" />
          {!isMapReady ? (
            <div className="map-loading-fallback" aria-hidden="true">
              <div className="taiwan-fallback-shape" />
            </div>
          ) : null}
          <div className="map-hint">{text.mapHint}</div>
          <div className="map-coordinate-card">
            <span>{currentSummary}</span>
            <strong>
              {formatCoordinate(coordinate.lat)}, {formatCoordinate(coordinate.lng)}
            </strong>
          </div>
        </div>
      </section>

      <aside className="side-panel" aria-label={text.panelLabel}>
        <SearchForm
          query={query}
          radius={radius}
          isLoading={isLoading}
          errorMessage={errorMessage}
          geocodeNotice={geocodeNotice}
          onQueryChange={(value) => {
            setQuery(value);
            setQueryMode("search");
          }}
          onRadiusChange={setRadius}
          onSubmit={handleSearch}
        />

        <RiskSummarySection
          assessment={assessment}
          combinedRisk={combinedRisk}
          riskOverlay={riskOverlay}
          riskSummaryHeading={riskSummaryHeading}
          riskSummaryBasisLine={riskSummaryBasisLine}
          profileBasisText={profileBasisText}
          profilePreviewState={profilePreviewState}
        />

        <EvidenceSection
          assessment={assessment}
          displayedEvidence={displayedEvidence}
          evidenceDisplayState={evidenceDisplayState}
          profileBasisText={profileBasisText}
          profilePreviewState={profilePreviewState}
        />

        <UserReportSection
          enabled={USER_REPORTS_PUBLIC_ENABLED}
          coordinate={coordinate}
          reportSummary={reportSummary}
          reportStatus={reportStatus}
          reportDisplayState={reportDisplayState}
          isReportValid={userReportPayload.isValid}
          isReportLoading={isReportLoading}
          onSummaryChange={(value) => {
            setReportSummary(value);
            if (reportStatus !== "loading") setReportStatus("idle");
          }}
          onSubmit={handleUserReportSubmit}
        />

        <DiagnosticsSection
          assessment={assessment}
          coordinate={coordinate}
          radius={radius}
          currentSummary={currentSummary}
          layerDisplayState={layerDisplayState}
          latestNewsLinks={latestNewsLinks}
          latestNewsLinkSourceId={latestNewsLinkSourceId}
        />
      </aside>
    </main>
  );
}
