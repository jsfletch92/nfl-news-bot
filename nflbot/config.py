"""Configuration and environment loading.

All secrets are read from environment variables — never from a file committed
to the repo. See README.md for the variable names and how to set them in the
scheduled-routine settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# The ONLY accounts this bot is ever allowed to relay news from. News is only
# ever sourced and credited from these handles; nothing else is read or posted.
SOURCE_HANDLES: list[str] = [
    "TheAthleticNFL",
    "AdamSchefter",
    "RapSheet",
    "ESPNNFL",
    "JourdanRodrigue",
]

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
    # X (Twitter) API credentials.
    x_bearer_token: str
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_token_secret: str

    # Anthropic API for original-wording summarisation + news classification.
    anthropic_api_key: str
    anthropic_model: str

    # Behaviour knobs.
    source_handles: list[str] = field(default_factory=lambda: list(SOURCE_HANDLES))
    # How many recent tweets to pull per source each run.
    max_tweets_per_source: int = 10
    # Cap on items posted in a single run (guards against an accidental flood).
    max_posts_per_run: int = 8
    # When True, a real post is made. When False, the bot logs what it *would*
    # post without calling the X write API (useful for testing credentials).
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            x_bearer_token=_require("X_BEARER_TOKEN"),
            x_api_key=_require("X_API_KEY"),
            x_api_secret=_require("X_API_SECRET"),
            x_access_token=_require("X_ACCESS_TOKEN"),
            x_access_token_secret=_require("X_ACCESS_TOKEN_SECRET"),
            anthropic_api_key=_require("ANTHROPIC_API_KEY"),
            # Defaults to the most capable Opus model; override with a cheaper
            # model (e.g. claude-haiku-4-5) via ANTHROPIC_MODEL if desired.
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
            max_tweets_per_source=int(os.environ.get("MAX_TWEETS_PER_SOURCE", "10")),
            max_posts_per_run=int(os.environ.get("MAX_POSTS_PER_RUN", "8")),
            dry_run=os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"},
        )
