"use client";

import type { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { getBasemapStyleConfig } from "./lib/basemap-style";
import {
  buildRiskAssessmentPayload,
  buildLayerDisplayState,
  buildUserReportPayload,
  evidenceSourceUrl,
  evidenceTimeSummary,
  formatConfidence,
  formatCoordinate,
  formatDateTime,
  formatDistance,
  getEvidenceDisplayState,
  getUserReportSubmissionDisplayState,
  selectEvidenceItems,
  shouldFetchEvidenceList,
} from "./lib/risk-display";
import type { EvidenceItem, EvidencePreview, EvidenceStatus, UserReportSubmissionStatus } from "./lib/risk-display";
import type { LayerContractItem } from "./lib/risk-display";
import { postUserReport, UserReportSubmitError } from "./lib/user-reports";

type CoordinateSource = "default" | "map" | "search";

type Coordinate = {
  lat: number;
  lng: number;
  source: CoordinateSource;
};

type GeocodeResponse = {
  candidates: Array<{
    confidence: number;
    limitations?: string[];
    matched_query?: string | null;
    name: string;
    point: {
      lat: number;
      lng: number;
    };
    precision?: "exact_address" | "road_or_lane" | "poi" | "admin_area" | "map_click" | "unknown";
    requires_confirmation?: boolean;
    source: string;
  }>;
};

type EvidenceListResponse = {
  assessment_id: string;
  items: EvidenceItem[];
  next_cursor: string | null;
};

type RiskAssessmentResponse = {
  assessment_id: string;
  realtime: {
    level: string;
  };
  historical: {
    level: string;
  };
  confidence: {
    level: string;
  };
  explanation: {
    summary: string;
    main_reasons: string[];
    missing_sources: string[];
  };
  evidence: EvidencePreview[];
  data_freshness: Array<{
    source_id: string;
    name: string;
    health_status: string;
    observed_at: string | null;
    ingested_at: string | null;
    message: string | null;
  }>;
  query_heat: {
    attention_level: string;
    updated_at: string;
  };
  layers?: LayerContractItem[];
  map_layers?: LayerContractItem[];
};

type RadiusFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: Record<string, never>;
    geometry: {
      type: "Polygon";
      coordinates: number[][][];
    };
  }>;
};

type MapFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: Record<string, string>;
    geometry: {
      type: "Point";
      coordinates: number[];
    };
  }>;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
let activePmtilesProtocol: Protocol | null = null;

