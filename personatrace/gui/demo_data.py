"""Self-contained fictional demo data for the GUI.

Used when core/storage/adapters are not yet built (they are not, at the
time this module was written). Every username starts with ``demo_`` and
every payload is labelled demo, so demo data can never be mistaken for
real findings. No real personal data anywhere in this file.
"""

DEMO_TIMESTAMP = "2026-10-28T12:00:00Z"


def _evidence(platform, username, field, value, confidence, url):
    return {
        "source_url": url,
        "captured_at_utc": DEMO_TIMESTAMP,
        "method": "demo",
        "platform": platform,
        "field": field,
        "value": value,
        "confidence": confidence,
    }


def _profile(platform, username, display_name, bio, status, confidence,
              evidence, bridge=False, bio_links=None):
    profile = {
        "platform": platform,
        "username": username,
        "display_name": display_name,
        "bio": bio,
        "avatar_hash": "demo-phash-%s" % username,
        "bio_links": bio_links or [],
        "follower_count": 120,
        "following_count": 85,
        "created_at": "2023-04-01T00:00:00Z",
        "evidence": evidence,
        "status": status,
        "confidence": confidence,
        "confidence_drivers": [
            "exact username match (Low on its own)",
            "same avatar perceptual hash, Hamming distance 4",
            "same bio link domain",
        ],
        "ring": 1,
    }
    if bridge:
        profile["bridge"] = True
        profile["ring"] = 2
    return profile


def demo_profiles():
    """7 fictional profiles across 6 platforms (seed + bridge node)."""
    seed_evidence = [
        _evidence("github", "demo_user_01", "username", "demo_user_01", 92,
                  "https://github.com/demo_user_01"),
        _evidence("github", "demo_user_01", "bio_link", "demo.example.dev", 88,
                  "https://github.com/demo_user_01"),
    ]
    profiles = [
        dict(_profile(
            "github", "demo_user_01", "Demo User One",
            "Demo security researcher. Writes about demo APIs.",
            "confirmed", 92, seed_evidence,
            bio_links=["https://demo.example.dev"]),
            ring=0, node_id="demo_user_01:github"),
        _profile(
            "youtube", "demo_user_01", "Demo User One",
            "Demo channel about API security basics.",
            "confirmed", 90,
            [_evidence("youtube", "demo_user_01", "username", "demo_user_01",
                        90, "https://youtube.com/@demo_user_01")],
            bio_links=["https://demo.example.dev"]),
        _profile(
            "bluesky", "demo_user_01", "Demo User One",
            "Demo posts about public APIs. demo.example.dev",
            "confirmed", 88,
            [_evidence("bluesky", "demo_user_01", "username", "demo_user_01",
                        88, "https://bsky.app/profile/demo_user_01")],
            bio_links=["https://demo.example.dev"]),
        _profile(
            "mastodon", "demo_user_01", "Demo User One",
            "Demo account, same bio link as the seed.",
            "candidate", 85,
            [_evidence("mastodon", "demo_user_01", "username", "demo_user_01",
                        85, "https://mastodon.social/@demo_user_01")],
            bio_links=["https://demo.example.dev"]),
        _profile(
            "x", "demo_user01", "Demo User One",
            "Demo account; username without the underscore.",
            "candidate", 72,
            [_evidence("x", "demo_user01", "username", "demo_user01",
                        72, "https://x.com/demo_user01")]),
        _profile(
            "instagram", "demo_user_01_ig", "Demo User One",
            "Demo account; username with an _ig affix.",
            "candidate", 68,
            [_evidence("instagram", "demo_user_01_ig", "username",
                        "demo_user_01_ig", 68,
                        "https://instagram.com/demo_user_01_ig")]),
        dict(_profile(
            "mastodon", "demo_bridge_01", "Demo Bridge",
            "Demo account that links the seed cluster to a second cluster.",
            "possible", 64,
            [_evidence("mastodon", "demo_bridge_01", "network_overlap",
                        "follows demo_user_01 and demo_cluster_b", 64,
                        "https://mastodon.social/@demo_bridge_01")],
            bridge=True),
            node_id="demo_bridge_01:mastodon"),
    ]
    # Assign node ids + rings consistently.
    ids = ["demo_user_01:github", "demo_user_01:youtube",
           "demo_user_01:bluesky", "demo_user_01:mastodon",
           "demo_user01:x", "demo_user_01_ig:instagram",
           "demo_bridge_01:mastodon"]
    rings = [0, 1, 1, 1, 2, 2, 2]
    for profile, node_id, ring in zip(profiles, ids, rings):
        profile["node_id"] = node_id
        profile["ring"] = ring
    return profiles


