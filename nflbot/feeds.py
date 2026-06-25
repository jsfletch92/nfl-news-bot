"""NFL RSS feed list and fetching.

The source of news is public RSS feeds (free to read), not the X API.

Only feeds confirmed to return live content are listed in ``FEEDS`` — the bot
runs against these. The USA TODAY "Wire" per-team feeds and the NFL.com feed
that were here previously were all returning no entries (the ``*.usatoday.com``
/feed/ pattern and ``nfl.com/feeds/rss/news`` are dead from the runner), so they
have been removed rather than left as dead URLs.

To add more feeds — especially per-team beat coverage — run the "Verify feeds"
GitHub Actions workflow (it fetches candidate feeds from the runner, which has
real network, and prints which return content), then promote the working ones
here. See scripts/verify_feeds.py.

Each feed is (outlet_label, url, is_national). ``outlet_label`` is what gets
credited in the post ("via ESPN").
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# (outlet label, feed url, is_national)
# Confirmed working in production. Add verified feeds via scripts/verify_feeds.py.
FEEDS: list[tuple[str, str, bool]] = [
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news", True),
    ("ProFootballTalk", "https://profootballtalk.nbcsports.com/feed/", True),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/", True),
]

_USER_AGENT = "nfl-news-bot/1.0 (+https://github.com/jsfletch92/nfl-news-bot)"


@dataclass(frozen=True)
class FeedItem:
    uid: str          # stable per-item id (guid or link)
    outlet: str       # credit label, e.g. "ESPN" / "Colts Wire"
    is_national: bool
    title: str
    summary: str      # short description/body text from the feed (data only)
    link: str
    published: float | None  # epoch seconds, if the feed provided one


def _entry_uid(entry, fallback_outlet: str) -> str:
    for key in ("id", "guid", "link"):
        val = entry.get(key)
        if val:
            return str(val)
    # Last resort: outlet + title.
    return f"{fallback_outlet}:{entry.get('title', '')}"


def _entry_published(entry) -> float | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return time.mktime(parsed)
            except (OverflowError, ValueError):
                return None
    return None


def fetch_all(
    feeds: list[tuple[str, str, bool]] | None = None, max_items_per_feed: int = 25
) -> list[FeedItem]:
    """Fetch every configured feed and return a flat list of items.

    Individual feed failures are logged and skipped — one bad feed never sinks
    the run. Only the newest ``max_items_per_feed`` entries per feed are kept.
    """
    import feedparser  # lazy import: keeps the rest of the package importable without it

    feeds = feeds if feeds is not None else FEEDS
    items: list[FeedItem] = []
    for outlet, url, is_national in feeds:
        try:
            parsed = feedparser.parse(url, agent=_USER_AGENT)
        except Exception as exc:  # pragma: no cover - network path
            log.warning("Failed to fetch feed %s (%s): %s", outlet, url, exc)
            continue
        if getattr(parsed, "bozo", 0) and not parsed.entries:
            log.warning("Feed %s returned no usable entries (%s).", outlet, url)
            continue
        for entry in parsed.entries[:max_items_per_feed]:
            items.append(
                FeedItem(
                    uid=_entry_uid(entry, outlet),
                    outlet=outlet,
                    is_national=is_national,
                    title=(entry.get("title") or "").strip(),
                    summary=(entry.get("summary") or entry.get("description") or "").strip(),
                    link=(entry.get("link") or "").strip(),
                    published=_entry_published(entry),
                )
            )
    log.info("Fetched %d items across %d feeds.", len(items), len(feeds))
    return items
