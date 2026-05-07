import assert from "node:assert/strict";
import test from "node:test";

const basemapModulePath = "../../app/lib/basemap-style.ts";
const {
  buildPmtilesBasemapStyle,
  ensureBasemapLabelLayers,
  getBasemapStyleConfig,
  loadRuntimeBasemapStyleConfig,
} = (await import(basemapModulePath)) as typeof import("../../app/lib/basemap-style");

type RasterSourceForTest = {
  tiles?: string[];
  type: string;
};

type VectorSourceForTest = {
  attribution?: string;
  type: string;
  url?: string;
};

type LayerWithSourceLayerForTest = {
  id?: string;
  layout?: Record<string, unknown>;
  "source-layer"?: string;
  type?: string;
};

type AttributedSourceForTest = {
  attribution?: string;
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
  assert.match(config.style.glyphs ?? "", /basemaps-assets\/fonts/);
  assert.equal(config.style.layers.some((layer) => layer.id === "base-road-labels"), true);
  assert.equal(config.style.layers.some((layer) => layer.id === "base-place-labels"), true);
});

test("PMTiles helper does not duplicate pmtiles protocol prefixes", () => {
  const style = buildPmtilesBasemapStyle("pmtiles://https://cdn.example.test/taiwan.pmtiles");

  assert.equal(style.sources.basemap.type, "vector");
  assert.equal(style.sources.basemap.url, "pmtiles://https://cdn.example.test/taiwan.pmtiles");
});

test("external PMTiles styles are patched with text labels and glyphs", () => {
  const style = ensureBasemapLabelLayers({
    version: 8,
    sources: {
      basemap: {
        type: "vector",
        url: "pmtiles://https://cdn.example.test/taiwan.pmtiles",
      },
    },
    layers: [
      {
        id: "roads",
        type: "line",
        source: "basemap",
        "source-layer": "roads",
        paint: {
          "line-color": "#fff",
        },
      },
    ],
  });

  const roadLabel = style.layers.find((layer) => layer.id === "base-road-labels") as
    | LayerWithSourceLayerForTest
    | undefined;

  assert.match(style.glyphs ?? "", /basemaps-assets\/fonts/);
  assert.equal(roadLabel?.type, "symbol");
  assert.equal(roadLabel?.["source-layer"], "roads");
  assert.equal(roadLabel?.layout?.["symbol-placement"], "line");
});

test("label patch is idempotent", () => {
  const style = buildPmtilesBasemapStyle("https://cdn.example.test/taiwan.pmtiles");
  const patched = ensureBasemapLabelLayers(style);

  assert.equal(
    patched.layers.filter((layer) => layer.id === "base-road-labels").length,
    1,
  );
});

test("runtime BASEMAP aliases avoid build-time NEXT_PUBLIC inlining", () => {
  const config = getBasemapStyleConfig({
    BASEMAP_ATTRIBUTION: "Example runtime env attribution",
    BASEMAP_KIND: "pmtiles",
    BASEMAP_PMTILES_URL: "https://cdn.example.test/runtime.pmtiles",
    NODE_ENV: "production",
  });

  assert.equal(config.kind, "pmtiles");

  if (typeof config.style === "string") {
    throw new Error("expected PMTiles style object");
  }

  assert.equal(
    (config.style.sources.basemap as VectorSourceForTest).url,
    "pmtiles://https://cdn.example.test/runtime.pmtiles",
  );
  assert.equal(
    (config.style.sources.basemap as AttributedSourceForTest).attribution,
    "Example runtime env attribution",
  );
});

test("NEXT_PUBLIC basemap values keep backwards compatibility", () => {
  const config = getBasemapStyleConfig({
    BASEMAP_KIND: "pmtiles",
    BASEMAP_PMTILES_URL: "https://cdn.example.test/runtime.pmtiles",
    NEXT_PUBLIC_BASEMAP_KIND: "raster",
    NEXT_PUBLIC_BASEMAP_RASTER_TILES: "https://tiles.example.test/{z}/{x}/{y}.png",
    NODE_ENV: "development",
  });

  assert.equal(config.kind, "raster");
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

test("production default avoids public OSM tiles when basemap is unconfigured", () => {
  const config = getBasemapStyleConfig({
    NODE_ENV: "production",
  });

  assert.equal(config.kind, "production-unconfigured");
  assert.match(config.warnings.join("\n"), /Production basemap is not configured/);

  if (typeof config.style === "string") {
    throw new Error("expected fallback style object");
  }

  assert.deepEqual(config.style.sources, {});
  assert.equal(config.style.layers.some((layer) => layer.id === "base-water"), true);
});

test("development default still allows local OSM raster fallback", () => {
  const config = getBasemapStyleConfig({
    NODE_ENV: "development",
  });

  assert.equal(config.kind, "dev-osm-raster");
  assert.match(config.warnings.join("\n"), /Development fallback is using public OpenStreetMap/);

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
  assert.match(config.warnings.join("\n"), /Production raster basemap is configured/);
});

test("runtime basemap config loader accepts the public config endpoint payload", async () => {
  const config = await loadRuntimeBasemapStyleConfig(async (input, init) => {
    assert.equal(input, "/basemap-config");
    assert.equal(init?.cache, "no-store");

    return new Response(
      JSON.stringify({
        kind: "pmtiles",
        style: buildPmtilesBasemapStyle(
          "https://cdn.example.test/taiwan.pmtiles",
          "Example runtime attribution",
        ),
        warnings: [],
      }),
      { status: 200 },
    );
  });

  assert.equal(config.kind, "pmtiles");
  assert.deepEqual(config.warnings, []);

  if (typeof config.style === "string") {
    throw new Error("expected PMTiles style object");
  }

  assert.equal(
    (config.style.sources.basemap as AttributedSourceForTest).attribution,
    "Example runtime attribution",
  );
});
