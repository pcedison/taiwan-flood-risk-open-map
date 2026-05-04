import type { StyleSpecification } from "maplibre-gl";

export type BasemapKind = "style-url" | "pmtiles" | "raster" | "dev-osm-raster";

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
  "Using the public OpenStreetMap raster fallback. Configure NEXT_PUBLIC_BASEMAP_STYLE_URL or NEXT_PUBLIC_BASEMAP_KIND=pmtiles before production.";
const RASTER_WARNING =
  "Using raster basemap fallback. This is intended for development or temporary recovery, not the production basemap path.";

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

    return buildDevOsmFallback({
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

    return buildDevOsmFallback({
      isProduction,
      warnings: ["NEXT_PUBLIC_BASEMAP_KIND=raster requires NEXT_PUBLIC_BASEMAP_RASTER_TILES."],
    });
  }

  if (kind) {
    return buildDevOsmFallback({
      isProduction,
      warnings: [`Unsupported NEXT_PUBLIC_BASEMAP_KIND="${kind}".`],
    });
  }

  return buildDevOsmFallback({ isProduction, warnings: [] });
}

export function buildPmtilesBasemapStyle(
  pmtilesUrl: string,
  attribution = "OpenStreetMap contributors",
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
  attribution = "Basemap contributors",
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

function buildDevOsmFallback({
  isProduction,
  warnings,
}: {
  isProduction: boolean;
  warnings: string[];
}): BasemapStyleConfig {
  return {
    kind: "dev-osm-raster",
    style: buildRasterBasemapStyle(PUBLIC_OSM_RASTER_TILES, "OpenStreetMap contributors"),
    warnings: isProduction ? [...warnings, DEV_OSM_WARNING] : warnings,
  };
}

function parseRasterTiles(value: string | undefined): string[] {
  return trimValue(value)
    .split(",")
    .map((tile) => tile.trim())
    .filter(Boolean);
}

function attributionFromEnv(env: BasemapEnv): string {
  return trimValue(env.NEXT_PUBLIC_BASEMAP_ATTRIBUTION) || "OpenStreetMap contributors";
}
