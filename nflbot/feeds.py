"""NFL RSS feed list and fetching.

The source of news is public RSS feeds (free to read), not the X API.

National feeds only. ``FEEDS`` lists the feeds confirmed to return content on the
runner ("Verify feeds"); the bot runs against these. Dead candidates are dropped
rather than left in — Bleacher Report, NFL.com, Sporting News, Sports Illustrated
(main), and the USA TODAY "Wire"/SI/Reddit team-beat patterns all returned no
usable entries.

To add per-team beat coverage later, run the "Verify feeds" GitHub Actions
workflow (it fetches candidate feeds from the runner, which has real network,
and prints which return content), then promote the working ones here. See
scripts/verify_feeds.py.

Each feed is (outlet_label, url, is_national). ``outlet_label`` is what gets
credited in the post ("via ESPN").
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# (outlet label, feed url, is_national)
# National feeds confirmed working on the runner ("Verify feeds"). Add more via
# scripts/verify_feeds.py after confirming they return content.
FEEDS: list[tuple[str, str, bool]] = [
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news", True),
    ("ProFootballTalk", "https://profootballtalk.nbcsports.com/feed/", True),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/", True),
    ("Pro Football Rumors", "https://www.profootballrumors.com/feed", True),
    ("CBS Sports NFL", "https://www.cbssports.com/rss/headlines/nfl/", True),
    ("The Athletic", "https://theathletic.com/rss/nfl/", True),
]

# Outlet credit label -> the outlet's X handle (improvement 4). Keys must match
# the outlet labels in FEEDS. An outlet with no confident handle is omitted and
# falls back to the plain-text "via Outlet" credit rather than guessing.
OUTLET_HANDLES: dict[str, str] = {
    # Handles verified via web search (June 2026).
    "ESPN": "@espn",
    "ProFootballTalk": "@ProFootballTalk",
    "Yahoo Sports": "@YahooSports",  # per operator preference (generic Yahoo Sports account)
    "Pro Football Rumors": "@PFRumors",
    "CBS Sports NFL": "@NFLonCBS",
    "The Athletic": "@TheAthleticNFL",
}


def credit_for(outlet: str) -> str:
    """The credit token for an outlet: its @handle if known, else the label."""
    return OUTLET_HANDLES.get(outlet, outlet)


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
