import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// MapLibre 6's module worker imports this sibling shared module. Keep the
// installed pair together, outside Turbopack's rewriting of worker URLs.
const distDirectory = dirname(fileURLToPath(import.meta.resolve("maplibre-gl")));
const publicDirectory = fileURLToPath(new URL("../public/maplibre/", import.meta.url));
await mkdir(publicDirectory, { recursive: true });
for (const filename of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  await copyFile(join(distDirectory, filename), join(publicDirectory, filename));
}
