import { NextResponse } from "next/server";
import type { StyleSpecification } from "maplibre-gl";

import {
  ensureBasemapLabelLayers,
  getBasemapStyleConfig,
  type BasemapStyleConfig,
} from "../lib/basemap-style";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(await getRuntimeBasemapStyleConfig(), {
    headers: {
      "Cache-Control": "no-store",
    },
  });
}

async function getRuntimeBasemapStyleConfig(): Promise<BasemapStyleConfig> {
  const config = getBasemapStyleConfig();
  if (config.kind !== "style-url" || typeof config.style !== "string") {
    return config;
  }

  const patchedStyle = await fetchAndPatchStyleUrl(config.style);
  if (!patchedStyle) return config;

  return {
    ...config,
    style: patchedStyle,
  };
}

async function fetchAndPatchStyleUrl(styleUrl: string): Promise<StyleSpecification | null> {
  try {
    const response = await fetch(styleUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Style URL returned HTTP ${response.status}`);
    }

    const style: unknown = await response.json();
    if (!isStyleSpecification(style)) {
      throw new Error("Style URL did not return a MapLibre style document");
    }

    return ensureBasemapLabelLayers(style);
  } catch (error) {
    console.warn("Using configured basemap style URL without label patch.", error);
    return null;
  }
}

function isStyleSpecification(value: unknown): value is StyleSpecification {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<StyleSpecification>;
  return candidate.version === 8 && Array.isArray(candidate.layers) && !!candidate.sources;
}
