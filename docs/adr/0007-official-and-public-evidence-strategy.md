# ADR-0007: Official and Public Evidence Strategy

## Title

Official and Public Evidence Strategy

## Status

Accepted

## Date

2026-04-28

## Context

The SDD says official data is the basis for trustworthy risk judgment, but the MVP must not rely only on official data. At least one non-official public evidence family is required because public reports and discussions can be closer to on-the-ground conditions.

The project also explicitly rejects unauthorized large-scale scraping of Facebook, Instagram, and Threads, and does not allow anti-bot bypasses.

## Decision

Use official and open public data as the factual foundation for flood risk, including weather, water, and flood-potential sources.

Add at least one legally reviewed non-official public evidence family for MVP, with priority order:

1. News, RSS, or public web sources
2. PTT
3. Dcard
4. Authorized Meta-related sources

Forum adapters must be optional and disabled by default until legal/source review is complete. Facebook, Instagram, and Threads require official API access, Meta Content Library, research access, explicit permission, or a later ADR.

Non-official evidence must be displayed with source type, confidence, timestamp, and summary. It must not be the sole basis for asserting a flood fact.

## Consequences

The project balances official reliability with faster public situational awareness.

Legal and terms-of-service risk is reduced by preferring public web/news and authorized access paths.

Some potentially useful sources may remain unavailable until review or permission is complete.

The UI and API must make source confidence and evidence type visible.
