"""v8.0.0 tests: Direct Profile Mode + the 29 listed upgrades.
All network is mocked via injected fetchers / monkeypatching — no
live key is required and no real key route is claimed as proven."""
import io, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from personatrace import __version__
from personatrace.features import v8
from personatrace.features.v8 import (
    VERSION, SEED_TYPES_V8, github_profile_fetch, github_web_fallback,
    github_id_sets, follower_overlap, gated_full_fetch,
    stories_highlights_section, verify_all_keys, name_search_v8,
    free_search_chain, run_parallel_investigation, SITE_CHECKS_V8,
    site_presence_checks, company_seed, gravatar_linked_leads,
    score_pair_v8, variations_v8, apply_comment_limit, video_section,
    photo_variant_check, archive_diff, send_watch_alert, graph_levels,
    coordinated_v8, behaviour_v8, impersonation_finder, scam_signals,
    validate_wallet, wallet_seed, plate_seed, set_case_team,
    court_report, proof_card_png, build_proof_folder, offline_rebuild,
    fetch_direct_profile, investigate_direct_profile, parse_profile_url,
    GATED_FIELDS_REQUESTED,
)

GH_USER = {"login": "octocat", "name": "The Octocat", "bio": "GitHub mascot",
           "blog": "https://github.blog", "followers": 100, "following": 9,
           "created_at": "2011-01-25T18:44:36Z", "avatar_url": "https://avatars.example/o.png",
           "html_url": "https://github.com/octocat", "company": "@github", "location": "SF"}
OG_HTML = """<html><head><title>The Octocat · GitHub</title>
<meta property="og:title" content="The Octocat">
<meta property="og:description" content="GitHub mascot bio">
<meta property="og:image" content="https://avatars.example/o.png">
</head><body>hi</body></html>"""
NO_SLEEP = lambda s: None


def test_version_and_seed_types():
    assert VERSION == "8.0.0"  # v8 module version; package __version__ moves with the newest release (v9 test asserts it)
    for t in ("profile", "company", "wallet", "plate"):
        assert t in SEED_TYPES_V8


# ---------------------------------------------------------- #1 + #2 GitHub
def test_github_api_ok():
    r = github_profile_fetch("octocat", fetcher=lambda u, h: (200, json.dumps(GH_USER)), sleeper=NO_SLEEP)
    assert r["status"] == "found" and r["route"] == "github_api"
    assert r["follower_count"] == 100 and r["display_name"] == "The Octocat"


def test_github_403_retries_then_web_fallback():
    calls = {"api": 0}
    def fetch(u, h):
        if "api.github.com" in u:
            calls["api"] += 1
            return 403, ""
        return 200, OG_HTML
    r = github_profile_fetch("octocat", fetcher=fetch, sleeper=NO_SLEEP)
    assert calls["api"] == 3  # initial + 2 backoff retries
    assert r["status"] == "found" and r["route"] == "github_web_fallback" and r["derived"]
    assert r["display_name"] == "The Octocat" and r["follower_count"] is None


def test_github_both_routes_fail_is_degraded_not_faked():
    r = github_profile_fetch("octocat", fetcher=lambda u, h: (403, ""), sleeper=NO_SLEEP)
    assert r["status"] == "degraded" and r["route"] is None


def test_github_404_is_not_found():
    r = github_profile_fetch("ghost", fetcher=lambda u, h: (404, ""), sleeper=NO_SLEEP)
    assert r["status"] == "not_found"


