"""Thin wrapper around the X (Twitter) API for POSTING and own-timeline reads.

News is no longer read from X — it comes from RSS feeds (see feeds.py). X is
used only to post to the operator's account and to read that account's own
recent posts as a de-duplication safety net. Both use OAuth 1.0a user context.
"""

from __future__ import annotations

import logging

import tweepy

from .config import Config

log = logging.getLogger(__name__)


class XClient:
    def __init__(self, config: Config):
        self._config = config
        # User-context OAuth 1.0a is required to create a Tweet and to read the
        # authenticated account's own timeline.
        self._client = tweepy.Client(
            consumer_key=config.x_api_key,
            consumer_secret=config.x_api_secret,
            access_token=config.x_access_token,
            access_token_secret=config.x_access_token_secret,
        )
        self._own_user_id: str | None = None

    def own_recent_texts(self, max_results: int = 100) -> list[str]:
        """Return the bot account's own recent tweet texts (dedup safety net)."""
        try:
            if self._own_user_id is None:
                me = self._client.get_me()
                self._own_user_id = str(me.data.id)
            resp = self._client.get_users_tweets(
                id=self._own_user_id,
                max_results=max(5, min(max_results, 100)),
                tweet_fields=["text"],
                user_auth=True,
            )
        except tweepy.TweepyException as exc:  # pragma: no cover - network path
            log.warning("Could not read own timeline for dedup: %s", exc)
            return []
        return [tw.text or "" for tw in (resp.data or [])]

    def post(self, text: str) -> str | None:
        """Post a text-only tweet. Returns the new tweet ID, or None on dry run."""
        if self._config.dry_run:
            log.info("[dry-run] would post:\n%s", text)
            return None
        resp = self._client.create_tweet(text=text)
        new_id = str(resp.data["id"])
        log.info("Posted tweet %s", new_id)
        return new_id
