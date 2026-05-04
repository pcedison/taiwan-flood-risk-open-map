"""Dcard public discussion adapter acceptance boundary.

This module intentionally does not implement live fetching, crawling, or
scraping. The candidate adapter only normalizes caller-supplied synthetic local
fixtures so the pipeline contract can be tested without touching Dcard.
"""

from __future__ import annotations

from typing import Final

from app.adapters._forum_candidate import ForumCandidateFixtureAdapter
from app.adapters.contracts import AdapterMetadata, SourceFamily


ADAPTER_DISABLED_REASON: Final[str] = (
    "Dcard ingestion is blocked pending source approval, legal/terms/API "
    "review, forum allowlist, privacy minimization, retention, moderation, "
    "opt-out, and rate-limit acceptance."
)
SOURCE_APPROVAL_STATUS: Final[str] = "blocked"
REQUIRED_ACCEPTANCE_FIELDS: Final[tuple[str, ...]] = (
    "approved_forum_allowlist",
    "approved_access_method_or_authorized_api",
    "robots_terms_api_review_links",
    "no_login_hidden_content_or_antibot_bypass_attestation",
    "stored_field_inventory",
    "user_identity_exclusion_policy",
    "raw_body_retention_limit",
    "moderation_rejection_rules",
    "rate_limit_quota_and_backoff_policy",
    "audit_log_events",
    "opt_out_delete_workflow",
    "emergency_disable_owner",
)

METADATA: Final[AdapterMetadata] = AdapterMetadata(
    key="dcard",
    family=SourceFamily.FORUM,
    enabled_by_default=False,
    display_name="Dcard public discussion adapter (blocked pending approval)",
    terms_review_required=True,
)


class DcardCandidateFixtureAdapter(ForumCandidateFixtureAdapter):
    def __init__(self, records, *, fetched_at=None, raw_snapshot_key=None) -> None:
        super().__init__(
            records,
            metadata=METADATA,
            platform="Dcard",
            source_approval_status=SOURCE_APPROVAL_STATUS,
            disabled_reason=ADAPTER_DISABLED_REASON,
            required_acceptance_fields=REQUIRED_ACCEPTANCE_FIELDS,
            fetched_at=fetched_at,
            raw_snapshot_key=raw_snapshot_key,
        )


__all__ = [
    "ADAPTER_DISABLED_REASON",
    "DcardCandidateFixtureAdapter",
    "METADATA",
    "REQUIRED_ACCEPTANCE_FIELDS",
    "SOURCE_APPROVAL_STATUS",
]
