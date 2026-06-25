"""Thin wrapper around the X (Twitter) API v2 via tweepy.

Reading source timelines uses app-only (bearer) auth; posting uses OAuth 1.0a
user-context auth (the only way to write a Tweet on behalf of the account).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import tweepy

from .config import Config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceTweet:
    """A single candidate tweet pulled from a source account."""

    id: str
    handle: str  # source account handle, without the leading '@'
    text: str
    created_at: str | None


class XClient:
    def __init__(self, config: Config):
        self._config = config
        # Read client: app-only bearer token is sufficient for reading public
        # user timelines and is rate-limit-friendly.
        self._read = tweepy.Client(bearer_token=config.x_bearer_token)
        # Write client: user-context OAuth 1.0a is required to create a Tweet.
        self._write = tweepy.Client(
            consumer_key=config.x_api_key,
            consumer_secret=config.x_api_secret,
            access_token=config.x_access_token,
            access_token_secret=config.x_access_token_secret,
        )
        self._user_id_cache: dict[str, str] = {}
        self._own_user_id: str | None = None

    # ------------------------------------------------------------------ reads

    def resolve_user_ids(self, handles: list[str]) -> dict[str, str]:
        """Map source handles to numeric user IDs (batched, cached)."""
        missing = [h for h in handles if h not in self._user_id_cache]
        if missing:
            resp = self._read.get_users(usernames=missing)
            for user in resp.data or []:
                self._user_id_cache[user.username] = str(user.id)
            for handle in missing:
                if handle not in self._user_id_cache:
                    log.warning("Could not resolve source handle @%s", handle)
        return {h: self._user_id_cache[h] for h in handles if h in self._user_id_cache}

    def fetch_recent(
        self, handle: str, user_id: str, since_id: str | None, max_results: int
    ) -> list[SourceTweet]:
        """Fetch recent original posts from a source, newest last.

        Retweets and replies are excluded at the API level so they never enter
        the pipeline. ``since_id`` restricts results to tweets newer than the
        last one we processed for this source.
        """
        # The API requires max_results between 5 and 100.
        capped = max(5, min(max_results, 100))
        kwargs = dict(
            id=user_id,
            exclude=["retweets", "replies"],
            max_results=capped,
            tweet_fields=["created_at", "referenced_tweets", "text"],
        )
        if since_id:
            kwargs["since_id"] = since_id

        resp = self._read.get_users_tweets(**kwargs)
        tweets = resp.data or []

        results: list[SourceTweet] = []
        for tw in tweets:
            # Defensive: skip anything still flagged as a retweet/quote/reply
            # even though exclude should have handled retweets and replies.
            if _is_retweet_or_reply(tw):
                continue
            results.append(
                SourceTweet(
                    id=str(tw.id),
                    handle=handle,
                    text=tw.text or "",
                    created_at=str(tw.created_at) if tw.created_at else None,
                )
            )
        # API returns newest first; process oldest first so posts read in order.
        results.reverse()
        return results

    def own_recent_texts(self, max_results: int = 100) -> list[str]:
        """Return the bot account's own recent tweet texts (dedup safety net)."""
        if self._own_user_id is None:
            me = self._write.get_me()
            self._own_user_id = str(me.data.id)
        try:
            resp = self._read.get_users_tweets(
                id=self._own_user_id,
                max_results=max(5, min(max_results, 100)),
                tweet_fields=["text"],
            )
        except tweepy.TweepyException as exc:  # pragma: no cover - network path
            log.warning("Could not read own timeline for dedup: %s", exc)
            return []
        return [tw.text or "" for tw in (resp.data or [])]

    # ----------------------------------------------------------------- writes

    def post(self, text: str) -> str | None:
        """Post a text-only tweet. Returns the new tweet ID, or None on dry run."""
        if self._config.dry_run:
            log.info("[dry-run] would post:\n%s", text)
            return None
        resp = self._write.create_tweet(text=text)
        new_id = str(resp.data["id"])
        log.info("Posted tweet %s", new_id)
        return new_id


def _is_retweet_or_reply(tweet) -> bool:
    refs = getattr(tweet, "referenced_tweets", None) or []
    for ref in refs:
        ref_type = ref.get("type") if isinstance(ref, dict) else getattr(ref, "type", None)
        if ref_type in {"retweeted", "replied_to"}:
            return True
    return False
