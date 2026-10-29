"""Tests for PersonaTrace v3.0 — finishing the v2 gaps, one by one."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from personatrace.core.models import Profile
from personatrace.core.resolution import score_pair
from personatrace.features.v2 import SITE_TEMPLATES, check_sites
from personatrace.features.v3 import (
    coordinated_v3, native_ner, niche_overlap, reddit_archive,
)


def _profile(username, display="", bio="", created=""):
    return Profile(platform="github", username=username, display_name=display,
                   bio=bio, created_at=created)


def test_cross_script_and_negative_in_scoring():
    seed = _profile("privet", display="Privet", bio="hello world", created="2020-01-01")
    cand = _profile("привет", display="Privet", bio="hello world", created="2020-01-01")
    result = score_pair(seed, cand)
    assert any("cross-script" in r for r in result["reasons"]), result["reasons"]
    # Negative: different languages + far apart creation years pull score down.
    seed2 = _profile("sameuser", display="Same", bio="hello world", created="2020-01-01")
    cand2 = _profile("sameuser", display="Different", bio="مرحبا بالعالم", created="2010-01-01")
    plain = score_pair(seed2, cand2)
    assert any("negative" in r for r in plain["reasons"])
    assert plain["score"] < 100


def test_common_name_raises_merge_bar():
    seed = _profile("john", display="John", bio="", created="")
    cand = _profile("john", display="John", bio="", created="")
    result = score_pair(seed, cand)
    # Exact username alone is 40 points, so it should be possible, not auto-merge — and even a high score below 90 must not auto-merge for a common name.
    assert result["decision"] in ("possible", "reject")


def test_niche_overlap_weights_rare_over_celebrity():
    out = niche_overlap(["octocat", "a_rare_handle_xyz", "github"])
    assert "a_rare_handle_xyz" in out["niche_shared"]
    assert out["niche_ratio"] > 0


def test_coordinated_v3_signals():
    accounts = [
        {"username": "a", "bio": "I love cats @user", "links": ["https://example.com/x"], "posts": [{"text": "see https://example.com/x", "created_at": "2026-01-01T10:00:00Z"}]},
        {"username": "b", "bio": "I love cats @user", "links": ["https://example.com/x"], "posts": [{"text": "see https://example.com/x", "created_at": "2026-01-01T10:30:00Z"}]},
        {"username": "c", "bio": "I love cats @user", "links": ["https://example.com/x"], "posts": [{"text": "see https://example.com/x", "created_at": "2026-01-01T10:45:00Z"}]},
    ]
    out = coordinated_v3(accounts)
    kinds = " ".join(s["signal"] for s in out["signals"])
    assert "Star graph" in kinds
    assert "within an hour" in kinds
    assert "bio template" in kinds
    assert out["verdict"] == "pattern, not proof"


def test_native_ner_preserves_original():
    out = native_ner("I work at Acme Labs in Islamabad, Pakistan.")
    assert "Islamabad" in out["places"] or "Pakistan" in out["places"]
    assert out["original"] == "I work at Acme Labs in Islamabad, Pakistan."


def test_site_templates_are_hundreds():
    assert len(SITE_TEMPLATES) >= 150
    templates = check_sites("octocat", live=False)["templates"]
    assert len(templates) >= 150
    assert all(t["status"] == "template_only" for t in templates)


def test_reddit_archive_never_claims_not_found():
    out = reddit_archive("thisuserdoesnotexist123456", limit=1)
    assert out["status"] in ("ok", "degraded")
    if out["status"] == "degraded":
        assert "not" in out["reason"].lower() or "archive" in out["reason"].lower()
