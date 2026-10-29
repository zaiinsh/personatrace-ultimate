"""Username variation engine — CONTRACT.md order, ranked, deduplicated.

Families, in order:
  1. delimiters (_ . -)
  2. numeric tails (2, 99, 94, 1994, _v2)
  3. leetspeak (a->4, e->3, o->0, s->5, l->1)
  4. affixes (the, real, official, x, _ig, _x)
  5. truncations (15, 20, 24, 30, 39 chars)
  6. case variants — lower only

The seed itself is always first, output is deduplicated and capped at
``limit`` (default 60). No unbounded generation, and no birth-year
variants derived from a real name — the seed is a username, not a
person name, and the numeric tails above are fixed literals.
"""

from __future__ import annotations

import re

LEET_MAP = {"a": "4", "e": "3", "o": "0", "s": "5", "l": "1"}
_NUMERIC_TAILS = ("2", "99", "94", "1994", "_v2")
_TRUNCATIONS = (15, 20, 24, 30, 39)


def _clean_seed(seed_username: str) -> str:
    """Strip whitespace/@ and normalise internal whitespace to ``_``."""
    if seed_username is None:
        return ""
    cleaned = str(seed_username).strip().lstrip("@")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned


def _leet(text: str) -> str:
    return "".join(LEET_MAP.get(ch, ch) for ch in text.lower())


def generate_variations(seed_username: str, limit: int = 60) -> list[str]:
    """Return ranked, deduplicated username variations, seed first."""
    seed = _clean_seed(seed_username)
    if not seed:
        return []
    if limit is None or int(limit) <= 0:
        return []
    limit = int(limit)

    base = seed.lower()
    ordered: list[str] = []

    def add(value: str) -> None:
        if value and value not in ordered:
            ordered.append(value)

    # 0. Seed itself, verbatim, first.
    add(seed)

    # 1. Delimiters: replace all existing delimiters with each of _ . -,
    #    plus the stripped (delimiter-free) form.
    stripped = re.sub(r"[_\.\-]+", "", base)
    for delim in ("_", ".", "-"):
        add(re.sub(r"[_\.\-]+", delim, base))
    add(stripped)

    # 2. Numeric tails (fixed literals, appended to the lower base).
    for tail in _NUMERIC_TAILS:
        add(base + tail)

    # 3. Leetspeak (full translation, lower).
    add(_leet(base))

    # 4. Affixes: prefixes the/real/official (bare and with _),
    #    suffixes x/_ig/_x.
    for prefix in ("the", "real", "official"):
        add(prefix + base)
        add(prefix + "_" + base)
    add(base + "x")
    add(base + "_ig")
    add(base + "_x")

    # 5. Truncations (only when they actually shorten the base).
    for length in _TRUNCATIONS:
        if len(base) > length:
            add(base[:length])

    # 6. Case variant: lower only.
    add(base)

    return ordered[:limit]
