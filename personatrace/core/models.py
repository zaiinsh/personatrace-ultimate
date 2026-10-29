"""Core data shapes — names and fields exactly as in CONTRACT.md.

No behaviour lives here; confidence, variations, resolution, provenance
and the engine build on these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Evidence:  # one collected fact
    source_url: str
    captured_at_utc: str
    method: str
    platform: str
    field: str
    value: str
    confidence: int  # 0-100


@dataclass
class Profile:  # one public account candidate
    platform: str
    username: str
    display_name: str = ""
    bio: str = ""
    avatar_hash: str = ""
    bio_links: list = field(default_factory=list)
    follower_count: int | None = None
    following_count: int | None = None
    created_at: str = ""
    evidence: list = field(default_factory=list)
    status: str = "candidate"  # candidate | confirmed | possible | rejected | not_checked
    confidence: int = 0  # integration field: max evidence confidence, restored by storage; 0 = unknown


@dataclass
class Edge:
    from_id: str
    to_id: str
    kind: str  # same_username | avatar_reuse | bio_link | network_overlap | username_variant | style_timing | manual_note
    confidence: int
    band: str  # Low (<50) | Medium (50-79) | High (80+)
    evidence: list = field(default_factory=list)


@dataclass
class Investigation:
    case_id: str
    seed: str
    seed_type: str = "username"  # username | domain | email | name | url | image | hashtag | phrase | ip | auto | multi
    profiles: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    checklist: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    possible_matches: list = field(default_factory=list)  # dicts: {profile, score, reasons, status: pending|accepted|rejected}
    alerts: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    timeline: list = field(default_factory=list)  # dicts {ts_utc, kind, description}
    purpose: str = ""
