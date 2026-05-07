import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";

export type BasemapKind =
  | "style-url"
  | "pmtiles"
  | "raster"
  | "dev-osm-raster"
  | "production-unconfigured";

export type BasemapStyleConfig = {
  kind: BasemapKind;
  style: StyleSpecification | string;
  warnings: string[];
};

export type BasemapEnv = {
  BASEMAP_ATTRIBUTION?: string;
  BASEMAP_KIND?: string;
  BASEMAP_PMTILES_URL?: string;
  BASEMAP_RASTER_TILES?: string;
  BASEMAP_STYLE_URL?: string;
  NEXT_PUBLIC_BASEMAP_ATTRIBUTION?: string;
  NEXT_PUBLIC_BASEMAP_KIND?: string;
  NEXT_PUBLIC_BASEMAP_PMTILES_URL?: string;
  NEXT_PUBLIC_BASEMAP_RASTER_TILES?: string;
  NEXT_PUBLIC_BASEMAP_STYLE_URL?: string;
  NODE_ENV?: string;
};

type StyleLayer = StyleSpecification["layers"][number];
type SourceLayerStyleLayer = StyleLayer & {
  source?: string;
  "source-layer"?: string;
};
type VectorBasemapSource = StyleSpecification["sources"][string] & {
  maxzoom?: number;
  type: "vector";
};

const PUBLIC_OSM_RASTER_TILES = ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"];
const PROTOMAPS_GLYPHS_URL =
  "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf";
const DEFAULT_VECTOR_SOURCE_MAXZOOM = 14;
const VECTOR_SOURCE_OVERZOOM_LEVELS = 4;
const INTERACTIVE_VECTOR_MAXZOOM = 18;
const DEFAULT_OPEN_BASEMAP_ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>';
const DEV_OSM_WARNING =
  "Development fallback is using public OpenStreetMap raster tiles. Do not use this fallback for hosted public beta or production traffic.";
const PRODUCTION_BASEMAP_WARNING =
  "Production basemap is not configured. Set NEXT_PUBLIC_BASEMAP_STYLE_URL or a reviewed NEXT_PUBLIC_BASEMAP_KIND/PMTiles/raster URL before public map launch.";
const RASTER_WARNING =
  "Production raster basemap is configured. Confirm provider terms, attribution, cache behavior, and rate limits before public traffic.";

const trimValue = (value: string | undefined) => value?.trim() ?? "";

function readBasemapEnv(): BasemapEnv {
  return {
    BASEMAP_ATTRIBUTION: readRuntimeEnv("BASEMAP_ATTRIBUTION"),
    BASEMAP_KIND: readRuntimeEnv("BASEMAP_KIND"),
    BASEMAP_PMTILES_URL: readRuntimeEnv("BASEMAP_PMTILES_URL"),
    BASEMAP_RASTER_TILES: readRuntimeEnv("BASEMAP_RASTER_TILES"),
    BASEMAP_STYLE_URL: readRuntimeEnv("BASEMAP_STYLE_URL"),
    NEXT_PUBLIC_BASEMAP_ATTRIBUTION: readRuntimeEnv("NEXT_PUBLIC_BASEMAP_ATTRIBUTION"),
    NEXT_PUBLIC_BASEMAP_KIND: readRuntimeEnv("NEXT_PUBLIC_BASEMAP_KIND"),
    NEXT_PUBLIC_BASEMAP_PMTILES_URL: readRuntimeEnv("NEXT_PUBLIC_BASEMAP_PMTILES_URL"),
    NEXT_PUBLIC_BASEMAP_RASTER_TILES: readRuntimeEnv("NEXT_PUBLIC_BASEMAP_RASTER_TILES"),
    NEXT_PUBLIC_BASEMAP_STYLE_URL: readRuntimeEnv("NEXT_PUBLIC_BASEMAP_STYLE_URL"),
    NODE_ENV: readRuntimeEnv("NODE_ENV"),
  };
}

