import type { StyleSpecification } from "maplibre-gl";

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
  NEXT_PUBLIC_BASEMAP_ATTRIBUTION?: string;
  NEXT_PUBLIC_BASEMAP_KIND?: string;
  NEXT_PUBLIC_BASEMAP_PMTILES_URL?: string;
  NEXT_PUBLIC_BASEMAP_RASTER_TILES?: string;
  NEXT_PUBLIC_BASEMAP_STYLE_URL?: string;
  NODE_ENV?: string;
};

const PUBLIC_OSM_RASTER_TILES = ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"];
const DEV_OSM_WARNING =
  "Development fallback is using public OpenStreetMap raster tiles. Do not use this fallback for hosted public beta or production traffic.";
const PRODUCTION_BASEMAP_WARNING =
  "Production basemap is not configured. Set NEXT_PUBLIC_BASEMAP_STYLE_URL or a reviewed NEXT_PUBLIC_BASEMAP_KIND/PMTiles/raster URL before public map launch.";
const RASTER_WARNING =
  "Production raster basemap is configured. Confirm provider terms, attribution, cache behavior, and rate limits before public traffic.";

const trimValue = (value: string | undefined) => value?.trim() ?? "";

function readBasemapEnv(): BasemapEnv {
  return {
    NEXT_PUBLIC_BASEMAP_ATTRIBUTION: process.env.NEXT_PUBLIC_BASEMAP_ATTRIBUTION,
    NEXT_PUBLIC_BASEMAP_KIND: process.env.NEXT_PUBLIC_BASEMAP_KIND,
    NEXT_PUBLIC_BASEMAP_PMTILES_URL: process.env.NEXT_PUBLIC_BASEMAP_PMTILES_URL,
    NEXT_PUBLIC_BASEMAP_RASTER_TILES: process.env.NEXT_PUBLIC_BASEMAP_RASTER_TILES,
    NEXT_PUBLIC_BASEMAP_STYLE_URL: process.env.NEXT_PUBLIC_BASEMAP_STYLE_URL,
    NODE_ENV: process.env.NODE_ENV,
  };
}

export function getBasemapStyleConfig(env: BasemapEnv = readBasemapEnv()): BasemapStyleConfig {
  const styleUrl = trimValue(env.NEXT_PUBLIC_BASEMAP_STYLE_URL);
  if (styleUrl) {
    return {
      kind: "style-url",
      style: styleUrl,
      warnings: [],
    };
  }

  const kind = trimValue(env.NEXT_PUBLIC_BASEMAP_KIND).toLowerCase();
  const isProduction = env.NODE_ENV === "production";

  if (kind === "pmtiles") {
    const pmtilesUrl = trimValue(env.NEXT_PUBLIC_BASEMAP_PMTILES_URL);
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
    const rasterTiles = parseRasterTiles(env.NEXT_PUBLIC_BASEMAP_RASTER_TILES);
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

export function buildPmtilesBasemapStyle(
  pmtilesUrl: string,
  attribution = "OpenStreetMap 貢獻者",
): StyleSpecification {
  const sourceUrl = pmtilesUrl.startsWith("pmtiles://") ? pmtilesUrl : `pmtiles://${pmtilesUrl}`;

  return {
    version: 8,
    sources: {
      basemap: {
        type: "vector",
        url: sourceUrl,
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
  };
}

export function buildRasterBasemapStyle(
  tiles: string[],
  attribution = "底圖貢獻者",
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
    style: buildRasterBasemapStyle(PUBLIC_OSM_RASTER_TILES, "OpenStreetMap 貢獻者"),
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
  return trimValue(env.NEXT_PUBLIC_BASEMAP_ATTRIBUTION) || "OpenStreetMap 貢獻者";
}
