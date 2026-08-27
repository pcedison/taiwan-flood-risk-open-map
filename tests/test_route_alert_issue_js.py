"""Behaviour tests for the shared Actions alert-routing helper.

The helper is JavaScript because it runs inside actions/github-script, so the
test drives it through node with a stub GitHub client.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "scripts" / "ci" / "route-alert-issue.js"

HARNESS = """
const helper = require(process.argv[2]);
const scenario = JSON.parse(process.argv[3]);

const calls = [];
const issues = scenario.issues.map((issue) => ({ ...issue }));

const github = {
  rest: {
    issues: {
      listForRepo: async () => ({ data: issues }),
      create: async (params) => {
        calls.push({ op: "create", body: params.body, title: params.title });
        const created = { number: 1, title: params.title, body: params.body };
        issues.push(created);
        return { data: created };
      },
      update: async (params) => {
        calls.push({ op: "update", number: params.issue_number, body: params.body, state: params.state });
        const target = issues.find((issue) => issue.number === params.issue_number);
        if (target && params.body !== undefined) {
          target.body = params.body;
        }
        return { data: target };
      },
      createComment: async (params) => {
        calls.push({ op: "createComment", number: params.issue_number, body: params.body });
        return { data: { id: 1 } };
      },
    },
  },
};
const context = { repo: { owner: "o", repo: "r" } };
const core = { info: () => {} };

(async () => {
  const result = await helper.routeAlertIssue({
    github,
    context,
    core,
    title: scenario.title,
    body: scenario.body,
    signature: scenario.signature,
    backoffHours: scenario.backoffHours,
    now: new Date(scenario.now),
  });
  process.stdout.write(JSON.stringify({ result, calls, issues }));
})().catch((error) => {
  process.stderr.write(String(error && error.stack));
  process.exit(1);
});
"""


def _run(scenario: dict, tmp_path: Path) -> dict:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the runner image
        pytest.skip("node is not available")
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    completed = subprocess.run(
        [node, str(harness), str(HELPER_PATH), json.dumps(scenario)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _state_of(body: str) -> dict:
    marker = "<!-- alert-state: "
    start = body.index(marker) + len(marker)
    end = body.index(" -->", start)
    return json.loads(body[start:end])


def test_opens_a_new_issue_when_none_exists(tmp_path: Path) -> None:
    out = _run(
        {
            "issues": [],
            "title": "[alert] boom",
            "body": "first failure",
            "signature": "aaaa",
            "backoffHours": 24,
            "now": "2026-08-27T00:00:00Z",
        },
        tmp_path,
    )

    assert out["result"]["action"] == "created"
    assert [call["op"] for call in out["calls"]] == ["create"]
    assert _state_of(out["calls"][0]["body"])["signature"] == "aaaa"


def test_suppresses_a_duplicate_comment_inside_the_backoff_window(tmp_path: Path) -> None:
    existing_state = json.dumps(
        {
            "signature": "aaaa",
            "first_seen_at": "2026-08-26T00:00:00.000Z",
            "last_seen_at": "2026-08-26T23:00:00.000Z",
            "last_alert_at": "2026-08-26T23:00:00.000Z",
            "occurrences": 7,
        }
    )
    out = _run(
        {
            "issues": [
                {
                    "number": 42,
                    "title": "[alert] boom",
                    "body": f"older body\n\n<!-- alert-state: {existing_state} -->",
                }
            ],
            "title": "[alert] boom",
            "body": "same failure again",
            "signature": "aaaa",
            "backoffHours": 24,
            "now": "2026-08-27T00:00:00Z",
        },
        tmp_path,
    )

    assert out["result"]["action"] == "suppressed"
    ops = [call["op"] for call in out["calls"]]
    assert "createComment" not in ops
    assert ops == ["update"]
    # The body is still refreshed so the newest state is visible without a comment.
    assert "same failure again" in out["calls"][0]["body"]
    state = _state_of(out["calls"][0]["body"])
    assert state["occurrences"] == 8
    assert state["last_alert_at"] == "2026-08-26T23:00:00.000Z"


def test_comments_when_the_failure_signature_changes(tmp_path: Path) -> None:
    existing_state = json.dumps(
        {
            "signature": "aaaa",
            "first_seen_at": "2026-08-26T00:00:00.000Z",
            "last_seen_at": "2026-08-26T23:00:00.000Z",
            "last_alert_at": "2026-08-26T23:00:00.000Z",
            "occurrences": 7,
        }
    )
    out = _run(
        {
            "issues": [
                {
                    "number": 42,
                    "title": "[alert] boom",
                    "body": f"older body\n\n<!-- alert-state: {existing_state} -->",
                }
            ],
            "title": "[alert] boom",
            "body": "a different failure",
            "signature": "bbbb",
            "backoffHours": 24,
            "now": "2026-08-27T00:00:00Z",
        },
        tmp_path,
    )

    assert out["result"]["action"] == "commented"
    assert [call["op"] for call in out["calls"]] == ["update", "createComment"]


def test_comments_again_once_the_backoff_window_has_elapsed(tmp_path: Path) -> None:
    existing_state = json.dumps(
        {
            "signature": "aaaa",
            "first_seen_at": "2026-08-20T00:00:00.000Z",
            "last_seen_at": "2026-08-25T00:00:00.000Z",
            "last_alert_at": "2026-08-25T00:00:00.000Z",
            "occurrences": 3,
        }
    )
    out = _run(
        {
            "issues": [
                {
                    "number": 42,
                    "title": "[alert] boom",
                    "body": f"older body\n\n<!-- alert-state: {existing_state} -->",
                }
            ],
            "title": "[alert] boom",
            "body": "still failing",
            "signature": "aaaa",
            "backoffHours": 24,
            "now": "2026-08-27T00:00:00Z",
        },
        tmp_path,
    )

    assert out["result"]["action"] == "commented"
    assert [call["op"] for call in out["calls"]] == ["update", "createComment"]


def test_state_marker_is_not_duplicated_across_runs(tmp_path: Path) -> None:
    scenario_body = "failure text"
    first = _run(
        {
            "issues": [],
            "title": "[alert] boom",
            "body": scenario_body,
            "signature": "aaaa",
            "backoffHours": 24,
            "now": "2026-08-27T00:00:00Z",
        },
        tmp_path,
    )
    created_body = first["calls"][0]["body"]

    second = _run(
        {
            "issues": [{"number": 1, "title": "[alert] boom", "body": created_body}],
            "title": "[alert] boom",
            "body": scenario_body,
            "signature": "aaaa",
            "backoffHours": 24,
            "now": "2026-08-27T01:00:00Z",
        },
        tmp_path,
    )

    updated_body = second["calls"][0]["body"]
    assert updated_body.count("<!-- alert-state:") == 1