export function getBasemapStyleConfig(env: BasemapEnv = readBasemapEnv()): BasemapStyleConfig {
  const styleUrl = basemapEnvValue(env, "NEXT_PUBLIC_BASEMAP_STYLE_URL", "BASEMAP_STYLE_URL");
  if (styleUrl) {
    return {
      kind: "style-url",
      style: styleUrl,
      warnings: [],
    };
  }

  const kind = basemapEnvValue(env, "NEXT_PUBLIC_BASEMAP_KIND", "BASEMAP_KIND").toLowerCase();
  const isProduction = env.NODE_ENV === "production";

  if (kind === "pmtiles") {
    const pmtilesUrl = basemapEnvValue(
      env,
      "NEXT_PUBLIC_BASEMAP_PMTILES_URL",
      "BASEMAP_PMTILES_URL",
    );
    if (pmtilesUrl) {
      return {
        kind: "pmtiles",
        style: buildPmtilesBasemapStyle(pmtilesUrl, attributionFromEnv(env)),
        warnings: [],
      };
    }

    return buildUnconfiguredBasemapFallback({
      isProduction,
      warnings: ["NEXT_PUBLIC_BASEMAP_KIND=pmtiles requires NEXT_PUBLIC_BASEMAP_PMTILES_URL."],
    });
  }

  if (kind === "raster") {
    const rasterTiles = parseRasterTiles(
      basemapEnvValue(env, "NEXT_PUBLIC_BASEMAP_RASTER_TILES", "BASEMAP_RASTER_TILES"),
    );
    if (rasterTiles.length > 0) {
      return {
        kind: "raster",
        style: buildRasterBasemapStyle(rasterTiles, attributionFromEnv(env)),
        warnings: isProduction ? [RASTER_WARNING] : [],
      };
    }

    return buildUnconfiguredBasemapFallback({
      isProduction,
      warnings: ["NEXT_PUBLIC_BASEMAP_KIND=raster requires NEXT_PUBLIC_BASEMAP_RASTER_TILES."],
    });
  }

  if (kind) {
    return buildUnconfiguredBasemapFallback({
      isProduction,
      warnings: [`Unsupported NEXT_PUBLIC_BASEMAP_KIND="${kind}".`],
    });
  }

  return buildUnconfiguredBasemapFallback({ isProduction, warnings: [] });
}

type BasemapConfigFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export async function loadRuntimeBasemapStyleConfig(
  fetcher: BasemapConfigFetch = fetch,
): Promise<BasemapStyleConfig> {
  try {
    const response = await fetcher("/basemap-config", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Basemap config request failed with HTTP ${response.status}`);
    }

    const payload: unknown = await response.json();
    if (!isBasemapStyleConfig(payload)) {
      throw new Error("Basemap config response is not valid");
    }

    return payload;
  } catch (error) {
    console.warn("Falling back to build-time basemap config.", error);
    return getBasemapStyleConfig();
  }
}

export function buildPmtilesBasemapStyle(
  pmtilesUrl: string,
  attribution = DEFAULT_OPEN_BASEMAP_ATTRIBUTION,
): StyleSpecification {
  const sourceUrl = pmtilesUrl.startsWith("pmtiles://") ? pmtilesUrl : `pmtiles://${pmtilesUrl}`;

  return ensureBasemapLabelLayers({
    version: 8,
    sources: {
      basemap: {
        type: "vector",
        url: sourceUrl,
        maxzoom: DEFAULT_VECTOR_SOURCE_MAXZOOM,
        attribution,
      },
    },
    layers: [
      {
        id: "base-land",
        type: "background",
        paint: {
          "background-color": "#eef1ed",
        },
      },
      {
        id: "base-earth",
        type: "fill",
        source: "basemap",
        "source-layer": "earth",
        paint: {
          "fill-color": "#edf1ea",
        },
      },
      {
        id: "base-landcover",
        type: "fill",
        source: "basemap",
        "source-layer": "landcover",
        paint: {
          "fill-color": "#d9e6d0",
          "fill-opacity": 0.72,
        },
      },
      {
        id: "base-water",
        type: "fill",
        source: "basemap",
        "source-layer": "water",
        paint: {
          "fill-color": "#bfd8e6",
        },
      },
      {
        id: "base-buildings",
        type: "fill",
        source: "basemap",
        "source-layer": "buildings",
        minzoom: 12,
        paint: {
          "fill-color": "#d8d2c8",
          "fill-opacity": 0.58,
        },
      },
      {
        id: "base-roads",
        type: "line",
        source: "basemap",
        "source-layer": "roads",
        paint: {
          "line-color": "#ffffff",
          "line-opacity": 0.84,
          "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.4, 12, 1.2, 15, 4],
        },
      },
      {
        id: "base-boundaries",
        type: "line",
        source: "basemap",
        "source-layer": "boundaries",
        paint: {
          "line-color": "#7b8b83",
          "line-dasharray": [2, 2],
          "line-opacity": 0.48,
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 10, 1],
        },
      },
    ],
  });
}

export function ensureBasemapLabelLayers(style: StyleSpecification): StyleSpecification {
  const { source: basemapSource, style: styleWithOverzoom } =
    ensureVectorBasemapSourceMaxzoom(style);
  if (!basemapSource) return style;

  const existingLayerIds = new Set(styleWithOverzoom.layers.map((layer) => layer.id));
  const missingLabelLayers = buildBasemapLabelLayers(basemapSource).filter(
    (layer) => !existingLayerIds.has(layer.id),
  );

  if (missingLabelLayers.length === 0 && styleWithOverzoom.glyphs) return styleWithOverzoom;

  return {
    ...styleWithOverzoom,
    glyphs: styleWithOverzoom.glyphs || PROTOMAPS_GLYPHS_URL,
    layers: [...styleWithOverzoom.layers, ...missingLabelLayers],
  };
}

export function getInteractiveBasemapMaxZoom(
  style: BasemapStyleConfig["style"],
): number | undefined {
  if (typeof style === "string") return undefined;

  const basemapSource = findVectorBasemapSource(style);
  if (!basemapSource) return undefined;

  const source = style.sources[basemapSource];
  if (!source || source.type !== "vector") return undefined;

  const vectorSource = source as VectorBasemapSource;
  const sourceMaxzoom =
    typeof vectorSource.maxzoom === "number" ? vectorSource.maxzoom : inferBasemapMaxzoom(style);

  return Math.max(
    sourceMaxzoom,
    Math.min(INTERACTIVE_VECTOR_MAXZOOM, sourceMaxzoom + VECTOR_SOURCE_OVERZOOM_LEVELS),
  );
}

export function buildRasterBasemapStyle(
  tiles: string[],
  attribution = DEFAULT_OPEN_BASEMAP_ATTRIBUTION,
): StyleSpecification {
  return {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles,
        tileSize: 256,
        attribution,
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
        id: "basemap-raster",
        type: "raster",
        source: "basemap",
        paint: {
          "raster-opacity": 0.88,
        },
      },
    ],
  };
}

