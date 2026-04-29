import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const internalApiBaseUrl = process.env.INTERNAL_API_BASE_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: __dirname,
  reactStrictMode: true,
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
