"""Entry point: run one pass of the NFL breaking-news bot.

    python -m nflbot.bot

On each run the bot:
  1. Fetches all configured RSS feeds and collects items not seen before.
  2. Clusters items by story (the same news across many feeds = ONE story).
  3. Classifies, categorises, scores, and summarises each distinct new story
     (claude-haiku-4-5), composes the final post (topic prefix, #team tags,
     @outlet credit, hard char limit), and ENQUEUES newsworthy ones.
  4. Releases only a few queued posts per run, most-significant first, so posts
     stagger across runs rather than dumping at once. Honours the daily cap.
  5. Persists per-story dedup state and the queue so nothing is posted twice.
"""

from __future__ import annotations

import logging
import re
import sys

from .cluster import cluster_items, similar
from .config import STATE_FILE, Config, ConfigError
from .feeds import credit_for, fetch_all
from .state import State
from .summarizer import CATEGORY_PREFIXES, Analysis, Summarizer
from .teams import hashtagify_teams
from .x_client import DuplicatePostError, TransientPostError, XClient

log = logging.getLogger("nflbot")

_TAG_RE = re.compile(r"<[^>]+>")


def tweet_len(text: str) -> int:
    """X-style weighted length: non-ASCII (e.g. the 🚨 emoji) counts as 2."""
    return sum(2 if ord(c) > 127 else 1 for c in text)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _clean_description(html: str, limit: int = 500) -> str:
    """Strip HTML tags and trim a feed description for classification."""
    text = _TAG_RE.sub(" ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def compose_post(summarizer: Summarizer, analysis: Analysis, outlet: str, max_total: int) -> str | None:
    """Build the final post text, or None if it can't be made to fit.

    Layout: "<prefix> <#tagged summary>\\n\\n[<@handle|Outlet>]". Enforces the
    hard length limit; if the composed post is too long, asks Haiku for a shorter
    summary (a couple of attempts) and gives up rather than posting truncated.
    """
    prefix = CATEGORY_PREFIXES.get(analysis.category, CATEGORY_PREFIXES["NEWS"])
    credit = f"[{credit_for(outlet)}]"

    def build(summary: str) -> str:
        return f"{prefix} {hashtagify_teams(summary)}\n\n{credit}"

    text = build(analysis.summary)
    if tweet_len(text) <= max_total:
        return text

    # Overhead = everything except the summary body (prefix + framing + credit).
    overhead = tweet_len(build(""))
    budget = max_total - overhead
    summary = analysis.summary
    for _ in range(2):
        if budget < 20:
            break
        summary = summarizer.shorten(summary, budget)
        if not summary:
            break
        text = build(summary)
        if tweet_len(text) <= max_total:
            return text
        budget -= 15  # tighten and try once more (hashtags can re-expand length)
    log.warning("Could not fit post within %d chars (%s); skipping.", max_total, outlet)
    return None


def run(config: Config | None = None) -> int:
    config = config or Config.from_env()
    x = XClient(config)
    summarizer = Summarizer(config)
    state = State.load(STATE_FILE)

    items = fetch_all(max_items_per_feed=config.max_items_per_feed)
    new_items = [it for it in items if not state.entry_seen(it.uid)]
    log.info("%d new feed items since last run.", len(new_items))

    # First run for this repo: record the current backlog without posting.
    if not state.seeded:
        for it in items:
            state.mark_entry_seen(it.uid)
        state.mark_seeded()
        state.save()
        log.info("Seeded %d items on first run (no posting).", len(items))
        return 0

    # New feed items are always marked seen — once a newsworthy story is composed
    # it lives in the durable queue, so a later transient post failure retries
    # from the queue (not by re-reading the feed).
    try:
        return _process(config, x, summarizer, state, new_items)
    finally:
        for it in new_items:
            state.mark_entry_seen(it.uid)
        wrote = state.save()
        log.info("State %s; queue depth %d.", "updated" if wrote else "unchanged", state.queue_len())


def _process(config, x, summarizer, state, new_items) -> int:
    thr = config.story_similarity_threshold

    # 1. Drop stale queued posts (old news shouldn't surface later).
    pruned = state.prune_queue(config.queue_ttl_hours * 3600)
    if pruned:
        log.info("Pruned %d stale queued post(s).", pruned)

    # 2. Compose + enqueue newsworthy new stories (best-first ordering is handled
    #    at release time via each story's significance score).
    enqueued = 0
    if new_items:
        stories = cluster_items(new_items, thr)
        log.info("Clustered %d new items into %d stories.", len(new_items), len(stories))
        # Guard against re-queuing anything already posted or already queued.
        guard = state.posted_story_tokens() + state.queued_token_sets()
        for story in stories:
            if any(similar(story.tokens, prev, thr) for prev in guard):
                continue
            rep = story.representative
            a = summarizer.analyze(rep.title, _clean_description(rep.summary), config.summary_target_chars)
            if not a.is_news:
                continue
            text = compose_post(summarizer, a, story.outlet, config.max_total_chars)
            if text is None:
                continue
            state.enqueue(text, a.significance, story.tokens, story.outlet, a.category)
            guard.append(story.tokens)
            enqueued += 1
        log.info("Enqueued %d new newsworthy stor%s.", enqueued, "y" if enqueued == 1 else "ies")

    # 3. Release a few from the queue, most significant first, within the daily cap.
    remaining_today = state.remaining_today(config.max_posts_per_day)
    release_budget = min(config.release_per_run, remaining_today)
    if release_budget <= 0:
        log.info("Nothing to release (daily cap %d reached or per-run budget 0).", config.max_posts_per_day)
        return 0

    own_recent = {_normalize(t) for t in x.own_recent_texts()}
    released = 0
    for item in state.queue_sorted():
        if released >= release_budget:
            break
        tokens = set(item.get("tokens", []))
        text = item["text"]

        if _normalize(text) in own_recent:
            log.info("Queued post already on own timeline; marking handled.")
            state.remove_queued(item["id"])
            state.record_posted_story(tokens)
            continue

        try:
            x.post(text)
        except DuplicatePostError as exc:
            log.info("X rejected queued post as duplicate; marking handled: %s", exc)
            state.remove_queued(item["id"])
            state.record_posted_story(tokens)
            continue
        except TransientPostError as exc:
            # Leave it in the queue and stop releasing this run; retry next run.
            log.warning("Transient post failure; leaving in queue, retry next run: %s", exc)
            break
        except Exception as exc:  # pragma: no cover - network path
            # Non-transient, unexpected (auth/400): drop from queue to avoid a loop.
            log.error("Failed to post queued item (%s); dropping: %s", item.get("outlet"), exc)
            state.remove_queued(item["id"])
            continue

        state.remove_queued(item["id"])
        state.record_posted_story(tokens)
        state.increment_posts_today()
        own_recent.add(_normalize(text))
        released += 1

    log.info("Run complete: %d post(s) released; %d still queued.", released, state.queue_len())
    return released


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
