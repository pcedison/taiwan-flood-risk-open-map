import type { Map as MapLibreMap } from "maplibre-gl";
import { Protocol } from "pmtiles";
import type { Coordinate } from "./page-types";

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

export const INITIAL_RADIUS = 500;
export const INITIAL_COORDINATE: Coordinate = {
  lat: 25.04776,
  lng: 121.51706,
  source: "default",
};
export const TAIWAN_OVERVIEW = {
  lat: 23.72,
  lng: 120.96,
  zoom: 7.2,
};

const TAIWAN_CITY_GEOJSON: MapFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "臺北" },
      geometry: { type: "Point", coordinates: [121.51706, 25.04776] },
    },
    {
      type: "Feature",
      properties: { name: "臺中" },
      geometry: { type: "Point", coordinates: [120.68686, 24.13716] },
    },
    {
      type: "Feature",
      properties: { name: "高雄" },
      geometry: { type: "Point", coordinates: [120.30203, 22.63937] },
    },
    {
      type: "Feature",
      properties: { name: "花蓮" },
      geometry: { type: "Point", coordinates: [121.60681, 23.99107] },
    },
  ],
};

export const BASEMAP_LABEL_LAYER_IDS = ["base-place-labels", "base-poi-labels", "base-road-labels"];

let activePmtilesProtocol: Protocol | null = null;

export const targetZoom = (coordinate: Coordinate, radius: number) => {
  if (coordinate.source === "default") return TAIWAN_OVERVIEW.zoom;
  if (coordinate.source === "search") return radius <= 500 ? 15.2 : 14.2;
  return radius <= 500 ? 14.2 : 13.2;
};

export const targetCenter = (coordinate: Coordinate): [number, number] =>
  coordinate.source === "default"
    ? [TAIWAN_OVERVIEW.lng, TAIWAN_OVERVIEW.lat]
    : [coordinate.lng, coordinate.lat];

export function createRadiusFeature(coordinate: Coordinate, radiusMeters: number): RadiusFeatureCollection {
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

export function createMarkerElement() {
  const marker = document.createElement("div");
  marker.className = "map-marker";
  const inner = document.createElement("span");
  marker.append(inner);
  return marker;
}

export function registerPmtilesProtocol(maplibregl: typeof import("maplibre-gl")) {
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

export function ensureTaiwanCityDots(map: MapLibreMap) {
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

export function firstExistingLayerId(map: MapLibreMap, layerIds: string[]): string | undefined {
  return layerIds.find((layerId) => map.getLayer(layerId));
}
