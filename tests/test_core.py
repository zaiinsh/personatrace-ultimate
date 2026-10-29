"""Core engine tests — stdlib + pytest only, no network.

All fixtures are fictional dummy data (demo_user_01 etc.), never real
personal data, per CONTRACT.md.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from personatrace.core import (
    Investigation,
    Profile,
    accept_possible_match,
    band_for,
    candidates_for_seed,
    edge_confidence,
    entity_confidence,
    generate_variations,
    make_evidence,
    merge_candidate,
    resolve_candidate,
    run_investigation,
    score_pair,
    survivorship,
    unmerge,
)
from personatrace.core.confidence import classify_merge
from personatrace.core.models import Edge


def _profile(platform, username, **kwargs):
    kwargs.setdefault("evidence", [])
    return Profile(platform=platform, username=username, **kwargs)


def _inv(seed="demo_user_01"):
    return Investigation(case_id="case_test", seed=seed)


# ---------------------------------------------------------------- variations

def test_variations_seed_first_and_families():
    out = generate_variations("demo_user_01")
    assert out[0] == "demo_user_01"
    # delimiters
    assert "demo.user.01" in out
    assert "demo-user-01" in out
    assert "demouser01" in out
    # numeric tails
    assert "demo_user_012" in out
    assert "demo_user_0199" in out
    assert "demo_user_0194" in out
    assert "demo_user_011994" in out
    assert "demo_user_01_v2" in out
    # leetspeak: e->3, o->0, s->5, l->1 (demo_user_01 -> d3m0_u53r_01)
    assert "d3m0_u53r_01" in out
    # affixes
    assert "thedemo_user_01" in out
    assert "realdemo_user_01" in out
    assert "officialdemo_user_01" in out
    assert "demo_user_01x" in out
    assert "demo_user_01_ig" in out
    assert "demo_user_01_x" in out
    # case variants: lower only, no upper-case variant generated
    assert "demo_user_01" in out
    assert not any(v != v.lower() for v in out[1:])


def test_variations_truncations_and_dedup_and_limit():
    long_seed = "demo_user_012345678901234567890"
    out = generate_variations(long_seed)
    assert long_seed[:15] in out
    assert long_seed[:20] in out
    assert long_seed[:24] in out
    assert len(out) == len(set(out)), "variations must be deduplicated"
    assert len(generate_variations("demo_user_01", limit=5)) == 5
    assert len(generate_variations("demo_user_01", limit=60)) <= 60
    assert generate_variations("") == []
    assert generate_variations("   ") == []


def test_variations_ranking_family_order():
    out = generate_variations("demo_user_01")
    # delimiter family comes before numeric tails, which come before affixes
    assert out.index("demo.user.01") < out.index("demo_user_012")
    assert out.index("demo_user_012") < out.index("thedemo_user_01")


def test_candidates_for_seed_uses_variations():
    profiles = [
        _profile("github", "demo_user_01"),
        _profile("github", "demo_user_01x"),
        _profile("github", "unrelated_person"),
    ]
    found = candidates_for_seed("demo_user_01", profiles)
    assert [p.username for p in found] == ["demo_user_01", "demo_user_01x"]


# ---------------------------------------------------------------- confidence

def test_confidence_bands():
    assert band_for(0) == "Low"
    assert band_for(49) == "Low"
    assert band_for(50) == "Medium"
    assert band_for(79) == "Medium"
    assert band_for(80) == "High"
    assert band_for(100) == "High"


def test_confidence_drivers_show_weights():
    score, band, drivers = edge_confidence([("exact_username", 0.40, 1.0)])
    assert score == 40
    assert band == "Low"
    assert any("exact_username" in d and "0.40" in d for d in drivers)
    assert any("weights sum" in d for d in drivers)


def test_exact_username_alone_is_low():
    score, band, _ = edge_confidence([("exact_username", 0.40, 1.0)])
    assert score < 50 and band == "Low"


def test_username_avatar_biolink_is_high():
    score, band, _ = edge_confidence(
        [
            ("exact_username", 0.40, 1.0),
            ("avatar_reuse", 0.30, 1.0),
            ("bio_link", 0.30, 1.0),
        ]
    )
    assert score == 100 and band == "High"


def test_entity_confidence_never_exceeds_100_and_empty_is_zero():
    score, band, drivers = entity_confidence(
        [Edge("a", "b", "same_username", 90, "High"), Edge("a", "c", "bio_link", 90, "High")]
    )
    assert score <= 100
    assert score >= 90  # corroboration raises, never lowers below the max edge
    assert drivers
    assert entity_confidence([])[0] == 0


def test_style_timing_capped_at_25():
    score, band, drivers = edge_confidence([("style_timing", 1.0, 1.0)])
    assert score == 25
    assert any("capped" in d for d in drivers)
    # even a perfect style signal plus nothing else stays Low
    assert band == "Low"


# ---------------------------------------------------------------- resolution / merges

def _seed_profile():
    return _profile("seed", "demo_user_01")


def test_merge_thresholds():
    assert classify_merge(80) == "auto_merge"
    assert classify_merge(100) == "auto_merge"
    assert classify_merge(79) == "possible"
    assert classify_merge(50) == "possible"
    assert classify_merge(49) == "reject"
    assert classify_merge(0) == "reject"


def test_resolve_high_auto_merges_and_is_logged():
    inv = _inv()
    cand = _profile(
        "github", "demo_user_01",
        avatar_hash="aabbccddeeff0011",
        bio_links=["https://demo.example/blog"],
    )
    seed = _seed_profile()
    seed.avatar_hash = "aabbccddeeff0011"
    seed.bio_links = ["https://demo.example/blog"]
    decision = resolve_candidate(inv, seed, cand)
    assert decision == "auto_merge"
    assert cand.status == "confirmed"
    assert len(inv.edges) == 1
    assert inv.edges[0].band == "High"
    assert any(e["action"] == "merge" for e in inv.audit)


def test_resolve_medium_goes_to_possible_queue_never_auto_merged():
    inv = _inv()
    cand = _profile("github", "demo_user_01", avatar_hash="aabbccddeeff0011")
    seed = _seed_profile()
    seed.avatar_hash = "aabbccddeeff0011"
    decision = resolve_candidate(inv, seed, cand)
    # exact (40) + avatar (30) = 70 -> Medium -> queue
    assert decision == "possible"
    assert cand.status == "possible"
    assert len(inv.edges) == 0
    assert len(inv.possible_matches) == 1
    entry = inv.possible_matches[0]
    assert entry["status"] == "pending" and entry["score"] == 70
    assert any(e["action"] == "possible_match_queued" for e in inv.audit)


def test_resolve_low_rejects_and_keeps_separate():
    inv = _inv()
    cand = _profile("github", "demo_user_01")  # exact username alone = 40
    decision = resolve_candidate(inv, _seed_profile(), cand)
    assert decision == "reject"
    assert cand.status == "rejected"
    assert len(inv.edges) == 0
    assert len(inv.possible_matches) == 0


def test_stylometry_never_sole_merge_basis():
    # Perfect style + timing, zero username/avatar/bio corroboration.
    result = score_pair(
        _seed_profile(),
        _profile("github", "totally_different"),
        style_similarity=1.0,
        timing_similarity=1.0,
    )
    assert result["score"] <= 25
    assert result["decision"] == "reject"
    assert result["decision"] != "auto_merge"
    # And via the public resolve path it is rejected, not merged/queued.
    inv = _inv()
    cand = _profile("github", "totally_different")
    decision = resolve_candidate(inv, _seed_profile(), cand, 1.0, 1.0)
    assert decision == "reject"
    assert cand.status == "rejected"
    assert len(inv.edges) == 0


def test_reversible_merge_unmerge():
    inv = _inv()
    seed = _seed_profile()
    seed.avatar_hash = "aabbccddeeff0011"
    seed.bio_links = ["https://demo.example/blog"]
    cand = _profile(
        "github", "demo_user_01",
        avatar_hash="aabbccddeeff0011",
        bio_links=["https://demo.example/blog"],
    )
    assert resolve_candidate(inv, seed, cand) == "auto_merge"
    assert cand.status == "confirmed" and len(inv.edges) == 1
    assert unmerge(inv, cand) is True
    assert cand.status == "candidate"
    assert len(inv.edges) == 0
    assert any(e["action"] == "unmerge" for e in inv.audit)
    # second unmerge: nothing left to reverse
    assert unmerge(inv, cand) is False


def test_accept_possible_match_then_unmerge_reopens_queue():
    inv = _inv()
    seed = _seed_profile()
    seed.avatar_hash = "aabbccddeeff0011"
    cand = _profile("github", "demo_user_01", avatar_hash="aabbccddeeff0011")
    assert resolve_candidate(inv, seed, cand) == "possible"
    assert accept_possible_match(inv, cand) is True
    assert cand.status == "confirmed"
    assert inv.possible_matches[0]["status"] == "accepted"
    assert unmerge(inv, cand) is True
    assert cand.status == "possible"
    assert inv.possible_matches[0]["status"] == "pending"


def test_survivorship_rules():
    profiles = [
        _profile("github", "demo_user_01", display_name="Demo",
                 bio="short", avatar_hash="hashA",
                 bio_links=["https://a.example"], follower_count=10),
        _profile("youtube", "demo_user_01", display_name="Demo User Long",
                 bio="a much longer biography here", avatar_hash="hashA",
                 bio_links=["https://b.example", "https://a.example"],
                 follower_count=50, following_count=7),
    ]
    won = survivorship(profiles)
    assert won["display_name"] == "Demo User Long"  # longest wins
    assert won["bio"] == "a much longer biography here"
    assert won["avatar_hash"] == "hashA"  # most common
    assert won["bio_links"] == ["https://a.example", "https://b.example"]  # union, deduped
    assert won["follower_count"] == 50
    assert won["following_count"] == 7


# ---------------------------------------------------------------- provenance

def test_provenance_fields_present_on_every_evidence_item():
    ev = make_evidence(
        "https://github.com/demo_user_01", "public_api", "github",
        "username", "demo_user_01", 90,
    )
    assert ev.source_url == "https://github.com/demo_user_01"
    assert ev.captured_at_utc  # UTC timestamp auto-filled
    assert ev.captured_at_utc.endswith("Z")
    assert ev.method == "public_api"
    assert ev.platform == "github"
    assert ev.field == "username"
    assert ev.value == "demo_user_01"
    assert ev.confidence == 90
    # explicit timestamp kept verbatim; confidence clamped
    ev2 = make_evidence("https://x.example/d", "public_lookup", "x",
                        "bio", "hello", 150, captured_at_utc="2026-01-01T00:00:00Z")
    assert ev2.captured_at_utc == "2026-01-01T00:00:00Z"
    assert ev2.confidence == 100


# ---------------------------------------------------------------- engine

class _FakeAdapter:
    name = "fake"
    platform = "github"

    def __init__(self, profiles, status="ok"):
        self._profiles = profiles
        self._status = status

    def search(self, seed, keys):
        from types import SimpleNamespace

        return SimpleNamespace(
            profiles=list(self._profiles), status=self._status,
            message="", cost_units=0.0,
        )


class _NotCheckedAdapter(_FakeAdapter):
    def search(self, seed, keys):
        from types import SimpleNamespace

        return SimpleNamespace(profiles=[], status="not_checked",
                              message="Add a key in Settings > API Keys", cost_units=0.0)


class _FailingAdapter:
    name = "failing"
    platform = "github"

    def search(self, seed, keys):
        raise RuntimeError("boom")


def test_engine_runs_adapters_and_resolves():
    strong = _profile("github", "demo_user_01", avatar_hash="aabbccddeeff0011",
                      bio_links=["https://demo.example/blog"])
    weak = _profile("youtube", "demo_user_01")
    inv = run_investigation(
        "demo_user_01",
        adapters=[_FakeAdapter([strong, weak])],
        keys={},
    )
    assert inv.seed == "demo_user_01"
    assert len(inv.profiles) == 2
    # engine's internal seed profile has no avatar/bio, so both score
    # exact-username-alone (40) and are rejected — resolution is applied,
    # not bypassed. (A corroborated adapter result merges; see next test.)
    assert all(p.status == "rejected" for p in inv.profiles)
    assert any(e["action"] == "investigation_completed" for e in inv.audit)


def test_engine_merges_with_enriched_seed_profile():
    # With an enriched seed reference (known avatar + bio link), an
    # adapter profile matching all three signals scores 100 -> auto-merge.
    seed_ref = _profile("seed", "demo_user_01", avatar_hash="aabbccddeeff0011",
                        bio_links=["https://demo.example/blog"], status="confirmed")
    hit = _profile("github", "demo_user_01", avatar_hash="aabbccddeeff0011",
                   bio_links=["https://demo.example/blog"])
    inv = run_investigation("demo_user_01", adapters=[_FakeAdapter([hit])],
                            keys={}, seed_profile=seed_ref)
    assert hit.status == "confirmed"
    assert len(inv.edges) == 1
    assert inv.edges[0].confidence == 100 and inv.edges[0].band == "High"
    assert any(e["action"] == "merge" for e in inv.audit)


def test_engine_empty_adapter_list_is_clean():
    inv = run_investigation("demo_user_01", adapters=[], keys={})
    assert inv.profiles == [] and inv.edges == []
    assert any(e["action"] == "investigation_completed" for e in inv.audit)


def test_engine_not_checked_adapter_yields_zero_profiles_not_not_found():
    inv = run_investigation("demo_user_01", adapters=[_NotCheckedAdapter([])], keys={})
    assert inv.profiles == []
    assert not any("not found" in str(e["detail"]).lower() for e in inv.audit)
    assert any(e["detail"].get("status") == "not_checked" for e in inv.audit
               if e["action"] == "adapter_search")


def test_engine_tolerates_failing_adapter_and_missing_registry():
    inv = run_investigation("demo_user_01", adapters=[_FailingAdapter()], keys={})
    assert any(e["action"] == "adapter_error" for e in inv.audit)
    # INTEGRATION UPDATE: adapters=None now loads the real registry when it
    # exists (integrated tree), so profiles may be non-empty; the contract
    # is no crash + adapters_loaded audit, and adapters=[] is the empty case.
    inv2 = run_investigation("demo_user_01", adapters=None, keys={})
    assert any(e["action"] == "adapters_loaded" for e in inv2.audit)
    inv3 = run_investigation("demo_user_01", adapters=[], keys={})
    assert inv3.profiles == []


def test_merge_candidate_direct_high_path():
    inv = _inv()
    seed = _seed_profile()
    cand = _profile("github", "demo_user_01")
    edge = merge_candidate(inv, seed, cand, score=90, reasons=["exact username match"])
    assert cand.status == "confirmed"
    assert edge.confidence == 90 and edge.band == "High"
    assert unmerge(inv, cand) is True
