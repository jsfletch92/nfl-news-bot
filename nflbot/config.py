"""Configuration and environment loading.

All secrets are read from environment variables — never from a file committed
to the repo. See README.md for the variable names and how to set them in the
scheduled-routine settings.

News is sourced from public RSS feeds (see feeds.py); the X API is only used to
*post* to the operator's own account.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Path (relative to repo root) of the committed de-duplication record.
STATE_FILE = os.environ.get("STATE_FILE", "state.json")


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            "Set it in the scheduled-routine settings (see README.md)."
        )
    return value


@dataclass(frozen=True)
class Config:
    # X (Twitter) API credentials — OAuth 1.0a user context, for POSTING only.
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_token_secret: str

    # Anthropic API for original-wording summarisation, classification, ranking.
    anthropic_api_key: str
    anthropic_model: str

    # Behaviour knobs.
    # Max items considered per feed each run (newest first).
    max_items_per_feed: int = 25
    # Hard cap on posts per UTC calendar day.
    max_posts_per_day: int = 10
    # Overlap-coefficient threshold for treating two headlines as the same story
    # (used both for clustering within a run and for cross-run de-duplication).
    story_similarity_threshold: float = 0.4
    # Posts released from the queue per run (staggered delivery, improvement 2).
    release_per_run: int = 2
    # Queued posts older than this are dropped unposted (stale news), in hours.
    queue_ttl_hours: int = 24
    # Hard ceiling on total post length (improvement 5); kept under X's 280 with
    # headroom, measured with X-style weighting (emoji counts as 2).
    max_total_chars: int = 270
    # Character budget hint passed to Haiku for the summary body.
    summary_target_chars: int = 200
    # When True, log what would be posted without calling the X write API.
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            x_api_key=_require("X_API_KEY"),
            x_api_secret=_require("X_API_SECRET"),
            x_access_token=_require("X_ACCESS_TOKEN"),
            x_access_token_secret=_require("X_ACCESS_TOKEN_SECRET"),
            anthropic_api_key=_require("ANTHROPIC_API_KEY"),
            # Cheap, fast model is the right fit for this high-frequency,
            # lightweight classify/summarise/rank workload. Use ``or`` rather
            # than a get() default so an unset *or* empty ANTHROPIC_MODEL (the
            # workflow passes "" when the repo variable isn't set) falls back to
            # the default instead of sending an empty model string to the API.
            anthropic_model=(os.environ.get("ANTHROPIC_MODEL") or "").strip() or "claude-haiku-4-5",
            max_items_per_feed=int(os.environ.get("MAX_ITEMS_PER_FEED", "25")),
            max_posts_per_day=int(os.environ.get("MAX_POSTS_PER_DAY", "10")),
            story_similarity_threshold=float(
                os.environ.get("STORY_SIMILARITY_THRESHOLD", "0.4")
            ),
            release_per_run=int(os.environ.get("RELEASE_PER_RUN", "2")),
            queue_ttl_hours=int(os.environ.get("QUEUE_TTL_HOURS", "24")),
            max_total_chars=int(os.environ.get("MAX_TOTAL_CHARS", "270")),
            summary_target_chars=int(os.environ.get("SUMMARY_TARGET_CHARS", "200")),
            dry_run=os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"},
        )
