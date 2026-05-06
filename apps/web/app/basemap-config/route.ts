import { NextResponse } from "next/server";

import { getBasemapStyleConfig } from "../lib/basemap-style";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(getBasemapStyleConfig(), {
    headers: {
      "Cache-Control": "no-store",
    },
  });
}
