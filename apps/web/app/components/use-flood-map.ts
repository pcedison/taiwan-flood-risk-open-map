"use client";

import type { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import {
  getInteractiveBasemapMaxZoom,
  loadRuntimeBasemapStyleConfig,
} from "../lib/basemap-style";
import {
  BASEMAP_LABEL_LAYER_IDS,
  INITIAL_COORDINATE,
  INITIAL_RADIUS,
  TAIWAN_OVERVIEW,
  createMarkerElement,
  createRadiusFeature,
  ensureTaiwanCityDots,
  firstExistingLayerId,
  registerPmtilesProtocol,
  targetCenter,
  targetZoom,
} from "../lib/map-setup";
import type { Coordinate } from "../lib/page-types";
import type { riskOverlayPresentation } from "../lib/risk-display";

type RiskOverlay = ReturnType<typeof riskOverlayPresentation>;

const NAVIGATION_CONTROL_LABELS: Record<string, string> = {
  "maplibregl-ctrl-zoom-in": "放大",
  "maplibregl-ctrl-zoom-out": "縮小",
  "maplibregl-ctrl-compass": "重設方位",
};

function localizeNavigationControl(control: { _container?: HTMLElement }): void {
  const container = control._container;
  if (!container) return;
  for (const [className, label] of Object.entries(NAVIGATION_CONTROL_LABELS)) {
    const button = container.querySelector<HTMLButtonElement>(`.${className}`);
    if (!button) continue;
    button.title = label;
    button.setAttribute("aria-label", label);
  }
}

type UseFloodMapOptions = {
  coordinate: Coordinate;
  radius: number;
  riskOverlay: RiskOverlay;
  idleRiskOverlay: RiskOverlay;
  onMapClick: (point: { lat: number; lng: number }) => void;
};

export function useFloodMap({
  coordinate,
  radius,
  riskOverlay,
  idleRiskOverlay,
  onMapClick,
}: UseFloodMapOptions) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const [isMapReady, setIsMapReady] = useState(false);

  onMapClickRef.current = onMapClick;

  useEffect(() => {
    let disposed = false;
    let unregisterPmtilesProtocol: (() => void) | null = null;
    const idleOverlay = idleRiskOverlay;

    async function mountMap() {
      const [maplibregl, basemap] = await Promise.all([
        import("maplibre-gl"),
        loadRuntimeBasemapStyleConfig(),
      ]);
      if (disposed || !mapContainerRef.current || mapRef.current) return;

      unregisterPmtilesProtocol = registerPmtilesProtocol(maplibregl);
      basemap.warnings.forEach((warning) => console.warn(warning));
      const interactiveMaxZoom = getInteractiveBasemapMaxZoom(basemap.style);

      const map = new maplibregl.Map({
        attributionControl: false,
        center: [TAIWAN_OVERVIEW.lng, TAIWAN_OVERVIEW.lat],
        container: mapContainerRef.current,
        maxBounds: [
          [118.0, 20.5],
          [123.8, 26.8],
        ],
        ...(interactiveMaxZoom ? { maxZoom: interactiveMaxZoom } : {}),
        style: basemap.style,
        zoom: TAIWAN_OVERVIEW.zoom,
      });

      mapRef.current = map;
      const navigationControl = new maplibregl.NavigationControl({ visualizePitch: false });
      map.addControl(navigationControl, "top-left");
      // MapLibre's built-in zoom buttons ship English title/aria-label text;
      // localize them so the control matches the Traditional Chinese UI.
      localizeNavigationControl(navigationControl);
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

      map.on("load", () => {
        ensureTaiwanCityDots(map);

        if (!map.getSource("query-radius")) {
          map.addSource("query-radius", {
            type: "geojson",
            data: createRadiusFeature(INITIAL_COORDINATE, INITIAL_RADIUS),
          });
          const beforeBasemapLabels = firstExistingLayerId(map, BASEMAP_LABEL_LAYER_IDS);
          map.addLayer(
            {
              id: "query-radius-fill",
              type: "fill",
              source: "query-radius",
              paint: {
                "fill-color": idleOverlay.fillColor,
                "fill-opacity": idleOverlay.fillOpacity,
              },
            },
            beforeBasemapLabels,
          );
          map.addLayer(
            {
              id: "query-radius-line",
              type: "line",
              source: "query-radius",
              paint: {
                "line-color": idleOverlay.lineColor,
                "line-width": 2,
                ...(idleOverlay.lineDasharray
                  ? { "line-dasharray": idleOverlay.lineDasharray }
                  : {}),
              },
            },
            beforeBasemapLabels,
          );
        }
        setIsMapReady(true);
      });

      map.on("click", (event) => {
        onMapClickRef.current({ lat: event.lngLat.lat, lng: event.lngLat.lng });
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
    // The idle overlay palette is a stable module constant; the map mounts once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    if (map.getLayer("query-radius-fill")) {
      map.setPaintProperty("query-radius-fill", "fill-color", riskOverlay.fillColor);
      map.setPaintProperty("query-radius-fill", "fill-opacity", riskOverlay.fillOpacity);
    }
    if (map.getLayer("query-radius-line")) {
      map.setPaintProperty("query-radius-line", "line-color", riskOverlay.lineColor);
      map.setPaintProperty("query-radius-line", "line-dasharray", riskOverlay.lineDasharray);
    }
  }, [isMapReady, riskOverlay]);

  return { mapContainerRef, mapRef, isMapReady };
}
