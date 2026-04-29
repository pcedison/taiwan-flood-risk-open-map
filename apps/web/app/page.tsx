"use client";

import type { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

type CoordinateSource = "default" | "map" | "search";

type Coordinate = {
  lat: number;
  lng: number;
  source: CoordinateSource;
};

type GeocodeResponse = {
  candidates: Array<{
    confidence: number;
    name: string;
    point: {
      lat: number;
      lng: number;
    };
    source: string;
  }>;
};

type RiskAssessmentResponse = {
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
  evidence: Array<{
    id: string;
    source_type: string;
    event_type: string;
    title: string;
    summary: string;
    confidence: number;
    observed_at: string | null;
    ingested_at: string | null;
    distance_to_query_m: number | null;
  }>;
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
  limitations: "資料限制",
  evidenceFlood: "尚未查詢附近淹水事件。",
  evidenceRain: "查詢後會顯示雨量、水位與淹水潛勢資料。",
  evidenceTerrain: "公開資料會保留來源與時間，方便回頭查證。",
  freshness: "資料新鮮度",
  offline: "尚未連線",
  online: "已連線",
  loading: "查詢中",
  queryFailed: "查詢失敗，請稍後再試。",
  noGeocodeResult: "找不到這個地點，請換一個關鍵字再試。",
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

const formatCoordinate = (value: number) => value.toFixed(5);

const healthLabels: Record<string, string> = {
  healthy: "正常",
  degraded: "延遲",
  failed: "失敗",
  disabled: "停用",
  unknown: "未知",
};

const healthLabel = (value: string) => healthLabels[value] ?? value;

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

const formatConfidence = (value: number) => `${Math.round(value * 100)}%`;

const formatDistance = (value: number | null) =>
  value === null ? "未提供" : `${Math.round(value).toLocaleString("zh-TW")} m`;

const formatDateTime = (value: string | null) => {
  if (!value) return "未提供";
  return new Intl.DateTimeFormat("zh-TW", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
  }).format(new Date(value));
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

export default function HomePage() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const [query, setQuery] = useState(text.taipeiMainStation);
  const [radius, setRadius] = useState(INITIAL_RADIUS);
  const [coordinate, setCoordinate] = useState<Coordinate>(INITIAL_COORDINATE);
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isMapReady, setIsMapReady] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState(text.taipeiMainStation);

  const statusText = isMapReady ? text.mapStatusReady : text.mapStatusLoading;
  const currentSummary = useMemo(
    () =>
      coordinate.source === "search"
        ? `${text.locatedPrefix}：${locationLabel}`
        : `${text.selectedPrefix}：${sourceLabels[coordinate.source]}`,
    [coordinate.source, locationLabel],
  );

  useEffect(() => {
    let disposed = false;

    async function mountMap() {
      const maplibregl = await import("maplibre-gl");
      if (disposed || !mapContainerRef.current || mapRef.current) return;

      const map = new maplibregl.Map({
        attributionControl: false,
        center: [TAIWAN_OVERVIEW.lng, TAIWAN_OVERVIEW.lat],
        container: mapContainerRef.current,
        maxBounds: [
          [118.0, 20.5],
          [123.8, 26.8],
        ],
        style: {
          version: 8,
          sources: {
            osm: {
              type: "raster",
              tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
              tileSize: 256,
              attribution: "© OpenStreetMap contributors",
            },
            "taiwan-cities": {
              type: "geojson",
              data: TAIWAN_CITY_GEOJSON,
            },
          },
          layers: [
            {
              id: "base-water",
              type: "background",
              paint: {
                "background-color": "#c9d9d5",
              },
            },
            {
              id: "osm",
              type: "raster",
              source: "osm",
              paint: {
                "raster-opacity": 0.88,
              },
            },
            {
              id: "taiwan-city-dots",
              type: "circle",
              source: "taiwan-cities",
              paint: {
                "circle-color": "#0d5f4b",
                "circle-radius": 4,
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 2,
              },
            },
          ],
        },
        zoom: TAIWAN_OVERVIEW.zoom,
      });

      mapRef.current = map;
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-left");
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

      map.on("load", () => {
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
        setAssessment(null);
        setErrorMessage(null);
      });
    }

    void mountMap();

    return () => {
      disposed = true;
      markerRef.current?.remove();
      markerRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
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
    setIsLoading(true);
    setErrorMessage(null);

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
        resolvedLocationText = candidate.name;
        mapRef.current?.resize();
        mapRef.current?.flyTo({
          center: [target.lng, target.lat],
          duration: 900,
          essential: true,
          zoom: targetZoom(target, radius),
        });
      }

      const risk = await postJson<RiskAssessmentResponse>("/v1/risk/assess", {
        point: {
          lat: target.lat,
          lng: target.lng,
        },
        radius_m: radius,
        time_context: "now",
        location_text: resolvedLocationText,
      });
      setAssessment(risk);
    } catch {
      setErrorMessage(text.queryFailed);
    } finally {
      setIsLoading(false);
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
          {assessment?.explanation.missing_sources.length ? (
            <div className="limitations">
              <strong>{text.limitations}</strong>
              <ul>
                {assessment.explanation.missing_sources.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        <section className="panel-section evidence-panel">
          <div className="section-heading">
            <span className="section-kicker">{text.evidenceKicker}</span>
            <strong>{text.evidenceTitle}</strong>
          </div>
          {assessment ? (
            <ul className="evidence-list">
              {assessment.evidence.map((item) => (
                <li key={item.id}>
                  <strong>{item.title}</strong>
                  <span>{item.summary}</span>
                  <dl className="evidence-meta">
                    <div>
                      <dt>{text.evidenceSource}</dt>
                      <dd>{sourceTypeLabel(item.source_type)}</dd>
                    </div>
                    <div>
                      <dt>{text.evidenceConfidence}</dt>
                      <dd>{formatConfidence(item.confidence)}</dd>
                    </div>
                    <div>
                      <dt>{text.evidenceDistance}</dt>
                      <dd>{formatDistance(item.distance_to_query_m)}</dd>
                    </div>
                    <div>
                      <dt>{text.evidenceObservedAt}</dt>
                      <dd>{formatDateTime(item.observed_at)}</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          ) : (
            <ul>
              <li>{text.evidenceFlood}</li>
              <li>{text.evidenceRain}</li>
              <li>{text.evidenceTerrain}</li>
            </ul>
          )}
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
