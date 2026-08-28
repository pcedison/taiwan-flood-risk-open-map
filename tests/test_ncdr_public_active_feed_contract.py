from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT / "infra" / "migrations" / "0044_ncdr_public_active_feed_source.sql"
)
CATALOG = (
    REPO_ROOT / "docs" / "data-sources" / "official" / "official-source-catalog.yaml"
)
PUBLIC_ACTIVE_FEED = "https://alerts.ncdr.nat.gov.tw/RssAtomFeeds.ashx"


def test_ncdr_catalog_and_migration_use_the_public_active_feed() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    source = next(
        item for item in catalog["sources"] if item["key"] == "official.ncdr.cap"
    )

    assert source["resource_url"] == PUBLIC_ACTIVE_FEED
    assert PUBLIC_ACTIVE_FEED in migration
    assert "public_feed_authentication', 'none'" in migration
    assert "member_api_key', 'optional'" in migration
    assert "feed_refresh_seconds', 60" in migration
    assert "is_enabled" not in migration
    assert "spatial_review" not in migration
