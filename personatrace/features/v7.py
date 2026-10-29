"""PersonaTrace v7.0.0 — full seed expansion + key catalog + elite exports.

Seeds added on top of v6 (username, domain):
  email | name | url | image | hashtag | phrase | ip | auto | multi

Rules (same hard limits as v6, unchanged):
- Public data only. No private accounts/DMs, no live location, no face
  identification (image seed = same-photo reuse / OCR / reverse-image
  with a key only), no bulk personal-data export, no password or
  breach-dump search, no phone people-search, no active port scanning.
- Stop on 429 / CAPTCHA / login wall. Never retry in a loop.
- Keys are never logged, echoed, or exported. Every field carries a
  provenance status from the v6 taxonomy. Anything that cannot run
  reliably returns a labelled stub (not_checked / gated_paid / blocked /
  search_snippet / derived), never fabricated data.
- Name and email candidates are LEADS for a human review queue, never
  a certain identity match on a name/email alone.
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

VERSION = "7.0.0"

SEED_TYPES = ("username", "domain", "email", "name", "url", "image",
              "hashtag", "phrase", "ip", "auto", "multi")

INNOCENT_EXPLANATIONS = [
    "A different person with the same name / a common name",
    "A recycled or re-registered handle",
    "An impersonator or fan / parody account",
    "A namesake business, character, or organisation",
    "An old account the person no longer controls",
    "Coincidence: shared hashtag, phrase, or employer with no other link",
]

# ---------------------------------------------------------------- detection
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_DOMAIN_RE = re.compile(r"^(?=.{3,253}$)([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")

def validate_email(seed: str) -> dict:
    e = (seed or "").strip().lower()
    ok = bool(_EMAIL_RE.match(e)) and len(e) <= 254 and ".." not in e
    return {"email": e, "valid": ok,
            "domain": e.rsplit("@", 1)[1] if ok and "@" in e else None,
            "status": "found" if ok else "not_found",
            "note": "Format validation only (regex + length). It does not prove the mailbox exists or belongs to any person." if ok
                    else "Not a valid email format; no lookup was run."}

def is_ip(seed: str) -> bool:
    try:
        ipaddress.ip_address((seed or "").strip())
        return True
    except Exception:
        return False

def detect_seed_type(seed: str) -> str:
    """Auto-detect. Order matters: email > url > ip > hashtag > domain
    > phrase (multi-word) > username. Name is NOT auto-detected from a
    multi-word string, because a name and a phrase are indistinguishable
    without context — multi-word auto seeds are treated as phrase, and
    the investigator picks 'name' explicitly (with context) instead."""
    s = (seed or "").strip()
    if _EMAIL_RE.match(s.lower()):
        return "email"
    if s.lower().startswith(("http://", "https://")):
        # An image URL is still a URL at detect time; the URL handler
        # routes image extensions to the image handler.
        return "url"
    if is_ip(s):
        return "ip"
    if s.startswith("#") and " " not in s:
        return "hashtag"
    if _DOMAIN_RE.match(s) and " " not in s:
        return "domain"
    if " " in s:
        return "phrase"
    return "username"

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

def looks_like_image_url(seed: str) -> bool:
    try:
        path = urllib.parse.urlparse(seed).path.lower()
    except Exception:
        return False
    return path.endswith(_IMAGE_EXTS)

# ---------------------------------------------------------------- gravatar
def gravatar_hashes(email: str) -> dict:
    e = (email or "").strip().lower().encode("utf-8")
    return {"md5": hashlib.md5(e).hexdigest(),
            "sha256": hashlib.sha256(e).hexdigest()}

def gravatar_lookup(email: str, fetcher=None):
    """GET https://www.gravatar.com/<sha256>.json
    fetcher (injectable, for tests): (url, headers) -> (status, body).
    Returns only what Gravatar publishes in that response: preferred
    username, display name, profile URL, and public linked-account /
    listed URLs from the same entry. Nothing else is extracted."""
    v = validate_email(email)
    if not v["valid"]:
        return {"status": "not_found", "fields": {}, "validation": v,
                "note": v["note"]}
    h = gravatar_hashes(v["email"])
    url = f"https://www.gravatar.com/{h['sha256']}.json"
    profile_url = f"https://gravatar.com/{h['sha256']}"
    try:
        if fetcher is not None:
            status, body = fetcher(url, {"User-Agent": "PersonaTrace/7.0"})
            data = json.loads(body) if isinstance(body, str) and body else body
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "PersonaTrace/7.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                status = resp.status
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        status, data = exc.code, None
    except Exception as exc:
        if "404" in str(exc):
            status, data = 404, None
        else:
            return {"status": "blocked" if "429" in str(exc) else "not_checked",
                    "fields": {}, "hashes": h, "source_url": url,
                    "note": f"Gravatar lookup did not complete ({str(exc)[:120]}). Not a finding that no profile exists."}
    if status == 404:
        return {"status": "not_found", "fields": {}, "hashes": h,
                "source_url": url,
                "note": "Gravatar returned 404: no public Gravatar profile for this email hash. That does not mean the mailbox does not exist."}
    if status in (401, 403, 429):
        return {"status": "blocked", "fields": {}, "hashes": h, "source_url": url,
                "note": f"Gravatar blocked the request (HTTP {status}). Stopped, not bypassed."}
    if status != 200 or not isinstance(data, dict):
        return {"status": "not_checked", "fields": {}, "hashes": h, "source_url": url,
                "note": f"Gravatar returned HTTP {status} with no usable profile."}
    entries = data.get("entry") or []
    if not entries:
        return {"status": "not_found", "fields": {}, "hashes": h, "source_url": url,
                "note": "Gravatar returned no profile entry for this email hash."}
    e0 = entries[0] if isinstance(entries[0], dict) else {}
    from .v6 import field as _field
    src = e0.get("profileUrl") or profile_url
    linked = []
    for acc in e0.get("accounts") or []:
        if isinstance(acc, dict) and acc.get("url"):
            linked.append(acc["url"])
    for u in e0.get("urls") or []:
        if isinstance(u, dict) and u.get("value"):
            linked.append(u["value"])
    linked = list(dict.fromkeys(linked))
    fields = {
        "username": _field(e0.get("preferredUsername"), src, "public_api", "found" if e0.get("preferredUsername") else "not_found"),
        "display_name": _field(e0.get("displayName"), src, "public_api", "found" if e0.get("displayName") else "not_found"),
        "profile_url": _field(src, src, "public_api", "found"),
        "linked_accounts": _field(linked, src, "public_api", "found" if linked else "not_found",
                                  "Only account / listed URLs published inside this Gravatar entry."),
    }
    return {"status": "found", "fields": fields, "hashes": h, "source_url": src,
            "note": "Public Gravatar profile only. The email itself is never published by this lookup; only its hash was sent to Gravatar."}

# ---------------------------------------------------------------- dork helper
def _dork_search(queries, keys=None, search_fetcher=None, engine_note=""):
    """Run queries through the v6 search route. search_fetcher
    (injectable): (query) -> [{title, url, snippet}]. Without a search
    key / fetcher this uses the v6 DDG/SearXNG fallback via
    search_dorks on the first query only, labelled search_snippet;
    a 0-snippet outcome is returned as not_checked, never as not_found.
    """
    from .v6 import search_dorks
    results = []
    if search_fetcher is not None:
        for q in queries:
            try:
                for item in (search_fetcher(q) or [])[:5]:
                    results.append({"query": q, "title": item.get("title", ""),
                                    "url": item.get("url", ""), "snippet": item.get("snippet", ""),
                                    "status": "search_snippet"})
            except Exception as exc:
                results.append({"query": q, "title": "", "url": "", "snippet": "",
                                "status": "blocked", "note": str(exc)[:120]})
        return {"status": "search_snippet" if results else "not_checked",
                "queries": queries, "results": results,
                "note": engine_note or "Search snippets are unverified until the source URL is opened."}
    # Reuse v6 route keyed on the first query's seed token: v6 builds its
    # own template queries, so for arbitrary queries we call its Brave
    # path only when a Brave key exists; otherwise honest not_checked.
    keys = dict(keys or {})
    brave = keys.get("brave_search_key") or os.environ.get("BRAVE_SEARCH_KEY")
    if brave:
        for q in queries[:4]:
            try:
                req = urllib.request.Request(
                    "https://api.search.brave.com/res/v1/web/search?q=" + urllib.parse.quote(q),
                    headers={"X-Subscription-Token": brave, "User-Agent": "PersonaTrace/7.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                for item in (data.get("web", {}).get("results") or [])[:3]:
                    results.append({"query": q, "title": item.get("title", ""), "url": item.get("url", ""),
                                    "snippet": item.get("description", ""), "status": "search_snippet"})
            except Exception as exc:
                results.append({"query": q, "title": "", "url": "", "snippet": "",
                                "status": "blocked", "note": str(exc)[:120]})
        return {"status": "search_snippet" if results else "not_checked",
                "engine": "brave", "queries": queries, "results": results,
                "note": "Brave search API. Snippets are unverified until opened."}
    return {"status": "not_checked", "queries": queries, "results": [],
            "note": "No search API key configured (Brave/Tavily/Serper) and no search fetcher supplied, so dorking was not run. Add a search key in the key wizard, then re-run. 0 snippets here means not_checked, not not_found."}

def email_dorks(email: str, keys=None, search_fetcher=None):
    v = validate_email(email)
    if not v["valid"]:
        return {"status": "not_found", "results": [], "note": v["note"]}
    q = f'"{v["email"]}"'
    out = _dork_search([q], keys=keys, search_fetcher=search_fetcher,
                       engine_note="Exact-email dork, one query. Snippets only — an email appearing in a snippet is a lead, not proof the account belongs to that person.")
    out["query"] = q
    return out

# ---------------------------------------------------------------- name seed
def name_queries(name: str, context: str = "") -> list:
    n = (name or "").strip()
    ctx = (context or "").strip()
    qs = [f'"{n}" {ctx}'.strip(), f'site:linkedin.com/in "{n}"',
          f'site:github.com "{n}"', f'"{n}" {ctx} instagram OR twitter OR x.com'.strip()]
    return qs

def name_search(name: str, context: str = "", keys=None, search_fetcher=None):
    n = (name or "").strip()
    if len(n) < 3 or " " not in n:
        return {"status": "not_found", "candidates": [], "queries": [],
                "note": "A name seed needs a full name (at least two words). A single word is a username — run it as a username seed instead."}
    qs = name_queries(n, context)
    out = _dork_search(qs, keys=keys, search_fetcher=search_fetcher)
    ctx_terms = [t.lower() for t in re.split(r"[,\s]+", context or "") if len(t) > 2]
    candidates = []
    for r in out.get("results", []):
        if not r.get("url"):
            continue
        blob = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        score = 40
        reasons = ["name appears in a public search result (snippet)"]
        if n.lower() in blob:
            score += 20; reasons.append("full name in title/snippet text")
        for t in ctx_terms:
            if t in blob:
                score += 15; reasons.append(f"context term matched: {t}")
        candidates.append({"title": r.get("title"), "url": r.get("url"),
                           "snippet": r.get("snippet"), "query": r.get("query"),
                           "status": "search_snippet", "confidence": min(score, 79),
                           "reasons": reasons,
                           "innocent_explanations": INNOCENT_EXPLANATIONS,
                           "review_status": "pending"})
    return {"status": "search_snippet" if candidates else out.get("status", "not_checked"),
            "candidates": candidates, "queries": qs, "results": out.get("results", []),
            "note": "Name results are candidates for human review only. A name match is never a certain identity — common names, namesakes and impersonators are expected (see innocent_explanations on every candidate). " + (out.get("note") or "")}

# ---------------------------------------------------------------- url seed
_PLATFORM_HOSTS = {
    "instagram.com": "instagram", "tiktok.com": "tiktok", "x.com": "x",
    "twitter.com": "x", "youtube.com": "youtube", "youtu.be": "youtube",
    "github.com": "github", "bsky.app": "bluesky",
    "mastodon.social": "mastodon", "linkedin.com": "linkedin",
    "reddit.com": "reddit",
}

def parse_url_seed(seed: str) -> dict:
    s = (seed or "").strip()
    if not s.lower().startswith(("http://", "https://")):
        return {"status": "not_found", "note": "A URL seed must start with http:// or https://."}
    u = urllib.parse.urlparse(s)
    host = (u.hostname or "").lower().removeprefix("www.")
    platform = _PLATFORM_HOSTS.get(host, "web")
    parts = [p for p in u.path.split("/") if p]
    username, kind, item_id = None, "page", None
    if platform in ("instagram", "tiktok", "x", "github", "bluesky", "linkedin", "reddit") and parts:
        first = parts[0]
        if platform == "tiktok" and first.startswith("@"):
            username = first[1:]
        elif platform == "linkedin" and first in ("in", "company") and len(parts) > 1:
            username, kind = parts[1], "profile"
        elif platform == "reddit" and first in ("user", "u") and len(parts) > 1:
            username = parts[1]
        elif first not in ("p", "reel", "reels", "watch", "video", "videos", "status", "in", "company", "user", "u"):
            username = first
        if username:
            kind = "profile" if len(parts) <= (2 if platform in ("linkedin", "reddit") else 1) else "post"
        if len(parts) >= 2 and parts[-2] in ("p", "reel", "status", "video", "videos", "watch"):
            item_id, kind = parts[-1], "post"
    if platform == "youtube":
        if parts and parts[0] in ("watch",) or "v" in urllib.parse.parse_qs(u.query):
            kind = "post"; item_id = (urllib.parse.parse_qs(u.query).get("v") or [None])[0]
        elif parts and parts[0].startswith("@"):
            username, kind = parts[0][1:], "profile"
        elif parts and parts[0] == "channel" and len(parts) > 1:
            item_id, kind = parts[1], "profile"
    return {"status": "derived", "url": s, "host": host, "platform": platform,
            "kind": kind, "username": username, "item_id": item_id,
            "note": "Parsed locally from the URL only (derived). The username/handle above is a lead: the follow-on username investigation is what verifies it on that platform."}

def url_seed_detail(seed: str, keys=None):
    """Parse + (YouTube only, free no-key) oEmbed for a video URL."""
    parsed = parse_url_seed(seed)
    detail = {"parsed": parsed}
    if parsed.get("platform") == "youtube" and parsed.get("kind") == "post":
        from .v6 import youtube_oembed
        detail["oembed"] = youtube_oembed(seed)
    elif parsed.get("platform") in ("instagram", "tiktok", "x", "linkedin"):
        detail["fetch"] = {"status": "gated_paid",
                           "note": f"{parsed['platform']} item fetch needs an aggregator key or a consented login; without one only the URL parse (derived) is returned. No scraping around the login wall was attempted."}
    else:
        detail["fetch"] = {"status": "derived",
                           "note": "Author handle parsed from the URL; run the follow-on username investigation for the platform profile (done automatically by the CLI/GUI seed handler)."}
    return detail

# ---------------------------------------------------------------- image seed
def image_seed_detail(image_url: str, keys=None, image_fetcher=None, collected_avatar_bytes=None):
    """Same-photo reuse + OCR + reverse image (key-gated). Never face ID.
    image_fetcher (injectable): (url) -> bytes. collected_avatar_bytes:
    optional list of bytes of avatars already held, for local pHash reuse."""
    out = {"image_url": image_url, "status": "not_checked",
           "note": "Image seed finds reuse of the SAME photo, runs OCR/description, and (with a key) reverse-image search. It never identifies a face or a person."}
    try:
        if image_fetcher is not None:
            data = image_fetcher(image_url)
        else:
            req = urllib.request.Request(image_url, headers={"User-Agent": "PersonaTrace/7.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read(5_000_000)
    except Exception as exc:
        out["status"] = "blocked" if "429" in str(exc) or "403" in str(exc) else "not_checked"
        out["note"] = f"Image could not be downloaded ({str(exc)[:120]}). " + out["note"]
        out["download"] = {"status": out["status"]}
        return out
    out["download"] = {"status": "found", "bytes": len(data or b"")}
    try:
        from .ocr import describe_image
        out["description_ocr"] = describe_image(data)
    except Exception as exc:
        out["description_ocr"] = {"status": "not_checked", "note": str(exc)[:120]}
    reuse = []
    try:
        from .phash import ahash, hamming
        h = ahash(data)
        out["phash"] = h
        for i, other in enumerate(collected_avatar_bytes or []):
            try:
                d = hamming(h, ahash(other))
                if d <= 10:
                    reuse.append({"collected_index": i, "hamming_distance": d, "status": "derived",
                                  "note": "Same/near-same image as a collected avatar (whole-image pHash). This is photo reuse, not face identification."})
            except Exception:
                pass
    except Exception as exc:
        out["phash_error"] = str(exc)[:120]
    out["avatar_reuse"] = reuse
    try:
        from .reverse_image import reverse_search
        out["reverse_image"] = reverse_search(image_url=image_url, image_bytes=data, keys=dict(keys or {}))
    except Exception as exc:
        out["reverse_image"] = {"status": "not_checked", "note": str(exc)[:120]}
    out["manual_reverse_links"] = {"google_lens": "https://lens.google.com/uploadbyurl?url=" + urllib.parse.quote(image_url),
                                   "yandex": "https://yandex.com/images/search?from=tabbar&text=&rpt=imageview&url=" + urllib.parse.quote(image_url),
                                   "note": "Manual links only; open them yourself. Automated Lens/Yandex runs need a SerpApi key (see key catalog)."}
    out["status"] = "found"
    return out

# ---------------------------------------------------------------- hashtag / phrase
def _http_json(url, fetcher=None, timeout=6):
    if fetcher is not None:
        status, body = fetcher(url, {"User-Agent": "PersonaTrace/7.0"})
        return status, (json.loads(body) if isinstance(body, str) and body else body)
    req = urllib.request.Request(url, headers={"User-Agent": "PersonaTrace/7.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:
        return None, {"error": str(exc)[:120]}

def hashtag_search(tag: str, fetcher=None, keys=None):
    t = (tag or "").strip().lstrip("#")
    if not t or " " in t:
        return {"status": "not_found", "posts": [], "note": "A hashtag seed is one word, with or without #. Multi-word text is a phrase seed."}
    posts, statuses = [], {}
    # Mastodon public hashtag timeline (no key)
    st, data = _http_json(f"https://mastodon.social/api/v1/timelines/tag/{urllib.parse.quote(t)}?limit=20", fetcher=fetcher)
    statuses["mastodon"] = "found" if st == 200 else ("blocked" if st in (401, 403, 429) else "not_checked")
    if st == 200 and isinstance(data, list):
        for item in data[:20]:
            acct = ((item.get("account") or {}).get("acct")) or ""
            posts.append({"platform": "mastodon", "author": acct,
                          "url": item.get("url"), "created_at": item.get("created_at"),
                          "text": re.sub(r"<[^>]+>", " ", item.get("content") or "").strip()[:280],
                          "status": "found", "source": "mastodon public hashtag timeline"})
    # Hacker News Algolia full-text search for the tag (no key)
    st2, data2 = _http_json("https://hn.algolia.com/api/v1/search?query=" + urllib.parse.quote(t) + "&tags=story", fetcher=fetcher)
    statuses["hackernews"] = "found" if st2 == 200 else "not_checked"
    if st2 == 200 and isinstance(data2, dict):
        for hit in (data2.get("hits") or [])[:10]:
            posts.append({"platform": "hackernews", "author": hit.get("author"),
                          "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                          "created_at": hit.get("created_at"), "text": (hit.get("title") or "")[:280],
                          "status": "found", "source": "HN Algolia search"})
    authors = Counter(p["author"] for p in posts if p.get("author"))
    return {"status": "found" if posts else (statuses.get("mastodon") if statuses.get("mastodon") == "blocked" else "not_found"),
            "tag": t, "posts": posts, "source_statuses": statuses,
            "accounts_using_it": [{"author": a, "posts_in_sample": c, "status": "derived"} for a, c in authors.most_common(20)],
            "note": f"Sample from open platforms only ({len(posts)} items). Instagram/X/TikTok hashtag grids need an aggregator key; they are gated_paid here, not searched by scraping."}

def phrase_search(phrase: str, fetcher=None, keys=None, search_fetcher=None):
    p = (phrase or "").strip()
    if len(p) < 4:
        return {"status": "not_found", "posts": [], "note": "A phrase seed needs at least 4 characters."}
    st, data = _http_json("https://hn.algolia.com/api/v1/search?query=" + urllib.parse.quote(f'"{p}"'), fetcher=fetcher)
    posts = []
    if st == 200 and isinstance(data, dict):
        for hit in (data.get("hits") or [])[:10]:
            posts.append({"platform": "hackernews", "author": hit.get("author"),
                          "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                          "text": (hit.get("title") or hit.get("story_text") or "")[:280], "status": "found"})
    dorks = _dork_search([f'"{p}"'], keys=keys, search_fetcher=search_fetcher)
    return {"status": "found" if posts else dorks.get("status", "not_checked"),
            "phrase": p, "posts": posts, "dorks": dorks,
            "note": "HN exact-phrase search (free) plus a dork query when a search key/fetcher is present. Social-platform phrase search is search-key or aggregator only."}

# ---------------------------------------------------------------- ip seed
def ip_seed_detail(ip: str, fetcher=None):
    s = (ip or "").strip()
    if not is_ip(s):
        return {"status": "not_found", "note": "Not a valid IPv4/IPv6 address; no lookup was run."}
    out = {"ip": s, "status": "not_checked", "note": "Passive lookups only (RDAP + Shodan InternetDB). No port scan was run."}
    from .v6 import shodan_internetdb
    try:
        out["internetdb"] = shodan_internetdb(s) if fetcher is None else {"status": "not_checked", "note": "InternetDB skipped when a test fetcher is injected."}
    except Exception as exc:
        out["internetdb"] = {"status": "not_checked", "note": str(exc)[:120]}
    st, data = (None, None)
    try:
        st, data = _http_json(f"https://rdap.org/ip/{urllib.parse.quote(s)}", fetcher=fetcher)
    except Exception as exc:
        out["rdap"] = {"status": "not_checked", "note": str(exc)[:120]}
    if st == 200 and isinstance(data, dict):
        out["rdap"] = {"status": "found", "name": data.get("name"), "handle": data.get("handle"),
                       "country": data.get("country"), "start_address": data.get("startAddress"),
                       "end_address": data.get("endAddress"),
                       "entities": [e.get("handle") for e in (data.get("entities") or []) if isinstance(e, dict)][:5],
                       "note": "RDAP registrant/operator data as published by the registry. Redacted fields are shown as redacted/absent, never unmasked."}
        out["status"] = "found"
    elif st == 404:
        out["rdap"] = {"status": "not_found"}
    elif st in (401, 403, 429):
        out["rdap"] = {"status": "blocked", "note": f"RDAP blocked (HTTP {st})."}
    else:
        out.setdefault("rdap", {"status": "not_checked"})
    if out.get("internetdb", {}).get("status") == "found":
        out["status"] = "found"
    return out

# ---------------------------------------------------------------- key catalog v7
def providers_v7() -> dict:
    from .v6 import PROVIDERS
    extra = {
        "serpapi_key": {"label": "SerpApi", "unlocks": "Search/dorks + Google Lens + Yandex reverse image (SerpApi engines)", "verify_url": None, "verify_header": None, "cost_preview": "100 trial searches reported; verify at setup.", "env": "SERPAPI_KEY"},
        "google_pse_key": {"label": "Google Programmable Search Engine", "unlocks": "Search/dorks via Google PSE (needs a PSE engine ID cx as google_pse_cx)", "verify_url": None, "verify_header": None, "cost_preview": "100 queries/day free reported; verify in Google console.", "env": "GOOGLE_PSE_KEY"},
        "virustotal_api_key": {"label": "VirusTotal", "unlocks": "Domain/IP/file reputation for domains and IPs actually found in a case", "verify_url": None, "verify_header": None, "cost_preview": "Free tier rate-limited; verify at setup.", "env": "VIRUSTOTAL_API_KEY"},
        "securitytrails_api_key": {"label": "SecurityTrails", "unlocks": "Passive DNS / domain history for domains actually found in a case", "verify_url": None, "verify_header": None, "cost_preview": "Provider plan price; verify at setup.", "env": "SECURITYTRAILS_API_KEY"},
        "urlscan_api_key": {"label": "urlscan.io", "unlocks": "URL scan lookups for bio-link / post URLs in a case (lookups, not new scans of people)", "verify_url": None, "verify_header": None, "cost_preview": "Free tier available; verify at setup.", "env": "URLSCAN_API_KEY"},
        "tineye_api_key": {"label": "TinEye", "unlocks": "Reverse image search for the image seed / collected avatars", "verify_url": None, "verify_header": None, "cost_preview": "Provider plan price; verify at setup.", "env": "TINEYE_API_KEY"},
        "bing_visual_search_key": {"label": "Bing Visual Search (Azure)", "unlocks": "Reverse image / visually similar pages for the image seed", "verify_url": None, "verify_header": None, "cost_preview": "Azure pricing; verify at setup.", "env": "BING_VISUAL_SEARCH_KEY"},
        "email_verification_key": {"label": "Email verification API (Hunter/Abstract etc.)", "unlocks": "PUBLIC verification only: is the address format/domain deliverable. Never personal-data harvesting, never owner identification from an email API.", "verify_url": None, "verify_header": None, "cost_preview": "Provider plan price; verify at setup.", "env": "EMAIL_VERIFICATION_KEY"},
        "openai_api_key": {"label": "AI — OpenAI-compatible API key", "unlocks": "Vision description, NER, tone, translation only (features already in v6). An AI key never substitutes for a platform key and never invents profile data.", "verify_url": None, "verify_header": None, "cost_preview": "Provider usage price; verify at setup. Ollama local model needs no key.", "env": "OPENAI_API_KEY"},
    }
    merged = dict(PROVIDERS)
    merged.update(extra)
    return merged

# ---------------------------------------------------------------- exports
def maltego_csv(dossier: dict) -> str:
    import csv, io
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Value", "Type", "Weight", "Properties"])
    seed = dossier.get("seed", "")
    w.writerow([seed, "personatrace.Seed", 100, f"seed_type={dossier.get('seed_type','')}"])
    for p in dossier.get("profile_summary", []) or []:
        w.writerow([f"{p.get('platform')}:{p.get('username')}", "personatrace.Profile", 90,
                    f"platform={p.get('platform')}; status={p.get('status')}"])
    for e in (dossier.get("network_graph", {}) or {}).get("edges", []) or []:
        w.writerow([f"{e.get('from')}->{e.get('to')}", "personatrace.Edge", 50,
                    f"kind={e.get('kind')}; confidence={e.get('confidence')}"])
    return buf.getvalue()

def obsidian_folder(dossier: dict, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    seed = str(dossier.get("seed", "case"))
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", seed)[:60] or "case"
    root = os.path.join(out_dir, f"obsidian-{safe}")
    os.makedirs(os.path.join(root, "profiles"), exist_ok=True)
    lines = [f"# PersonaTrace case — {seed}", "",
             f"Seed type: {dossier.get('seed_type', '')} · Version: {dossier.get('version', VERSION)}",
             f"Profile summary status: {dossier.get('profile_summary_status')}", "", "## Profiles"]
    for p in dossier.get("profile_summary", []) or []:
        lines.append(f"- [[profiles/{p.get('platform')}-{p.get('username')}|{p.get('platform')}: {p.get('username')}]]")
        with open(os.path.join(root, "profiles", f"{p.get('platform')}-{p.get('username')}.md"), "w") as fh:
            fh.write(f"# {p.get('platform')}: {p.get('username')}\n\nBio: {p.get('bio') or ''}\n\nFollowers: {p.get('follower_count')} · Following: {p.get('following_count')}\n\nStatus: {p.get('status')}\n")
    lines += ["", "## Honest limits"] + [f"- {x}" for x in dossier.get("honest_limits", []) or []]
    with open(os.path.join(root, "index.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    tl = ["# Timeline", ""] + [f"- {i.get('date')}: {i.get('text')}" for i in (dossier.get("timeline", {}) or {}).get("items", [])]
    with open(os.path.join(root, "timeline.md"), "w") as fh:
        fh.write("\n".join(tl) + "\n")
    return {"obsidian_index": os.path.join(root, "index.md"), "obsidian_folder": root}

# ---------------------------------------------------------------- candidate queue
def build_candidate_queue(dossier: dict) -> list:
    queue = []
    for cand in (dossier.get("v7", {}).get("name", {}) or {}).get("candidates", []) or []:
        queue.append({"kind": "name_candidate", "label": cand.get("title") or cand.get("url"),
                      "url": cand.get("url"), "confidence": cand.get("confidence", 0),
                      "status": cand.get("status", "search_snippet"),
                      "reasons": cand.get("reasons", []),
                      "innocent_explanations": cand.get("innocent_explanations", INNOCENT_EXPLANATIONS),
                      "review_status": "pending"})
    email = (dossier.get("v7", {}).get("email", {}) or {})
    grav = email.get("gravatar", {}) or {}
    if grav.get("status") == "found":
        queue.append({"kind": "email_gravatar_profile", "label": "Gravatar public profile for the seed email hash",
                      "url": grav.get("source_url"), "confidence": 80, "status": "found",
                      "reasons": ["Gravatar returned a public profile for this exact email hash"],
                      "innocent_explanations": ["An email can be shared, role-based, or reassigned; a Gravatar profile proves the hash was registered, not who the person is today."],
                      "review_status": "pending"})
    for pm in dossier.get("possible_matches", []) or []:
        if isinstance(pm, dict):
            queue.append({"kind": "possible_match", "label": str(pm.get("profile")),
                          "url": None, "confidence": pm.get("score", 0), "status": pm.get("status", "pending"),
                          "reasons": pm.get("reasons", []), "innocent_explanations": INNOCENT_EXPLANATIONS,
                          "review_status": pm.get("status", "pending")})
    return queue

# ---------------------------------------------------------------- central dispatch
def _blank_investigation(seed, seed_type, keys):
    from ..core.engine import run_investigation
    return run_investigation(seed, adapters=[], keys=dict(keys or {}),
                             seed_type=seed_type, analyse=False)

def investigate_seed(seed, seed_type="auto", keys=None, context="",
                     fetcher=None, search_fetcher=None, image_fetcher=None):
    """Dispatch any seed type. Returns (Investigation, v7_section dict).
    fetcher: (url, headers) -> (status, body) for Gravatar/RDAP/HN/Mastodon.
    search_fetcher: (query) -> [{title,url,snippet}] for dorks.
    This is the single entry point used by both the CLI and the GUI, so
    the two never diverge."""
    keys = dict(keys or {})
    st = (seed_type or "auto").lower()
    if st == "auto":
        st = detect_seed_type(seed)
    section = {"seed_type_resolved": st, "context": context or ""}
    inv = None
    from ..core.engine import run_investigation
    from ..core.models import Profile
    from ..core.provenance import utc_now_iso
    from ..adapters.base import Evidence

    def _audit(action, detail):
        inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v7",
                          "action": action, "detail": detail})

    if st == "username" or st == "domain":
        inv = run_investigation(seed, keys=keys, seed_type=st)
        section["base"] = {"status": "found" if inv.profiles else "not_found",
                           "note": "Existing v6 username/domain investigation."}
    elif st == "email":
        v = validate_email(seed)
        section["validation"] = v
        if not v["valid"]:
            inv = _blank_investigation(seed, "email", keys)
            section["gravatar"] = {"status": "not_found", "note": v["note"]}
            section["dorks"] = {"status": "not_found", "results": []}
            _audit("email_seed_invalid", {"domain": None})
            return inv, section
        inv = run_investigation(v["domain"], keys=keys, seed_type="domain")
        inv.seed, inv.seed_type = v["email"], "email"
        grav = gravatar_lookup(v["email"], fetcher=fetcher)
        section["gravatar"] = grav
        if grav.get("status") == "found":
            f = grav["fields"]
            username = (f["username"]["value"] or f["display_name"]["value"] or v["email"].split("@")[0])
            links = f["linked_accounts"]["value"] or []
            prof = Profile(platform="gravatar", username=str(username),
                           display_name=str(f["display_name"]["value"] or ""),
                           bio="", bio_links=list(links), status="candidate",
                           evidence=[Evidence(source_url=grav["source_url"],
                                              captured_at_utc=utc_now_iso(),
                                              method="public_api", platform="gravatar",
                                              field="profile_url", value=str(f["profile_url"]["value"] or grav["source_url"]),
                                              confidence=90)])
            inv.profiles.append(prof)
        section["dorks"] = email_dorks(v["email"], keys=keys, search_fetcher=search_fetcher)
        section["domain"] = v["domain"]
        _audit("email_seed", {"domain": v["domain"], "gravatar_status": grav.get("status"),
                              "dork_status": section["dorks"].get("status")})
        # Note: analysis already ran inside run_investigation for the
        # domain; re-running it here doubled the live cost for no gain.
    elif st == "name":
        inv = _blank_investigation(seed, "name", keys)
        section["name"] = name_search(seed, context=context, keys=keys, search_fetcher=search_fetcher)
        _audit("name_seed", {"candidates": len(section["name"].get("candidates", [])),
                             "status": section["name"].get("status")})
    elif st == "url":
        detail = url_seed_detail(seed, keys=keys)
        section["url"] = detail
        parsed = detail["parsed"]
        if looks_like_image_url(seed):
            inv, img_section = investigate_seed(seed, "image", keys=keys,
                                                image_fetcher=image_fetcher)
            section["image"] = img_section.get("image")
            inv.seed, inv.seed_type = seed, "url"
            _audit("url_seed_image", {"platform": parsed.get("platform")})
            return inv, section
        if parsed.get("username"):
            inv = run_investigation(parsed["username"], keys=keys, seed_type="username")
            inv.seed, inv.seed_type = seed, "url"
        else:
            inv = _blank_investigation(seed, "url", keys)
        _audit("url_seed", {"platform": parsed.get("platform"), "kind": parsed.get("kind"),
                            "username": parsed.get("username")})
    elif st == "image":
        inv = _blank_investigation(seed, "image", keys)
        section["image"] = image_seed_detail(seed, keys=keys, image_fetcher=image_fetcher)
        _audit("image_seed", {"status": section["image"].get("status")})
    elif st == "hashtag":
        inv = _blank_investigation(seed, "hashtag", keys)
        hs = hashtag_search(seed, fetcher=fetcher, keys=keys)
        section["hashtag"] = hs
        seen_authors = {}
        for post in hs.get("posts", []):
            a = post.get("author")
            if a and post.get("platform") == "mastodon" and a not in seen_authors:
                seen_authors[a] = post
                inv.profiles.append(Profile(platform="mastodon", username=a, status="candidate",
                                            bio="", evidence=[Evidence(source_url=post.get("url") or "",
                                                captured_at_utc=utc_now_iso(), method="public_api",
                                                platform="mastodon", field="hashtag_post",
                                                value=f"#{hs.get('tag')}", confidence=70)]))
        _audit("hashtag_seed", {"posts": len(hs.get("posts", [])), "status": hs.get("status")})
    elif st == "phrase":
        inv = _blank_investigation(seed, "phrase", keys)
        section["phrase"] = phrase_search(seed, fetcher=fetcher, keys=keys, search_fetcher=search_fetcher)
        _audit("phrase_seed", {"status": section["phrase"].get("status")})
    elif st == "ip":
        inv = _blank_investigation(seed, "ip", keys)
        section["ip"] = ip_seed_detail(seed, fetcher=fetcher)
        _audit("ip_seed", {"status": section["ip"].get("status")})
    else:
        inv = run_investigation(seed, keys=keys, seed_type="username")
        section["base"] = {"status": "not_checked", "note": f"Unknown seed type {st!r}; ran as username."}
    return inv, section

def investigate_multi(seed_text, keys=None, context="",
                      fetcher=None, search_fetcher=None, image_fetcher=None):
    """Multi-seed case: seeds separated by ';' (comma also accepted when
    a part is not an email/name). Each sub-seed is dispatched with its
    own auto-detected type; results are merged with provenance kept
    per sub-seed — profiles are NOT merged into one identity, they are
    collected into one case file for human review."""
    parts = [p.strip() for p in re.split(r";", seed_text or "") if p.strip()]
    if len(parts) <= 1 and "," in (seed_text or ""):
        parts = [p.strip() for p in seed_text.split(",") if p.strip()]
    investigations, sections = [], {}
    from ..core.engine import run_investigation
    merged = None
    for part in parts:
        st = detect_seed_type(part)
        inv, section = investigate_seed(part, st, keys=keys, context=context,
                                        fetcher=fetcher, search_fetcher=search_fetcher,
                                        image_fetcher=image_fetcher)
        sections[part] = {"seed_type": st, "section": section}
        if merged is None:
            merged = inv
            merged.seed, merged.seed_type = seed_text, "multi"
        else:
            seen = {f"{p.platform}:{p.username}" for p in merged.profiles}
            for p in inv.profiles:
                if f"{p.platform}:{p.username}" not in seen:
                    merged.profiles.append(p); seen.add(f"{p.platform}:{p.username}")
            merged.edges.extend(inv.edges)
            merged.audit.extend(inv.audit)
            merged.possible_matches.extend(inv.possible_matches)
    if merged is None:
        merged = _blank_investigation(seed_text or "", "multi", keys)
    return merged, {"sub_seeds": sections,
                    "note": "Multi-seed case: profiles from different seeds are collected, not identity-merged. A human must confirm any link between them; see the candidate review queue."}

def build_v7_dossier(payload, seed, seed_type="auto", keys=None, v7_section=None,
                     include_dorks=True):
    """v6 dossier + v7 sections + candidate queue. Payload is the
    investigation dict (asdict) for the (possibly dispatched) case."""
    from .v6 import build_dossier, strip_keys
    base_seed = seed
    # For dispatched seeds, v6 public-web collectors keyed on the raw
    # seed would be wrong (e.g. instagram.com/<email>); disable them and
    # dorks (v7 runs its own, correctly-typed dorks).
    plain = seed_type in ("username", "domain")
    dossier = build_dossier(payload, base_seed, keys=keys,
                            include_dorks=include_dorks and plain,
                            include_public_web=plain)
    dossier["version"] = VERSION
    dossier["seed_type"] = v7_section.get("seed_type_resolved", seed_type) if v7_section else seed_type
    dossier["v7"] = v7_section or {}
    # Possible matches live on the investigation payload, mirror for queue
    if isinstance(payload, dict) and payload.get("possible_matches"):
        dossier["possible_matches"] = payload["possible_matches"]
    dossier["candidate_review_queue"] = build_candidate_queue(dossier)
    dossier["honest_limits"] = list(dossier.get("honest_limits", [])) + [
        "Name/email candidates are leads (search_snippet / gravatar public profile), never a certain identity match.",
        "Image seed = same-photo reuse, OCR and key-gated reverse image only — never face identification.",
        "IP seed = passive RDAP + InternetDB only — no port scan, no person is identified from an IP in this tool.",
    ]
    if not dossier.get("profile_summary") and dossier.get("no_profiles_found_note"):
        # Keep the v6 honest note; v7 dispatched seeds may still have
        # found section data (gravatar/candidates/posts) — say so.
        found_sections = [k for k, v in (v7_section or {}).items()
                          if isinstance(v, dict) and v.get("status") == "found"]
        if found_sections:
            dossier["no_profiles_found_note"] += f" Note: v7 section(s) returned data: {', '.join(found_sections)}."
    return strip_keys(dossier)

def export_v7_dossier(dossier, out_dir):
    """v6 exports + Maltego CSV + Obsidian folder."""
    from .v6 import export_dossier
    paths = export_dossier(dossier, out_dir)
    with open(os.path.join(out_dir, "maltego.csv"), "w") as fh:
        fh.write(maltego_csv(dossier))
    paths["maltego.csv"] = os.path.join(out_dir, "maltego.csv")
    paths.update(obsidian_folder(dossier, out_dir))
    return paths
