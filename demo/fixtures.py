"""Demo fixtures: fictional dummy data ONLY (demo_* usernames).

NOTE: the core module does not exist yet in this tree, so the
CONTRACT.md data shapes are defined here exactly as specified
(Evidence / Profile / Edge / Investigation). When core lands, this
module should import those classes instead; field names and the
``status`` / band conventions already match the contract, so the
demo investigation will be interchangeable.

All evidence is labelled method="demo" and must never be presented
as real collected data.
"""

from dataclasses import asdict, dataclass, field

__all__ = [
    "Evidence",
    "Profile",
    "Edge",
    "Investigation",
    "demo_investigation",
    "to_dict",
]


def _band(confidence: int) -> str:
    if confidence >= 80:
        return "High"
    if confidence >= 50:
        return "Medium"
    return "Low"


from personatrace.core.models import Edge, Evidence, Investigation, Profile


def _ev(platform, username, field_name, value, confidence=80):
    return Evidence(
        source_url=f"https://example.invalid/demo/{platform}/{username}",
        captured_at_utc="2026-10-28T00:00:00Z",
        method="demo",
        platform=platform,
        field=field_name,
        value=value,
        confidence=confidence,
    )


def _profile(platform, username, bio, links, status="candidate", confidence=80):
    return Profile(
        platform=platform,
        username=username,
        display_name=f"Demo {username}",
        bio=bio,
        bio_links=list(links),
        follower_count=120,
        following_count=90,
        created_at="2024-01-15T00:00:00Z",
        evidence=[_ev(platform, username, "username", username, confidence)],
        status=status,
    )


def demo_investigation() -> Investigation:
    """Build the demo investigation: seed demo_user_01.

    7 dummy profiles across 5 platforms, 9 edges including one bridge
    node (demo_bridge_01) that links the seed cluster to a second
    cluster, plus timeline events, alerts, one possible-match entry
    (status pending, never auto-merged) and audit entries.
    """
    seed = _profile(
        "github", "demo_user_01",
        "Demo security researcher. Writes about web security.",
        ["https://demo-user-01.example.invalid"],
        status="confirmed", confidence=90,
    )
    yt = _profile(
        "youtube", "demo_user_01",
        "Demo security researcher. Videos about web security.",
        ["https://demo-user-01.example.invalid"],
        status="confirmed", confidence=85,
    )
    bsky = _profile(
        "bluesky", "demo_user01",
        "Demo security researcher.",
        ["https://demo-user-01.example.invalid"],
        status="confirmed", confidence=80,
    )
    mast = _profile(
        "mastodon", "demo_user_0194",
        "Demo security researcher.",
        [],
        status="candidate", confidence=65,
    )
    bridge = _profile(
        "github", "demo_bridge_01",
        "Demo collaborator account linking two demo clusters.",
        ["https://demo-bridge.example.invalid"],
        status="candidate", confidence=70,
    )
    second = _profile(
        "mastodon", "demo_second_01",
        "Demo second-cluster account.",
        ["https://demo-bridge.example.invalid"],
        status="candidate", confidence=60,
    )
    other = _profile(
        "youtube", "demo_second_01",
        "Demo second-cluster account.",
        [],
        status="candidate", confidence=60,
    )
    profiles = [seed, yt, bsky, mast, bridge, second, other]

    def edge(a, b, kind, confidence):
        from personatrace.core.confidence import band_for

        return Edge(
            from_id=a, to_id=b, kind=kind, confidence=confidence,
            band=band_for(confidence),
            evidence=[_ev("demo", a, "edge", f"{a} -> {b} ({kind})", confidence)],
        )

    edges = [
        edge("github:demo_user_01", "youtube:demo_user_01", "same_username", 90),
        edge("github:demo_user_01", "bluesky:demo_user01", "username_variant", 75),
        edge("github:demo_user_01", "youtube:demo_user_01", "bio_link", 85),
        edge("youtube:demo_user_01", "bluesky:demo_user01", "avatar_reuse", 82),
        edge("github:demo_user_01", "mastodon:demo_user_0194", "username_variant", 62),
        edge("github:demo_user_01", "github:demo_bridge_01", "network_overlap", 70),
        edge("github:demo_bridge_01", "mastodon:demo_second_01", "bio_link", 68),
        edge("mastodon:demo_second_01", "youtube:demo_second_01", "same_username", 88),
        edge("github:demo_user_01", "bluesky:demo_user01", "style_timing", 55),
    ]

    possible_matches = [
        {
            "profile": asdict(mast),
            "score": 62,
            "reasons": ["username variant of seed", "similar bio wording"],
            "status": "pending",
        }
    ]
    alerts = [
        {
            "kind": "new_edge",
            "edge_kind": "bio_link",
            "from_id": "github:demo_bridge_01",
            "to_id": "mastodon:demo_second_01",
            "message": "New edge: github:demo_bridge_01 -> mastodon:demo_second_01 (bio_link).",
            "ts_utc": "2026-10-28T00:00:00Z",
        }
    ]
    audit = [
        {
            "ts_utc": "2026-10-28T00:00:00Z",
            "actor": "demo",
            "action": "case_created",
            "detail": "Demo case created from fixtures (fictional data only).",
        },
        {
            "ts_utc": "2026-10-28T00:00:00Z",
            "actor": "demo",
            "action": "possible_match_queued",
            "detail": "mastodon:demo_user_0194 queued at score 62 (below auto-merge threshold 80); not auto-merged.",
        },
    ]
    timeline = [
        {"ts_utc": "2024-01-15T00:00:00Z", "kind": "profile_created", "description": "Demo github profile created (fixture)."},
        {"ts_utc": "2024-03-02T00:00:00Z", "kind": "profile_created", "description": "Demo youtube profile created (fixture)."},
        {"ts_utc": "2025-06-10T00:00:00Z", "kind": "edge_found", "description": "Demo bio_link edge found between seed cluster and bridge node."},
        {"ts_utc": "2026-10-28T00:00:00Z", "kind": "alert", "description": "Demo new-edge alert raised."},
    ]
    return Investigation(
        case_id="demo-case-01",
        seed="demo_user_01",
        seed_type="username",
        profiles=profiles,
        edges=edges,
        possible_matches=possible_matches,
        alerts=alerts,
        audit=audit,
        timeline=timeline,
    )


def to_dict(inv: Investigation) -> dict:
    """Serialise an investigation (dataclass-aware)."""
    return asdict(inv)