const text = {
  appLabel: "台灣淹水風險地圖",
  eyebrow: "公開資料風險查詢",
  title: "台灣淹水風險開放地圖",
  mapStatus: "地圖狀態",
  mapStatusLoading: "底圖載入中",
  mapStatusReady: "互動地圖",
  mapHint: "可拖曳縮放，也可以直接點選地圖更新查詢座標",
  mapLabel: "台灣互動地圖，點選地圖可設定查詢座標",
  panelLabel: "風險查詢面板",
  searchPlace: "搜尋地點",
  searchPlaceholder: "輸入地標、地址或行政區",
  radius: "分析半徑",
  assessRisk: "查詢風險",
  currentCoordinate: "目前座標",
  latitude: "緯度",
  longitude: "經度",
  riskSummary: "風險摘要",
  pendingData: "尚未查詢",
  riskPlaceholder: "搜尋地點或點選地圖後，按下查詢即可整理半徑內公開淹水相關資料。",
  riskMeter: "風險等級",
  realtime: "即時",
  historical: "歷史參考",
  confidence: "資料信心",
  evidenceKicker: "資料證據",
  evidenceTitle: "附近資料線索",
  evidenceSource: "來源",
  evidenceConfidence: "信心",
  evidenceDistance: "距離",
  evidenceObservedAt: "觀測",
  evidenceCountSuffix: "筆來源",
  evidenceTime: "觀測 / 發布",
  evidenceUrl: "來源連結",
  evidenceOpenSource: "開啟來源",
  evidenceMissingUrl: "未提供連結",
  evidenceEmpty: "本次查詢尚未回傳可列出的資料佐證。",
  evidenceLoading: "正在載入完整資料佐證。",
  evidenceError: "完整資料佐證載入失敗，先顯示風險摘要中的預覽資料。",
  limitations: "資料限制",
  evidenceFlood: "尚未查詢附近淹水事件。",
  evidenceRain: "查詢後會顯示雨量、水位與淹水潛勢資料。",
  evidenceTerrain: "公開資料會保留來源與時間，方便回頭查證。",
  freshness: "資料新鮮度",
  layers: "圖層管線",
  layerReady: "可顯示",
  layerLimited: "部分可用",
  layerEmpty: "無圖層資料",
  layerPending: "等待查詢",
  layerContract: "API 圖層合約",
  layerFallback: "由 freshness / evidence 推導",
  layerNoTile: "尚未提供 tile URL",
  layerNoData: "本次查詢未回傳可展示的圖層或資料來源。",
  layerFeatureCount: "資料筆數",
  offline: "尚未連線",
  online: "已連線",
  loading: "查詢中",
  queryFailed: "查詢失敗，請稍後再試。",
  noGeocodeResult: "找不到這個地點，請換一個關鍵字再試。",
  geocodeNeedsConfirmation: "定位只到較粗範圍，請改輸入道路或門牌，或直接點選地圖後再查詢。",
  geocodePrecision: "定位精度",
  lastSync: "最後同步：--",
  freshnessNote: "查詢後會顯示資料來源的最新狀態。",
  defaultSource: "預設位置",
  mapSource: "地圖點選",
  searchSource: "搜尋定位",
  taipeiMainStation: "台北火車站",
  locatedPrefix: "已定位",
  selectedPrefix: "已選取",
};

const sourceLabels: Record<CoordinateSource, string> = {
  default: text.defaultSource,
  map: text.mapSource,
  search: text.searchSource,
};

const radiusOptions = [300, 500, 1000, 2000];
const MIN_GEOCODE_CONFIDENCE = 0.65;
const INITIAL_RADIUS = 500;
const INITIAL_COORDINATE: Coordinate = {
  lat: 25.04776,
  lng: 121.51706,
  source: "default",
};
const TAIWAN_OVERVIEW = {
  lat: 23.72,
  lng: 120.96,
  zoom: 7.2,
};
const TAIWAN_CITY_GEOJSON: MapFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "Taipei" },
      geometry: { type: "Point", coordinates: [121.51706, 25.04776] },
    },
    {
      type: "Feature",
      properties: { name: "Taichung" },
      geometry: { type: "Point", coordinates: [120.68686, 24.13716] },
    },
    {
      type: "Feature",
      properties: { name: "Kaohsiung" },
      geometry: { type: "Point", coordinates: [120.30203, 22.63937] },
    },
    {
      type: "Feature",
      properties: { name: "Hualien" },
      geometry: { type: "Point", coordinates: [121.60681, 23.99107] },
    },
  ],
};

const healthLabels: Record<string, string> = {
  healthy: "正常",
  degraded: "延遲",
  failed: "失敗",
  disabled: "停用",
  unknown: "未知",
};

const healthLabel = (value: string) => healthLabels[value] ?? value;

const geocodePrecisionLabels: Record<string, string> = {
  admin_area: "行政區",
  exact_address: "門牌",
  map_click: "地圖點選",
  poi: "地標 / POI",
  road_or_lane: "道路 / 巷道",
  unknown: "未知",
};

const geocodePrecisionLabel = (value?: string) =>
  geocodePrecisionLabels[value ?? "unknown"] ?? geocodePrecisionLabels.unknown;

const geocodeCandidateNotice = (candidate: GeocodeResponse["candidates"][number]) => {
  const parts = [`${text.geocodePrecision}：${geocodePrecisionLabel(candidate.precision)}`];
  if (candidate.matched_query && candidate.matched_query !== candidate.name) {
    parts.push(`匹配：${candidate.matched_query}`);
  }
  if (candidate.limitations?.length) {
    parts.push(candidate.limitations.join(" "));
  }
  return parts.join("。");
};

