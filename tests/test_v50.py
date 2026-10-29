"""Tests for PersonaTrace v5.0 — the 10/10 improvements."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from personatrace.features.v5 import (
    check_keys, error_next_step, load_official_lists, parallel_map,
    redact_text, register_case, search_cases, sign_chain, verify_chain,
    sherlock_templates, resume_targets, retention_cleanup,
)

def test_key_wizard_check():
    out = check_keys({})
    assert any(r["key"] == "youtube_api_key" and not r["present"] for r in out)
    out2 = check_keys({"youtube_api_key": "x"})
    assert any(r["key"] == "youtube_api_key" and r["present"] for r in out2)

def test_error_next_steps():
    assert "add the key" in error_next_step("not_checked", "youtube").lower()
    assert "resume" in error_next_step("degraded", "github").lower()
    assert "private" in error_next_step("private_terminal", "instagram").lower()

def test_signed_chain():
    chain = sign_chain([{"a": 1}, {"b": 2}], "test-key")
    assert verify_chain(chain, "test-key") is True
    chain[0]["item"]["a"] = 99
    assert verify_chain(chain, "test-key") is False

def test_case_management(tmp_path):
    register_case(str(tmp_path), "octocat", "out1", tags=["test"], note="n")
    found = search_cases(str(tmp_path), query="octocat")
    assert len(found) == 1
    assert search_cases(str(tmp_path), tag="nope") == []

def test_redact_and_parallel():
    assert "[EMAIL REDACTED]" in redact_text("contact me at a@b.com please")
    res = parallel_map(lambda x: x * 2, [1, 2, 3], max_workers=2)
    assert sorted(v for _, v in res) == [2, 4, 6]
    assert resume_targets({"audit": [{"action": "adapter_search", "detail": {"adapter": "github", "status": "degraded"}}]}) == ["github"]

def test_official_lists():
    # Files are shipped in the app root; test from repo root if present
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    out = load_official_lists(str(root))
    assert out["sherlock"] >= 400
    assert out["whatsmyname"] >= 600
    assert len(sherlock_templates(str(root))) >= 400
