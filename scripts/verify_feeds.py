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
    # --- Currently live in production (baseline / sanity check) ---
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news"),
    ("ProFootballTalk", "https://profootballtalk.nbcsports.com/feed/"),
    ("Yahoo Sports", "https://sports.yahoo.com/nfl/rss/"),
    ("Pro Football Rumors", "https://www.profootballrumors.com/feed"),
    ("CBS Sports NFL", "https://www.cbssports.com/rss/headlines/nfl/"),
    # --- New national candidates to verify (multiple URL guesses where unsure) ---
    # The Athletic (now under NYTimes): best-known feed path.
    ("The Athletic NFL", "https://www.nytimes.com/athletic/rss/nfl/"),
    ("The Athletic NFL (alt)", "https://theathletic.com/rss/nfl/"),
    # Bleacher Report: no documented official feed — long-shot guesses.
    ("Bleacher Report NFL", "https://bleacherreport.com/articles/feed"),
    ("Bleacher Report NFL (alt)", "https://syndication.bleacherreport.com/nfl.rss"),
    # NFL.com: old path was dead; re-checking it plus a couple alternates.
    ("NFL.com (old path)", "https://www.nfl.com/feeds/rss/news"),
    ("NFL.com (rss landing)", "https://www.nfl.com/rss/rsslanding"),
    # SB Nation main league NFL hub (Vox section-feed pattern).
    ("SB Nation NFL", "https://www.sbnation.com/nfl/rss/index.xml"),
    # Sporting News NFL section.
    ("Sporting News NFL", "https://www.sportingnews.com/us/nfl/rss"),
    # USA TODAY main NFL section (rssfeeds.usatoday.com pattern), not the Wire sites.
    ("USA TODAY NFL", "https://rssfeeds.usatoday.com/usatodaycomnfl-topstories"),
    # Sports Illustrated main NFL feed (SI/Minute Media section pattern), not team SI sites.
    ("Sports Illustrated NFL", "https://www.si.com/nfl/.rss/full/"),
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
