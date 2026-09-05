"""Behaviour tests for the local source dispatch watchdog dedupe helper.

The helper is JavaScript because it runs inside actions/github-script, so the
test drives its CLI through node. Issue bodies carry ``<`` and ``>`` in the
state marker, so they are always passed as files rather than as command-line
arguments: on Windows ``node`` can resolve to a ``.CMD`` shim that treats those
characters as shell redirections.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "scripts" / "ci" / "local-source-watchdog-state.js"

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _node() -> str:
    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the runner image
        pytest.skip("node is not available")
    return node


def _run(args: list[str]) -> str:
    completed = subprocess.run(
        [_node(), str(HELPER_PATH), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _decide(
    tmp_path: Path,
    *,
    digest: str,
    body: str,
    new_body: str = "fresh watchdog report",
    now: str,
    backoff_days: int = 7,
) -> dict:
    body_file = tmp_path / "body.md"
    body_file.write_text(body, encoding="utf-8")
    new_body_file = tmp_path / "new-body.md"
    new_body_file.write_text(new_body, encoding="utf-8")
    return json.loads(
        _run(
            [
                "--digest",
                digest,
                "--body-file",
                str(body_file),
                "--new-body-file",
                str(new_body_file),
                "--now",
                now,
                "--backoff-days",
                str(backoff_days),
            ]
        )
    )


def _state_of(body: str) -> dict:
    marker = "<!-- dispatch-state: "
    start = body.index(marker) + len(marker)
    end = body.index(" -->", start)
    return json.loads(body[start:end])


def _body_with_state(state: dict, text: str = "older watchdog report") -> str:
    return f"{text}\n\n<!-- dispatch-state: {json.dumps(state)} -->"


def _prior_state(digest: str = DIGEST_A, occurrences: int = 4) -> dict:
    return {
        "digest": digest,
        "first_seen_at": "2026-08-20T00:00:00.000Z",
        "last_seen_at": "2026-09-01T00:00:00.000Z",
        "last_comment_at": "2026-09-01T00:00:00.000Z",
        "occurrences": occurrences,
    }


def test_comments_when_the_bundle_digest_changes(tmp_path: Path) -> None:
    out = _decide(
        tmp_path,
        digest=DIGEST_B,
        body=_body_with_state(_prior_state()),
        now="2026-09-02T00:00:00Z",
    )

    assert out["shouldComment"] is True
    assert out["reason"] == "digest_changed"
    state = _state_of(out["newBody"])
    assert state["digest"] == DIGEST_B
    # A new digest is a new situation, so its counters restart.
    assert state["occurrences"] == 1
    assert state["first_seen_at"] == "2026-09-02T00:00:00.000Z"
    assert state["last_comment_at"] == "2026-09-02T00:00:00.000Z"


def test_suppresses_a_duplicate_comment_inside_the_backoff_window(
    tmp_path: Path,
) -> None:
    out = _decide(
        tmp_path,
        digest=DIGEST_A,
        body=_body_with_state(_prior_state(occurrences=4)),
        now="2026-09-02T00:00:00Z",
    )

    assert out["shouldComment"] is False
    assert out["reason"] == "suppressed"
    state = _state_of(out["newBody"])
    assert state["occurrences"] == 5
    assert state["last_seen_at"] == "2026-09-02T00:00:00.000Z"
    # The comment clock does not move while the comment is suppressed.
    assert state["last_comment_at"] == "2026-09-01T00:00:00.000Z"
    # The body still carries the newest report so it is readable without a comment.
    assert "fresh watchdog report" in out["newBody"]
    assert out["newBody"].count("<!-- dispatch-state:") == 1


def test_comments_again_once_the_backoff_window_has_elapsed(tmp_path: Path) -> None:
    out = _decide(
        tmp_path,
        digest=DIGEST_A,
        body=_body_with_state(_prior_state(occurrences=4)),
        now="2026-09-09T00:00:00Z",
    )

    assert out["shouldComment"] is True
    assert out["reason"] == "backoff_elapsed"
    state = _state_of(out["newBody"])
    assert state["occurrences"] == 5
    assert state["first_seen_at"] == "2026-08-20T00:00:00.000Z"
    assert state["last_comment_at"] == "2026-09-09T00:00:00.000Z"


def test_treats_a_body_without_a_state_marker_as_the_first_sighting(
    tmp_path: Path,
) -> None:
    out = _decide(
        tmp_path,
        digest=DIGEST_A,
        body="a watchdog body written before this helper existed",
        now="2026-09-02T00:00:00Z",
    )

    assert out["shouldComment"] is True
    assert out["reason"] == "digest_changed"
    state = _state_of(out["newBody"])
    assert state["digest"] == DIGEST_A
    assert state["occurrences"] == 1


def test_bundle_digest_ignores_the_per_run_captured_at_stamp(tmp_path: Path) -> None:
    """Two identical bundles from different runs must dedupe to one comment."""
    payload = {"queue": [{"queue_id": "q1", "request_type": "signal_gap"}]}
    digests = []
    for captured_at in ("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"):
        bundle = tmp_path / captured_at.replace(":", "-")
        bundle.mkdir()
        (bundle / "local-source-request-dispatch-queue.json").write_text(
            json.dumps({"captured_at": captured_at, **payload}),
            encoding="utf-8",
        )
        (bundle / "local-source-request-packet-bundle.md").write_text(
            f"captured_at: {captured_at}", encoding="utf-8"
        )
        digests.append(
            _run(["--bundle-dir", str(bundle), "--print-digest"]).strip()
        )

    assert digests[0] == digests[1]

    changed = tmp_path / "changed"
    changed.mkdir()
    (changed / "local-source-request-dispatch-queue.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-09-02T00:00:00Z",
                "queue": [{"queue_id": "q2", "request_type": "source_contract"}],
            }
        ),
        encoding="utf-8",
    )
    assert _run(["--bundle-dir", str(changed), "--print-digest"]).strip() != digests[0]


def test_bundle_digest_of_a_missing_directory_is_distinct_and_stable(
    tmp_path: Path,
) -> None:
    missing = str(tmp_path / "never-written")
    empty = tmp_path / "empty"
    empty.mkdir()
    populated = tmp_path / "populated"
    populated.mkdir()
    (populated / "queue.json").write_text("{}", encoding="utf-8")

    missing_digest = _run(["--bundle-dir", missing, "--print-digest"]).strip()
    assert missing_digest == _run(["--bundle-dir", str(empty), "--print-digest"]).strip()
    assert (
        missing_digest
        != _run(["--bundle-dir", str(populated), "--print-digest"]).strip()
    )
