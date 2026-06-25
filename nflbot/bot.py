"""Entry point: run one pass of the NFL breaking-news bot.

    python -m nflbot.bot

On each run the bot:
  1. Fetches all configured RSS feeds and collects items not seen before.
  2. Clusters items by story (the same news across many feeds = ONE story).
  3. Classifies each distinct new story (real news vs. opinion/list/ad/filler)
     and rewrites the news in original wording.
  4. Posts up to the remaining daily budget (cap 10/day); if more stories clear
     the bar than fit, ranks by significance and posts only the top ones.
  5. Persists per-story dedup state so the same story is never posted twice.
"""

from __future__ import annotations

import logging
import re
import sys

from .cluster import Story, cluster_items, similar
from .config import STATE_FILE, Config, ConfigError
from .feeds import fetch_all
from .state import State
from .summarizer import Summarizer
from .x_client import XClient

log = logging.getLogger("nflbot")

_TWEET_LIMIT = 280
_TAG_RE = re.compile(r"<[^>]+>")


def format_post(summary: str, outlet: str) -> str:
    """Build the exact required post format, including the blank line."""
    return f"🚨 NEW: {summary}\n\nvia {outlet}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _clean_description(html: str, limit: int = 500) -> str:
    """Strip HTML tags and trim a feed description for classification."""
    text = _TAG_RE.sub(" ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def run(config: Config | None = None) -> int:
    config = config or Config.from_env()
    x = XClient(config)
    summarizer = Summarizer(config)
    state = State.load(STATE_FILE)

    items = fetch_all(max_items_per_feed=config.max_items_per_feed)
    new_items = [it for it in items if not state.entry_seen(it.uid)]
    log.info("%d new feed items since last run.", len(new_items))

    # First run for this repo: record the current backlog without posting, so we
    # never dump history.
    if not state.seeded:
        for it in items:
            state.mark_entry_seen(it.uid)
        state.mark_seeded()
        state.save()
        log.info("Seeded %d items on first run (no posting).", len(items))
        return 0

    # Every new item is marked seen this run regardless of outcome, so dropped /
    # over-budget stories are never carried over to a later run.
    try:
        return _process(config, x, summarizer, state, new_items)
    finally:
        for it in new_items:
            state.mark_entry_seen(it.uid)
        wrote = state.save()
        log.info("State %s.", "updated" if wrote else "unchanged")


def _process(config, x, summarizer, state, new_items) -> int:
    remaining = state.remaining_today(config.max_posts_per_day)
    if remaining <= 0:
        log.info("Daily cap (%d) already reached; nothing to post.", config.max_posts_per_day)
        return 0
    if not new_items:
        return 0

    stories = cluster_items(new_items, config.story_similarity_threshold)
    log.info("Clustered %d new items into %d stories.", len(new_items), len(stories))

    # Cross-run de-dup: drop stories matching anything already posted.
    posted_tokens = state.posted_story_tokens()
    fresh: list[Story] = []
    for story in stories:
        if any(similar(story.tokens, prev, config.story_similarity_threshold) for prev in posted_tokens):
            continue
        fresh.append(story)
    log.info("%d stories remain after cross-run de-dup.", len(fresh))

    # Classify + summarise each story.
    candidates: list[tuple[Story, str]] = []
    for story in fresh:
        rep = story.representative
        is_news, summary = summarizer.analyze(rep.title, _clean_description(rep.summary))
        if is_news:
            candidates.append((story, summary))
    log.info("%d stories classified as news.", len(candidates))
    if not candidates:
        return 0

    # If more clear the bar than fit in the remaining daily budget, rank by
    # significance and keep the top N; the rest are dropped (not carried over).
    if len(candidates) > remaining:
        order = summarizer.rank_by_significance([s for _, s in candidates])
        candidates = [candidates[i] for i in order][:remaining]
        log.info("Ranked and trimmed to top %d by significance.", remaining)

    own_recent = {_normalize(t) for t in x.own_recent_texts()}
    # Running set of story fingerprints already posted (state + this run) to
    # guard against two near-duplicate clusters slipping through.
    seen_tokens = list(posted_tokens)

    posts_made = 0
    for story, summary in candidates:
        if posts_made >= remaining:
            break
        if any(similar(story.tokens, prev, config.story_similarity_threshold) for prev in seen_tokens):
            continue

        post_text = format_post(summary, story.outlet)
        if len(post_text) > _TWEET_LIMIT:
            log.warning("Skipping over-length post (%d chars).", len(post_text))
            continue
        if _normalize(post_text) in own_recent:
            log.info("Skipping duplicate already on own timeline.")
            state.record_posted_story(story.tokens)
            seen_tokens.append(story.tokens)
            continue

        try:
            x.post(post_text)
        except Exception as exc:  # pragma: no cover - network path
            log.error("Failed to post story (%s): %s", story.outlet, exc)
            continue

        state.record_posted_story(story.tokens)
        state.increment_posts_today()
        seen_tokens.append(story.tokens)
        own_recent.add(_normalize(post_text))
        posts_made += 1

    log.info("Run complete: %d post(s) made.", posts_made)
    return posts_made


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