const layerAvailabilityLabels: Record<string, string> = {
  available: text.layerReady,
  empty: text.layerEmpty,
  limited: text.layerLimited,
  pending: text.layerPending,
  unavailable: "不可用",
};

const layerAvailabilityLabel = (value: string) => layerAvailabilityLabels[value] ?? value;

const sourceTypeLabels: Record<string, string> = {
  official: "官方公開資料",
  news: "公開新聞",
  derived: "衍生資料",
  user_report: "使用者通報",
};

const sourceTypeLabel = (value: string) => sourceTypeLabels[value] ?? value;

const riskMeterPosition = (level?: string) => {
  if (level === "低") return "16%";
  if (level === "中") return "50%";
  if (level === "高") return "75%";
  if (level === "極高") return "92%";
  return "8%";
};

const targetZoom = (coordinate: Coordinate, radius: number) => {
  if (coordinate.source === "default") return TAIWAN_OVERVIEW.zoom;
  if (coordinate.source === "search") return radius <= 500 ? 15.2 : 14.2;
  return radius <= 500 ? 14.2 : 13.2;
};

const targetCenter = (coordinate: Coordinate): [number, number] =>
  coordinate.source === "default"
    ? [TAIWAN_OVERVIEW.lng, TAIWAN_OVERVIEW.lat]
    : [coordinate.lng, coordinate.lat];

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function createRadiusFeature(coordinate: Coordinate, radiusMeters: number): RadiusFeatureCollection {
  const steps = 96;
  const earthRadius = 6371008.8;
  const angularDistance = radiusMeters / earthRadius;
  const latRad = (coordinate.lat * Math.PI) / 180;
  const lngRad = (coordinate.lng * Math.PI) / 180;
  const ring: number[][] = [];

  for (let index = 0; index <= steps; index += 1) {
    const bearing = (index / steps) * Math.PI * 2;
    const lat = Math.asin(
      Math.sin(latRad) * Math.cos(angularDistance) +
        Math.cos(latRad) * Math.sin(angularDistance) * Math.cos(bearing),
    );
    const lng =
      lngRad +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latRad),
        Math.cos(angularDistance) - Math.sin(latRad) * Math.sin(lat),
      );

    ring.push([(lng * 180) / Math.PI, (lat * 180) / Math.PI]);
  }

  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [ring],
        },
      },
    ],
  };
}

function createMarkerElement() {
  const marker = document.createElement("div");
  marker.className = "map-marker";
  const inner = document.createElement("span");
  marker.append(inner);
  return marker;
}

function registerPmtilesProtocol(maplibregl: typeof import("maplibre-gl")) {
  const protocol = new Protocol();

  try {
    maplibregl.removeProtocol("pmtiles");
  } catch {
    // MapLibre does not expose a protocol registry check, so cleanup is best-effort.
  }

  maplibregl.addProtocol("pmtiles", protocol.tile);
  activePmtilesProtocol = protocol;

  return () => {
    if (activePmtilesProtocol !== protocol) return;
    maplibregl.removeProtocol("pmtiles");
    activePmtilesProtocol = null;
  };
}

