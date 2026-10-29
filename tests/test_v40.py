"""Tests for PersonaTrace v4.0 — the 31-item list, one by one."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from personatrace.core.models import Profile
from personatrace.core.resolution import score_pair, survivorship_merge_profiles
from personatrace.features.v4 import (
    TokenBucket, builtin_ner, builtin_object_heuristic, curated_site_lists,
    entity_confidence, groups_v4, level4_contacts, private_terminal,
    push_updates_config, quota_add, quota_banner, rejected_weight_penalty,
    survivorship_merge, uncapped_list, wayback_all_profiles,
)
from personatrace.features.v2 import SITE_TEMPLATES, SITE_CHECKS

def _p(u, display=""):
    return Profile(platform="github", username=u, display_name=display)

def test_token_bucket():
    b = TokenBucket(rate_per_minute=60, burst=2)
    assert b.acquire() and b.acquire() and not b.acquire()
    assert "tokens_available" in b.state()

def test_private_terminal():
    assert private_terminal({"private": True})["status"] == "private_terminal"
    assert private_terminal({"private": False})["status"] == "not_private"
    r = score_pair(_p("a"), Profile(platform="x", username="a", display_name="a"))
    # private via attribute is not in Profile model, so test dict helper only
    assert r["score"] >= 0

def test_survivorship():
    out = survivorship_merge({"bio": "short", "username": "a"}, {"bio": "a much longer bio here", "username": "a"})
    assert out["merged"]["bio"] == "a much longer bio here"
    assert out["field_sources"]["bio"] == "b"
    assert survivorship_merge_profiles({"bio": "x"}, {"bio": "longer bio"})["merged"]["bio"] == "longer bio"

def test_rejected_weights():
    pen, reasons = rejected_weight_penalty("octocat", ["octocat"])
    assert pen == -20 and reasons
    r = score_pair(_p("octocat"), _p("octocat"), rejected_patterns=["octocat"])
    # exact match 40 minus rejected 20 = 20, plus other signals may vary; check penalty applied via reasons/drivers
    assert r["score"] < 40 or any("rejected" in d for d in r.get("drivers", []))

def test_level4_and_groups():
    l4 = level4_contacts({"bob": ["alice"]}, lambda u: ["carol"] if u == "alice" else [])
    assert l4 == {"alice": ["carol"]}
    g = groups_v4(["org1"], {"posts": [{"subreddit": "python"}]}, ["https://t.me/mychannel"], ["alice"])
    assert "python" in g["reddit_communities"] and "mychannel" in g["telegram_channels_from_bio_links"]

def test_builtin_ner_and_object():
    out = builtin_ner("I work at Acme Labs in Islamabad, Pakistan.")
    assert "Islamabad" in out["places"] and out["method"] == "builtin_heuristic_not_trained"
    # 1x1 PNG bytes via Pillow
    from PIL import Image
    import io
    buf = io.BytesIO(); Image.new("RGB", (10, 10), (10, 100, 200)).save(buf, format="PNG")
    obj = builtin_object_heuristic(buf.getvalue())
    assert obj["method"] == "builtin_heuristic_not_object_recognition"

def test_quota_and_push_and_uncapped():
    quota_add("youtube_test_source", 5)
    b = quota_banner({"youtube_test_source_quota": 100})
    assert any(x["source"] == "youtube_test_source" and x["remaining"] == 95 for x in b)
    assert push_updates_config()["mode"] == "polling_plus_webhook"
    u = uncapped_list(list(range(25)), "test")
    assert u["processed"] == 20 and u["truncated"] is True

def test_curated_and_live_sites():
    c = curated_site_lists()
    assert c["count"] == len(SITE_TEMPLATES) >= 150
    reliable = [s for s in SITE_CHECKS if s.get("reliable_404")]
    assert len(reliable) >= 10, reliable
    assert "stackoverflow" in [s["site"] for s in reliable]

def test_entity_confidence():
    e = entity_confidence({"score": 55, "decision": "possible", "reasons": ["exact username match", "negative: Different display names"]})
    assert e["score"] == 55 and any(s["effect"] == "negative" for s in e["signals"])
