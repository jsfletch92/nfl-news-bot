"""Durable de-duplication state.

Each scheduled cloud run starts fresh with no local memory, so what has already
been processed/posted is persisted to a JSON file that the routine commits back
to the repo (see the GitHub Actions workflow). The file tracks, per source:

  * since_id          – the newest source tweet ID we have already processed, so
                        the next run only fetches genuinely new tweets.
  * posted_source_ids – a capped list of recently handled source tweet IDs, a
                        second guard against ever processing the same item twice.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# Keep the per-source seen-id list bounded so the file does not grow forever.
_MAX_SEEN_IDS = 200


class State:
    def __init__(self, path: str, data: dict | None = None):
        self._path = path
        self._data = data or {"sources": {}}
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

    def _source(self, handle: str) -> dict:
        return self._data.setdefault("sources", {}).setdefault(
            handle, {"since_id": None, "posted_source_ids": []}
        )

    def since_id(self, handle: str) -> str | None:
        return self._source(handle).get("since_id")

    def is_first_run(self, handle: str) -> bool:
        return self._source(handle).get("since_id") is None

    def already_seen(self, handle: str, tweet_id: str) -> bool:
        return tweet_id in self._source(handle).get("posted_source_ids", [])

    def mark_seen(self, handle: str, tweet_id: str) -> None:
        src = self._source(handle)
        ids = src.setdefault("posted_source_ids", [])
        if tweet_id not in ids:
            ids.append(tweet_id)
            del ids[:-_MAX_SEEN_IDS]
            self._dirty = True

    def advance_since_id(self, handle: str, tweet_id: str) -> None:
        """Move since_id forward (IDs are monotonically increasing on X)."""
        src = self._source(handle)
        current = src.get("since_id")
        if current is None or int(tweet_id) > int(current):
            src["since_id"] = tweet_id
            self._dirty = True

    def save(self) -> bool:
        """Persist to disk if anything changed. Returns True if it wrote."""
        if not self._dirty:
            return False
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        log.info("Wrote state file %s", self._path)
        return True