def test_github_adapter_403_web_fallback(monkeypatch):
    import urllib.error, urllib.request
    from personatrace.adapters.free import GitHubAdapter
    monkeypatch.delenv("PERSONATRACE_DEMO", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    class Resp:
        def __init__(self, body, status=200):
            self._b = body.encode(); self.status = status
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._b
        def geturl(self): return "https://github.com/octocat"

    def fake_urlopen(req, timeout=None):
        if "api.github.com" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return Resp(OG_HTML)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    res = GitHubAdapter().search("octocat", {})
    assert res.status == "ok" and len(res.profiles) == 1
    assert "fallback" in res.message and res.profiles[0].evidence[0].method == "public_web"


def test_github_adapter_uses_token_header(monkeypatch):
    import urllib.request
    from personatrace.adapters.free import GitHubAdapter
    monkeypatch.delenv("PERSONATRACE_DEMO", raising=False)
    seen = {}
    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(GH_USER).encode()
    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.headers.get("Authorization")
        return Resp()
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    res = GitHubAdapter().search("octocat", {"github_token": "tok123"})
    assert res.status == "ok" and seen["auth"] == "Bearer tok123"
    assert "tok123" not in res.message


# ------------------------------------------------------- #1 direct profile
def test_direct_github_anchor(monkeypatch):
    section, prof = fetch_direct_profile(
        "https://github.com/octocat",
        fetcher=lambda u, h: (200, json.dumps(GH_USER)), sleeper=NO_SLEEP)
    assert section["status"] == "found" and section["fetch_route"] == "github_api"
    assert prof is not None and prof.status == "confirmed_anchor"
    assert section["snapshot"]["sha256"] and len(section["snapshot"]["sha256"]) == 64
    assert "confirmed_anchor" in section["anchor_semantics"]


def test_direct_unknown_host_not_blank():
    section, prof = fetch_direct_profile(
        "https://profiles.example.net/users/jane",
        fetcher=lambda u, h: (200, OG_HTML), sleeper=NO_SLEEP)
    assert section["status"] == "found" and section["fetch_route"] == "generic_web"
    assert section["fetched"]["display_name"] == "The Octocat"


def test_direct_post_instagram_mocked():
    section, prof = fetch_direct_profile(
        "https://www.instagram.com/someuser/p/ABC123/",
        fetcher=lambda u, h: (200, OG_HTML), sleeper=NO_SLEEP)
    assert section["parsed"]["kind"] == "post" and section["parsed"]["item_id"] == "ABC123"
    assert section["post_item"]["status"] == "found" and section["post_item"]["sha256"]
    assert "NOT fetched" in section["post_item"]["note"]


def test_direct_post_blocked():
    section, prof = fetch_direct_profile(
        "https://www.instagram.com/someuser/p/ABC123/",
        fetcher=lambda u, h: (403, ""), sleeper=NO_SLEEP)
    assert section["post_item"]["status"] == "blocked"
    assert section["fetch_status"] in ("blocked", "gated_paid")


def test_direct_profile_mode_anchors_and_expands(monkeypatch):
    from personatrace.core.models import Investigation
    fake_inv = Investigation(case_id="case_x", seed="octocat", seed_type="username")
    monkeypatch.setattr(v8, "run_parallel_investigation", lambda *a, **k: fake_inv)
    # A fetcher is injected here, so the expansion branch calls the
    # engine directly — stub it too so no live network runs.
    monkeypatch.setattr("personatrace.core.engine.run_investigation", lambda *a, **k: fake_inv)
    inv, section = investigate_direct_profile(
        "https://github.com/octocat",
        fetcher=lambda u, h: (200, json.dumps(GH_USER)), sleeper=NO_SLEEP)
    assert inv.seed_type == "profile"
    anchors = [p for p in inv.profiles if p.status == "confirmed_anchor"]
    assert len(anchors) == 1 and anchors[0].platform == "github"
    assert section["direct_profile"]["fetch_route"] == "github_api"


def test_parse_profile_url_gitlab():
    p = parse_profile_url("https://gitlab.com/someuser")
    assert p["platform"] == "gitlab" and p["username"] == "someuser"


# ------------------------------------------------------------- #3 verify
def test_verify_keys_none(monkeypatch):
    for name in ("HIKERAPI_KEY", "YOUTUBE_API_KEY", "BRAVE_SEARCH_KEY", "TAVILY_API_KEY",
                 "SERPER_API_KEY", "GITHUB_TOKEN", "SHODAN_API_KEY", "SERPAPI_KEY",
                 "GOOGLE_PSE_KEY", "VIRUSTOTAL_API_KEY", "SECURITYTRAILS_API_KEY",
                 "URLSCAN_API_KEY", "TINEYE_API_KEY", "BING_VISUAL_SEARCH_KEY",
                 "EMAIL_VERIFICATION_KEY", "OPENAI_API_KEY", "PERSONATRACE_AGGREGATOR_KEY"):
        monkeypatch.delenv(name, raising=False)
    r = verify_all_keys({})
    assert r["status"] == "not_checked"
    assert all(row["status"] == "not_checked" for row in r["providers"])


def test_verify_keys_verified_and_unverified(monkeypatch):
    r = verify_all_keys({"github_token": "tok", "tavily_api_key": "tv"},
                        fetcher=lambda u, h: (200, "{}"))
    by = {row["provider"]: row["status"] for row in r["providers"]}
    assert by["github_token"] == "verified"
    assert by["tavily_api_key"] == "present_unverified"
    r2 = verify_all_keys({"github_token": "bad"}, fetcher=lambda u, h: (401, ""))
    by2 = {row["provider"]: row["status"] for row in r2["providers"]}
    assert by2["github_token"] == "invalid"


# ---------------------------------------------------------- #4 + #16 gated
def test_gated_full_fetch_no_key():
    r = gated_full_fetch("instagram", "someuser", keys={})
    assert r["status"] == "not_checked" and "stories" in r["fields_requested"]
    assert stories_highlights_section("instagram", "someuser", keys={})["status"] == "gated_paid"


def test_gated_full_fetch_mocked_key():
    keys = {"licensed_aggregator_key": "k", "licensed_aggregator_base_url": "https://agg.example"}
    body = {"username": "someuser", "display_name": "Some User", "followers_count": 5,
            "posts": [{"id": 1, "text": "hi"}], "comments": [{"text": "yo"}],
            "stories": [{"id": "s1"}], "highlights": []}
    seen = {}
    def fetch(u, h):
        seen["url"] = u
        return 200, json.dumps(body)
    r = gated_full_fetch("instagram", "someuser", keys=keys, fetcher=fetch)
    assert r["status"] == "found" and len(r["posts"]) == 1 and len(r["comments"]) == 1
    assert "include=" in seen["url"] and "stories" in seen["url"]
    sh = stories_highlights_section("instagram", "someuser", keys=keys, fetcher=fetch)
    assert sh["status"] == "found" and len(sh["stories"]) == 1


# ---------------------------------------------------------------- #5 name
def test_name_search_free_chain():
    ddg = ('<a class="result__a" href="https://duckduckgo.com/l/?uddg='
           'https%3A%2F%2Fexample.com%2Fjane&rut=1">Jane Example — Acme Berlin</a>')
    def fetch(u, h):
        if "duckduckgo" in u:
            return 200, ddg
        return 503, ""
    r = name_search_v8("Jane Example", context="Berlin", fetcher=fetch)
    assert r["engine_chain"] == ["searxng_public", "duckduckgo_html"]
    assert r["candidates"] and r["candidates"][0]["status"] == "search_snippet"
    assert r["candidates"][0]["confidence"] <= 79
    assert free_search_chain("anything", fetcher=fetch)


# ------------------------------------------------------------- #6 parallel
def test_parallel_investigation(monkeypatch):
    monkeypatch.setenv("PERSONATRACE_DEMO", "1")
    from personatrace.adapters.base import AdapterResult

    class Fake:
        def __init__(self, plat): self.platform = plat; self.name = plat
        def status(self, keys): return "active"
        def search(self, seed, keys): return AdapterResult(profiles=[], status="ok", message="fake")
    inv = run_parallel_investigation("octocat", adapters=[Fake("a1"), Fake("a2"), Fake("a3")],
                                     parallel=3, progress=False)
    searched = [a for a in inv.audit if a.get("action") == "adapter_search"]
    assert len(searched) == 3


# --------------------------------------------------------- #7 site checks
def test_site_checks_v8_count_and_live_mock():
    assert len(SITE_CHECKS_V8) == 24
    services = {e["service"] for e in SITE_CHECKS_V8}
    for s in ("lemmy", "medium", "substack", "devto", "twitch", "steam", "strava", "angellist"):
        assert s in services
    r = site_presence_checks("octocat")
    assert r["count"] == 24 and all(c["status"] == "presence_check_only" for c in r["checks"])
    r2 = site_presence_checks("octocat", live=True, fetcher=lambda u, h: (404, ""))
    assert all(c["status"] == "not_found" for c in r2["checks"])


# -------------------------------------------------------------- #8 company
def test_company_seed_leads_only():
    home = ('<a href="https://www.linkedin.com/in/jane-doe">Jane Doe — Engineer</a>'
            '<a href="/team">Our team</a>')
    def fetch(u, h):
        if u.rstrip("/").endswith("example.com"):
            return 200, home
        return 404, ""
    r = company_seed("example.com", fetcher=fetch)
    assert r["status"] == "found" and r["staff_candidates"]
    assert all(c["status"] == "lead" for c in r["staff_candidates"])
    assert any("linkedin.com" in c["url"] for c in r["staff_candidates"])


# ----------------------------------------------------------------- #9 email
def test_gravatar_linked_leads():
    grav = {"status": "found", "fields": {"linked_accounts": {"value": ["https://github.com/tester", "https://example.com"]}}}
    r = gravatar_linked_leads(grav)
    assert r["status"] == "found" and r["leads"][0]["platform"] == "github"
    assert gravatar_linked_leads({"status": "not_found"})["status"] == "not_checked"


# -------------------------------------------------------------- #10 scoring
def test_score_pair_v8_signals_and_timing_cap():
    a = {"username": "jane", "bio_links": ["https://jane.dev/about"], "website": "https://jane.dev",
         "language": "en", "posting_hours": [9, 10], "outbound_links": ["https://x.dev/a"]}
    b = {"username": "jane", "bio_links": ["https://jane.dev"], "website": "https://jane.dev/",
         "language": "en", "posting_hours": [9, 10], "outbound_links": ["https://x.dev/a"]}
    r = score_pair_v8(a, b)
    assert "bio_link" in r["signals"] and "shared_website" in r["signals"]
    assert r["score"] >= 80
    cap = score_pair_v8({"username": "a", "posting_hours": [1, 2, 3]},
                        {"username": "b", "posting_hours": [1, 2, 3]})
    assert cap["score"] <= 25  # timing alone is capped, never a merge basis


# ----------------------------------------------------------- #11 variations
def test_variations_v8():
    r = variations_v8("john.doe", city="Lahore", years=["1990"])
    v = r["variations"]
    assert "john.doe1990" in v and "doe.john" in v and "jdoe" in v
    assert any("lahore" in x for x in v)
    assert r["params"]["years"] == ["1990"]


# ------------------------------------------------------------- #12 comments
def test_comment_limit(monkeypatch):
    r = apply_comment_limit([{"text": str(i)} for i in range(150)], limit=100)
    assert len(r["items"]) == 100 and r["truncated"] and r["collected"] == 150
    monkeypatch.setenv("PERSONATRACE_COMMENT_LIMIT", "7")
    from personatrace.features.social import _comment_limit
    assert _comment_limit() == 7


# ---------------------------------------------------------- #13 overlap
def test_follower_overlap_id_sets_and_mocked_api():
    a = {"followers": ["x", "y", "z"], "following": ["y"]}
    b = {"followers": ["y", "w"], "following": ["y", "q"]}
    r = follower_overlap("anchor", "other", id_sets=(a, b))
    assert r["status"] == "found" and r["common_followers"] == ["y"]
    def fetch(u, h):
        if "/followers" in u:
            return 200, json.dumps([{"login": "hubot"}, {"login": "mona"}])
        return 200, json.dumps([{"login": "mona"}])
    sets = github_id_sets("octocat", fetcher=fetch)
    assert sets["followers"] == ["hubot", "mona"]


# --------------------------------------------------------------- #14 video
def test_video_section_no_fake_transcript():
    r = video_section([{"title": "My Talk", "text": "api security talk", "url": "https://example.com/v"}])
    assert r["items"][0]["transcript"]["status"] == "not_checked"
    assert r["items"][0]["text_topics_status"] == "derived"
    assert video_section([])["status"] == "not_checked"


# --------------------------------------------------------------- #15 photo
def _png_bytes(color=(200, 30, 30), size=(64, 64)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_photo_variant_check():
    img = _png_bytes()
    r = photo_variant_check(img, [img])
    assert r["status"] == "found" and "centre_crop" in r["variants"]
    assert r["matches"] and r["matches"][0]["best_distance"] <= 10
    assert photo_variant_check(b"not an image", [img])["status"] == "not_checked"


# ------------------------------------------------------------- #17 archive
def test_archive_diff_two_sources():
    rows = json.dumps([["urlkey", "timestamp", "original", "statuscode", "digest"],
                       ["x", "20240101000000", "https://github.com/octocat", "200", "ABC"]])
    r = archive_diff("https://github.com/octocat", fetcher=lambda u, h: (200, rows))
    assert r["snapshot_count_wayback"] == 2 and "archive_today" in r


# -------------------------------------------------------------- #18 alerts
def test_watch_alerts_not_configured_and_sent(monkeypatch):
    for name in ("PERSONATRACE_ALERT_WEBHOOK_URL", "PERSONATRACE_SMTP_HOST",
                 "PERSONATRACE_ALERT_EMAIL_TO", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    r = send_watch_alert("hello", keys={})
    assert r["webhook"]["status"] == "not_configured"
    assert r["email"]["status"] == "not_configured"
    assert r["telegram"]["status"] == "not_configured"
    r2 = send_watch_alert("hello", keys={"alert_webhook_url": "https://hook.example/x"},
                          webhook_sender=lambda url, msg: {"status": "sent"})
    assert r2["summary"]["sent_channels"] == ["webhook"]


# --------------------------------------------------------------- #19 graph
def test_graph_levels():
    profiles = [
        {"platform": "github", "username": "octocat", "status": "confirmed_anchor", "bio_links": ["https://github.blog"]},
        {"platform": "gitlab", "username": "octocat", "status": "candidate", "bio_links": ["https://github.blog"]},
    ]
    g = graph_levels(profiles, [], contacts_of_contacts={"github:octocat": ["hubot"]},
                     anchor_id="github:octocat")
    levels = {n["level"] for n in g["nodes"]}
    assert levels == {1, 2, 3, 4}
    assert [n for n in g["nodes"] if n["level"] == 1][0]["centre"] is True


# --------------------------------------------------------- #20 coordinated
def test_coordinated_v8_rare_followers():
    accounts = [{"bio": "same bio text here", "created_at": "2024-01-01T00:00:00Z", "posts": []},
                {"bio": "same bio text here", "created_at": "2024-01-02T00:00:00Z", "posts": []}]
    r = coordinated_v8(accounts, follower_sets=[["a", "rare1", "b"], ["a", "rare1"]])
    assert "rare1" in r["shared_rare_followers"] and r["verdict"] == "pattern, not proof"


# ------------------------------------------------------------ #21 behaviour
def test_behaviour_v8():
    items = [
        {"created_at": "2024-01-01T10:00:00Z", "text": "#api first", "reply_to_created_at": "2024-01-01T09:00:00Z", "language": "en"},
        {"created_at": "2024-01-03T10:00:00Z", "text": "#web second", "reply_to_created_at": "2024-01-03T09:30:00Z", "language": "en"},
        {"created_at": "2024-01-10T10:00:00Z", "text": "#api third", "language": "ur"},
    ]
    r = behaviour_v8(items)
    assert r["sample_n"] == 3 and r["reply_speed_minutes"]["count"] == 2
    assert r["posting_gap_hours"]["count"] == 2


# -------------------------------------------------------- #22 impersonation
def test_impersonation_finder():
    anchor = {"platform": "github", "username": "jane", "display_name": "Jane", "avatar_hash": "h1", "bio": "hello"}
    others = [{"platform": "x", "username": "jane2", "display_name": "Jane", "avatar_hash": "h1", "bio": "other"},
              {"platform": "x", "username": "bob", "display_name": "Bob", "avatar_hash": "h9", "bio": "x"}]
    r = impersonation_finder(anchor, others)
    assert r["status"] == "found" and len(r["candidates"]) == 1
    assert r["candidates"][0]["status"] == "lead"


# ---------------------------------------------------------------- #23 scam
def test_scam_signals():
    profiles = [
        {"platform": "github", "username": "a", "bio": "tips 0x" + "a" * 40, "texts": ["shop https://shop.example/x"]},
        {"platform": "x", "username": "b", "bio": "", "texts": ["shop https://shop.example/x"]},
    ]
    r = scam_signals(profiles)
    assert any(w["kind"] == "eth_address" for w in r["wallet_addresses"])
    assert len(r["repeated_links_across_accounts"]) == 1


# --------------------------------------------------------------- #24 wallet
def test_wallet_seed_mocked():
    assert validate_wallet("0x" + "a" * 40)["kind"] == "eth"
    assert validate_wallet("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")["kind"] == "btc"
    assert not validate_wallet("nope")["valid"]
    def fetch(u, h):
        if "blockcypher" in u:
            return 200, json.dumps({"balance": 5, "total_received": 9, "n_tx": 2})
        return 200, json.dumps({"hits": []})
    r = wallet_seed("0x" + "a" * 40, fetcher=fetch)
    assert r["chain_basics"]["status"] == "found" and r["chain_basics"]["n_tx"] == 2


# ---------------------------------------------------------------- #25 plate
def test_plate_seed_public_posts_only():
    r = plate_seed("ABC-123", fetcher=lambda u, h: (200, json.dumps({"hits": []})))
    assert "No vehicle database" in r["note"] and "owner" not in r["note"].split("No vehicle database")[0][-20:]


# ------------------------------------------------------------ #26 teamwork
def test_case_team_fields(tmp_path):
    from personatrace.features.v5 import register_case
    register_case(str(tmp_path), "seedx", "out_dir")
    r = set_case_team(str(tmp_path), "seedx", assigned_to="zain", lead_status="open")
    assert r["status"] == "found" and r["case"]["assigned_to"] == "zain"
    reg = json.load(open(os.path.join(str(tmp_path), "cases.json")))
    assert reg[0]["lead_status"] == "open"


# --------------------------------------------------------- #27 court report
def test_court_report():
    dossier = {"seed": "octocat", "profile_summary": [
        {"platform": "github", "username": "octocat", "evidence": [
            {"field": "username", "value": "octocat", "source_url": "https://github.com/octocat",
             "captured_at_utc": "2024-01-01T00:00:00Z", "method": "public_api", "confidence": 90}]}]}
    md = court_report(dossier, fmt="md")
    assert "sha256" in md and "https://github.com/octocat" in md
    assert "<table>" in court_report(dossier, fmt="html")


# --------------------------------------------------------------- #28 proof
def test_proof_folder(tmp_path):
    dossier = {"seed": "octocat", "profile_summary": [
        {"platform": "github", "username": "octocat", "display_name": "The Octocat", "status": "confirmed_anchor",
         "evidence": [{"source_url": "https://github.com/octocat", "captured_at_utc": "2024-01-01T00:00:00Z"}]}]}
    r = build_proof_folder(dossier, str(tmp_path))
    assert r["count"] == 1 and os.path.exists(os.path.join(str(tmp_path), "proof_index.json"))
    files = os.listdir(os.path.join(str(tmp_path), "proof"))
    assert any(f.endswith(".png") or f.endswith(".json") for f in files)
    card = proof_card_png(dossier["profile_summary"][0], str(tmp_path / "card.png"))
    assert card["status"] == "found" and len(card["sha256"]) == 64


# -------------------------------------------------------------- #29 offline
def test_offline_rebuild_no_network(tmp_path, monkeypatch):
    import urllib.request
    def boom(*a, **k):
        raise RuntimeError("network is forbidden in offline mode")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    case = tmp_path / "case"; case.mkdir()
    payload = {"case_id": "case_1", "seed": "octocat", "seed_type": "username",
               "profiles": [{"platform": "github", "username": "octocat", "display_name": "The Octocat",
                             "bio": "", "bio_links": [], "follower_count": 1, "following_count": 2,
                             "created_at": "", "status": "candidate",
                             "evidence": [{"source_url": "https://github.com/octocat", "captured_at_utc": "2024-01-01T00:00:00Z",
                                           "method": "public_api", "platform": "github", "field": "username",
                                           "value": "octocat", "confidence": 90}]}],
               "edges": [], "possible_matches": [], "alerts": [], "audit": [], "timeline": [],
               "notes": [], "checklist": []}
    (case / "investigation.json").write_text(json.dumps(payload))
    out = tmp_path / "out"
    r = offline_rebuild(str(case), str(out))
    assert r["status"] == "found"
    assert r["dossier"]["version"] == "8.0.0" and r["dossier"]["public_web"] == {}
    assert os.path.exists(os.path.join(str(out), "dossier.json"))
    assert os.path.exists(os.path.join(str(out), "court_report.md"))


def test_build_v8_sections_real_analysis_shape():
    # Regression: analysis["comments"] is a comments_info DICT in real
    # payloads (not a list) — the v8 dossier build must not crash on it.
    from personatrace.features.v8 import build_v8_sections
    dossier = {"seed": "octocat", "profile_summary": [
        {"platform": "github", "username": "octocat", "bio": "hi", "bio_links": [], "evidence": []}],
        "network_graph": {"nodes": [], "edges": [], "note": ""}}
    payload = {"analysis": {"comments": {"comments": [{"platform": "github", "text": "hello"}]},
                            "timeline": [{"date": "2024-01-01", "title": "x"}],
                            "contacts_of_contacts": {}}}
    out = build_v8_sections(dossier, payload, v8_section={})
    assert out["v8"]["comments_v8"]["collected"] == 1
    assert out["network_graph"]["centre"] == "github:octocat"


# ------------------------------------------------------------ #30 GUI + CLI
def test_gui_v8_static():
    import pathlib
    root = pathlib.Path(__file__).parent.parent / "personatrace" / "gui"
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    # v8 seed options stay in the GUI; the header version string moves
    # with the newest release (v9 test asserts it).
    assert 'value="profile"' in html and 'value="company"' in html
    assert 'value="wallet"' in html and 'value="plate"' in html and 'id="live-direct"' in html
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")
    assert "480px" in css and "390px" in css
    server = (root / "server.py").read_text(encoding="utf-8")
    assert "investigate_v8" in server and "/api/keys/verify" in server and "/api/cases/team" in server


def test_cli_verify_keys_flag(tmp_path, monkeypatch):
    for name in ("HIKERAPI_KEY", "YOUTUBE_API_KEY", "BRAVE_SEARCH_KEY", "TAVILY_API_KEY",
                 "SERPER_API_KEY", "GITHUB_TOKEN", "SHODAN_API_KEY", "SERPAPI_KEY",
                 "GOOGLE_PSE_KEY", "VIRUSTOTAL_API_KEY", "SECURITYTRAILS_API_KEY",
                 "URLSCAN_API_KEY", "TINEYE_API_KEY", "BING_VISUAL_SEARCH_KEY",
                 "EMAIL_VERIFICATION_KEY", "OPENAI_API_KEY", "PERSONATRACE_AGGREGATOR_KEY",
                 "PERSONATRACE_AGGREGATOR_BASE_URL", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    from personatrace.cli import main
    rc = main(["--seed", "octocat", "--verify-keys", "--out", str(tmp_path)])
    assert rc == 0
    data = json.load(open(tmp_path / "key_verification.json"))
    assert data["status"] == "not_checked"
