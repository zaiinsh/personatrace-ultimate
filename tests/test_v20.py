"""Tests for PersonaTrace v2.0 features (no network, except where mocked)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from personatrace.features.v2 import (
    behaviour_over_time, capture_hash, common_name_check, cross_script_match,
    label_bio_links, manual_reverse_links, native_entities, negative_signals,
    soundex, transliterate_to_latin, v2_variants,
)
from personatrace.monitor import compare_investigations
from personatrace.storage.vault import ROLES, can, load_key, store_key


def test_soundex_and_variants():
    assert soundex("robert") == soundex("rupert")
    variants = v2_variants("robert_smith")["variants"]
    assert any(v["variant"] == "rob_smith" for v in variants)
    assert transliterate_to_latin("привет") == "privet"
    assert cross_script_match("привет", "privet")


def test_capture_hash_stable():
    a = capture_hash("https://x", "bio", "hi", "2026-01-01")
    assert a == capture_hash("https://x", "bio", "hi", "2026-01-01")
    assert a != capture_hash("https://x", "bio", "bye", "2026-01-01")


def test_common_name_and_negative():
    assert common_name_check("john")["is_common"] is True
    assert common_name_check("zxainunique99")["is_common"] is False
    negs = negative_signals(
        {"language": "english", "created_at": "2020-01-01", "display_name": "John"},
        {"language": "arabic", "created_at": "2010-01-01", "display_name": "Ali"})
    assert len(negs) == 3


def test_behaviour_over_time():
    activity = [
        {"date": "2026-01-05", "timestamp": "2026-01-05T10:00:00Z", "text": "great work"},
        {"date": "2026-02-05", "timestamp": "2026-02-05T10:00:00Z", "text": "great work"},
        {"date": "2026-02-06", "timestamp": "2026-02-06T11:00:00Z", "text": "great work"},
        {"date": "2026-02-07", "timestamp": "2026-02-07T11:00:00Z", "text": "great work"},
        {"date": "2026-02-08", "timestamp": "2026-02-08T11:00:00Z", "text": "bad day"},
    ]
    out = behaviour_over_time(activity)
    assert out["per_month"]["2026-02"]["count"] == 4
    assert out["sudden_shifts"]  # 1 -> 4 is a 4x jump


def test_bio_link_labels_and_native():
    profiles = [
        {"platform": "github", "username": "a", "bio_links": ["https://bit.ly/abc", "https://example.com"]},
        {"platform": "bluesky", "username": "b", "bio_links": ["https://example.com"]},
    ]
    labels = label_bio_links(profiles)
    assert any("shortened_link" in l["labels"] for l in labels)
    assert any("shared_link" in l["labels"] for l in labels)
    ent = native_entities("Hello @bob #test https://example.com and مرحبا")
    assert "@bob" in ent["mentions"]
    assert ent["non_latin_runs"]


def test_manual_reverse_links_are_links_not_scrapes():
    links = manual_reverse_links("https://example.com/a.jpg")
    assert links["google_lens_manual"].startswith("https://lens.google.com/")
    assert links["yandex_manual"].startswith("https://yandex.com/")


def test_monitor_before_after_and_deleted_notes(tmp_path):
    old = {"case_id": "1", "profiles": [{"platform": "github", "username": "octocat", "display_name": "Old", "bio": "old bio", "follower_count": 10}],
           "edges": [], "analysis": {"activity": {"github:octocat": [{"text": "old post"}]}}}
    new = {"case_id": "2", "profiles": [{"platform": "github", "username": "octocat", "display_name": "New", "bio": "new bio", "follower_count": 12}],
           "edges": [], "analysis": {"activity": {"github:octocat": []}}}
    out = compare_investigations(old, new)
    assert out["before_after"]["github:octocat"]["display_name"]["before"] == "Old"
    assert out["before_after"]["github:octocat"]["display_name"]["after"] == "New"
    assert out["deleted_notes"] and out["deleted_notes"][0]["preserved"] is True


def test_vault_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONATRACE_VAULT_PATH", str(tmp_path / "vault.json"))
    monkeypatch.setenv("PERSONATRACE_VAULT_PASSPHRASE", "test-pass-123")
    assert store_key("test_key", "secret-value")["status"] == "stored"
    loaded = load_key("test_key")
    assert loaded["status"] == "ok" and loaded["value"] == "secret-value"
    assert can("viewer", "can_search") is False
    assert can("analyst", "can_search") is True
    assert can("admin", "can_manage_keys") is True
    assert "viewer" in ROLES
