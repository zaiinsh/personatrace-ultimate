"""v7.0.0 tests: new seed types, key catalog, candidate queue, exports.
All network is mocked via injected fetchers — no live key required."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from personatrace import __version__
from personatrace.features.v7 import (
    VERSION, SEED_TYPES, validate_email, gravatar_hashes, gravatar_lookup,
    email_dorks, detect_seed_type, name_search, name_queries,
    parse_url_seed, url_seed_detail, image_seed_detail, hashtag_search,
    phrase_search, ip_seed_detail, providers_v7, maltego_csv,
    obsidian_folder, build_candidate_queue, investigate_seed,
    investigate_multi, build_v7_dossier, export_v7_dossier,
    INNOCENT_EXPLANATIONS,
)

def test_version():
    assert VERSION == "7.0.0"  # v7 module version; package __version__ moves with the newest release (v8 test asserts it)
    for t in ("email", "name", "url", "image", "hashtag", "phrase", "ip", "auto", "multi"):
        assert t in SEED_TYPES

def test_detect():
    assert detect_seed_type("someone@example.com") == "email"
    assert detect_seed_type("https://github.com/octocat") == "url"
    assert detect_seed_type("8.8.8.8") == "ip"
    assert detect_seed_type("#osint") == "hashtag"
    assert detect_seed_type("example.com") == "domain"
    assert detect_seed_type("hello world example") == "phrase"
    assert detect_seed_type("octocat") == "username"

def test_email_validate_and_hash():
    v = validate_email("  Test@Example.COM ")
    assert v["valid"] and v["domain"] == "example.com" and v["email"] == "test@example.com"
    assert not validate_email("not-an-email")["valid"]
    h = gravatar_hashes("test@example.com")
    assert len(h["md5"]) == 32 and len(h["sha256"]) == 64

def test_gravatar_mocked_found_and_404():
    body = json.dumps({"entry": [{"preferredUsername": "tester", "displayName": "Test User",
        "profileUrl": "https://gravatar.com/tester",
        "accounts": [{"url": "https://github.com/tester"}],
        "urls": [{"value": "https://example.com"}]}]})
    r = gravatar_lookup("test@example.com", fetcher=lambda u, h: (200, body))
    assert r["status"] == "found"
    assert r["fields"]["display_name"]["value"] == "Test User"
    assert "https://github.com/tester" in r["fields"]["linked_accounts"]["value"]
    assert r["fields"]["display_name"]["method"] == "public_api"
    r404 = gravatar_lookup("ghost@example.com", fetcher=lambda u, h: (404, ""))
    assert r404["status"] == "not_found"
    rbad = gravatar_lookup("nope", fetcher=lambda u, h: (200, body))
    assert rbad["status"] == "not_found"

def test_email_dorks_snippet_only():
    r = email_dorks("test@example.com", search_fetcher=lambda q: [{"title": "t", "url": "https://example.com/x", "snippet": "mail me"}])
    assert r["status"] == "search_snippet" and r["results"][0]["status"] == "search_snippet"
    assert r["query"] == '"test@example.com"'
    r2 = email_dorks("test@example.com")
    assert r2["status"] == "not_checked" and r2["results"] == []

def test_name_search_candidates_are_leads():
    r = name_search("Jane Example", context="Berlin, Acme",
                    search_fetcher=lambda q: [{"title": "Jane Example — Acme, Berlin", "url": "https://example.com/jane", "snippet": "Jane Example works at Acme in Berlin"}])
    assert r["status"] == "search_snippet" and r["candidates"]
    c = r["candidates"][0]
    assert c["confidence"] <= 79 and c["innocent_explanations"] == INNOCENT_EXPLANATIONS
    assert r["note"].lower().startswith("name results are candidates")
    assert name_search("single", search_fetcher=lambda q: [])["status"] == "not_found"

def test_url_parse():
    p = parse_url_seed("https://www.instagram.com/someuser/p/ABC123/")
    assert p["platform"] == "instagram" and p["username"] == "someuser" and p["kind"] == "post" and p["item_id"] == "ABC123"
    p2 = parse_url_seed("https://github.com/octocat")
    assert p2["platform"] == "github" and p2["username"] == "octocat" and p2["kind"] == "profile"
    p3 = parse_url_seed("https://www.tiktok.com/@creator/video/123")
    assert p3["username"] == "creator" and p3["kind"] == "post"
    assert parse_url_seed("not a url")["status"] == "not_found"
    d = url_seed_detail("https://instagram.com/someuser/p/ABC123/")
    assert d["fetch"]["status"] == "gated_paid"

def _png_bytes():
    # 1x1 PNG
    import base64
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

def test_image_seed_mocked():
    r = image_seed_detail("https://example.com/a.png", image_fetcher=lambda u: _png_bytes(),
                          collected_avatar_bytes=[_png_bytes()])
    assert r["status"] == "found" and r["download"]["status"] == "found"
    assert r["manual_reverse_links"]["google_lens"].startswith("https://lens.google.com")
    assert "face" in r["note"].lower()
    r2 = image_seed_detail("https://example.com/x.png", image_fetcher=lambda u: (_ for _ in ()).throw(Exception("HTTP 404")))
    assert r2["status"] == "not_checked"

def test_hashtag_mocked():
    def fetcher(url, headers):
        if "timelines/tag" in url:
            return 200, json.dumps([{"account": {"acct": "alice"}, "url": "https://mastodon.social/@alice/1", "created_at": "2026-01-01", "content": "<p>hi #osint</p>"}])
        return 200, json.dumps({"hits": []})
    r = hashtag_search("#osint", fetcher=fetcher)
    assert r["status"] == "found" and r["posts"][0]["author"] == "alice"
    assert r["accounts_using_it"][0]["status"] == "derived"

def test_phrase_mocked():
    def fetcher(url, headers):
        return 200, json.dumps({"hits": [{"author": "bob", "title": "the exact phrase here", "objectID": "1"}]})
    r = phrase_search("the exact phrase here", fetcher=fetcher, search_fetcher=lambda q: [])
    assert r["status"] == "found"

def test_ip_mocked():
    def fetcher(url, headers):
        return 200, json.dumps({"name": "GOOGLE", "handle": "NET-8-8-8-0", "country": "US", "entities": [{"handle": "GOOGL"}]})
    r = ip_seed_detail("8.8.8.8", fetcher=fetcher)
    # internetdb is skipped with injected fetcher; rdap must be found
    assert r["rdap"]["status"] == "found" and r["status"] == "found"
    assert ip_seed_detail("999.1.1.1", fetcher=fetcher)["status"] == "not_found"

def test_providers_v7_catalog():
    prov = providers_v7()
    for k in ("hikerapi_key", "youtube_api_key", "brave_search_key", "tavily_api_key",
              "serper_api_key", "serpapi_key", "google_pse_key", "shodan_api_key",
              "virustotal_api_key", "securitytrails_api_key", "urlscan_api_key",
              "tineye_api_key", "bing_visual_search_key", "email_verification_key",
              "openai_api_key", "github_token", "licensed_aggregator_key"):
        assert k in prov and prov[k]["unlocks"]
    assert "never" in prov["email_verification_key"]["unlocks"].lower() or "only" in prov["email_verification_key"]["unlocks"].lower()

def test_dispatch_email_mocked(monkeypatch):
    monkeypatch.setenv("PERSONATRACE_DEMO", "1")
    body = json.dumps({"entry": [{"preferredUsername": "tester", "displayName": "Test User", "profileUrl": "https://gravatar.com/tester", "accounts": [], "urls": []}]})
    inv, section = investigate_seed("test@example.com", "email",
                                    fetcher=lambda u, h: (200, body),
                                    search_fetcher=lambda q: [])
    assert inv.seed_type == "email" and inv.seed == "test@example.com"
    assert section["gravatar"]["status"] == "found"
    assert any(p.platform == "gravatar" for p in inv.profiles)

def test_dispatch_name_and_hashtag_mocked():
    inv, section = investigate_seed("Jane Example", "name", context="Berlin",
                                    search_fetcher=lambda q: [{"title": "Jane Example Berlin", "url": "https://example.com/j", "snippet": "Jane Example Berlin"}])
    assert inv.seed_type == "name" and section["name"]["candidates"]
    def fetcher(url, headers):
        if "timelines/tag" in url:
            return 200, json.dumps([{"account": {"acct": "alice"}, "url": "https://mastodon.social/@alice/1", "content": "x"}])
        return 200, json.dumps({"hits": []})
    inv2, section2 = investigate_seed("#osint", "hashtag", fetcher=fetcher)
    assert inv2.seed_type == "hashtag" and any(p.username == "alice" for p in inv2.profiles)

def test_multi_seed_mocked(monkeypatch):
    monkeypatch.setenv("PERSONATRACE_DEMO", "1")
    body = json.dumps({"entry": [{"preferredUsername": "t", "displayName": "T", "profileUrl": "https://gravatar.com/t", "accounts": [], "urls": []}]})
    inv, section = investigate_multi("test@example.com; 8.8.8.8",
                                     fetcher=lambda u, h: (200, body) if "gravatar" in u else (200, json.dumps({"name": "X", "entities": []})),
                                     search_fetcher=lambda q: [])
    assert inv.seed_type == "multi"
    assert "test@example.com" in section["sub_seeds"]

def test_v7_dossier_queue_and_exports(tmp_path):
    payload = {"profiles": [], "edges": [], "audit": [], "possible_matches": []}
    section = {"seed_type_resolved": "name",
               "name": {"status": "search_snippet", "candidates": [
                   {"title": "Jane Example", "url": "https://example.com/j", "confidence": 60,
                    "status": "search_snippet", "reasons": ["name in snippet"], "innocent_explanations": INNOCENT_EXPLANATIONS}]}}
    d = build_v7_dossier(payload, "Jane Example", seed_type="name", v7_section=section, include_dorks=False)
    assert d["version"] == "7.0.0"
    assert d["candidate_review_queue"] and d["candidate_review_queue"][0]["kind"] == "name_candidate"
    assert "Jane Example" in maltego_csv(d)
    paths = export_v7_dossier(d, str(tmp_path))
    assert os.path.exists(paths["maltego.csv"]) and os.path.exists(paths["obsidian_index"])
    assert os.path.exists(paths["dossier.json"])

def test_gui_v7_seed_selector():
    import pathlib
    html = (pathlib.Path(__file__).parent.parent / "personatrace" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    for opt in ('value="email"', 'value="name"', 'value="url"', 'value="image"', 'value="hashtag"', 'value="ip"', 'value="auto"'):
        assert opt in html
    # Header carries the newest release version (v8 test asserts it);
    # this v7 test keeps asserting the v7 seed options it introduced.
    server = (pathlib.Path(__file__).parent.parent / "personatrace" / "gui" / "server.py").read_text(encoding="utf-8")
    assert '"email"' in server and "investigate_seed" in server