function ensureTaiwanCityDots(map: MapLibreMap) {
  if (!map.getSource("taiwan-cities")) {
    map.addSource("taiwan-cities", {
      type: "geojson",
      data: TAIWAN_CITY_GEOJSON,
    });
  }

  if (!map.getLayer("taiwan-city-dots")) {
    map.addLayer({
      id: "taiwan-city-dots",
      type: "circle",
      source: "taiwan-cities",
      paint: {
        "circle-color": "#0d5f4b",
        "circle-radius": 4,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });
  }
}

export default function HomePage() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const requestIdRef = useRef(0);
  const [query, setQuery] = useState(text.taipeiMainStation);
  const [radius, setRadius] = useState(INITIAL_RADIUS);
  const [coordinate, setCoordinate] = useState<Coordinate>(INITIAL_COORDINATE);
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);
  const [evidenceStatus, setEvidenceStatus] = useState<EvidenceStatus>("idle");
  const [isLoading, setIsLoading] = useState(false);
  const [isMapReady, setIsMapReady] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [geocodeNotice, setGeocodeNotice] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState(text.taipeiMainStation);
  const [reportSummary, setReportSummary] = useState("");
  const [reportStatus, setReportStatus] = useState<UserReportSubmissionStatus>("idle");

  const statusText = isMapReady ? text.mapStatusReady : text.mapStatusLoading;
  const displayedEvidence = assessment
    ? selectEvidenceItems(assessment.evidence, evidenceItems, evidenceStatus)
    : [];
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
  const currentSummary = useMemo(
    () =>
      coordinate.source === "search"
        ? `${text.locatedPrefix}：${locationLabel}`
        : `${text.selectedPrefix}：${sourceLabels[coordinate.source]}`,
    [coordinate.source, locationLabel],
  );
  const userReportPayload = useMemo(
    () => buildUserReportPayload(coordinate, reportSummary),
    [coordinate, reportSummary],
  );
  const reportDisplayState = getUserReportSubmissionDisplayState(reportStatus);
  const isReportLoading = reportStatus === "loading";

  useEffect(() => {
    let disposed = false;
    let unregisterPmtilesProtocol: (() => void) | null = null;

    async function mountMap() {
      const maplibregl = await import("maplibre-gl");
      if (disposed || !mapContainerRef.current || mapRef.current) return;

      unregisterPmtilesProtocol = registerPmtilesProtocol(maplibregl);
      const basemap = getBasemapStyleConfig();
      basemap.warnings.forEach((warning) => console.warn(warning));

      const map = new maplibregl.Map({
        attributionControl: false,
        center: [TAIWAN_OVERVIEW.lng, TAIWAN_OVERVIEW.lat],
        container: mapContainerRef.current,
        maxBounds: [
          [118.0, 20.5],
          [123.8, 26.8],
        ],
        style: basemap.style,
        zoom: TAIWAN_OVERVIEW.zoom,
      });

      mapRef.current = map;
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-left");
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

      map.on("load", () => {
        ensureTaiwanCityDots(map);

        if (!map.getSource("query-radius")) {
          map.addSource("query-radius", {
            type: "geojson",
            data: createRadiusFeature(INITIAL_COORDINATE, INITIAL_RADIUS),
          });
          map.addLayer({
            id: "query-radius-fill",
            type: "fill",
            source: "query-radius",
            paint: {
              "fill-color": "#c66a21",
              "fill-opacity": 0.18,
            },
          });
          map.addLayer({
            id: "query-radius-line",
            type: "line",
            source: "query-radius",
            paint: {
              "line-color": "#c66a21",
              "line-width": 2,
            },
          });
        }
        setIsMapReady(true);
      });

      map.on("click", (event) => {
        setCoordinate({
          lat: event.lngLat.lat,
          lng: event.lngLat.lng,
          source: "map",
        });
        setLocationLabel(sourceLabels.map);
        requestIdRef.current += 1;
        setAssessment(null);
        setEvidenceItems([]);
        setEvidenceStatus("idle");
        setErrorMessage(null);
        setGeocodeNotice(null);
      });
    }

    void mountMap();

    return () => {
      disposed = true;
      markerRef.current?.remove();
      markerRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
      unregisterPmtilesProtocol?.();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const source = map.getSource("query-radius") as GeoJSONSource | undefined;
    source?.setData(createRadiusFeature(coordinate, radius));

    if (!markerRef.current) {
      void import("maplibre-gl").then((maplibregl) => {
        if (!mapRef.current || markerRef.current) return;
        markerRef.current = new maplibregl.Marker({
          anchor: "center",
          element: createMarkerElement(),
        })
          .setLngLat([coordinate.lng, coordinate.lat])
          .addTo(mapRef.current);
      });
    } else {
      markerRef.current.setLngLat([coordinate.lng, coordinate.lat]);
    }

    map.resize();
    map.flyTo({
      center: targetCenter(coordinate),
      duration: coordinate.source === "search" ? 900 : 450,
      essential: true,
      zoom: targetZoom(coordinate, radius),
    });
  }, [coordinate, isMapReady, radius]);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setIsLoading(true);
    setErrorMessage(null);
    setGeocodeNotice(null);

    const normalized = query.trim();
    let target = coordinate;
    let resolvedLocationText = normalized || locationLabel;

    try {
      if (normalized) {
        const geocode = await postJson<GeocodeResponse>("/v1/geocode", {
          input_type: "address",
          limit: 1,
          query: normalized,
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
          setAssessment(null);
          setEvidenceItems([]);
          setEvidenceStatus("idle");
          setGeocodeNotice(`${geocodeCandidateNotice(candidate)}。${text.geocodeNeedsConfirmation}`);
          return;
        }
      }

      const risk = await postJson<RiskAssessmentResponse>(
        "/v1/risk/assess",
        buildRiskAssessmentPayload(target, radius, resolvedLocationText),
      );
      if (requestIdRef.current !== requestId) return;
      setAssessment(risk);
      setEvidenceItems(risk.evidence);

      if (shouldFetchEvidenceList(risk.assessment_id)) {
        setEvidenceStatus("loading");
        try {
          const evidence = await getJson<EvidenceListResponse>(
            `/v1/evidence/${encodeURIComponent(risk.assessment_id)}`,
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
    } catch {
      if (requestIdRef.current === requestId) {
        setErrorMessage(text.queryFailed);
      }
    } finally {
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
        <form className="panel-section query-panel" onSubmit={handleSearch}>
          <label className="field">
            <span>{text.searchPlace}</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={text.searchPlaceholder}
              aria-label={text.searchPlaceholder}
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
                    onChange={() => setRadius(option)}
                  />
                  <span>{option >= 1000 ? `${option / 1000} km` : `${option} m`}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <button className="primary-action" type="submit" disabled={isLoading}>
            {isLoading ? text.loading : text.assessRisk}
          </button>
          {errorMessage ? <p className="form-error">{errorMessage}</p> : null}
          {geocodeNotice ? <p className="form-notice">{geocodeNotice}</p> : null}
        </form>

        <section className="panel-section coordinate-panel">
          <div>
            <span className="section-kicker">{text.currentCoordinate}</span>
            <strong>{currentSummary}</strong>
          </div>
          <dl>
            <div>
              <dt>{text.latitude}</dt>
              <dd>{formatCoordinate(coordinate.lat)}</dd>
            </div>
            <div>
              <dt>{text.longitude}</dt>
              <dd>{formatCoordinate(coordinate.lng)}</dd>
            </div>
            <div>
              <dt>{text.radius}</dt>
              <dd>{radius.toLocaleString("zh-TW")} m</dd>
            </div>
          </dl>
        </section>

        <form className="panel-section user-report-panel" onSubmit={handleUserReportSubmit}>
          <div className="section-heading">
            <span className="section-kicker">Public report</span>
            <strong>Share local flood signal</strong>
          </div>
          <div className="report-location">
            <span>Report location</span>
            <strong>
              {formatCoordinate(coordinate.lat)}, {formatCoordinate(coordinate.lng)}
            </strong>
          </div>
          <label className="field">
            <span>Observation</span>
            <textarea
              value={reportSummary}
              onChange={(event) => {
                setReportSummary(event.target.value);
                if (reportStatus !== "loading") setReportStatus("idle");
              }}
              placeholder="Briefly describe visible flooding, water depth, or road impact."
              maxLength={500}
              rows={4}
            />
          </label>
          {!userReportPayload.isValid && reportSummary.length > 0 ? (
            <p className="form-error">Add a short observation before submitting.</p>
          ) : null}
          <button
            className="primary-action"
            type="submit"
            disabled={isReportLoading || !userReportPayload.isValid}
          >
            {isReportLoading ? reportDisplayState.submitLabel : "Submit report"}
          </button>
          {reportDisplayState.message ? (
            <p className={`report-state report-state-${reportDisplayState.kind}`} role="status">
              {reportDisplayState.message}
            </p>
          ) : null}
        </form>

        <section className="panel-section layer-panel">
          <div className="section-heading">
            <span className="section-kicker">{text.layers}</span>
            <strong>
              {layerDisplayState.status === "ready"
                ? text.layerReady
                : layerDisplayState.status === "limited"
                  ? text.layerLimited
                  : layerDisplayState.status === "empty"
                    ? text.layerEmpty
                    : text.layerPending}
            </strong>
          </div>
          <div className="layer-contract-status">
            {layerDisplayState.hasTileContract ? text.layerContract : text.layerFallback}
          </div>
          {layerDisplayState.items.length ? (
            <ul className="layer-list">
              {layerDisplayState.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <strong>{item.name}</strong>
                    <span>{`${item.kind} / ${layerAvailabilityLabel(item.availability)}`}</span>
                  </div>
                  <dl>
                    <div>
                      <dt>{text.freshness}</dt>
                      <dd>{formatDateTime(item.freshnessAt)}</dd>
                    </div>
                    <div>
                      <dt>{text.layerFeatureCount}</dt>
                      <dd>{item.featureCount ?? "--"}</dd>
                    </div>
                    <div>
                      <dt>{text.mapStatus}</dt>
                      <dd>{healthLabel(item.status)}</dd>
                    </div>
                    <div>
                      <dt>Tile</dt>
                      <dd>{item.tileUrl ? "XYZ" : text.layerNoTile}</dd>
                    </div>
                  </dl>
                  {item.message ? <p>{item.message}</p> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p>{assessment ? text.layerNoData : text.freshnessNote}</p>
          )}
        </section>

        <section className="panel-section risk-summary">
          <div className="section-heading">
            <span className="section-kicker">{text.riskSummary}</span>
            <strong>
              {assessment
                ? `${assessment.realtime.level} / ${assessment.historical.level}`
                : text.pendingData}
            </strong>
          </div>
          <div className="risk-meter" aria-label={text.riskMeter}>
            <span style={{ left: riskMeterPosition(assessment?.historical.level) }} />
          </div>
          <p>{assessment ? assessment.explanation.summary : text.riskPlaceholder}</p>
          {assessment ? (
            <dl className="risk-levels">
              <div>
                <dt>{text.realtime}</dt>
                <dd>{assessment.realtime.level}</dd>
              </div>
              <div>
                <dt>{text.historical}</dt>
                <dd>{assessment.historical.level}</dd>
              </div>
              <div>
                <dt>{text.confidence}</dt>
                <dd>{assessment.confidence.level}</dd>
              </div>
            </dl>
          ) : null}
        </section>

        <section className="panel-section evidence-panel">
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
                {assessment.explanation.missing_sources.length ? (
                  <div className="evidence-warning" role="status">
                    <strong>{text.limitations}</strong>
                    <ul>
                      {assessment.explanation.missing_sources.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="freshness-strip" aria-label={text.freshness}>
                  {assessment.data_freshness.map((item) => (
                    <div key={item.source_id}>
                      <strong>{item.name}</strong>
                      <span>{healthLabel(item.health_status)}</span>
                      <small>{formatDateTime(item.observed_at ?? item.ingested_at)}</small>
                    </div>
                  ))}
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
                  <div className="evidence-empty">{text.evidenceEmpty}</div>
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

        <section className="panel-section freshness-panel">
          <div>
            <span className="section-kicker">{text.freshness}</span>
            <strong>{assessment ? text.online : text.offline}</strong>
          </div>
          {assessment ? (
            <ul className="freshness-list">
              {assessment.data_freshness.map((item) => (
                <li key={item.source_id}>
                  <strong>{`${item.name}：${healthLabel(item.health_status)}`}</strong>
                  {item.message ? <span>{item.message}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p>{text.lastSync}</p>
          )}
          <p>
            {assessment
              ? `查詢關注度：${assessment.query_heat.attention_level}`
              : text.freshnessNote}
          </p>
        </section>
      </aside>
    </main>
  );
}
