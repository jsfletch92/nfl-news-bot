"""Story clustering and story-level fingerprints.

The same news appears across many feeds (ESPN, the team site, a beat blog may
all carry it). We group those into ONE story so a story is never posted twice
just because multiple feeds carried it. Clustering and cross-run de-duplication
share the same lexical similarity over title tokens.

This is deliberately cheap and deterministic (no API calls): tokenise titles,
drop stopwords, and compare token sets with a Jaccard threshold. It is fuzzy by
nature — tune ``threshold`` after watching it run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .feeds import FeedItem

# Common words that carry no disambiguating signal for NFL headlines.
_STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "in", "on", "at", "with", "and", "or",
    "as", "is", "are", "be", "was", "were", "after", "before", "from", "by",
    "his", "her", "their", "it", "its", "that", "this", "what", "who", "how",
    "will", "could", "would", "should", "vs", "but", "not", "no", "new",
    "nfl", "report", "reports", "says", "say", "per", "amid", "ahead",
    "week", "day", "season", "game", "team", "teams", "player", "players",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(title: str) -> set[str]:
    """Significant token set for a headline."""
    tokens = _TOKEN_RE.findall((title or "").lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def similar(a: set[str], b: set[str], threshold: float) -> bool:
    """True if two token sets describe the same story.

    Uses the overlap coefficient (intersection / smaller set) rather than
    Jaccard: headlines for the same story vary a lot in length and in the filler
    words around the core facts, and Jaccard penalises that heavily. A minimum
    of two shared significant tokens prevents single-shared-token merges (e.g.
    two unrelated stories that merely share a team name).
    """
    if not a or not b:
        return False
    inter = len(a & b)
    if inter < 2:  # require at least two shared significant tokens
        return False
    return inter / min(len(a), len(b)) >= threshold


@dataclass
class Story:
    """A cluster of feed items judged to be the same news story."""

    items: list[FeedItem] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)  # union, used as the dedup fingerprint
    member_tokens: list[set[str]] = field(default_factory=list)  # per-item token sets

    def add(self, item: FeedItem, tokens: set[str]) -> None:
        self.items.append(item)
        self.member_tokens.append(tokens)
        self.tokens |= tokens

    def matches(self, tokens: set[str], threshold: float) -> bool:
        """True if ``tokens`` is similar to ANY member (not the diluted union)."""
        return any(similar(tokens, m, threshold) for m in self.member_tokens)

    @property
    def representative(self) -> FeedItem:
        """The item used for summarisation/credit.

        Prefer a national outlet when present (recognisable credit, usually the
        cleanest headline); otherwise the earliest-published item.
        """
        national = [i for i in self.items if i.is_national]
        pool = national or self.items
        with_ts = [i for i in pool if i.published is not None]
        if with_ts:
            return min(with_ts, key=lambda i: i.published)
        return pool[0]

    @property
    def outlet(self) -> str:
        return self.representative.outlet


def cluster_items(items: list[FeedItem], threshold: float) -> list[Story]:
    """Greedily group items into stories by title-token similarity."""
    stories: list[Story] = []
    for item in items:
        toks = tokenize(item.title)
        if not toks:
            continue
        placed = False
        for story in stories:
            if story.matches(toks, threshold):
                story.add(item, toks)
                placed = True
                break
        if not placed:
            new = Story()
            new.add(item, toks)
            stories.append(new)
    return stories
