from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_major_updates_require_explicit_migration_review() -> None:
    config = yaml.safe_load(
        (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    npm_updates = next(
        update
        for update in config["updates"]
        if update["package-ecosystem"] == "npm" and update["directory"] == "/apps/web"
    )

    ignored_major_updates = {
        item["dependency-name"]
        for item in npm_updates["ignore"]
        if item["update-types"] == ["version-update:semver-major"]
    }

    assert ignored_major_updates == {"eslint", "maplibre-gl"}
