# Worker Tests

Worker tests are fixture-first. External data adapters must prove that they can:

- fetch a raw source item from a stable fixture;
- accept an injected fetcher for live-client code paths so tests never call
  external APIs;
- normalize it into `NormalizedEvidence`;
- preserve source URL, timestamp, source family, event type, attribution, and confidence;
- pass promotion validation before production persistence is added;
- project adapter run results into raw snapshot and staging evidence upserts.

Runtime live clients stay disabled by default. CWA and WRA API adapters are
covered with official-shaped payload fixtures plus injected fetchers.
