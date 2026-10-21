import assert from "node:assert/strict";
import test from "node:test";
import { registerPmtilesProtocol } from "../../app/lib/map-setup.ts";

test("PMTiles cleanup does not unregister a newer map's protocol", () => {
  const operations: string[] = [];
  const maplibre = {
    addProtocol: (name: string) => operations.push(`add:${name}`),
    removeProtocol: (name: string) => operations.push(`remove:${name}`),
  } as unknown as typeof import("maplibre-gl");

  const cleanupFirstMap = registerPmtilesProtocol(maplibre);
  const cleanupSecondMap = registerPmtilesProtocol(maplibre);
  cleanupFirstMap();
  assert.deepEqual(operations, ["remove:pmtiles", "add:pmtiles", "remove:pmtiles", "add:pmtiles"]);
  cleanupSecondMap();
  assert.equal(operations.at(-1), "remove:pmtiles");
  assert.equal(operations.length, 5);
  cleanupSecondMap();
  assert.equal(operations.length, 5);
});
