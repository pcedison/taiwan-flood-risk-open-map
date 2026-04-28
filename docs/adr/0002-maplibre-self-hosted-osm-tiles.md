# ADR-0002: MapLibre and Self-Hosted OSM Tiles

## Title

MapLibre and Self-Hosted OSM Tiles

## Status

Accepted

## Date

2026-04-28

## Context

The product is map-first and must remain open-source-first, self-hostable, and usable without a commercial map API. During development, public OpenStreetMap tiles may be acceptable. For public deployment, the SDD prefers self-hosted Taiwan OSM vector tiles, rendered with MapLibre GL JS, and built from Geofabrik Taiwan extract or another official usable OSM extract.

OSM-derived data carries attribution and ODbL obligations. Map layer changes should be isolated behind layer metadata and tile/source endpoints.

## Decision

Use MapLibre GL JS as the primary web map renderer.

Use self-hosted Taiwan OSM vector tiles for public staging and production beta. Public OSM tiles may be used only for local development, prototypes, or temporary fallback while self-hosted tiles are unavailable.

Build tile data from Geofabrik Taiwan extract or another official usable OSM extract. Maintain attribution, source metadata, and license notes for OSM-derived layers.

Expose map sources through explicit layer metadata and tile/source endpoint configuration so new layers do not require changes to the core query flow.

## Consequences

The project avoids lock-in to commercial map providers and can run in self-hosted environments.

Production operations must include tile generation, tile serving, cache behavior, and OSM attribution checks.

ODbL compliance must be considered whenever OSM-derived data is stored, transformed, or exported.

Development can move quickly with public tiles, but production readiness depends on self-hosted tile infrastructure.
