import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
// Exercise the installed Next plugin, so an incompatible glob replacement fails.
const { getRootDirs } = require("@next/eslint-plugin-next/dist/utils/get-root-dirs.js") as {
  getRootDirs: (context: { cwd: string; settings: { next?: { rootDir?: unknown } } }) => string[];
};

test("Next ESLint root discovery supports directories, braces, arrays and Windows paths", () => {
  const root = mkdtempSync(join(tmpdir(), "flood-next-roots-"));
  const normal = (path: string) => resolve(path).replaceAll("\\", "/");
  try {
    for (const name of ["web", "admin", "api"]) mkdirSync(join(root, name));
    const discover = (rootDir: unknown) => getRootDirs({ cwd: root, settings: { next: { rootDir } } }).map(normal).sort();
    assert.deepEqual(getRootDirs({ cwd: root, settings: {} }), [root]);
    assert.deepEqual(discover(normal(root) + "/{web,admin}"),
      [normal(join(root, "admin")), normal(join(root, "web"))].sort());
    assert.deepEqual(discover([normal(root) + "/w*", normal(root) + "/a*", null]),
      ["admin", "api", "web"].map((name) => normal(join(root, name))).sort());
    assert.deepEqual(discover(join(root, "web").replaceAll("/", "\\")),
      [normal(join(root, "web"))]);
    assert.deepEqual(discover(normal(root) + "/missing-*"), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});


test("Next link lint still detects internal anchors with a globbed root", () => {
  const root = mkdtempSync(join(tmpdir(), "flood-next-link-"));
  try {
    mkdirSync(join(root, "web", "pages"), { recursive: true });
    writeFileSync(join(root, "web", "pages", "about.js"), "export default function Page() {}\n");
    const { Linter } = require("eslint");
    const next = require("@next/eslint-plugin-next");
    const messages = new Linter().verify('<a href="/about">About</a>', [{
      files: ["**/*.jsx"],
      languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
      plugins: { "@next/next": next },
      settings: { next: { rootDir: root.replaceAll("\\", "/") + "/{web,missing}" } },
      rules: { "@next/next/no-html-link-for-pages": "error" },
    }], { filename: "component.jsx" });
    assert.equal(messages.length, 1);
    assert.equal(messages[0].ruleId, "@next/next/no-html-link-for-pages");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
