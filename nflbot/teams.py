"""Team-name → #Nickname substitution (improvement 1).

Maps all 32 teams — full names, city/region names, and common variants — to their
hashtagged nickname, and rewrites those references in composed post text (e.g.
"the Pittsburgh Steelers" → "the #Steelers", "Denver Broncos" → "#Broncos").

Confidence guards (per the requirement to leave plain text rather than guess):
  * Matching is CASE-SENSITIVE on the canonical capitalisation, so an everyday
    lowercase word like "bills" is never turned into "#Bills" — only "Bills".
  * Ambiguous bare city names that host two teams ("New York", "Los Angeles")
    are deliberately NOT mapped; only the full "New York Giants" / "Los Angeles
    Rams" forms (and the unique nicknames) are.
  * Substitution is a single pass with longest-match-first, so "Pittsburgh
    Steelers" maps once to "#Steelers" rather than cascading.
"""

from __future__ import annotations

import re

# (hashtag, [match variants — exact capitalisation as they appear in prose]).
# Order within a team doesn't matter; the regex is built longest-first.
TEAMS: list[tuple[str, list[str]]] = [
    ("#Cardinals", ["Arizona Cardinals", "Cardinals", "Arizona", "Cards"]),
    ("#Falcons", ["Atlanta Falcons", "Falcons", "Atlanta"]),
    ("#Ravens", ["Baltimore Ravens", "Ravens", "Baltimore"]),
    ("#Bills", ["Buffalo Bills", "Bills", "Buffalo"]),
    ("#Panthers", ["Carolina Panthers", "Panthers", "Carolina"]),
    ("#Bears", ["Chicago Bears", "Bears", "Chicago"]),
    ("#Bengals", ["Cincinnati Bengals", "Bengals", "Cincinnati"]),
    ("#Browns", ["Cleveland Browns", "Browns", "Cleveland"]),
    ("#Cowboys", ["Dallas Cowboys", "Cowboys", "Dallas"]),
    ("#Broncos", ["Denver Broncos", "Broncos", "Denver"]),
    ("#Lions", ["Detroit Lions", "Lions", "Detroit"]),
    ("#Packers", ["Green Bay Packers", "Packers", "Green Bay"]),
    ("#Texans", ["Houston Texans", "Texans", "Houston"]),
    ("#Colts", ["Indianapolis Colts", "Colts", "Indianapolis", "Indy"]),
    ("#Jaguars", ["Jacksonville Jaguars", "Jaguars", "Jacksonville", "Jags"]),
    ("#Chiefs", ["Kansas City Chiefs", "Chiefs", "Kansas City"]),
    ("#Raiders", ["Las Vegas Raiders", "Raiders", "Las Vegas", "Vegas"]),
    # Bare "Los Angeles" is ambiguous (Rams/Chargers) — only the full form maps.
    ("#Chargers", ["Los Angeles Chargers", "Chargers"]),
    ("#Rams", ["Los Angeles Rams", "Rams"]),
    ("#Dolphins", ["Miami Dolphins", "Dolphins", "Miami"]),
    ("#Vikings", ["Minnesota Vikings", "Vikings", "Minnesota", "Vikes"]),
    ("#Patriots", ["New England Patriots", "Patriots", "New England", "Pats"]),
    ("#Saints", ["New Orleans Saints", "Saints", "New Orleans"]),
    # Bare "New York" is ambiguous (Giants/Jets) — only the full forms map.
    ("#Giants", ["New York Giants", "Giants"]),
    ("#Jets", ["New York Jets", "Jets"]),
    ("#Eagles", ["Philadelphia Eagles", "Eagles", "Philadelphia", "Philly"]),
    ("#Steelers", ["Pittsburgh Steelers", "Steelers", "Pittsburgh"]),
    ("#49ers", ["San Francisco 49ers", "49ers", "San Francisco", "Niners"]),
    ("#Seahawks", ["Seattle Seahawks", "Seahawks", "Seattle"]),
    ("#Buccaneers", ["Tampa Bay Buccaneers", "Buccaneers", "Tampa Bay", "Bucs", "Tampa"]),
    ("#Titans", ["Tennessee Titans", "Titans", "Tennessee"]),
    ("#Commanders", ["Washington Commanders", "Commanders", "Washington"]),
]

# Flat exact-string → hashtag lookup.
_LOOKUP: dict[str, str] = {}
for _tag, _variants in TEAMS:
    for _v in _variants:
        _LOOKUP[_v] = _tag

# Longest variant first so multi-word names match before their sub-words.
# Lookbehind/ahead prevent matching inside a word or re-hashtagging an existing
# #tag / @handle. Case-sensitive (no re.IGNORECASE).
_PATTERN = re.compile(
    r"(?<![#@\w])(" + "|".join(re.escape(v) for v in sorted(_LOOKUP, key=len, reverse=True)) + r")(?!\w)"
)


def hashtagify_teams(text: str) -> str:
    """Replace confidently-matched team references with their #Nickname."""
    if not text:
        return text
    return _PATTERN.sub(lambda m: _LOOKUP.get(m.group(1), m.group(1)), text)
