"""Fictional demo fixtures for PersonaTrace adapters.

All data here is dummy data only: every username starts with ``demo_``,
every bio starts with ``[DEMO DATA`` and every evidence entry uses
``method="demo"`` with confidence 0 (demo confidence is not a real score).
Never present these profiles as real people or real accounts.

Seed family: ``demo_user_01`` (primary), plus the variation-family
usernames ``demo_user_01_v2`` and ``demo_user.01``.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from .base import Evidence, Profile

DEMO_SEED = "demo_user_01"
_DEMO_TS = "2026-01-01T00:00:00+00:00"

# One demo profile per platform covered by the adapters module.
_DEMO_SPECS = [
    # (platform, username, display_name, bio_links)
    ("github", "demo_user_01", "Demo User", ["https://example.invalid/demo"]),
    ("youtube", "demo_user_01", "Demo User", []),
    ("bluesky", "demo_user_01", "Demo User", ["https://example.invalid/demo"]),
    ("mastodon", "demo_user_01", "Demo User", []),
    ("wayback", "demo_user_01", "Demo User", []),
    ("crtsh", "demo_user_01", "Demo User", []),
    ("dns", "demo_user_01", "Demo User", []),
    ("x", "demo_user_01", "Demo User", ["https://example.invalid/demo"]),
    ("instagram", "demo_user_01", "Demo User", []),
    ("reddit", "demo_user_01", "Demo User", []),
    ("tiktok", "demo_user_01", "Demo User", []),
    ("github", "demo_user_01_v2", "Demo User V2", []),
    ("github", "demo_user.01", "Demo User Dot", []),
]


def _profile_url(platform: str, username: str) -> str:
    templates = {
        "github": f"https://github.com/{username}",
        "youtube": f"https://www.youtube.com/@{username}",
        "bluesky": f"https://bsky.app/profile/{username}",
        "mastodon": f"https://mastodon.social/@{username}",
        "x": f"https://x.com/{username}",
        "instagram": f"https://www.instagram.com/{username}/",
        "reddit": f"https://www.reddit.com/user/{username}/",
        "tiktok": f"https://www.tiktok.com/@{username}",
    }
    return templates.get(platform, f"https://example.invalid/demo/{platform}/{username}")


def demo_profiles(platform: str | None = None, seed: str = DEMO_SEED) -> list:
    """Return deep copies of demo profiles, optionally filtered by platform.

    The ``seed`` argument is accepted for API symmetry but the returned
    fixtures always use the fictional ``demo_*`` family — a caller asking
    for a real username in demo mode still only ever gets dummy data.
    """
    out = []
    for plat, username, display_name, bio_links in _DEMO_SPECS:
        if platform is not None and plat != platform:
            continue
        url = _profile_url(plat, username)
        evidence = [
            Evidence(
                source_url=url,
                captured_at_utc=_DEMO_TS,
                method="demo",
                platform=plat,
                field="demo_label",
                value="demo data - not real",
                confidence=0,
            ),
            Evidence(
                source_url=url,
                captured_at_utc=_DEMO_TS,
                method="demo",
                platform=plat,
                field="username",
                value=username,
                confidence=0,
            ),
        ]
        out.append(
            Profile(
                platform=plat,
                username=username,
                display_name=display_name,
                bio="[DEMO DATA - NOT REAL] Fictional demo profile for testing only.",
                bio_links=list(bio_links),
                follower_count=100,
                following_count=50,
                created_at="2026-01-01T00:00:00+00:00",
                evidence=evidence,
                status="candidate",
            )
        )
    return copy.deepcopy(out)


# Backwards-friendly alias used by some callers.
DEMO_PROFILES = demo_profiles()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
