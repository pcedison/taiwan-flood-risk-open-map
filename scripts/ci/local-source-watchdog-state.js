"use strict";

/**
 * Deduplicated, backed-off commenting for the local source dispatch watchdog.
 *
 * The watchdog runs on a daily schedule and, before this helper existed, added
 * one comment per run to the same issue even when nothing had changed; issue
 * #71 in this repository collected 18 comments that all said the same thing.
 *
 * The identity of a run is the request-packet bundle it produced: when the
 * bundle is byte-identical to the previous run's, the operator has nothing new
 * to act on. State is stored in an HTML comment at the end of the issue body,
 * the same trick `scripts/ci/route-alert-issue.js` uses, so no external storage
 * is needed and a human can still read it.
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DEFAULT_BACKOFF_DAYS = 7;
const DEFAULT_BUNDLE_DIR = "artifacts/request-packet-bundle";
const STATE_PREFIX = "<!-- dispatch-state: ";
const STATE_SUFFIX = " -->";
const STATE_PATTERN = /<!-- dispatch-state: (\{[\s\S]*?\}) -->/;

// Every bundle file stamps the run's wall clock into `captured_at`. Hashing it
// would make every run look different and defeat the deduplication, so it is
// dropped before hashing; every other field is content the operator cares about.
const VOLATILE_KEYS = new Set(["captured_at"]);

/** Recursively drop volatile keys and sort object keys so hashing is stable. */
function canonicalize(value) {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value && typeof value === "object") {
    const canonical = {};
    for (const key of Object.keys(value).sort()) {
      if (VOLATILE_KEYS.has(key)) {
        continue;
      }
      canonical[key] = canonicalize(value[key]);
    }
    return canonical;
  }
  return value;
}

function canonicalContent(raw) {
  try {
    return JSON.stringify(canonicalize(JSON.parse(raw)));
  } catch {
    // A file the bundle writer produced that is not valid JSON is still a
    // meaningful change signal, so hash it verbatim rather than dropping it.
    return raw;
  }
}

/**
 * SHA-256 over every `*.json` file in the bundle directory, sorted by filename.
 *
 * A missing or empty directory hashes to a stable digest of its own, so a run
 * that failed before writing the bundle does not masquerade as a bundle change.
 *
 * @returns {string} hex digest
 */
function bundleDigest(bundleDir = DEFAULT_BUNDLE_DIR) {
  let names = [];
  try {
    names = fs.readdirSync(bundleDir);
  } catch {
    names = [];
  }
  const hash = crypto.createHash("sha256");
  for (const name of names.filter((entry) => entry.endsWith(".json")).sort()) {
    let raw;
    try {
      raw = fs.readFileSync(path.join(bundleDir, name), "utf8");
    } catch {
      continue;
    }
    hash.update(`${name}\n${canonicalContent(raw)}\n`);
  }
  return hash.digest("hex");
}

function parseState(body) {
  const match = STATE_PATTERN.exec(body || "");
  if (!match) {
    return {};
  }
  try {
    return JSON.parse(match[1]);
  } catch {
    return {};
  }
}

function renderBody(body, state) {
  const stripped = (body || "").replace(STATE_PATTERN, "").trimEnd();
  return `${stripped}\n\n${STATE_PREFIX}${JSON.stringify(state)}${STATE_SUFFIX}`;
}

/**
 * Decide whether this run earns a comment, and render the body to write back.
 *
 * @param {object} options
 * @param {string} options.digest bundle digest for this run
 * @param {string} [options.body] the issue body as it stands, carrying the state
 * @param {string} [options.newBody] freshly composed report text; defaults to
 *   the existing body with its state marker stripped
 * @param {Date|string} [options.now]
 * @param {number} [options.backoffDays]
 * @returns {{shouldComment: boolean, newBody: string, reason: "digest_changed"|"backoff_elapsed"|"suppressed"}}
 */
function decideDispatchComment({
  digest,
  body = "",
  newBody = null,
  now = new Date(),
  backoffDays = DEFAULT_BACKOFF_DAYS,
}) {
  const nowDate = now instanceof Date ? now : new Date(now);
  const nowIso = nowDate.toISOString();
  const previous = parseState(body);

  const hadState = typeof previous.digest === "string" && previous.digest !== "";
  const sameDigest = hadState && previous.digest === digest;
  const lastCommentAt = Date.parse(previous.last_comment_at || "");
  const backoffMs = backoffDays * 24 * 60 * 60 * 1000;
  const backoffElapsed =
    !Number.isFinite(lastCommentAt) || nowDate.getTime() - lastCommentAt >= backoffMs;

  let reason;
  if (!sameDigest) {
    reason = "digest_changed";
  } else if (backoffElapsed) {
    reason = "backoff_elapsed";
  } else {
    reason = "suppressed";
  }
  const shouldComment = reason !== "suppressed";

  const state = {
    digest,
    // A new digest is a new situation, so its counters restart.
    first_seen_at: sameDigest ? previous.first_seen_at || nowIso : nowIso,
    last_seen_at: nowIso,
    last_comment_at: shouldComment ? nowIso : previous.last_comment_at || nowIso,
    occurrences:
      sameDigest && Number.isFinite(previous.occurrences) ? previous.occurrences + 1 : 1,
  };

  const content =
    newBody === null || newBody === undefined
      ? (body || "").replace(STATE_PATTERN, "").trimEnd()
      : newBody;

  return { shouldComment, newBody: renderBody(content, state), reason };
}

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (!flag.startsWith("--")) {
      continue;
    }
    const key = flag.slice(2);
    const next = argv[index + 1];
    if (next === undefined || next.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = next;
      index += 1;
    }
  }
  return args;
}

function readFileArg(value) {
  return value === undefined ? "" : fs.readFileSync(value, "utf8");
}

function main(argv) {
  const args = parseArgs(argv);
  const digest =
    typeof args.digest === "string" ? args.digest : bundleDigest(args["bundle-dir"] || DEFAULT_BUNDLE_DIR);
  if (args["print-digest"]) {
    process.stdout.write(`${digest}\n`);
    return;
  }
  const decision = decideDispatchComment({
    digest,
    body: readFileArg(args["body-file"]),
    newBody: args["new-body-file"] === undefined ? null : readFileArg(args["new-body-file"]),
    now: typeof args.now === "string" ? new Date(args.now) : new Date(),
    backoffDays:
      typeof args["backoff-days"] === "string"
        ? Number(args["backoff-days"])
        : DEFAULT_BACKOFF_DAYS,
  });
  process.stdout.write(`${JSON.stringify({ ...decision, digest })}\n`);
}

if (require.main === module) {
  main(process.argv.slice(2));
}

module.exports = {
  DEFAULT_BACKOFF_DAYS,
  DEFAULT_BUNDLE_DIR,
  bundleDigest,
  decideDispatchComment,
  parseState,
  renderBody,
};