export function buildNoTileBasemapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "base-water",
        type: "background",
        paint: {
          "background-color": "#c9d9d5",
        },
      },
    ],
  };
}

function buildBasemapLabelLayers(source: string): StyleLayer[] {
  const localNameExpression = [
    "coalesce",
    ["get", "name:zh-Hant"],
    ["get", "name"],
    ["get", "name:en"],
  ] as ExpressionSpecification;
  const labelFont = ["Open Sans Regular", "Arial Unicode MS Regular"];

  return [
    {
      id: "base-place-labels",
      type: "symbol",
      source,
      "source-layer": "places",
      minzoom: 6,
      filter: ["has", "name"],
      layout: {
        "text-field": localNameExpression,
        "text-font": labelFont,
        "text-size": ["interpolate", ["linear"], ["zoom"], 6, 10, 11, 12, 15, 16],
        "text-max-width": 8,
        "text-padding": 3,
        "text-allow-overlap": false,
        "text-ignore-placement": false,
      },
      paint: {
        "text-color": "#314238",
        "text-halo-color": "#f8fbf5",
        "text-halo-width": 1.3,
      },
    },
    {
      id: "base-poi-labels",
      type: "symbol",
      source,
      "source-layer": "pois",
      minzoom: 13.2,
      filter: ["has", "name"],
      layout: {
        "text-field": localNameExpression,
        "text-font": labelFont,
        "text-size": ["interpolate", ["linear"], ["zoom"], 13, 9, 14, 11],
        "text-max-width": 7,
        "text-padding": 2,
        "text-allow-overlap": false,
        "text-ignore-placement": false,
      },
      paint: {
        "text-color": "#52615a",
        "text-halo-color": "#f8fbf5",
        "text-halo-width": 1,
      },
    },
    {
      id: "base-road-labels",
      type: "symbol",
      source,
      "source-layer": "roads",
      minzoom: 11,
      filter: ["has", "name"],
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": ["interpolate", ["linear"], ["zoom"], 11, 420, 13, 220, 14, 150],
        "text-field": localNameExpression,
        "text-font": labelFont,
        "text-size": ["interpolate", ["linear"], ["zoom"], 11, 10, 13, 12, 14, 14],
        "text-keep-upright": true,
        "text-rotation-alignment": "map",
        "text-pitch-alignment": "viewport",
        "text-letter-spacing": 0,
        "text-padding": 2,
        "text-allow-overlap": true,
        "text-ignore-placement": false,
      },
      paint: {
        "text-color": "#5b5f59",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.5,
      },
    },
  ] as StyleLayer[];
}

