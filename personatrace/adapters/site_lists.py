"""Curated site list — URL templates only, NOT live existence checks.

This list is sherlock/maigret/whatsmyname-*style* in shape only: a small
curated list of ``(platform, url_template)`` pairs for building a public
profile URL from a username. It does NOT claim that a profile exists, and
it does NOT perform a live check.

Closed platforms are deliberately EXCLUDED: x, instagram, reddit and
tiktok have no entry here. Their profiles may only be looked up through
the gated ``licensed_aggregator`` adapter (see gated.py), which requires
a licensed aggregator key. Never treat a constructed URL for a closed
platform as a verified profile, and never probe a closed platform behind
a login wall from this list.
"""

from __future__ import annotations

# Only platforms whose public profile pages are openly viewable without
# an account. Templates use {username}.
SITE_LISTS: list = [
    ("github", "https://github.com/{username}"),
    ("youtube", "https://www.youtube.com/@{username}"),
    ("bluesky", "https://bsky.app/profile/{username}"),
    ("mastodon", "https://mastodon.social/@{username}"),
    ("gitlab", "https://gitlab.com/{username}"),
    # Telegram: public channel URL template only. There is no general
    # public API for arbitrary Telegram channels, so this is never a
    # verified profile and is never live-checked by an adapter.
    ("telegram", "https://t.me/{username}"),
]

# Platforms that must NEVER be live-checked from this list.
CLOSED_PLATFORMS = frozenset({"x", "instagram", "reddit", "tiktok"})


def site_url(platform: str, username: str) -> str | None:
    """Build a public profile URL template for ``platform``, or None if
    the platform is not in the curated open list (including all closed
    platforms, which go through the gated adapter instead)."""
    for plat, template in SITE_LISTS:
        if plat == platform:
            return template.format(username=username)
    return None


def build_site_urls(username: str) -> list:
    """All curated (platform, url) pairs for ``username``. URL construction
    only — existence is never implied."""
    return [(plat, template.format(username=username)) for plat, template in SITE_LISTS]
