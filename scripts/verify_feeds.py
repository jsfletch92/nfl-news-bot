"""Fetch candidate RSS feeds and report which actually return recent content.

This exists because feed liveness can only be checked from an environment with
real outbound network (e.g. the GitHub Actions runner that the bot itself runs
on) — not from the restricted dev sandbox. Run it via the "Verify feeds"
workflow (Actions tab) or locally:

    pip install -r requirements.txt
    python scripts/verify_feeds.py

It prints a table: STATUS | ENTRIES | NEWEST ENTRY | OUTLET | URL. Promote the
feeds that return content into nflbot/feeds.py; drop the rest.

The candidate list deliberately probes several *families* of team-beat source
with a few sample teams each, so one run reveals which family works from the
runner's IP. Once a family is confirmed, it can be expanded to all 32 teams.
"""

from __future__ import annotations

import socket
import time
from datetime import datetime, timezone

# (outlet label, url). Run on the Actions runner ("Verify feeds" workflow) to
# confirm liveness; promote only the ones that return content into nflbot/feeds.py.
CANDIDATES: list[tuple[str, str]] = [
    # --- Confirmed-working national feeds (final FEEDS set) ---
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news"),
    ("ProFootballTalk", "https://profootballtalk.nbcsports.com/feed/"),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/"),
    ("Pro Football Rumors", "https://www.profootballrumors.com/feed"),
    ("CBS Sports NFL", "https://www.cbssports.com/rss/headlines/nfl/"),
    ("The Athletic", "https://theathletic.com/rss/nfl/"),
    # --- Retries: keep ONLY if these return recent NFL content ---
    # SB Nation: per-league /nfl/rss/index.xml 404'd; trying the site-wide feed
    # (note: site-wide covers ALL sports, so inspect the sample titles below for
    # whether it's NFL-heavy or mixed — it may need an NFL filter).
    ("SB Nation (site-wide)", "https://www.sbnation.com/rss/index.xml"),
    # USA TODAY: this URL 301-redirects; feedparser follows redirects, so a live
    # target feed will still show entries here.
    ("USA TODAY NFL", "https://rssfeeds.usatoday.com/usatodaycomnfl-topstories"),
]


def _newest(entries) -> str:
    best = None
    for e in entries:
        parsed = e.get("published_parsed") or e.get("updated_parsed")
        if parsed:
            try:
                ts = time.mktime(parsed)
            except (OverflowError, ValueError):
                continue
            best = ts if best is None else max(best, ts)
    if best is None:
        return "(no dates)"
    dt = datetime.fromtimestamp(best, tz=timezone.utc)
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return f"{dt:%Y-%m-%d %H:%M}Z ({age_h:.0f}h ago)"


def main() -> int:
    import feedparser

    socket.setdefaulttimeout(20)
    ua = "nfl-news-bot/1.0 (+https://github.com/jsfletch92/nfl-news-bot)"

    rows = []
    for outlet, url in CANDIDATES:
        try:
            parsed = feedparser.parse(url, agent=ua)
            n = len(parsed.entries)
            status_code = getattr(parsed, "status", "?")
            titles = [(e.get("title") or "").strip() for e in parsed.entries[:3]]
            if n > 0:
                status = "OK"
                detail = _newest(parsed.entries)
            else:
                status = "EMPTY"
                bozo = getattr(parsed, "bozo_exception", "")
                detail = f"http={status_code} {str(bozo)[:60]}"
            rows.append((status, n, detail, outlet, url, titles))
        except Exception as exc:  # noqa: BLE001 - report everything
            rows.append(("ERROR", 0, str(exc)[:60], outlet, url, []))

    print(f"{'STATUS':7} {'N':>4}  {'NEWEST / DETAIL':32}  OUTLET")
    print("-" * 90)
    for status, n, detail, outlet, url, titles in rows:
        print(f"{status:7} {n:>4}  {detail:32}  {outlet}")
        print(f"{'':47}  {url}")
        # Sample titles help judge relevance (e.g. NFL vs. mixed-sport feeds).
        for t in titles:
            print(f"{'':47}  · {t[:90]}")
    ok = sum(1 for r in rows if r[0] == "OK")
    print("-" * 90)
    print(f"{ok}/{len(rows)} candidate feeds returned content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
