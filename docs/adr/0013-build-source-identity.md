# ADR-0013: Retain public source identity through a multi-stage image

- Status: Proposed; local validation only
- Date: 2026-10-21

## Context

After release #422, Zeabur reported successful deployment and real hosted
vector/query acceptance passed, but health/readiness returned deployment_sha=null.
The API resolver currently reads runtime metadata only. Zeabur documents Git
metadata as build-only and supports explicit ARG auto-injection for multi-stage
Docker builds. Missing identity must continue to fail expected-SHA acceptance.

## Decision

Declare ARG ZEABUR_GIT_COMMIT_SHA and retain it as IMAGE_SOURCE_SHA in the final
image configuration. It is public source identity, not a credential. Existing
runtime SHA aliases retain precedence. Only a full hexadecimal image SHA is
accepted as fallback; missing/malformed data stays unknown. Do not extract SHA
from a cached RUN secret mount or pin a permanent service value to one release.

## Consequences

ARG/ENV values make public identity part of image configuration and cache
identity. Validate two builds with identical source/cache but distinct SHA args
and inspect the runtime resolver with no runtime Git metadata. This is trusted
builder input, not cryptographic attestation. Confirm actual production SHA
against the final merged commit before declaring acceptance. No source-health,
security, DB or expected-SHA gate is relaxed.

## References

- https://zeabur.com/docs/en-US/deploy/methods/dockerfile#arg
- https://zeabur.com/docs/en-US/deploy/config/environment-variables#git-information


## Local verification

46 targeted API/config/deployment-contract tests passed; Ruff and mypy passed.
Independent review found no remaining code blockers after replacing RUN-mounted
metadata persistence with explicit ARG/ENV. Two full Docker builds with identical
source and all shared layers cached, using a40 then b40 public test values,
returned the matching distinct values through the runtime API settings resolver.
These are local test identities, not claims about actual deployed source.
Tracking: Refs #426. Publication and production acceptance are recorded in the
linked repair PR; local test identities are not deployed version evidence.
