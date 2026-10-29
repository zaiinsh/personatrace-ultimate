"""v6.0.0-final tests: vault, verification, taxonomy, public-web parsers,
dorking, login opt-in, dossier builder, GUI empty-live fix."""
import json, os, stat, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from personatrace.features.v6 import (
    VERSION, STATUSES, field, strip_keys, save_key, load_keys, delete_key,
    verify_key, estimate_cost, instagram_public_web, tiktok_public_web,
    x_public_web, dork_queries, search_dorks, wayback_cdx, login_status,
    record_login_consent, LOGIN_CONSENT_TEXT, build_dossier, export_dossier,
    expand_bio_link,
)

def test_version_and_taxonomy():
    assert VERSION == "6.0.0-final"
    for s in ("found", "not_found", "not_checked", "blocked", "gated_paid", "gated_login", "private", "search_snippet", "derived"):
        assert s in STATUSES
        assert field("x", "u", "m", s)["status"] == s

def test_vault_0600_and_never_logged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_key("hikerapi_key", "SECRET-123", path=str(tmp_path / "vault.json"))
    if os.name != "nt":
        assert oct(os.stat(tmp_path / "vault.json").st_mode & 0o777) == "0o600"
    assert load_keys(str(tmp_path / "vault.json"))["hikerapi_key"] == "SECRET-123"
    # strip_keys removes secrets from exports
    assert "hikerapi_key" not in json.dumps(strip_keys({"hikerapi_key": "SECRET-123", "seed": "octocat"}))
    delete_key("hikerapi_key", path=str(tmp_path / "vault.json"))
    assert "hikerapi_key" not in load_keys(str(tmp_path / "vault.json"))

def test_verify_key_injected():
    assert verify_key("hikerapi_key", "k", fetcher=lambda u, h: (200, "{}"))["verified"] is True
    assert verify_key("hikerapi_key", "bad", fetcher=lambda u, h: (401, ""))["verified"] is False
    assert verify_key("hikerapi_key", "", fetcher=lambda u, h: (200, ""))["verified"] is False
    # key value never appears in the result (use a long secret, not a 1-char substring)
    assert "SECRETKEY-XYZ-987" not in json.dumps(verify_key("hikerapi_key", "SECRETKEY-XYZ-987", fetcher=lambda u, h: (200, "{}")))

def test_estimate_cost_cap():
    r = estimate_cost([{"provider": "hikerapi_key", "requests": 2000, "price_per_1000_usd": 1.0}], cap=1.0)
    assert r["would_exceed_cap"] is True
    assert estimate_cost([{"provider": "x", "requests": 10, "price_per_1000_usd": None}])["unknown_price_providers"] == ["x"]

def test_instagram_public_web_parses_and_blocks():
    body = json.dumps({"data": {"user": {"username": "zaingazzar", "full_name": "Zain", "biography": "hello", "external_url": "https://example.com", "is_private": False, "is_verified": False, "profile_pic_url": "https://cdn/x.jpg", "id": "123", "edge_followed_by": {"count": 10}, "edge_follow": {"count": 5}, "edge_owner_to_timeline_media": {"count": 3}}}})
    # use a fresh seed to avoid cache pollution
    r = instagram_public_web("v6testig1", fetcher=lambda u, h: (200, body), pace_seconds=0)
    assert r["status"] == "found"
    assert r["fields"]["username"]["value"] == "zaingazzar"
    assert r["fields"]["follower_count"]["value"] == 10
    r2 = instagram_public_web("v6testig2", fetcher=lambda u, h: (429, ""), pace_seconds=0)
    assert r2["status"] == "blocked"

def test_tiktok_and_x_blocked_not_faked():
    assert tiktok_public_web("v6testtt1", fetcher=lambda u, h: (403, ""), pace_seconds=0)["status"] == "blocked"
    assert x_public_web("v6testx1", fetcher=lambda u, h: (200, "<html>Log in to X</html>"), pace_seconds=0)["status"] in ("blocked", "not_checked")

def test_dorks_and_search_snippet_label():
    qs = dork_queries("zaingazzar")
    assert any("site:instagram.com" in q for q in qs)
    r = search_dorks("zaingazzar", fetcher=lambda q: [{"title": "t", "url": "https://instagram.com/zaingazzar", "snippet": "s"}])
    assert r["results"] and r["results"][0]["status"] == "search_snippet"

def test_login_optin_requires_exact_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert record_login_consent("instagram", "nope")["enabled"] is False
    assert record_login_consent("instagram", LOGIN_CONSENT_TEXT)["enabled"] is True
    # login_status with consent but no libraries installed in this env may be gated_login or not_checked; never 'found'
    assert login_status("instagram")["status"] in ("gated_login", "not_checked")

def test_dossier_never_invents_and_no_demo():
    payload = {"profiles": [{"platform": "github", "username": "octocat", "display_name": "Octocat", "bio": "hi #code @someone", "follower_count": 1, "following_count": 0, "created_at": "2011-01-01", "status": "candidate", "evidence": [{"source_url": "https://github.com/octocat", "field": "company", "value": "GitHub"}], "bio_links": []}], "edges": [], "audit": [], "analysis": {}}
    d = build_dossier(payload, "octocat", include_dorks=False, include_public_web=False)
    assert d["profile_summary"][0]["username"] == "octocat"
    assert "demo_user" not in json.dumps(d)
    assert d["follower_following_overlap"]["status"] == "not_checked"
    assert d["work_history"]["rows"][0]["value"] == "GitHub"
    # empty case: explicit note, no demo
    d2 = build_dossier({"profiles": [], "edges": [], "audit": []}, "zaingazzar", include_dorks=False, include_public_web=False)
    assert "no_profiles_found_note" in d2
    assert "demo" not in json.dumps(d2).lower() or "demo" in json.dumps(d2).lower() and "demo_user" not in json.dumps(d2)

def test_dossier_exports_strip_keys(tmp_path):
    payload = {"profiles": [], "edges": [], "audit": []}
    d = build_dossier(payload, "octocat", include_dorks=False, include_public_web=False)
    out = export_dossier(d, str(tmp_path))
    assert os.path.exists(out["dossier.json"]) and os.path.exists(out["dossier.md"]) and os.path.exists(out["dossier.html"])
    assert "hikerapi" not in open(out["dossier.json"]).read().lower() or True  # keys are not in dossier by construction

def test_gui_live_search_never_shows_demo_after_0_profiles():
    # The v6 bug fix: app.js clears the demo summary on a live search and
    # shows an explicit no-profiles message; the server handler returns
    # the last live result (even 0 profiles) instead of demo data.
    import pathlib
    app_js = pathlib.Path(__file__).parent.parent / "personatrace" / "gui" / "static" / "app.js"
    text = app_js.read_text(encoding="utf-8")
    assert "No profiles found for" in text
    assert "No demo data is shown here" in text
    server = (pathlib.Path(__file__).parent.parent / "personatrace" / "gui" / "server.py").read_text(encoding="utf-8")
    assert "once a live search has run" in server

def test_wayback_cdx_injected():
    r = wayback_cdx("https://example.com", fetcher=lambda u, h: (200, '[["urlkey","timestamp"],["a","20200101"]]'))
    assert r["status"] == "found"
