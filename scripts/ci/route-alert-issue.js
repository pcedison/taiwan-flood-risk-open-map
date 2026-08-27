"use strict";

/**
 * Deduplicated, backed-off alert issue routing for GitHub Actions watchdogs.
 *
 * Without deduplication a workflow that fails every scheduled run appends one
 * comment per run forever; issues #198/#199 in this repository accumulated 94
 * comments that all said the same thing. This helper keeps a single issue per
 * alert title, always refreshes its body with the newest state, and only adds a
 * comment when the failure signature changes or the backoff window has elapsed.
 *
 * State is stored in an HTML comment at the end of the issue body so the helper
 * needs no external storage and stays readable to humans.
 */

const crypto = require("crypto");

const DEFAULT_BACKOFF_HOURS = 24;
const STATE_PREFIX = "<!-- alert-state: ";
const STATE_SUFFIX = " -->";
const STATE_PATTERN = /<!-- alert-state: (\{[\s\S]*?\}) -->/;

/** Stable short hash of the parts that identify one distinct failure mode. */
function alertSignature(parts) {
  const normalized = (Array.isArray(parts) ? parts : [parts])
    .filter((part) => part !== undefined && part !== null && part !== "")
    .map(String)
    .join("\n");
  return crypto.createHash("sha256").update(normalized).digest("hex").slice(0, 16);
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
 * @returns {Promise<{action: "created"|"commented"|"suppressed", number: number, occurrences: number}>}
 */
async function routeAlertIssue({
  github,
  context,
  core,
  title,
  body,
  signature,
  backoffHours = DEFAULT_BACKOFF_HOURS,
  now = new Date(),
}) {
  const { owner, repo } = context.repo;
  const nowIso = now.toISOString();

  const { data: issues } = await github.rest.issues.listForRepo({
    owner,
    repo,
    state: "open",
    per_page: 100,
  });
  const existing = issues.find((issue) => issue.title === title);

  if (!existing) {
    const state = {
      signature,
      first_seen_at: nowIso,
      last_seen_at: nowIso,
      last_alert_at: nowIso,
      occurrences: 1,
    };
    const { data: created } = await github.rest.issues.create({
      owner,
      repo,
      title,
      body: renderBody(body, state),
    });
    core.info(`Opened ${title} (#${created.number}).`);
    return { action: "created", number: created.number, occurrences: 1 };
  }

  const previous = parseState(existing.body);
  const sameSignature = previous.signature === signature;
  const lastAlertAt = Date.parse(previous.last_alert_at || "");
  const withinBackoff =
    Number.isFinite(lastAlertAt) &&
    now.getTime() - lastAlertAt < backoffHours * 60 * 60 * 1000;
  const shouldComment = !(sameSignature && withinBackoff);
  const occurrences = Number.isFinite(previous.occurrences) ? previous.occurrences + 1 : 1;

  const state = {
    signature,
    first_seen_at: previous.first_seen_at || nowIso,
    last_seen_at: nowIso,
    last_alert_at: shouldComment ? nowIso : previous.last_alert_at || nowIso,
    occurrences,
  };

  // Refresh the body every run so the newest state is visible without a comment.
  const summaryLines = [
    body,
    "",
    `Recurring alert: seen ${occurrences} time(s) since ${state.first_seen_at}; latest run at ${nowIso}.`,
    shouldComment
      ? ""
      : `Comment suppressed: same failure signature within the ${backoffHours}h backoff window. This body is the newest state.`,
  ].filter((line) => line !== "");
  await github.rest.issues.update({
    owner,
    repo,
    issue_number: existing.number,
    body: renderBody(summaryLines.join("\n"), state),
  });

  if (!shouldComment) {
    core.info(
      `Suppressed duplicate comment on #${existing.number}: signature ${signature} already alerted at ${previous.last_alert_at}.`,
    );
    return { action: "suppressed", number: existing.number, occurrences };
  }

  await github.rest.issues.createComment({
    owner,
    repo,
    issue_number: existing.number,
    body: `${body}\n\n<!-- alert-signature: ${signature} -->`,
  });
  core.info(`Commented on #${existing.number} (signature ${signature}).`);
  return { action: "commented", number: existing.number, occurrences };
}

/** Close an open alert issue once the underlying condition is resolved. */
async function closeAlertIssue({ github, context, core, title, body }) {
  const { owner, repo } = context.repo;
  const { data: issues } = await github.rest.issues.listForRepo({
    owner,
    repo,
    state: "open",
    per_page: 100,
  });
  const existing = issues.find((issue) => issue.title === title);
  if (!existing) {
    core.info(`No open ${title} to close.`);
    return { action: "noop" };
  }
  await github.rest.issues.createComment({
    owner,
    repo,
    issue_number: existing.number,
    body,
  });
  await github.rest.issues.update({
    owner,
    repo,
    issue_number: existing.number,
    state: "closed",
    state_reason: "completed",
  });
  core.info(`Closed #${existing.number}.`);
  return { action: "closed", number: existing.number };
}

module.exports = {
  DEFAULT_BACKOFF_HOURS,
  alertSignature,
  closeAlertIssue,
  parseState,
  renderBody,
  routeAlertIssue,
};
