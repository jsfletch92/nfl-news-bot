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

# (outlet label, url). National candidates first, then sample team-beat families.
CANDIDATES: list[tuple[str, str]] = [
    # --- National (ESPN/PFT/Yahoo already confirmed working in production) ---
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news"),
    ("ProFootballTalk", "https://profootballtalk.nbcsports.com/feed/"),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/"),
    # National replacements for the dead NFL.com feed:
    ("Pro Football Rumors", "https://www.profootballrumors.com/feed"),
    ("CBS Sports NFL", "https://www.cbssports.com/rss/headlines/nfl/"),
    ("NFL.com (old path)", "https://www.nfl.com/feeds/rss/news"),  # expected dead; sanity check
    ("Sporting News NFL", "https://www.sportingnews.com/us/nfl/rss"),
    # --- Team-beat family A: USA TODAY "Wire" /feed/ (reported dead) ---
    ("Colts Wire (USAT)", "https://coltswire.usatoday.com/feed/"),
    ("Eagles Wire (USAT)", "https://theeagleswire.usatoday.com/feed/"),
    ("Chiefs Wire (USAT)", "https://chiefswire.usatoday.com/feed/"),
    # --- Team-beat family B: USA TODAY "Wire" ?feed=rss2 (alt WP path) ---
    ("Colts Wire (rss2)", "https://coltswire.usatoday.com/?feed=rss2"),
    # --- Team-beat family C: Reddit team subreddit ---
    ("r/Colts", "https://www.reddit.com/r/Colts/.rss"),
    ("r/eagles", "https://www.reddit.com/r/eagles/.rss"),
    ("r/KansasCityChiefs", "https://www.reddit.com/r/KansasCityChiefs/.rss"),
    # --- Team-beat family D: Sports Illustrated / On SI team sites ---
    ("SI Colts", "https://www.si.com/nfl/colts/.rss/full/"),
    ("SI Eagles", "https://www.si.com/nfl/eagles/.rss/full/"),
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
            if n > 0:
                status = "OK"
                detail = _newest(parsed.entries)
            else:
                status = "EMPTY"
                bozo = getattr(parsed, "bozo_exception", "")
                detail = f"http={status_code} {str(bozo)[:60]}"
            rows.append((status, n, detail, outlet, url))
        except Exception as exc:  # noqa: BLE001 - report everything
            rows.append(("ERROR", 0, str(exc)[:60], outlet, url))

    print(f"{'STATUS':7} {'N':>4}  {'NEWEST / DETAIL':32}  OUTLET")
    print("-" * 90)
    for status, n, detail, outlet, url in rows:
        print(f"{status:7} {n:>4}  {detail:32}  {outlet}")
        print(f"{'':47}  {url}")
    ok = sum(1 for r in rows if r[0] == "OK")
    print("-" * 90)
    print(f"{ok}/{len(rows)} candidate feeds returned content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