function findVectorBasemapSource(style: StyleSpecification): string | null {
  const sourceFromRoadLayer = style.layers
    .map((layer) => layer as SourceLayerStyleLayer)
    .find((layer) => layer["source-layer"] === "roads" && typeof layer.source === "string")
    ?.source;
  if (sourceFromRoadLayer) return sourceFromRoadLayer;

  const sourceEntries = Object.entries(style.sources);
  const vectorSource = sourceEntries.find(([, source]) => source.type === "vector");
  return vectorSource?.[0] ?? null;
}

function ensureVectorBasemapSourceMaxzoom(style: StyleSpecification): {
  source: string | null;
  style: StyleSpecification;
} {
  const basemapSource = findVectorBasemapSource(style);
  if (!basemapSource) return { source: null, style };

  const source = style.sources[basemapSource];
  if (!source || source.type !== "vector") return { source: null, style };

  const vectorSource = source as VectorBasemapSource;
  if (typeof vectorSource.maxzoom === "number") {
    return { source: basemapSource, style };
  }

  return {
    source: basemapSource,
    style: {
      ...style,
      sources: {
        ...style.sources,
        [basemapSource]: {
          ...vectorSource,
          maxzoom: inferBasemapMaxzoom(style),
        },
      },
    },
  };
}

function inferBasemapMaxzoom(style: StyleSpecification): number {
  const metadata = style.metadata as Record<string, unknown> | undefined;
  const metadataMaxzoom =
    metadata?.["flood-risk:maxzoom"] ?? metadata?.maxzoom ?? metadata?.["max_zoom"];

  if (typeof metadataMaxzoom === "number" && Number.isFinite(metadataMaxzoom)) {
    return metadataMaxzoom;
  }
  if (typeof metadataMaxzoom === "string") {
    const parsed = Number.parseInt(metadataMaxzoom, 10);
    if (Number.isFinite(parsed)) return parsed;
  }

  return DEFAULT_VECTOR_SOURCE_MAXZOOM;
}

function buildUnconfiguredBasemapFallback({
  isProduction,
  warnings,
}: {
  isProduction: boolean;
  warnings: string[];
}): BasemapStyleConfig {
  if (isProduction) {
    return {
      kind: "production-unconfigured",
      style: buildNoTileBasemapStyle(),
      warnings: [...warnings, PRODUCTION_BASEMAP_WARNING],
    };
  }

  return {
    kind: "dev-osm-raster",
    style: buildRasterBasemapStyle(PUBLIC_OSM_RASTER_TILES, DEFAULT_OPEN_BASEMAP_ATTRIBUTION),
    warnings: [...warnings, DEV_OSM_WARNING],
  };
}

function parseRasterTiles(value: string | undefined): string[] {
  return trimValue(value)
    .split(",")
    .map((tile) => tile.trim())
    .filter(Boolean);
}

function attributionFromEnv(env: BasemapEnv): string {
  return (
    basemapEnvValue(env, "NEXT_PUBLIC_BASEMAP_ATTRIBUTION", "BASEMAP_ATTRIBUTION") ||
    DEFAULT_OPEN_BASEMAP_ATTRIBUTION
  );
}

function basemapEnvValue(
  env: BasemapEnv,
  publicKey: keyof BasemapEnv,
  runtimeKey: keyof BasemapEnv,
): string {
  return trimValue(env[publicKey] || env[runtimeKey]);
}

function readRuntimeEnv(key: string): string | undefined {
  if (typeof process === "undefined") return undefined;
  return process.env?.[key];
}

function isBasemapStyleConfig(value: unknown): value is BasemapStyleConfig {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<BasemapStyleConfig>;
  return (
    typeof candidate.kind === "string" &&
    (typeof candidate.style === "string" ||
      (typeof candidate.style === "object" && candidate.style !== null)) &&
    Array.isArray(candidate.warnings) &&
    candidate.warnings.every((warning) => typeof warning === "string")
  );
}
