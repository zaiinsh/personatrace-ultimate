"""Stylometry + timing similarity (WEAK signal only).

Combined style+timing contribution to any entity confidence score is
capped at 25% -- that cap is ENFORCED in core/confidence.py, not here;
this module only documents it and always flags its output weak.
Never merge profiles on stylometry/timing alone (see CONTRACT.md).

``style_similarity`` compares function-word frequency profiles
(cosine similarity). Samples under 500 words carry a warning and are
especially unreliable.
"""

import math
import re
from collections import Counter

__all__ = ["style_similarity", "timing_similarity"]

_FUNCTION_WORDS = (
    "the", "be", "to", "of", "and", "a", "in", "that", "it", "was", "for",
    "on", "are", "as", "with", "his", "they", "i", "at", "be", "this",
    "have", "from", "or", "one", "had", "by", "word", "but", "not",
    "what", "all", "were", "we", "when", "your", "can", "said", "there",
    "use", "an", "each", "which", "she", "do", "how", "their", "if",
    "will", "up", "other", "about", "out", "many", "then", "them",
    "these", "so", "some", "her", "would", "make", "like", "him",
    "into", "time", "has", "look", "two", "more", "write", "go", "see",
    "number", "no", "way", "could", "people", "my", "than", "first",
    "water", "been", "call", "who", "oil", "its", "now", "find",
    "long", "down", "day", "did", "get", "come", "made", "may", "part",
    "is", "am", "are", "was", "were", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must", "ought", "need", "dare",
    "very", "just", "also", "only", "even", "still", "already", "yet",
    "however", "therefore", "because", "although", "though", "while",
    "since", "until", "unless", "whether", "either", "neither", "both",
    "you", "he", "she", "we", "they", "me", "him", "us", "them",
    "my", "your", "our", "their", "mine", "yours", "ours", "theirs",
)

_WORD_RE = re.compile(r"[a-z']+")


def _words(text: str) -> list:
    return _WORD_RE.findall((text or "").lower())


def _function_profile(words: list) -> dict:
    counts = Counter(w for w in words if w in _FUNCTION_WORDS)
    total = sum(counts.values())
    if total == 0:
        return {}
    return {w: c / total for w, c in counts.items()}


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in set(a) | set(b))
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def style_similarity(text_a: str, text_b: str) -> dict:
    """Compare writing style; always flagged as a weak signal."""
    words_a, words_b = _words(text_a), _words(text_b)
    score = _cosine(_function_profile(words_a), _function_profile(words_b))
    min_words = min(len(words_a), len(words_b))
    warning = None
    if min_words < 500:
        warning = (
            f"Small sample: smallest text has {min_words} words "
            "(below 500). Stylometry on small samples is unreliable "
            "and must not drive a merge decision."
        )
    return {
        "score": round(score, 4),
        "sample_words_a": len(words_a),
        "sample_words_b": len(words_b),
        "weak_signal": True,
        "warning": warning,
        # Cap reminder for consumers (enforcement lives in core/confidence.py):
        "max_confidence_contribution": 0.25,
    }


def timing_similarity(hours_a, hours_b) -> float:
    """Cosine similarity of two 24-hour posting histograms (0-1)."""
    def _hist(hours):
        counts = Counter()
        for h in hours or []:
            try:
                hour = int(h)
            except (TypeError, ValueError):
                continue
            if 0 <= hour <= 23:
                counts[hour] += 1
        total = sum(counts.values())
        if total == 0:
            return {}
        return {h: c / total for h, c in counts.items()}

    return round(_cosine(_hist(hours_a), _hist(hours_b)), 4)
