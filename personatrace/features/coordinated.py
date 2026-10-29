"""Coordinated-activity crowd check (pattern detection, not proof).

Input: a list of account dicts with ``posts`` (list of dicts with
``created_at`` and/or ``text``), ``created_at`` and ``bio``.
Output: group-level signals plus innocent explanations, with verdict
exactly "pattern, not proof".

This module NEVER labels any individual account. No account in the
output carries a classification label of any kind, and the output
contains no per-account verdict. A pattern alone proves nothing about
who runs an account or why.
"""

import re
from collections import Counter
from datetime import datetime

__all__ = ["crowd_check"]

_WORD_RE = re.compile(r"[a-z0-9]+")


def _parse_ts(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall((text or "").lower()))


def crowd_check(accounts) -> dict:
    """Check a group of accounts for coordinated-activity patterns."""
    accounts = list(accounts or [])
    signals = []
    if len(accounts) < 2:
        return {
            "accounts_checked": len(accounts),
            "signals": [],
            "innocent_explanations": [
                "Fewer than two accounts supplied; no group pattern can be assessed."
            ],
            "verdict": "pattern, not proof",
        }

    created = [_parse_ts(a.get("created_at")) for a in accounts]
    created = [c for c in created if c is not None]
    if len(created) >= 2:
        span_days = (max(created) - min(created)).days
        if span_days <= 7:
            signals.append(
                f"Accounts created within a {span_days}-day window "
                f"({len(created)} accounts with known creation dates)."
            )

    bios = [_tokens(a.get("bio")) for a in accounts]
    if all(bios):
        shared = set.intersection(*bios)
        shared = {w for w in shared if len(w) > 3}
        if shared:
            signals.append(
                "Shared distinctive bio wording across accounts: "
                + ", ".join(sorted(shared)[:10])
                + "."
            )

    all_hours = []
    for account in accounts:
        hours = []
        for post in account.get("posts") or []:
            ts = _parse_ts(post.get("created_at") if isinstance(post, dict) else None)
            if ts is not None:
                hours.append(ts.hour)
        all_hours.append(hours)
    if all(all_hours):
        common = set.intersection(*[set(h) for h in all_hours])
        if common:
            signals.append(
                "Posting activity overlaps in hour(s): "
                + ", ".join(str(h) for h in sorted(common))
                + " (UTC, as recorded)."
            )

    link_sets = []
    for account in accounts:
        links = set()
        for post in account.get("posts") or []:
            if isinstance(post, dict):
                for url in re.findall(r"https?://[^\s]+", post.get("text") or ""):
                    links.add(url.rstrip(".,)"))
        link_sets.append(links)
    if all(link_sets):
        shared_links = set.intersection(*link_sets)
        if shared_links:
            signals.append(
                f"Shared outbound link(s) across all accounts ({len(shared_links)})."
            )

    post_counts = Counter()
    for account in accounts:
        for post in account.get("posts") or []:
            if isinstance(post, dict) and post.get("text"):
                post_counts[post["text"].strip().lower()] += 1
    repeated = {t: n for t, n in post_counts.items() if n >= 2 and len(t) > 20}
    if repeated:
        signals.append(
            f"Repeated identical post text across accounts ({len(repeated)} text(s))."
        )

    if not signals:
        signals.append("No coordinated-activity pattern detected in the supplied data.")

    innocent = [
        "Accounts may belong to colleagues, classmates, or a team sharing announcements.",
        "Accounts may be fans or attendees of the same event, course, or community.",
        "Similar bios and posting times can reflect a shared template, campaign, or timezone.",
        "Shared links can reflect the same news story, product, or public resource.",
        "Identical short posts can be quotes, slogans, or copy-pasted public statements.",
    ]
    return {
        "accounts_checked": len(accounts),
        "signals": signals,
        "innocent_explanations": innocent,
        "verdict": "pattern, not proof",
    }
