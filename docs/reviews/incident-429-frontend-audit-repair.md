# PR #429 frontend audit repair: local verification

Date: 2026-10-24. Refs #428; follow-up to the existing audit failure on
PR #429 head 44b5e7fa4b8954c7a7ad921a3df5cdd6d230023b.

## Cause and minimal dependency change

The prior head failed CI before frontend lint/typecheck/unit/E2E at npm audit:
Next.js 16.3.8 and transitive Zod 4.4.3 were already present in base main;
the DB diagnostics/fail-fast change did not introduce these packages.
The new change addresses that existing gate failure without weakening audit.

Official advisory metadata lists Next 16.4.1 as the minimum patched 16.x
version for GHSA-2464-fhr4-w9xw, GHSA-p3m5-59mp-jv5r and
GHSA-673q-mjm6-r5xr, and Zod 4.6.6 for GHSA-mrhx-c7xc-m3w5:

- https://github.com/advisories/GHSA-2464-fhr4-w9xw
- https://github.com/advisories/GHSA-p3m5-59mp-jv5r
- https://github.com/advisories/GHSA-673q-mjm6-r5xr
- https://github.com/advisories/GHSA-mrhx-c7xc-m3w5

Pin Next and matching eslint-config-next to 16.4.1 rather than accepting newer
16.4.3 through caret resolution. Override transitive Zod to 4.6.6 rather than
adding it as a runtime dependency or selecting newer 4.6.7. The React Hooks
plugin and its validation-error dependency accept Zod 4.x. Next still requires
Node >=20.9 and supports the existing React 19 and Playwright versions. No
major framework migration or application rewrite is needed. Other root
versions/overrides remain unchanged. Lockfile changes are the matching Next
packages and Zod, plus npm's hoisting of existing glob dependencies; no
unrelated package-version upgrades are included.

The installed @next/eslint-plugin-next 16.4.1 root discovery still calls
fast-glob.globSync with onlyDirectories. The scoped tinyglobby 0.2.17 alias is
retained; the installed-plugin glob-root and internal-link rule tests pass.
This remains a narrow compatibility override, requiring re-review on upgrades.

## Fresh local verification

Windows Node v24.17.0; CI Node 22 validation is recorded on the PR.
Commands below ran in apps/web; loopback ports were 18381/18382/18383.

| Command | Result |
|---|---|
| npm ci --no-fund | clean installation succeeded |
| npm audit --audit-level=high | 0 vulnerabilities |
| npm ls next eslint-config-next @next/eslint-plugin-next zod --depth=3 | Next/config/plugin 16.4.1; Zod 4.6.6 |
| npm run lint | passed, max warnings 0 |
| npm run typecheck | passed |
| npm test | 79 passed, 0 failed, including 2 installed-plugin alias tests |
| npm run build | Next 16.4.1 production build passed |
| npm run e2e | 18 passed, desktop/mobile, production build |
| npm run e2e:vector | 2 passed, real production basemap data on local Next server |
| git diff --check | passed |

Real-vector assertions cover Range 206, glyphs/Chinese labels/roads, query
center/zoom/marker, overlay order, real worker/shared ESM loading, attribution
sanitization and document teardown/remount. Desktop snapshot had 13 Range
responses, 1290 roads, 191 labels, 0.5 px marker error. Mobile had 7 Range
responses, 380 roads, 41 labels, approximately 0.5 px marker error. All recorded
archive responses were 206. Both had loaded sources/tiles and glyph responses.
Search screenshots were visually inspected; existing dense label overlap
remains. Risk endpoints are fixtures in this vector suite; these are not
production database acceptance tests.

Prepared public worker/shared bytes match installed MapLibre 6.4.1:
- worker SHA256: ce4957017fe705ac2f9ebef206cca966d08d8621756c39326a78cf09757e7d75
- shared SHA256: fcf4d81450df235da0aea74897cc23926774b5228d38ae1de6a7d701c5905785

## Limits

The local Docker daemon is not running: docker version could not connect to
//./pipe/dockerDesktopLinuxEngine (pipe not found). No daemon restart,
permission change or workaround was attempted. A new Docker image and its
browser acceptance were therefore not run. Prior image verification does not
validate this Next update. The local production build/start and real-vector
browser checks passed; CI still must complete for the new exact head.

Existing Node module-format, terminal-color and npm's ESLint 9 deprecation
warnings were observed; no lint warning was suppressed. Docker availability is an environment limit,
not an application test failure. No production login, request, restart,
configuration/data change, merge or deployment occurred in this follow-up.
The incident's database root cause and service recovery remain unproven.
