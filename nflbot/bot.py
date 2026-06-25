"""Entry point: run one pass of the NFL breaking-news bot.

    python -m nflbot.bot

On each run the bot:
  1. Reads recent original posts from each allowlisted source account.
  2. Classifies each as news / not-news and rewrites news in original wording.
  3. Posts new items as text-only updates in the required format.
  4. Persists what has been handled so the same item is never posted twice.
"""

from __future__ import annotations

import logging
import re
import sys

from .config import STATE_FILE, Config, ConfigError
from .state import State
from .summarizer import Summarizer
from .x_client import SourceTweet, XClient

log = logging.getLogger("nflbot")

# Hard ceiling for a single X post.
_TWEET_LIMIT = 280


def format_post(summary: str, handle: str) -> str:
    """Build the exact required post format, including the blank line."""
    return f"🚨 NEW: {summary}\n\n@{handle}"


def _normalize(text: str) -> str:
    """Loose normalisation for comparing our own past posts (dedup safety net)."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def run(config: Config | None = None) -> int:
    config = config or Config.from_env()
    x = XClient(config)
    summarizer = Summarizer(config)
    state = State.load(STATE_FILE)

    # Safety net against the account already carrying an identical post (covers
    # the case where the state file was lost). Computed once per run.
    own_recent = {_normalize(t) for t in x.own_recent_texts()}

    user_ids = x.resolve_user_ids(config.source_handles)

    posts_made = 0
    for handle in config.source_handles:
        if handle not in user_ids:
            continue
        if posts_made >= config.max_posts_per_run:
            log.info("Reached max_posts_per_run (%d); stopping.", config.max_posts_per_run)
            break

        first_run = state.is_first_run(handle)
        try:
            tweets = x.fetch_recent(
                handle,
                user_ids[handle],
                since_id=state.since_id(handle),
                max_results=config.max_tweets_per_source,
            )
        except Exception as exc:  # pragma: no cover - network path
            log.error("Failed to fetch tweets for @%s: %s", handle, exc)
            continue

        if first_run:
            # Don't dump the backlog on the very first run for a source: just
            # record the latest tweet so future runs only post genuinely new
            # items. (X tweet IDs increase over time, so the max is the newest.)
            if tweets:
                newest = max(tweets, key=lambda t: int(t.id))
                state.advance_since_id(handle, newest.id)
                for t in tweets:
                    state.mark_seen(handle, t.id)
                log.info("Seeded @%s at tweet %s (no posting on first run).", handle, newest.id)
            continue

        for tweet in tweets:
            if posts_made >= config.max_posts_per_run:
                break
            posted = _handle_tweet(config, x, summarizer, state, own_recent, tweet)
            if posted:
                posts_made += 1

    wrote = state.save()
    log.info("Run complete: %d post(s) made; state %s.", posts_made, "updated" if wrote else "unchanged")
    return posts_made


def _handle_tweet(
    config: Config,
    x: XClient,
    summarizer: Summarizer,
    state: State,
    own_recent: set[str],
    tweet: SourceTweet,
) -> bool:
    """Process one source tweet. Returns True if a post was made."""
    # Always advance since_id past this tweet so we never reconsider it, even if
    # it turns out not to be news.
    state.advance_since_id(tweet.handle, tweet.id)

    if state.already_seen(tweet.handle, tweet.id):
        return False
    state.mark_seen(tweet.handle, tweet.id)

    is_news, summary = summarizer.analyze(tweet.text)
    if not is_news:
        return False

    post_text = format_post(summary, tweet.handle)
    if len(post_text) > _TWEET_LIMIT:
        log.warning("Skipping over-length post (%d chars) for @%s.", len(post_text), tweet.handle)
        return False

    # Dedup safety net: don't re-post something already on our own timeline.
    if _normalize(post_text) in own_recent:
        log.info("Skipping duplicate already on own timeline (@%s).", tweet.handle)
        return False

    try:
        x.post(post_text)
    except Exception as exc:  # pragma: no cover - network path
        log.error("Failed to post item from @%s: %s", tweet.handle, exc)
        return False

    own_recent.add(_normalize(post_text))
    return True


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        run()
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    except Exception as exc:  # pragma: no cover - top-level guard
        log.exception("Unexpected error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
