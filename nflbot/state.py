"""Durable de-duplication and rate state.

Each scheduled cloud run starts fresh with no local memory, so what has already
been seen/posted is persisted to a JSON file that the routine commits back to
the repo (see the GitHub Actions workflow). It tracks:

  * seen_entries   – capped list of raw feed-item UIDs already processed, so the
                     same feed item is never reconsidered.
  * posted_stories – capped list of {tokens, ts} fingerprints of stories already
                     posted, so the same STORY is never posted twice even when a
                     different feed carries it on a later run.
  * daily          – {date, count} post counter for the per-UTC-day cap.
  * seeded         – False until the first run has recorded the current backlog
                     (so the bot never dumps history on first run).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_MAX_SEEN_ENTRIES = 4000
_MAX_POSTED_STORIES = 400


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class State:
    def __init__(self, path: str, data: dict | None = None):
        self._path = path
        self._data = data or {}
        self._data.setdefault("seen_entries", [])
        self._data.setdefault("posted_stories", [])
        self._data.setdefault("daily", {"date": _today(), "count": 0})
        self._data.setdefault("seeded", False)
        self._seen_set = set(self._data["seen_entries"])
        self._dirty = False

    @classmethod
    def load(cls, path: str) -> "State":
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return cls(path, json.load(fh))
            except (ValueError, OSError) as exc:
                log.warning("Could not read state file %s (%s); starting fresh.", path, exc)
        return cls(path)

    # ------------------------------------------------------------- seeding

    @property
    def seeded(self) -> bool:
        return bool(self._data.get("seeded"))

    def mark_seeded(self) -> None:
        if not self._data.get("seeded"):
            self._data["seeded"] = True
            self._dirty = True

    # --------------------------------------------------- raw feed-item dedup

    def entry_seen(self, uid: str) -> bool:
        return uid in self._seen_set

    def mark_entry_seen(self, uid: str) -> None:
        if uid not in self._seen_set:
            self._seen_set.add(uid)
            self._data["seen_entries"].append(uid)
            del self._data["seen_entries"][:-_MAX_SEEN_ENTRIES]
            self._dirty = True

    # -------------------------------------------------- story-level dedup

    def posted_story_tokens(self) -> list[set[str]]:
        return [set(s.get("tokens", [])) for s in self._data.get("posted_stories", [])]

    def record_posted_story(self, tokens: set[str]) -> None:
        self._data.setdefault("posted_stories", []).append(
            {"tokens": sorted(tokens), "ts": datetime.now(timezone.utc).isoformat()}
        )
        del self._data["posted_stories"][:-_MAX_POSTED_STORIES]
        self._dirty = True

    # ----------------------------------------------------- daily post cap

    def _roll_day(self) -> None:
        if self._data["daily"].get("date") != _today():
            self._data["daily"] = {"date": _today(), "count": 0}
            self._dirty = True

    def posts_today(self) -> int:
        self._roll_day()
        return int(self._data["daily"].get("count", 0))

    def remaining_today(self, cap: int) -> int:
        return max(0, cap - self.posts_today())

    def increment_posts_today(self) -> None:
        self._roll_day()
        self._data["daily"]["count"] = int(self._data["daily"].get("count", 0)) + 1
        self._dirty = True

    # ----------------------------------------------------------- persist

    def save(self) -> bool:
        if not self._dirty:
            return False
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        log.info("Wrote state file %s", self._path)
        return True
