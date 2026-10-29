"""Exact-phrase search over a supplied corpus of public texts.

No live web search is performed here (and none in tests). The caller
supplies the corpus -- e.g. bios/posts already collected from public
sources -- and this module returns exact-phrase matches with source
URLs. Matching is case-insensitive with whitespace normalised, so a
phrase matches only when it actually appears in the supplied text.
"""

import re

__all__ = ["search_phrase"]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _get(item, field, default=""):
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def search_phrase(corpus, phrase: str) -> list:
    """Return matches for *phrase* in *corpus*.

    Each corpus item needs ``text`` and ``source_url`` (platform and
    username are included when present). Each match carries a snippet
    of surrounding context and the matched phrase.
    """
    needle = _normalise(phrase)
    if not needle:
        return []
    matches = []
    for item in corpus or []:
        text = _get(item, "text", "")
        flat = _normalise(text)
        idx = flat.find(needle)
        if idx < 0:
            continue
        start, end = max(0, idx - 60), min(len(flat), idx + len(needle) + 60)
        matches.append(
            {
                "matched_phrase": phrase,
                "source_url": _get(item, "source_url", ""),
                "platform": _get(item, "platform", ""),
                "username": _get(item, "username", ""),
                "snippet": flat[start:end],
            }
        )
    return matches
