# Local Scratch Artifacts

`tmp/` is reserved for local, regenerable artifacts: browser screenshots, smoke-test
responses, downloaded open-data samples, generated geocoder rows, basemap build
outputs, and deployment/debug logs.

Keep this directory out of normal commits. If an artifact becomes durable project
evidence, promote a small reviewed summary into `docs/` or a fixture into the
relevant test directory instead of committing raw `tmp/` contents.