def demo_edges():
    """9 edges, including edges incident to the bridge node."""
    def edge(frm, to, kind, confidence, band):
        return {"from_id": frm, "to_id": to, "kind": kind,
                "confidence": confidence, "band": band, "evidence": []}

    g = "demo_user_01:github"
    return [
        edge(g, "demo_user_01:youtube", "same_username", 92, "High"),
        edge(g, "demo_user_01:bluesky", "same_username", 90, "High"),
        edge(g, "demo_user_01:mastodon", "same_username", 85, "High"),
        edge(g, "demo_user01:x", "username_variant", 72, "Medium"),
        edge(g, "demo_user_01_ig:instagram", "username_variant", 68, "Medium"),
        edge("demo_user_01:youtube", "demo_user_01:bluesky",
             "avatar_reuse", 88, "High"),
        edge("demo_user_01:bluesky", "demo_bridge_01:mastodon",
             "network_overlap", 76, "Medium"),
        edge("demo_bridge_01:mastodon", "demo_user_01:mastodon",
             "network_overlap", 64, "Medium"),
        edge(g, "demo_bridge_01:mastodon", "bio_link", 55, "Medium"),
        edge("demo_user_01:youtube", "demo_user_01_ig:instagram",
             "style_timing", 45, "Low"),
    ]


def demo_timeline():
    return [
        {"ts_utc": "2026-10-24T09:00:00Z", "kind": "profile_found",
         "description": "Demo seed profile found on github (demo data)."},
        {"ts_utc": "2026-10-25T10:30:00Z", "kind": "profile_found",
         "description": "Demo matching profile found on youtube (demo data)."},
        {"ts_utc": "2026-10-26T14:15:00Z", "kind": "edge_added",
         "description": "Demo avatar-reuse edge linked youtube and bluesky."},
        {"ts_utc": "2026-10-27T08:45:00Z", "kind": "possible_match",
         "description": "Demo bridge node demo_bridge_01 queued as a possible match."},
        {"ts_utc": "2026-10-28T12:00:00Z", "kind": "alert",
         "description": "Demo alert: new edge to the bridge node."},
    ]


def demo_alerts():
    return [
        {"ts_utc": "2026-10-28T12:00:00Z", "kind": "new_edge",
         "message": "Demo alert: new medium-confidence edge to demo_bridge_01.",
         "acknowledged": 0},
        {"ts_utc": "2026-10-27T08:45:00Z", "kind": "possible_match",
         "message": "Demo alert: demo_bridge_01 is in the possible-match queue (score 64).",
         "acknowledged": 0},
    ]


def demo_possible_matches():
    return [{
        "profile": {"platform": "mastodon", "username": "demo_bridge_01"},
        "score": 64,
        "reasons": ["network overlap with seed cluster",
                    "shared bio link domain"],
        "status": "pending",
    }]


def demo_audit():
    return [
        {"ts_utc": "2026-10-24T09:00:00Z", "actor": "demo",
         "action": "case_created", "detail": "Demo case created for demo_user_01."},
        {"ts_utc": "2026-10-27T08:45:00Z", "actor": "demo",
         "action": "possible_match_queued",
         "detail": "demo_bridge_01 queued (score 64, below auto-merge threshold 80)."},
        {"ts_utc": "2026-10-28T12:00:00Z", "actor": "demo",
         "action": "export_viewed", "detail": "Demo single-case export viewed."},
    ]


def demo_investigation():
    """Full demo investigation payload, always labelled demo."""
    return {
        "demo": True,
        "label": "demo",
        "case_id": "demo-case-01",
        "seed": "demo_user_01",
        "seed_type": "username",
        "profiles": demo_profiles(),
        "edges": demo_edges(),
        "possible_matches": demo_possible_matches(),
        "alerts": demo_alerts(),
        "timeline": demo_timeline(),
        "audit": demo_audit(),
    }


def demo_adapters(key_names):
    """Adapter statuses. Free adapters are active; gated ones are active
    only once a key name has been stored, otherwise not_checked with a
    prompt to add the key in Settings. ``key_names`` is a set of names
    only — key values are never handled here."""
    free = ["github", "gitlab", "youtube", "bluesky", "mastodon", "wayback", "crtsh",
            "dns"]
    gated = ["x", "instagram", "reddit", "tiktok"]
    adapters = []
    for name in free:
        adapters.append({"name": name, "platform": name,
                         "status": "active", "requires_key": False,
                         "message": "Free source, active."})
    for name in gated:
        if name in key_names:
            adapters.append({"name": name, "platform": name,
                             "status": "active", "requires_key": True,
                             "message": "Key stored (name only)."})
        else:
            adapters.append({"name": name, "platform": name,
                             "status": "not_checked", "requires_key": True,
                             "message": "Add a key in Settings > API Keys "
                                        "to check this source."})
    return adapters
