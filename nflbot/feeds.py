"""NFL RSS feed list and fetching.

The source of news is now public RSS feeds (free to read), not the X API. The
list below aims for broad, all-32-teams coverage: a handful of national outlets
for headline news plus a team-level "Wire" beat feed for every franchise, which
is where granular camp/roster detail shows up. Refine the list as needed — the
bot tolerates individual feeds being unreachable or returning junk.

Each feed is (outlet_label, url, is_national). ``outlet_label`` is what gets
credited in the post ("via ESPN", "via Colts Wire").
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

# (outlet label, feed url, is_national)
FEEDS: list[tuple[str, str, bool]] = [
    # --- National / league-wide headline news ---
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news", True),
    ("NFL.com", "https://www.nfl.com/feeds/rss/news", True),
    ("ProFootballTalk", "https://profootballtalk.nbcsports.com/feed/", True),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/", True),
    # --- Team-level beat feeds (USA TODAY "Wire" network), one per team ---
    ("Cardinals Wire", "https://cardswire.usatoday.com/feed/", False),
    ("Falcons Wire", "https://thefalconswire.usatoday.com/feed/", False),
    ("Ravens Wire", "https://ravenswire.usatoday.com/feed/", False),
    ("Bills Wire", "https://billswire.usatoday.com/feed/", False),
    ("Panthers Wire", "https://pantherswire.usatoday.com/feed/", False),
    ("Bears Wire", "https://bearswire.usatoday.com/feed/", False),
    ("Bengals Wire", "https://bengalswire.usatoday.com/feed/", False),
    ("Browns Wire", "https://brownswire.usatoday.com/feed/", False),
    ("Cowboys Wire", "https://cowboyswire.usatoday.com/feed/", False),
    ("Broncos Wire", "https://broncoswire.usatoday.com/feed/", False),
    ("Lions Wire", "https://lionswire.usatoday.com/feed/", False),
    ("Packers Wire", "https://packerswire.usatoday.com/feed/", False),
    ("Texans Wire", "https://texanswire.usatoday.com/feed/", False),
    ("Colts Wire", "https://coltswire.usatoday.com/feed/", False),
    ("Jaguars Wire", "https://jaguarswire.usatoday.com/feed/", False),
    ("Chiefs Wire", "https://chiefswire.usatoday.com/feed/", False),
    ("Raiders Wire", "https://raiderswire.usatoday.com/feed/", False),
    ("Chargers Wire", "https://chargerswire.usatoday.com/feed/", False),
    ("Rams Wire", "https://ramswire.usatoday.com/feed/", False),
    ("Dolphins Wire", "https://dolphinswire.usatoday.com/feed/", False),
    ("Vikings Wire", "https://vikingswire.usatoday.com/feed/", False),
    ("Patriots Wire", "https://patriotswire.usatoday.com/feed/", False),
    ("Saints Wire", "https://saintswire.usatoday.com/feed/", False),
    ("Giants Wire", "https://giantswire.usatoday.com/feed/", False),
    ("Jets Wire", "https://jetswire.usatoday.com/feed/", False),
    ("Eagles Wire", "https://eagleswire.usatoday.com/feed/", False),
    ("Steelers Wire", "https://steelerswire.usatoday.com/feed/", False),
    ("Niners Wire", "https://ninerswire.usatoday.com/feed/", False),
    ("Seahawks Wire", "https://seahawkswire.usatoday.com/feed/", False),
    ("Buccaneers Wire", "https://buccaneerswire.usatoday.com/feed/", False),
    ("Titans Wire", "https://titanswire.usatoday.com/feed/", False),
    ("Commanders Wire", "https://commanderswire.usatoday.com/feed/", False),
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
