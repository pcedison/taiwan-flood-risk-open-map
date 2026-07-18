import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const internalApiBaseUrl =
  process.env.INTERNAL_API_BASE_URL?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";

// External origins the browser may contact: basemap style/tiles (env-driven),
// a direct API base when configured, plus an operator escape hatch
// (CSP_EXTRA_ORIGINS, comma-separated) for style-referenced hosts such as
// glyph/sprite CDNs — extend without a code change.
function contentSecurityPolicyOrigins() {
  const values = [
    process.env.NEXT_PUBLIC_BASEMAP_STYLE_URL,
    process.env.NEXT_PUBLIC_BASEMAP_PMTILES_URL,
    process.env.NEXT_PUBLIC_BASEMAP_RASTER_TILES,
    // Runtime aliases served through /basemap-config (see
    // app/lib/basemap-style.ts basemapEnvValue) must be allowlisted too.
    process.env.BASEMAP_STYLE_URL,
    process.env.BASEMAP_PMTILES_URL,
    process.env.BASEMAP_RASTER_TILES,
    process.env.NEXT_PUBLIC_API_BASE_URL,
    process.env.CSP_EXTRA_ORIGINS,
  ];
  // Hosts baked into the app's own style builder (app/lib/basemap-style.ts):
  // the Protomaps glyph host used by the built-in PMTiles label layers and
  // the OSM raster tiles used as the local/dev fallback basemap.
  const origins = new Set([
    "https://protomaps.github.io",
    "https://tile.openstreetmap.org",
  ]);
  for (const value of values) {
    if (!value) continue;
    for (const raw of value.split(",")) {
      // Tile templates may carry a {s} subdomain placeholder; map it to a
      // CSP host wildcard.
      const candidate = raw.trim().replace(/\{s\}/g, "csp-subdomain-wildcard");
      if (!candidate) continue;
      try {
        const url = new URL(candidate);
        const host = url.host.replace(/csp-subdomain-wildcard/g, "*");
        origins.add(`${url.protocol}//${host}`);
      } catch {
        // Relative or non-URL values are covered by 'self'.
      }
    }
  }
  return [...origins].join(" ");
}

function contentSecurityPolicy() {
  const origins = contentSecurityPolicyOrigins();
  return [
    "default-src 'self'",
    // Next.js injects inline bootstrap scripts/styles; external hosts stay
    // blocked, which is the main win for this defense-in-depth layer.
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob:${origins ? ` ${origins}` : ""}`,
    "font-src 'self' data:",
    `connect-src 'self'${origins ? ` ${origins}` : ""}`,
    // MapLibre GL runs its workers from blob: URLs.
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy() },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: __dirname,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/v1/:path*",
        destination: `${internalApiBaseUrl}/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${internalApiBaseUrl}/health`,
      },
      {
        source: "/ready",
        destination: `${internalApiBaseUrl}/ready`,
      },
    ];
  },
};

export default nextConfig;
