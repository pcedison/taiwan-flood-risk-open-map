import assert from "node:assert/strict";
import test from "node:test";

const basemapModulePath = "../../app/lib/basemap-style.ts";
const {
  buildPmtilesBasemapStyle,
  getBasemapStyleConfig,
} = (await import(basemapModulePath)) as typeof import("../../app/lib/basemap-style");

type RasterSourceForTest = {
  tiles?: string[];
  type: string;
};

type LayerWithSourceLayerForTest = {
  id?: string;
  "source-layer"?: string;
};

const sourceLayerNames = (layers: unknown[]): string[] =>
  layers
    .map((layer) => (layer as LayerWithSourceLayerForTest)["source-layer"])
    .filter((value): value is string => typeof value === "string");

test("style URL takes precedence and is passed through to MapLibre", () => {
  const config = getBasemapStyleConfig({
    NEXT_PUBLIC_BASEMAP_KIND: "pmtiles",
    NEXT_PUBLIC_BASEMAP_PMTILES_URL: "https://cdn.example.test/taiwan.pmtiles",
    NEXT_PUBLIC_BASEMAP_STYLE_URL: "https://cdn.example.test/styles/flood-risk.json",
    NODE_ENV: "production",
  });

  assert.equal(config.kind, "style-url");
  assert.equal(config.style, "https://cdn.example.test/styles/flood-risk.json");
  assert.deepEqual(config.warnings, []);
});

test("PMTiles configuration builds a vector basemap style", () => {
  const config = getBasemapStyleConfig({
    NEXT_PUBLIC_BASEMAP_ATTRIBUTION: "Example PMTiles attribution",
    NEXT_PUBLIC_BASEMAP_KIND: "pmtiles",
    NEXT_PUBLIC_BASEMAP_PMTILES_URL: "https://cdn.example.test/taiwan.pmtiles",
    NODE_ENV: "production",
  });

  assert.equal(config.kind, "pmtiles");
  assert.deepEqual(config.warnings, []);
  assert.equal(typeof config.style, "object");

  if (typeof config.style === "string") {
    throw new Error("expected PMTiles style object");
  }

  assert.equal(config.style.sources.basemap.type, "vector");
  assert.equal(config.style.sources.basemap.url, "pmtiles://https://cdn.example.test/taiwan.pmtiles");
  assert.equal(config.style.sources.basemap.attribution, "Example PMTiles attribution");
  assert.equal(sourceLayerNames(config.style.layers).includes("buildings"), true);
  assert.equal(sourceLayerNames(config.style.layers).includes("roads"), true);
  assert.equal(sourceLayerNames(config.style.layers).includes("boundaries"), true);
  assert.equal(config.style.layers.some((layer) => layer.id === "base-roads"), true);
});

test("PMTiles helper does not duplicate pmtiles protocol prefixes", () => {
  const style = buildPmtilesBasemapStyle("pmtiles://https://cdn.example.test/taiwan.pmtiles");

  assert.equal(style.sources.basemap.type, "vector");
  assert.equal(style.sources.basemap.url, "pmtiles://https://cdn.example.test/taiwan.pmtiles");
});

test("raster fallback uses configured tile templates", () => {
  const config = getBasemapStyleConfig({
    NEXT_PUBLIC_BASEMAP_ATTRIBUTION: "Example tiles",
    NEXT_PUBLIC_BASEMAP_KIND: "raster",
    NEXT_PUBLIC_BASEMAP_RASTER_TILES:
      "https://tiles-a.example.test/{z}/{x}/{y}.png, https://tiles-b.example.test/{z}/{x}/{y}.png",
    NODE_ENV: "development",
  });

  assert.equal(config.kind, "raster");
  assert.deepEqual(config.warnings, []);

  if (typeof config.style === "string") {
    throw new Error("expected raster style object");
  }

  assert.equal(config.style.sources.basemap.type, "raster");
  assert.equal(config.style.sources.basemap.attribution, "Example tiles");
  assert.deepEqual(config.style.sources.basemap.tiles, [
    "https://tiles-a.example.test/{z}/{x}/{y}.png",
    "https://tiles-b.example.test/{z}/{x}/{y}.png",
  ]);
});

test("production default OSM fallback emits an unsafe fallback warning", () => {
  const config = getBasemapStyleConfig({
    NODE_ENV: "production",
  });

  assert.equal(config.kind, "dev-osm-raster");
  assert.match(config.warnings.join("\n"), /OpenStreetMap raster fallback/);

  if (typeof config.style === "string") {
    throw new Error("expected fallback style object");
  }

  assert.deepEqual((config.style.sources.basemap as RasterSourceForTest).tiles, [
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  ]);
});

test("production raster mode warns that raster is temporary", () => {
  const config = getBasemapStyleConfig({
    NEXT_PUBLIC_BASEMAP_KIND: "raster",
    NEXT_PUBLIC_BASEMAP_RASTER_TILES: "https://tiles.example.test/{z}/{x}/{y}.png",
    NODE_ENV: "production",
  });

  assert.equal(config.kind, "raster");
  assert.match(config.warnings.join("\n"), /temporary recovery/);
});
