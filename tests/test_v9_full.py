"""PersonaTrace v9 tests — the 16 no-key items.

All network is mocked through injectable fetchers, except the marked
screenshot fallback test (mocked Playwright factory) — CI needs no
browser and no network. Live proofs live in V9_CHECKLIST.md /
BENCHMARK.md, not here.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from personatrace import __version__  # noqa: E402
from personatrace.features.v9 import (  # noqa: E402
    VERSION, SITE_ADAPTERS_V9, free_search_chain_v9, name_search_v9,
    name_api_candidates, dork_v9, site_adapter_fetch, site_adapters_v9,
    check_site_two_signal, site_check_audit, disk_cache_get, disk_cache_put,
    github_profile_cached, wayback_snapshots_v9, crtsh_v9, dns_lookup_v9,
    run_fingerprint, diff_fingerprints, capture_screenshots,
    youtube_video_id, youtube_captions, whisper_status,
    video_transcripts_v9, local_nlp, detect_language,
    run_parallel_timed, graph_levels_real, investigate_v9,
    build_v9_dossier,
)

GH_USER = {"login": "octocat", "name": "The Octocat", "bio": "GitHub mascot",
           "blog": "https://github.blog", "followers": 100, "following": 9,
           "created_at": "2011-01-25T18:44:36Z", "avatar_url": "https://avatars.example/octo.png",
           "html_url": "https://github.com/octocat", "company": "@github", "location": "San Francisco"}


def test_version_v9():
    assert VERSION == "9.0.0" and __version__ == "9.0.0"


# ---------------------------------------------------------- #1 search chain
def _searx_ok(url, headers):
    if "format=json" in url:
        return 200, {"results": [{"title": "Barack Obama — GitHub", "url": "https://github.com/barackobama",
                                  "content": "Barack Obama on GitHub"}]}
    return 404, ""


def test_chain_searxng_first():
    out = free_search_chain_v9('"Barack Obama"', fetcher=_searx_ok)
    assert out["status"] == "search_snippet" and out["engine"] == "searxng"
    assert out["results"][0]["status"] == "search_snippet"
    assert out["results"][0]["engine"] == "searxng"


def test_chain_falls_to_ddg_lite():
    def fetch(url, headers):
        if "lite.duckduckgo.com" in url:
            return 200, '<a class="result-link" href="https://example.com/obama">Obama page</a>'
        return 404, ""
    out = free_search_chain_v9("Barack Obama", fetcher=fetch)
    assert out["engine"] == "duckduckgo_lite" and out["results"][0]["url"] == "https://example.com/obama"
    assert out["engines_tried"][:2] == ["searxng", "duckduckgo_lite"]


def test_chain_bing_and_all_fail():
    def fetch(url, headers):
        if "bing.com" in url:
            return 200, '<li class="b_algo"><h2><a href="https://ex.com/a">A title</a></h2><p>snip text</p></li>'
        return 404, ""
    out = free_search_chain_v9("q", fetcher=fetch)
    assert out["engine"] == "bing_html" and out["results"][0]["snippet"] == "snip text"
    out2 = free_search_chain_v9("q", fetcher=lambda u, h: (404, ""))
    assert out2["status"] == "not_checked" and out2["results"] == []


def test_name_search_v9_candidates_capped_and_reviewable():
    def fetch(url, headers):
        if "api.github.com/search/users" in url:
            return 200, {"items": [{"login": "barackobama", "html_url": "https://github.com/barackobama"}]}
        if "gitlab.com/api/v4/users" in url:
            return 200, [{"username": "barack", "name": "Barack Obama", "web_url": "https://gitlab.com/barack"}]
        if "format=json" in url:
            return 200, {"results": [{"title": "Barack Obama", "url": "https://example.com/obama", "content": "Barack Obama, Chicago"}]}
        return 404, ""
    out = name_search_v9("Barack Obama", context="Chicago", fetcher=fetch)
    assert out["status"] == "search_snippet" and len(out["candidates"]) >= 3
    for c in out["candidates"]:
        assert c["confidence"] <= 79 and c["innocent_explanations"]
        assert c["review_status"] == "pending"
    assert any(c.get("source") == "github_user_search_api" for c in out["candidates"])


def test_name_api_candidates():
    def fetch(url, headers):
        if "api.github.com" in url:
            return 200, {"items": [{"login": "torvalds", "html_url": "https://github.com/torvalds"}]}
        if "gitlab.com" in url:
            return 200, []
        return 404, ""
    out = name_api_candidates("Linus Torvalds", fetcher=fetch)
    assert len(out) == 1 and out[0]["platform"] == "github"


def test_dork_v9_uses_chain():
    def fetch(url, headers):
        if "bing.com" in url:
            return 200, '<li class="b_algo"><h2><a href="https://ex.com/e">Mail</a></h2><p>a@b.com found</p></li>'
        return 404, ""
    out = dork_v9(['"a@b.com"'], fetcher=fetch)
    assert out["status"] == "search_snippet"
    assert out["results"][0]["engine"] == "bing_html"


def test_investigate_v9_name_seed():
    inv, v7, v8, v9 = investigate_v9("Barack Obama", "name", fetcher=_searx_ok, use_cache=False)
    assert v9["name"]["candidates"]
    assert inv.seed_type == "name"


# ---------------------------------------------------------- #3 site adapters
def test_site_adapter_classification_24():
    assert len(SITE_ADAPTERS_V9) == 24
    counts = {}
    for e in SITE_ADAPTERS_V9:
        counts[e["classification"]] = counts.get(e["classification"], 0) + 1
        if e["classification"] == "presence_only":
            assert e["route"].startswith("none"), e["service"]
    assert counts == {"data_adapter": 9, "meta_adapter": 7, "presence_only": 8}


def test_devto_adapter_mocked():
    def fetch(url, headers):
        if "dev.to/api" in url:
            return 200, {"username": "ben", "name": "Ben Halpern", "summary": "Forem co-founder",
                         "twitter_username": "bendhalpern", "github_username": "benhalpern",
                         "website_url": "https://benhalpern.com"}
        return 404, ""
    r = site_adapter_fetch("devto", "ben", fetcher=fetch)
    assert r["status"] == "found" and r["classification"] == "data_adapter"
    assert r["profile"]["display_name"] == "Ben Halpern"


def test_oembed_and_presence_adapters_mocked():
    def fetch(url, headers):
        if "oembed" in url:
            return 200, {"author_name": "Some Artist", "title": "Profile", "author_url": "https://soundcloud.com/someartist"}
        return 404, "not found"
    r = site_adapter_fetch("soundcloud", "someartist", fetcher=fetch)
    assert r["status"] == "found" and r["profile"]["display_name"] == "Some Artist"
    r2 = site_adapter_fetch("quora", "whoever", fetcher=lambda u, h: (404, "page not found"))
    assert r2["classification"] == "presence_only" and r2["status"] == "not_found"


def test_site_adapters_v9_batch_mocked():
    out = site_adapters_v9("octocat", fetcher=lambda u, h: (404, "not found"),
                           services=["devto", "lemmy", "quora"])
    assert out["count"] == 3 and out["classifications"]["devto"] == "data_adapter"


# ---------------------------------------------------------- #4 two-signal
_PAGE_FOUND = ('<html><head><meta property="og:title" content="octocat on GitHub">'
               '<meta property="og:image" content="https://x/y.png"></head>'
               '<body>octocat profile page</body></html>')


def test_two_signal_verdicts():
    ent = {"service": "github", "url": "https://github.com/{u}"}
    r = check_site_two_signal(ent, "octocat", fetcher=lambda u, h: (200, _PAGE_FOUND))
    assert r["status"] == "found"
    r = check_site_two_signal(ent, "octocat", fetcher=lambda u, h: (404, "nope"))
    assert r["status"] == "not_found"
    r = check_site_two_signal(ent, "octocat", fetcher=lambda u, h: (200, _PAGE_FOUND + " page not found"))
    assert r["status"] == "uncertain"  # signals disagree — never found
    r = check_site_two_signal(ent, "octocat", fetcher=lambda u, h: (200, "Sorry, this page could not be found"))
    assert r["status"] == "not_found"
    r = check_site_two_signal(ent, "octocat", fetcher=lambda u, h: (403, "captcha"))
    assert r["status"] == "blocked"


def test_site_check_audit_mocked():
    def fetch(url, headers):
        if "pt-no-such-user" in url:
            return 404, "not found"
        return 200, _PAGE_FOUND
    out = site_check_audit(fetcher=fetch, sites=["github", "dev.to"])
    assert out["false_positives"] == 0 and out["false_negatives"] == 0
    assert out["sampled_sites"] == 2 and out["checks_run"] == 4


# ---------------------------------------------------------- #5 cache + routes
def test_disk_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONATRACE_CACHE_DIR", str(tmp_path))
    assert disk_cache_put("k1", {"a": 1})
    payload, age = disk_cache_get("k1")
    assert payload == {"a": 1} and age is not None and age < 5
    payload2, _ = disk_cache_get("k1", ttl_seconds=-1)
    assert payload2 is None  # expired entries are not served


def test_github_cached_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONATRACE_CACHE_DIR", str(tmp_path / "c"))
    ok = github_profile_cached("octocat", fetcher=lambda u, h: (200, json.dumps(GH_USER)), sleeper=lambda s: None)
    assert ok["status"] == "found" and ok["route"] == "github_api"
    down = github_profile_cached("octocat", fetcher=lambda u, h: (403, "rate limited"), sleeper=lambda s: None)
    assert down["status"] == "found" and down["route"] == "disk_cache"
    assert "cache_age_seconds" in down


def test_wayback_and_crtsh_and_dns_v9(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONATRACE_CACHE_DIR", str(tmp_path / "c2"))
    def fetch(url, headers):
        if "web.archive.org" in url:
            return 200, json.dumps([["timestamp", "original"], ["20200101000000", "https://github.com/octocat"]])
        if "crt.sh" in url:
            return 200, [{"name_value": "a.example.com\nb.example.com"}]
        if "cloudflare-dns.com" in url:
            return 200, {"Answer": [{"type": 1, "data": "93.184.216.34"}]}
        return 404, ""
    w = wayback_snapshots_v9("https://github.com/octocat", fetcher=fetch)
    assert w["status"] == "found" and w["route"] == "wayback_cdx"
    c = crtsh_v9("example.com", fetcher=fetch)
    assert c["status"] == "found" and "a.example.com" in c["names"]
    import socket as _sock
    orig = _sock.getaddrinfo
    _sock.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(OSError("no dns"))
    try:
        d = dns_lookup_v9("example.com", fetcher=fetch)
    finally:
        _sock.getaddrinfo = orig
    assert d["status"] == "found" and d["route"] == "cloudflare_doh"


def test_fingerprint_and_diff():
    fp_a = run_fingerprint([{"platform": "github", "username": "octocat", "status": "candidate"}])
    fp_b = run_fingerprint([{"platform": "github", "username": "octocat", "status": "candidate"}])
    assert fp_a["sha256"] == fp_b["sha256"]
    audit_a = [{"action": "adapter_search", "detail": {"platform": "github", "status": "ok"}}]
    audit_b = [{"action": "adapter_search", "detail": {"platform": "github", "status": "degraded"}}]
    fp_c = run_fingerprint([{"platform": "gitlab", "username": "octocat", "status": "candidate"}])
    d = diff_fingerprints(fp_a, fp_c, audit_a=audit_a, audit_b=audit_b)
    assert d["match"] is False and d["changed_source_statuses"][0]["platform"] == "github"


# ---------------------------------------------------------- #6 screenshots
class _FakePage:
    def goto(self, url, timeout=None, wait_until=None):
        self.url = url
    def wait_for_timeout(self, ms):
        pass
    def screenshot(self, path=None):
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes" * 10)


class _FakeBrowser:
    def new_context(self, viewport=None, ignore_https_errors=None):
        return self
    def new_page(self, viewport=None):
        return _FakePage()
    def close(self):
        pass


class _FakePW:
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    @property
    def firefox(self):
        class _FF:
            @staticmethod
            def launch():
                return _FakeBrowser()
        return _FF()


def test_screenshots_mocked_playwright(tmp_path):
    out = capture_screenshots(["https://github.com/octocat"], str(tmp_path),
                              playwright_factory=lambda: _FakePW())
    assert out["status"] == "found" and out["proof_type"] == "browser_screenshot"
    row = out["screenshots"][0]
    assert row["sha256"] and row["bytes"] > 50 and os.path.isfile(row["path"])


def test_screenshots_unavailable_fallback():
    def boom():
        raise ImportError("no playwright")
    out = capture_screenshots(["https://github.com/octocat"], "/tmp/pt_shots_x",
                              playwright_factory=boom)
    assert out["status"] == "not_available" and out["proof_type"] == "snapshot_card"


# ---------------------------------------------------------- #7 transcription
def test_youtube_captions_mocked():
    assert youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    watch = ('"captionTracks":[{"baseUrl":"https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ\\u0026lang=en",'
             '"languageCode":"en"}]')
    def fetch(url, headers):
        if "youtube.com/watch" in url:
            return 200, watch
        if "timedtext" in url:
            return 200, {"events": [{"segs": [{"utf8": "Hello "}, {"utf8": "world"}]}]}
        return 404, ""
    r = youtube_captions("dQw4w9WgXcQ", fetcher=fetch)
    assert r["status"] == "found" and r["transcript"] == "Hello world"
    assert r["source"] == "youtube_captions" and r["language"] == "en"


def test_transcripts_no_fake_and_whisper_status():
    out = video_transcripts_v9([{"url": "https://vimeo.com/123", "platform": "vimeo"}],
                               fetcher=lambda u, h: (404, ""))
    assert out["status"] == "not_checked"
    ws = whisper_status()
    assert ws["status"] in ("available", "not_installed")


# ---------------------------------------------------------- #8 local NLP
def test_local_nlp_pack():
    r = local_nlp(["Linus Torvalds created Linux in Helsinki and lives in the United States.",
                   "Octocat works at GitHub Inc in San Francisco. Security researcher and python developer from Pakistan."])
    assert "Linus Torvalds" in r["persons"]
    assert "GitHub Inc" in r["organisations"]
    assert "San Francisco" in r["places"] and "Pakistan" in r["places"]
    assert r["topics"].get("security", 0) >= 1 and r["topics"].get("web_dev", 0) >= 1
    assert r["engine"].startswith("built-in") or r["spacy"]["used"]
    assert detect_language("Bonjour, ceci est un test de la langue française dans le monde") == "fr"
    assert detect_language("یہ ایک اردو جملہ ہے اور یہ پاکستان سے ہے") == "ur"
    assert detect_language("El perro come en la casa de la playa con los niños") == "es"


# ---------------------------------------------------------- #9 timed parallel
class _FakeAdapter:
    def __init__(self, platform, delay=0.0):
        self.platform = platform
        self.name = platform
        self.delay = delay
    def status(self, keys):
        return "active"
    def search(self, seed, keys):
        from personatrace.adapters.base import AdapterResult
        if self.delay:
            time.sleep(self.delay)
        return AdapterResult(profiles=[], status="ok", message="")


def test_parallel_timed_timeout():
    adapters = [_FakeAdapter("fast"), _FakeAdapter("slow", delay=3.0)]
    inv, timing = run_parallel_timed("octocat", parallel=2, time_budget=1,
                                     adapters=adapters, progress=False, analyse=False)
    assert timing["timed_out_adapters"] == ["slow"]
    statuses = {r["detail"]["platform"]: r["detail"]["status"] for r in inv.audit
                if r.get("action") == "adapter_search"}
    assert statuses.get("slow") == "degraded_timeout"
    assert timing["wall_seconds"] < 8


# ---------------------------------------------------------- #10 graph real
def test_graph_levels_real_mocked():
    def fetch(url, headers):
        if url.endswith("/followers?per_page=100"):
            return 200, [{"login": "a1"}, {"login": "a2"}]
        if url.endswith("/following?per_page=100"):
            return 200, [{"login": "a2"}, {"login": "a3"}]
        for login in ("a1", "a2", "a3"):
            if url.endswith(f"/users/{login}"):
                blog = "https://shared.example.com" if login in ("a1", "a2") else "https://other.example.org"
                return 200, {"login": login, "blog": blog, "followers": 1, "following": 1,
                             "html_url": f"https://github.com/{login}"}
        return 404, ""
    out = graph_levels_real("anchor", fetcher=fetch)
    assert out["status"] == "found"
    assert out["level_counts"]["3"] == 3
    assert out["level_counts"]["4"] == 1
    assert out["shared_domains"] == ["shared.example.com"]


# ---------------------------------------------------------- dossier + GUI
def test_build_v9_dossier_minimal():
    payload = {"case_id": "c1", "seed": "octocat", "seed_type": "username",
               "profiles": [], "edges": [], "possible_matches": [], "alerts": [],
               "audit": [], "timeline": [], "notes": [], "checklist": []}
    d = build_v9_dossier(payload, "octocat", seed_type="username", keys={},
                         include_dorks=False)
    assert d["version"] == "9.0.0"
    assert "run_fingerprint" in d and "v9" in d


def test_gui_v9_static_and_i18n():
    import pathlib
    root = pathlib.Path(__file__).parent.parent / "personatrace" / "gui"
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert "v9.0.0" in html and 'id="lang-select"' in html
    assert 'id="live-screenshots"' in html and 'id="live-cache"' in html
    assert 'id="live-direct"' in html and 'value="profile"' in html
    i18n = json.loads((root / "static" / "i18n.json").read_text(encoding="utf-8"))
    langs = i18n["strings"]
    assert i18n["languages"] == ["en", "ur", "ar", "es", "fr", "de"]
    en_keys = set(langs["en"])
    assert len(en_keys) >= 50
    for code, strings in langs.items():
        assert set(strings) == en_keys, code
    assert set(i18n["rtl"]) == {"ur", "ar"}
    import re as _re
    html_keys = set(_re.findall(r'data-i18n(?:-placeholder)?="([a-z_]+)"', html))
    assert html_keys <= en_keys and len(html_keys) >= 50
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")
    assert 'dir="rtl"' in css or '[dir="rtl"]' in css
    server = (root / "server.py").read_text(encoding="utf-8")
    assert "investigate_v9" in server and "/api/v9/info" in server
    js = (root / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "localStorage" in js and "pt-lang" in js
