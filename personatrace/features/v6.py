"""PersonaTrace v6.0.0-final — key-first, free-fallback, provenance-labelled dossier.

Built from the deep-research blueprint (2026-10-29). This module does NOT
invent data. Every field it produces carries a status from the taxonomy:

  found | not_found | not_checked | blocked | gated_paid | gated_login
  | private | search_snippet | derived

Rules kept from the blueprint and from v5:
- Public data only. No private accounts/DMs, no live location, no face
  identification, no bulk personal-data export (follower contact lists
  are never exported), no active port scanning.
- Stop on 429 / CAPTCHA / login wall / challenge. Never retry in a loop,
  never solve a CAPTCHA, never sign requests (no X-Bogus / X-Argus style
  signing, no private-API request signing).
- Keys are never logged, never echoed, never included in exports, never
  baked into the ZIP. The local vault file is chmod 0600 and git-ignored.
- A key route runs FIRST for its field when a key is present and verified;
  free routes are the fallback, in the order: official free API ->
  public web -> search/dork -> consented login opt-in -> labelled status.
- Demo data never appears in a live run. Live 0-profile results show an
  explicit "no profiles found, routes tried" record, never demo_user_01.
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter

VERSION = "6.0.0-final"

STATUSES = (
    "found", "not_found", "not_checked", "blocked", "gated_paid",
    "gated_login", "private", "search_snippet", "derived",
)

# ------------------------------------------------------------------ helpers
def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def field(value=None, source="", method="", status="not_checked", note=""):
    """One provenance-labelled field. status must be in STATUSES."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return {"value": value, "source": source, "method": method,
            "status": status, "fetched_at_utc": now_iso(), "note": note}

def strip_keys(obj):
    """Recursively remove anything that looks like a key/secret from a payload."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            # v7 fix: 'auth' as a bare substring also stripped innocent
            # fields like 'author'; match auth keys precisely instead.
            if any(t in lk for t in ("api_key", "apikey", "token", "secret", "password", "sessionid")) or lk == "auth" or lk.startswith("auth_") or lk in ("authorization", "authorisation"):
                continue
            out[k] = strip_keys(v)
        return out
    if isinstance(obj, list):
        return [strip_keys(x) for x in obj]
    return obj

# ------------------------------------------------------------------ key vault
def default_vault_path():
    return os.path.join(os.getcwd(), ".personatrace_keys.json")

def save_key(name, value, path=None):
    """Save one key locally, chmod 0600. Returns name only, never the value."""
    path = path or default_vault_path()
    data = {}
    if os.path.exists(path):
        try:
            data = json.load(open(path))
        except Exception:
            data = {}
    data[str(name)] = str(value)
    # Write atomically-ish, then lock permissions.
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return {"key": str(name), "stored": "local_vault_0600", "path": path}

def load_keys(path=None):
    path = path or default_vault_path()
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path))
        return {str(k): str(v) for k, v in data.items() if v}
    except Exception:
        return {}

def delete_key(name, path=None):
    path = path or default_vault_path()
    data = load_keys(path)
    data.pop(str(name), None)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return {"key": str(name), "deleted": True}

def ensure_gitignore(path=None):
    """Add the vault filename to .gitignore in the working dir if absent."""
    gi = os.path.join(os.getcwd(), ".gitignore")
    line = ".personatrace_keys.json"
    try:
        existing = open(gi).read() if os.path.exists(gi) else ""
        if line not in existing:
            with open(gi, "a") as fh:
                fh.write((existing and not existing.endswith("\n") and "\n" or "") + line + "\n")
            return True
    except Exception:
        pass
    return False

# ------------------------------------------------------------ provider catalog
PROVIDERS = {
    "hikerapi_key": {
        "label": "HikerAPI (Instagram aggregator)",
        "unlocks": "Instagram profile, posts, followers/following lists, comments, likers (paginated, billed per request)",
        "verify_url": "https://api.hikerapi.com/v2/user/by/username?username=instagram",
        "verify_header": "x-access-key",
        "cost_preview": "Estimate only: ~$1 per 1,000 requests in 2026 vendor round-ups; 100 free requests reported. Verify the provider's current price at setup; pagination is billed separately.",
        "env": "HIKERAPI_KEY",
    },
    "youtube_api_key": {
        "label": "YouTube Data API v3",
        "unlocks": "YouTube channels, videos, comments, captions",
        "verify_url": "https://www.googleapis.com/youtube/v3/channels?part=id&forHandle=YouTube",
        "verify_header": None,
        "cost_preview": "Free quota 10,000 units/day reported; search.list = 100 units, channels/playlistItems = 1 unit. Verify in Google Cloud console.",
        "env": "YOUTUBE_API_KEY",
    },
    "brave_search_key": {
        "label": "Brave Search API",
        "unlocks": "Google/Bing-style dorking via a search API (site:instagram.com etc.), snippets only",
        "verify_url": "https://api.search.brave.com/res/v1/web/search?q=instagram",
        "verify_header": "X-Subscription-Token",
        "cost_preview": "Free tier reported ~2,000 queries/month in 2026 round-ups; verify the provider's own quota response at setup.",
        "env": "BRAVE_SEARCH_KEY",
    },
    "tavily_api_key": {
        "label": "Tavily Search API",
        "unlocks": "Search/dork queries, snippets only",
        "verify_url": None,
        "verify_header": None,
        "cost_preview": "Free tier reported 1,000 credits/month in 2026 round-ups; verify at setup.",
        "env": "TAVILY_API_KEY",
    },
    "serper_api_key": {
        "label": "Serper (Google Search API)",
        "unlocks": "Search/dork queries, snippets only",
        "verify_url": None,
        "verify_header": None,
        "cost_preview": "2,500 one-time credits reported; verify at setup.",
        "env": "SERPER_API_KEY",
    },
    "github_token": {
        "label": "GitHub personal access token",
        "unlocks": "GitHub 5,000 req/hour instead of 60/hour unauthenticated; public repos, followers, orgs",
        "verify_url": "https://api.github.com/user",
        "verify_header": "Authorization",
        "cost_preview": "Free token; no cash cost.",
        "env": "GITHUB_TOKEN",
    },
    "shodan_api_key": {
        "label": "Shodan API",
        "unlocks": "Full Shodan host search (InternetDB below is the free, no-key subset)",
        "verify_url": "https://api.shodan.io/api-info",
        "verify_header": None,
        "cost_preview": "Provider plan price; verify at setup. InternetDB (no key) is free for non-commercial use.",
        "env": "SHODAN_API_KEY",
    },
    "licensed_aggregator_key": {
        "label": "Licensed aggregator (generic)",
        "unlocks": "Instagram, X, TikTok, Reddit live via the investigator's aggregator base URL",
        "verify_url": None,
        "verify_header": None,
        "cost_preview": "Provider price; set a per-run spend cap before running (see estimate_cost).",
        "env": "PERSONATRACE_AGGREGATOR_KEY",
    },
}

def verify_key(provider, key, fetcher=None):
    """Verify a key against its provider's cheapest endpoint.

    Returns {provider, verified, cost_preview, next_step} — never the key.
    `fetcher` is an injectable (url, headers) -> (status, json_or_text) for tests;
    in production it does one GET with a 5s timeout, no retry on 429/401.
    A 401/403 means 'key invalid'; 429 means 'blocked, do not retry';
    any other failure means 'could not verify, key not accepted as verified'.
    """
    info = PROVIDERS.get(provider)
    if not info:
        return {"provider": provider, "verified": False, "cost_preview": "",
                "next_step": f"Unknown provider {provider}; add it to PROVIDERS in features/v6.py first."}
    if not key:
        return {"provider": provider, "verified": False, "cost_preview": info["cost_preview"],
                "next_step": f"Add {provider} (env {info['env']}) to unlock: {info['unlocks']}"}
    url = info.get("verify_url")
    if not url:
        # No cheap verification endpoint documented for this provider:
        # accept as 'present, unverified' — never claim verified.
        return {"provider": provider, "verified": False, "present": True,
                "cost_preview": info["cost_preview"],
                "next_step": "Key present but not verified (no cheap verification endpoint for this provider). It will be tried on the first real run and disabled for that run on 401/403."}
    headers = {"User-Agent": "PersonaTrace/6.0-final (key verification)"}
    if info.get("verify_header") == "x-access-key":
        headers["x-access-key"] = key
    elif info.get("verify_header") == "Authorization":
        headers["Authorization"] = f"Bearer {key}"
    elif url.startswith("https://www.googleapis.com/youtube"):
        url = url + "&key=" + urllib.parse.quote(key)
    elif url.startswith("https://api.search.brave.com"):
        headers["X-Subscription-Token"] = key
    elif url.startswith("https://api.shodan.io"):
        url = url + "?key=" + urllib.parse.quote(key)
    try:
        if fetcher is not None:
            status, _body = fetcher(url, headers)
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:
        return {"provider": provider, "verified": False, "cost_preview": info["cost_preview"],
                "next_step": f"Could not reach provider to verify ({exc}); key not accepted as verified. Check network, then retry once."}
    if status == 200:
        return {"provider": provider, "verified": True, "cost_preview": info["cost_preview"],
                "next_step": f"Verified. Unlocks: {info['unlocks']}"}
    if status in (401, 403):
        return {"provider": provider, "verified": False, "cost_preview": info["cost_preview"],
                "next_step": "Provider rejected the key (401/403). Check the key, rotate it if it was ever shared, and re-enter it."}
    if status == 429:
        return {"provider": provider, "verified": False, "cost_preview": info["cost_preview"],
                "next_step": "Provider rate-limited the verification (429). Wait, then retry once. Do not retry in a loop."}
    return {"provider": provider, "verified": False, "cost_preview": info["cost_preview"],
            "next_step": f"Provider returned HTTP {status} on verification; key not accepted as verified."}

def estimate_cost(plan, cap=None):
    """plan: list of {provider, requests, price_per_1000_usd or None}.
    Returns estimated cost and whether the cap would abort the run.
    A None price means 'provider price, unknown here' — never invented."""
    total_requests = 0
    total_usd = 0.0
    unknown = []
    for item in plan or []:
        n = int(item.get("requests", 0))
        total_requests += n
        price = item.get("price_per_1000_usd")
        if price is None:
            unknown.append(item.get("provider", "?"))
        else:
            total_usd += n * float(price) / 1000.0
    result = {"requests": total_requests, "estimated_usd": round(total_usd, 4),
              "unknown_price_providers": unknown,
              "cap": cap, "would_exceed_cap": (cap is not None and total_usd > float(cap))}
    if result["would_exceed_cap"]:
        result["action"] = "ABORT before running: estimated cost exceeds the per-run spend cap. Reduce requests or raise the cap deliberately."
    elif unknown:
        result["action"] = "Cost is partial: some providers have no price in this estimate. Check their plan before running; the cap above covers only priced requests."
    else:
        result["action"] = "Within cap."
    return result

# ------------------------------------------------------------ pacing / http
_LAST_CALL = {"t": 0.0}
def _pace(seconds=3.0):
    if seconds <= 0:
        return
    now = time.time()
    wait = seconds - (now - _LAST_CALL["t"])
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL["t"] = time.time()

def _http_get(url, headers=None, timeout=5, fetcher=None, pace_seconds=3.0):
    """One GET, no retry. Returns (status_or_None, body_text, error_or_None).
    A 429/401/403 is returned, never retried, never bypassed."""
    _pace(pace_seconds)
    hdrs = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
    if headers:
        hdrs.update(headers)
    if fetcher is not None:
        try:
            status, body = fetcher(url, hdrs)
            return status, (body if isinstance(body, str) else json.dumps(body)), None
        except Exception as exc:
            return None, "", str(exc)
    # curl_cffi impersonation if installed (better TLS fingerprint for IG/TikTok);
    # otherwise stdlib httpx-style urllib with a browser UA.
    try:
        from curl_cffi import requests as _cffi  # type: ignore
        resp = _cffi.get(url, headers=hdrs, timeout=timeout, impersonate="chrome")
        return resp.status_code, resp.text, None
    except ImportError:
        pass
    except Exception as exc:
        return None, "", str(exc)
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", str(exc)

# Collector result cache, keyed by seed+platform, for the dossier builder
# to reuse what the adapters already fetched instead of re-hitting a site.
_COLLECTOR_CACHE = {}
def record_collector(seed, platform, result):
    _COLLECTOR_CACHE[(str(seed), str(platform))] = result
    return result
def cached_collector(seed, platform):
    return _COLLECTOR_CACHE.get((str(seed), str(platform)))

# ------------------------------------------------------------ public web collectors
def instagram_public_web(seed, fetcher=None, pace_seconds=3.0):
    """Anonymous Instagram profile header via web_profile_info, then __a=1.
    Returns a dict with status + fields (each field is a provenance field).
    On private: status private, header only if returned. On 429/login wall:
    status blocked, no data, no retry."""
    cached = cached_collector(seed, "instagram_web")
    if cached is not None:
        return cached
    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={urllib.parse.quote(seed)}"
    status, body, err = _http_get(url, headers={"x-ig-app-id": "936619743392459"}, fetcher=fetcher, pace_seconds=pace_seconds)
    data = None
    if status == 200 and body:
        try:
            data = json.loads(body).get("data", {}).get("user")
        except Exception:
            data = None
    if data:
        def _f(name, value, note=""):
            return field(value, f"https://www.instagram.com/{seed}/", "public_web", "found" if value not in (None, "") else "not_found", note)
        result = {
            "platform": "instagram", "method": "public_web", "url": f"https://www.instagram.com/{seed}/",
            "status": "private" if data.get("is_private") else "found",
            "fields": {
                "username": _f("username", data.get("username")),
                "display_name": _f("display_name", data.get("full_name")),
                "bio": _f("bio", data.get("biography")),
                "external_url": _f("external_url", data.get("external_url")),
                "follower_count": _f("follower_count", (data.get("edge_followed_by") or {}).get("count") if isinstance(data.get("edge_followed_by"), dict) else data.get("follower_count")),
                "following_count": _f("following_count", (data.get("edge_follow") or {}).get("count") if isinstance(data.get("edge_follow"), dict) else data.get("following_count")),
                "post_count": _f("post_count", (data.get("edge_owner_to_timeline_media") or {}).get("count") if isinstance(data.get("edge_owner_to_timeline_media"), dict) else data.get("media_count")),
                "is_verified": _f("is_verified", data.get("is_verified")),
                "is_private": _f("is_private", data.get("is_private")),
                "profile_pic_url": _f("profile_pic_url", data.get("profile_pic_url")),
                "user_id": _f("user_id", data.get("id")),
            },
            "note": "Anonymous public-web header only. Posts, comments, followers list and stories are NOT returned by this route; they need an aggregator key or a consented login.",
        }
        return record_collector(seed, "instagram_web", result)
    if status in (401, 403, 429):
        return record_collector(seed, "instagram_web", {"platform": "instagram", "method": "public_web",
            "url": f"https://www.instagram.com/{seed}/", "status": "blocked",
            "fields": {}, "note": f"Instagram public web blocked this request (HTTP {status}). Stopped, not bypassed. Try an aggregator key, a consented login, or retry later from a different IP."})
    if status == 404:
        return record_collector(seed, "instagram_web", {"platform": "instagram", "method": "public_web",
            "url": f"https://www.instagram.com/{seed}/", "status": "not_found",
            "fields": {}, "note": "Instagram public web returned 404 for this username."})
    return record_collector(seed, "instagram_web", {"platform": "instagram", "method": "public_web",
        "url": f"https://www.instagram.com/{seed}/", "status": "not_checked",
        "fields": {}, "note": f"Instagram public web did not return a usable profile ({err or f'HTTP {status}'}). This is not a finding that no account exists."})

def tiktok_public_web(seed, fetcher=None, pace_seconds=3.0):
    cached = cached_collector(seed, "tiktok_web")
    if cached is not None:
        return cached
    url = f"https://www.tiktok.com/@{urllib.parse.quote(seed)}"
    status, body, err = _http_get(url, fetcher=fetcher, pace_seconds=pace_seconds)
    if status == 200 and body:
        # SIGI_STATE / rehydration blob, or JSON-LD, best-effort only.
        # Guard against false positives: the page's first "nickname" can
        # be a suggested/related account, not the target. Only accept
        # when the page actually carries this seed as its uniqueId.
        if not re.search(r'"uniqueId"\s*:\s*"' + re.escape(seed) + r'"', body):
            return record_collector(seed, "tiktok_web", {"platform": "tiktok", "method": "public_web", "url": url, "status": "not_checked", "fields": {},
                "note": "TikTok public page loaded but did not carry this username as its uniqueId (first nickname on the page may be a suggested account, not the target). Not claimed as a profile."})
        m = re.search(r'"nickname"\s*:\s*"([^"]+)"', body)
        bio_m = re.search(r'"signature"\s*:\s*"([^"]*)"', body)
        fc_m = re.search(r'"followerCount"\s*:\s*(\d+)', body)
        if m or bio_m:
            result = {"platform": "tiktok", "method": "public_web", "url": url, "status": "found",
                "fields": {
                    "username": field(seed, url, "public_web", "found"),
                    "display_name": field(m.group(1) if m else None, url, "public_web", "found" if m else "not_found"),
                    "bio": field(bio_m.group(1) if bio_m else None, url, "public_web", "found" if bio_m else "not_found"),
                    "follower_count": field(int(fc_m.group(1)) if fc_m else None, url, "public_web", "found" if fc_m else "not_found"),
                },
                "note": "Best-effort public page parse (SIGI_STATE/JSON-LD). An empty 200 or a 403 is a known TikTok failure mode; see status."}
            return record_collector(seed, "tiktok_web", result)
    if status in (401, 403, 429):
        return record_collector(seed, "tiktok_web", {"platform": "tiktok", "method": "public_web", "url": url, "status": "blocked", "fields": {},
            "note": f"TikTok public page blocked this request (HTTP {status}). Stopped, not bypassed. Try an aggregator key or a search dork."})
    return record_collector(seed, "tiktok_web", {"platform": "tiktok", "method": "public_web", "url": url, "status": "not_checked", "fields": {},
        "note": f"TikTok public page did not return a usable profile ({err or f'HTTP {status}'})."})

def x_public_web(seed, fetcher=None, pace_seconds=3.0):
    cached = cached_collector(seed, "x_web")
    if cached is not None:
        return cached
    url = f"https://x.com/{urllib.parse.quote(seed)}"
    status, body, err = _http_get(url, fetcher=fetcher, pace_seconds=pace_seconds)
    if status == 200 and body and "Log in" not in body[:2000] and "login" not in body[:500].lower():
        title = re.search(r"<title>(.*?)</title>", body, re.S)
        if title and f"(@{seed})".lower() in title.group(1).lower():
            return record_collector(seed, "x_web", {"platform": "x", "method": "public_web", "url": url, "status": "found",
                "fields": {"username": field(seed, url, "public_web", "found"),
                           "display_name": field(title.group(1).strip(), url, "public_web", "found")},
                "note": "Public X page title only. Timeline, followers and search are gated_paid (X API, pay-per-use) without a key."})
    if status in (401, 403, 429):
        return record_collector(seed, "x_web", {"platform": "x", "method": "public_web", "url": url, "status": "blocked", "fields": {},
            "note": f"X public page blocked this request (HTTP {status}). X search redirects to login; timeline/search are gated_paid."})
    return record_collector(seed, "x_web", {"platform": "x", "method": "public_web", "url": url, "status": "not_checked", "fields": {},
        "note": "X public page did not return a usable profile (login wall or empty page). Timeline/search need a paid X API key; see gated_paid."})

# ------------------------------------------------------------ search / dorking
DORK_TEMPLATES = [
    'site:instagram.com "{seed}"',
    'site:instagram.com/{seed}',
    'site:instagram.com/p/ "{seed}"',
    'site:tiktok.com/@{seed}',
    'site:tiktok.com/@{seed}/video/',
    'site:x.com "{seed}"',
    'site:github.com "{seed}"',
    'site:linkedin.com/in "{seed}"',
    '"{seed}" site:instagram.com OR site:tiktok.com OR site:x.com',
]

def dork_queries(seed):
    return [t.format(seed=seed) for t in DORK_TEMPLATES]

def search_dorks(seed, keys=None, fetcher=None, max_queries=12):
    """Run dorks via a search API key if present, else SearXNG env, else DDG HTML (fragile).
    Every result is labelled search_snippet and is unverified until opened.
    Returns {status, engine, results:[{query, title, url, snippet, status}], note}."""
    keys = dict(keys or {})
    queries = dork_queries(seed)[:max_queries]
    # Brave
    brave = keys.get("brave_search_key") or os.environ.get("BRAVE_SEARCH_KEY")
    if brave and fetcher is None:
        results = []
        for q in queries[:4]:  # cap search-key spend: 4 dorks, not 12
            try:
                req = urllib.request.Request("https://api.search.brave.com/res/v1/web/search?q=" + urllib.parse.quote(q),
                    headers={"X-Subscription-Token": brave, "User-Agent": "PersonaTrace/6.0-final"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                for item in (data.get("web", {}).get("results") or [])[:3]:
                    results.append({"query": q, "title": item.get("title", ""), "url": item.get("url", ""),
                                    "snippet": item.get("description", ""), "status": "search_snippet", "engine": "brave"})
            except Exception as exc:
                results.append({"query": q, "title": "", "url": "", "snippet": "", "status": "blocked", "engine": "brave", "note": str(exc)[:120]})
        return {"status": "search_snippet" if results else "not_checked", "engine": "brave", "results": results,
                "note": "Brave search API, capped to 4 dork queries. Snippets are unverified until the source URL is opened."}
    if fetcher is not None:
        # Test / injectable path: fetcher(query) -> list of {title, url, snippet}
        results = []
        for q in queries[:4]:
            try:
                for item in (fetcher(q) or [])[:3]:
                    results.append({"query": q, "title": item.get("title", ""), "url": item.get("url", ""),
                                    "snippet": item.get("snippet", ""), "status": "search_snippet", "engine": "injected"})
            except Exception as exc:
                results.append({"query": q, "title": "", "url": "", "snippet": "", "status": "blocked", "engine": "injected", "note": str(exc)[:120]})
        return {"status": "search_snippet" if results else "not_checked", "engine": "injected", "results": results,
                "note": "Injected search fetcher (tests / SearXNG). Snippets are unverified until opened."}
    # SearXNG if configured
    searx = os.environ.get("SEARXNG_URL", "").rstrip("/")
    if searx:
        results = []
        for q in queries[:4]:
            try:
                req = urllib.request.Request(searx + "/search?q=" + urllib.parse.quote(q) + "&format=json",
                    headers={"User-Agent": "PersonaTrace/6.0-final"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                for item in (data.get("results") or [])[:3]:
                    results.append({"query": q, "title": item.get("title", ""), "url": item.get("url", ""),
                                    "snippet": item.get("content", ""), "status": "search_snippet", "engine": "searxng"})
            except Exception:
                break
        if results:
            return {"status": "search_snippet", "engine": "searxng", "results": results,
                    "note": "Self-hosted SearXNG. Snippets are unverified until opened."}
    # Fragile DDG HTML fallback, one query set only, labelled as fragile.
    results = []
    try:
        req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(queries[0]),
            headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', body):
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            results.append({"query": queries[0], "title": title, "url": urllib.parse.unquote(m.group(1)),
                            "snippet": "", "status": "search_snippet", "engine": "duckduckgo_html"})
            if len(results) >= 5:
                break
    except Exception:
        pass
    return {"status": "search_snippet" if results else "not_checked", "engine": "duckduckgo_html",
            "results": results,
            "note": "DuckDuckGo HTML fallback is fragile and may return nothing; absence here is not absence on the platform. Add a Brave/Tavily/Serper key for reliable dorking."}

# ------------------------------------------------------------ archive / infra (free, no key)
def wayback_cdx(url, limit=20, fetcher=None):
    api = "https://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(url) + f"&output=json&filter=statuscode:200&collapse=digest&limit={limit}"
    if fetcher is not None:
        try:
            status, body = fetcher(api, {})
            rows = json.loads(body) if isinstance(body, str) else body
            return {"status": "found" if rows else "not_found", "snapshots": rows or [], "source": api}
        except Exception as exc:
            return {"status": "not_checked", "snapshots": [], "source": api, "note": str(exc)[:120]}
    try:
        req = urllib.request.Request(api, headers={"User-Agent": "PersonaTrace/6.0-final"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            rows = json.loads(resp.read().decode("utf-8", errors="replace"))
        return {"status": "found" if len(rows) > 1 else "not_found", "snapshots": rows or [], "source": api}
    except Exception as exc:
        return {"status": "not_checked", "snapshots": [], "source": api, "note": str(exc)[:120]}

def shodan_internetdb(ip):
    url = f"https://internetdb.shodan.io/{ip}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PersonaTrace/6.0-final"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return {"status": "found", "data": data, "source": url, "note": "InternetDB is free, no-key, weekly data; not a live port scan."}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "not_found", "data": {}, "source": url}
        return {"status": "blocked", "data": {}, "source": url, "note": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"status": "not_checked", "data": {}, "source": url, "note": str(exc)[:120]}

def youtube_oembed(video_or_channel_url):
    url = "https://www.youtube.com/oembed?url=" + urllib.parse.quote(video_or_channel_url) + "&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PersonaTrace/6.0-final"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return {"status": "found", "data": data, "source": url}
    except Exception as exc:
        return {"status": "not_checked", "data": {}, "source": url, "note": str(exc)[:120]}

# ------------------------------------------------------------ login opt-in (stub + session check)
LOGIN_CONSENT_TEXT = "I understand this may ban this account"

def login_consent_path():
    return os.path.join(os.getcwd(), ".personatrace_login_consent.json")

def record_login_consent(platform, confirmation, account_label="throwaway"):
    """Only a typed exact confirmation enables login. Returns bool.
    No password is ever stored here — only the consent record."""
    if confirmation != LOGIN_CONSENT_TEXT:
        return {"enabled": False, "note": f"Type exactly: {LOGIN_CONSENT_TEXT!r}. Login NOT enabled."}
    record = {"platform": platform, "account_label": account_label, "read_only": True,
              "warning": "Throwaway/research account only, never a primary account. Read-only: PersonaTrace will not follow, like, comment, DM or post. The account may be challenged or banned.",
              "consented_at_utc": now_iso()}
    with open(login_consent_path(), "w") as fh:
        json.dump(record, fh, indent=2)
    try:
        os.chmod(login_consent_path(), 0o600)
    except Exception:
        pass
    return {"enabled": True, "note": "Login opt-in recorded (consent only, no credentials stored). Now provide a session file, not a password, to enable the route."}

def login_status(platform):
    """Check consent + available login libraries / session files.
    Returns a labelled stub when the route cannot run — never fake data."""
    path = login_consent_path()
    if not os.path.exists(path):
        return {"platform": platform, "status": "gated_login",
                "note": "Login not enabled. To enable: run record_login_consent() with the exact confirmation text, using a throwaway account, read-only. No credentials are stored by PersonaTrace."}
    try:
        import instaloader  # noqa: F401
        instaloader_available = True
    except Exception:
        instaloader_available = False
    try:
        import instagrapi  # noqa: F401
        instagrapi_available = True
    except Exception:
        instagrapi_available = False
    session_files = [f for f in os.listdir(os.getcwd()) if f.endswith(".session") or "session" in f.lower() and f.endswith(".json")]
    return {"platform": platform, "status": "gated_login" if not (instaloader_available or instagrapi_available) else "not_checked",
            "instaloader_available": instaloader_available, "instagrapi_available": instagrapi_available,
            "session_files_found": session_files,
            "note": ("Login consented, but no login library is installed. Install with: pip install instaloader instagrapi, then import a session file (Instaloader: instaloader --login=YOUR_THROWAWAY --sessionfile=... ; instagrapi: dump_settings/load_settings). "
                     "Until a session file is present, this route returns gated_login, never data.")
            if not (instaloader_available or instagrapi_available) else
            "Login consented and a login library is present. Import a session file for the throwaway account, then re-run; read-only, single-threaded, stop on challenge/429."}

# ------------------------------------------------------------ dossier builder
def _profiles_from_payload(payload):
    if isinstance(payload, dict):
        return payload.get("profiles") or []
    return getattr(payload, "profiles", []) or []

def _edges_from_payload(payload):
    if isinstance(payload, dict):
        return payload.get("edges") or []
    return getattr(payload, "edges", []) or []

def _get_profile(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

def expand_bio_link(url, fetcher=None):
    """One hop only: fetch the bio URL, follow redirects (urllib does),
    return title + anchor destinations. No second hop, no JS."""
    if not url or not str(url).startswith("http"):
        return {"status": "not_checked", "url": url, "title": None, "links": [], "note": "No http(s) bio link to expand."}
    try:
        if fetcher is not None:
            status, body = fetcher(url, {})
            html_text = body if isinstance(body, str) else ""
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")
                url = resp.geturl()
                status = resp.status
        title_m = re.search(r"<title>(.*?)</title>", html_text or "", re.S | re.I)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else None
        links = []
        for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text or "", re.S | re.I):
            clean = re.sub(r"<[^>]+>", "", text).strip()
            if href.startswith("http"):
                links.append({"url": href, "text": clean[:80]})
            if len(links) >= 20:
                break
        return {"status": "found", "url": url, "title": title, "links": links,
                "note": "One hop only (bio link destination title + anchors). Destinations are not crawled further."}
    except Exception as exc:
        return {"status": "blocked" if "429" in str(exc) or "403" in str(exc) else "not_checked",
                "url": url, "title": None, "links": [], "note": str(exc)[:160]}

def build_dossier(payload, seed, keys=None, include_dorks=True, include_public_web=True):
    """Build the full dossier dict from a completed investigation payload.
    Every section is filled ONLY from collected data; empty sections carry
    their exact status and the route that would fill them. No LLM biography,
    no guessed domain/employer/connection, no demo data."""
    keys = dict(keys or {})
    # Demo mode: never fetch live URLs for a demo dossier. Demo profiles
    # are labelled demo data; fetching their fake bio links / archive
    # URLs would be slow and meaningless, and would mix live and demo.
    _demo_mode = os.environ.get("PERSONATRACE_DEMO") == "1"
    if _demo_mode:
        include_dorks = False
        include_public_web = False
    profiles = _profiles_from_payload(payload)
    edges = _edges_from_payload(payload)
    seed_val = seed
    # Profile summary: field table, first profile per platform, provenance per row.
    summary = []
    for p in profiles:
        if isinstance(p, dict):
            summary.append({
                "platform": p.get("platform"), "username": p.get("username"),
                "display_name": p.get("display_name"), "bio": p.get("bio"),
                "follower_count": p.get("follower_count"), "following_count": p.get("following_count"),
                "created_at": p.get("created_at"), "status": p.get("status"),
                "evidence": p.get("evidence") or [], "bio_links": p.get("bio_links") or [],
            })
    # Bio links, one hop
    bio_links = []
    seen_domains = []
    for p in summary:
        for link in p.get("bio_links") or []:
            expanded = {"status": "not_checked", "note": "Demo mode: bio-link expansion skipped."} if _demo_mode else (expand_bio_link(link) if link else {"status": "not_checked"})
            bio_links.append({"from_platform": p["platform"], "from_username": p["username"],
                              "bio_link": link, "expanded": expanded})
            try:
                host = urllib.parse.urlparse(link).netloc
                if host and host not in seen_domains:
                    seen_domains.append(host)
            except Exception:
                pass
    # Timeline: collected created_at + analysis timeline if present, deduped.
    timeline = []
    seen_tl = set()
    for p in summary:
        if p.get("created_at"):
            key_tl = ("profile_created", p["platform"], p["username"], p["created_at"])
            if key_tl not in seen_tl:
                seen_tl.add(key_tl)
                timeline.append({"date": p["created_at"], "kind": "profile_created", "platform": p["platform"], "text": f"{p['username']} profile created (as reported by {p['platform']})", "status": "found"})
    analysis = payload.get("analysis") if isinstance(payload, dict) else getattr(payload, "analysis", None)
    if isinstance(analysis, dict):
        for item in analysis.get("timeline") or []:
            txt = str(item.get("title") or item.get("description") or "")
            k = (str(item.get("date")), txt[:80])
            if k not in seen_tl:
                seen_tl.add(k)
                timeline.append({"date": item.get("date"), "kind": item.get("kind", "activity"), "platform": "", "text": txt, "status": "found"})
    timeline.sort(key=lambda x: str(x.get("date") or ""))
    # Interests: Counter over collected bios + captions if analysis has them, N stated.
    texts = []
    for p in summary:
        if p.get("bio"):
            texts.append(p["bio"])
    if isinstance(analysis, dict):
        for item in (analysis.get("hashtags") or {}):
            pass  # hashtags dict is already a counter; handled below
    hashtags = Counter()
    mentions = Counter()
    for t in texts:
        for h in re.findall(r"#(\w+)", t):
            hashtags[h.lower()] += 1
        for m in re.findall(r"@(\w+)", t):
            mentions[m.lower()] += 1
    if isinstance(analysis, dict) and isinstance(analysis.get("hashtags"), dict):
        for k, v in analysis["hashtags"].items():
            if isinstance(v, (int, float)):
                hashtags[k] += int(v)
    sample_n = len(texts)
    interests = {"sample_texts_n": sample_n,
                 "top_hashtags": hashtags.most_common(20),
                 "top_mentions": mentions.most_common(20),
                 "status": "derived" if sample_n else "not_checked",
                 "note": f"Counter over {sample_n} collected bio/caption texts only. This is topics in the sample, not a persona. If sample_n is 0, interests are not_checked, not guessed."}
    # Mentions by vs of, kept separate
    mentions_by = [{"handle": h, "count": c, "status": "derived"} for h, c in mentions.most_common(20)]
    mentions_of = []
    # Work history: sourced rows only
    work_rows = []
    for p in summary:
        ev = p.get("evidence") or []
        for e in ev:
            if isinstance(e, dict) and e.get("field") in ("company", "location"):
                work_rows.append({"platform": p["platform"], "username": p["username"], "field": e["field"], "value": e["value"], "source_url": e.get("source_url"), "status": "found"})
    # Network graph: edges only from observed data
    graph_edges = []
    for e in edges:
        if isinstance(e, dict):
            graph_edges.append({"from": e.get("from_id"), "to": e.get("to_id"), "kind": e.get("kind"), "confidence": e.get("confidence")})
        else:
            graph_edges.append({"from": getattr(e, "from_id", ""), "to": getattr(e, "to_id", ""), "kind": getattr(e, "kind", ""), "confidence": getattr(e, "confidence", 0)})
    # Same-handle unverified edges for cross-platform same username
    by_username = {}
    for p in summary:
        by_username.setdefault(p["username"], []).append(p["platform"])
    for username, plats in by_username.items():
        if len(plats) > 1:
            for i in range(len(plats)):
                for j in range(i + 1, len(plats)):
                    graph_edges.append({"from": f"{plats[i]}:{username}", "to": f"{plats[j]}:{username}", "kind": "same_handle_unverified", "confidence": 40})
    # Public web + dorks (only if requested; adapters may already have cached them)
    public_web = {}
    if include_public_web:
        public_web["instagram"] = instagram_public_web(seed_val, pace_seconds=0)
        public_web["tiktok"] = tiktok_public_web(seed_val, pace_seconds=0)
        public_web["x"] = x_public_web(seed_val, pace_seconds=0)
    dorks = None
    if include_dorks:
        dorks = search_dorks(seed_val, keys=keys)
    # Archive snapshots for profile URLs + bio domains (capped: first 2 profiles + domains, demo skipped)
    archive = []
    if not _demo_mode:
        for p in summary[:2]:
            for e in (p.get("evidence") or []):
                if isinstance(e, dict) and e.get("source_url", "").startswith("http"):
                    archive.append({"url": e["source_url"], "wayback": wayback_cdx(e["source_url"], limit=5)})
                    break
        for d in seen_domains[:3]:
            archive.append({"url": f"https://{d}/", "wayback": wayback_cdx(f"https://{d}/", limit=5)})
    # Domain / infra only for domains actually found
    domain_infra = []
    for d in seen_domains:
        row = {"domain": d, "rdap_status": "not_checked", "dns_status": "not_checked", "crtsh_status": "not_checked", "internetdb_status": "not_checked", "note": "Passive lookups only; no active port scan. Registrant identity is redacted in RDAP and is never unmasked."}
        domain_infra.append(row)
    dossier = {
        "version": VERSION, "seed": seed_val,
        "profile_summary": summary,
        "profile_summary_status": "found" if summary else "not_found",
        "bio_links": bio_links, "bio_link_domains_found": seen_domains,
        "network_graph": {"nodes": [{"platform": p["platform"], "username": p["username"]} for p in summary], "edges": graph_edges,
                          "note": "Edges are only from observed follows/comments/tags/mentions/same-handle-unverified. No edge is drawn from a snippet alone."},
        "timeline": {"items": timeline, "denominator": f"{len(timeline)} timeline items from collected profiles/activity; total posts across platforms unknown unless a source returned a count.",
                     "status": "found" if timeline else "not_checked"},
        "interests": interests,
        "public_comments": {"items": [], "status": "not_checked",
                            "note": "Comments are only the comments returned with collected posts (see analysis.comments if present). Capped samples, never a full history. Without an aggregator key or login, Instagram comments are gated_paid/gated_login."},
        "mentions": {"by_target": mentions_by, "of_target": mentions_of,
                     "note": "Mentions by vs of are kept separate. Mentions-of from search are search_snippet only until opened."},
        "work_history": {"rows": work_rows,
                         "status": "found" if work_rows else "not_checked",
                         "note": "Sourced rows only (e.g. GitHub company/location, bio-link about page, search snippet). No job is listed without a source row."},
        "follower_following_overlap": {"status": "not_checked",
                                       "note": "Overlap requires two ID sets (target + a second handle supplied by the investigator, both collected via key/login). Without both sets, overlap is not_checked, never guessed. Bulk follower contact export is prohibited."},
        "archive_snapshots": archive,
        "domain_infra": domain_infra,
        "public_web": public_web,
        "search_dorks": dorks,
        "login_optin": login_status("instagram"),
        "routes_tried": [],
        "honest_limits": [
            "Instagram/X/TikTok full data (followers list, full comments, likers, stories) need an aggregator key or a consented throwaway login; without either they are gated_paid/gated_login, not not_found.",
            "Search snippets are unverified until opened; absence from search is not absence from the platform.",
            "Private profiles: header only if public; no private content is attempted.",
            "No face identification, no live location, no bulk personal-data export, no active port scanning, stop on 429/CAPTCHA/login wall.",
        ],
    }
    if isinstance(analysis, dict) and analysis.get("comments"):
        dossier["public_comments"] = {"items": analysis["comments"], "status": "found",
                                      "note": "Comments from analysis, capped samples from collected posts only."}
    # Routes tried: from investigation audit if present
    if isinstance(payload, dict):
        for entry in payload.get("audit") or []:
            if isinstance(entry, dict) and entry.get("action") == "adapter_search":
                dossier["routes_tried"].append(entry.get("detail"))
    if not summary:
        dossier["no_profiles_found_note"] = (f"No profiles found for '{seed_val}' on the free sources tried, and Instagram/X/TikTok are gated without a key/login. "
                                             "This is a real, checkable result: see routes_tried, public_web, and search_dorks above. Add a key (see USER_GUIDE.md) or enable the login opt-in, then re-run.")
    return strip_keys(dossier)

def export_dossier(dossier, out_dir):
    """Write JSON + CSV + Markdown + HTML exports. Keys are already stripped in build_dossier."""
    import csv, html as _html, io
    os.makedirs(out_dir, exist_ok=True)
    clean = strip_keys(dossier)
    with open(os.path.join(out_dir, "dossier.json"), "w") as fh:
        json.dump(clean, fh, indent=2, default=str)
    # CSV: one row per profile, one per graph edge
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["platform", "username", "display_name", "bio", "follower_count", "following_count", "created_at", "status"])
    for p in clean.get("profile_summary", []):
        w.writerow([p.get("platform"), p.get("username"), p.get("display_name"), p.get("bio"), p.get("follower_count"), p.get("following_count"), p.get("created_at"), p.get("status")])
    with open(os.path.join(out_dir, "dossier_profiles.csv"), "w") as fh:
        fh.write(buf.getvalue())
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["from", "to", "kind", "confidence"])
    for e in clean.get("network_graph", {}).get("edges", []):
        w.writerow([e.get("from"), e.get("to"), e.get("kind"), e.get("confidence")])
    with open(os.path.join(out_dir, "dossier_edges.csv"), "w") as fh:
        fh.write(buf.getvalue())
    lines = [f"# PersonaTrace dossier — {clean.get('seed')} (v{VERSION})", "",
             f"Profile summary status: {clean.get('profile_summary_status')}",
             f"Profiles found: {len(clean.get('profile_summary', []))}",
             f"Bio-link domains found: {', '.join(clean.get('bio_link_domains_found', [])) or 'none'}",
             "", "## Profiles"]
    for p in clean.get("profile_summary", []):
        lines.append(f"- {p.get('platform')}: {p.get('username')} — {p.get('bio') or ''} (followers: {p.get('follower_count')})")
    lines += ["", "## Honest limits"] + [f"- {x}" for x in clean.get("honest_limits", [])]
    if clean.get("no_profiles_found_note"):
        lines += ["", "## No profiles found", clean["no_profiles_found_note"]]
    with open(os.path.join(out_dir, "dossier.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    rows = "".join(f"<tr><td>{_html.escape(str(p.get('platform')))}</td><td>{_html.escape(str(p.get('username')))}</td><td>{_html.escape(str(p.get('bio') or ''))}</td></tr>" for p in clean.get("profile_summary", []))
    html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>PersonaTrace dossier {clean.get('seed')}</title></head><body><h1>Dossier: {clean.get('seed')}</h1><p>Version {VERSION} — provenance per field in dossier.json</p><table><tr><th>Platform</th><th>Username</th><th>Bio</th></tr>{rows}</table><p>{_html.escape(clean.get('no_profiles_found_note',''))}</p></body></html>"
    with open(os.path.join(out_dir, "dossier.html"), "w") as fh:
        fh.write(html_doc)
    return {"dossier.json": os.path.join(out_dir, "dossier.json"), "dossier_profiles.csv": os.path.join(out_dir, "dossier_profiles.csv"),
            "dossier_edges.csv": os.path.join(out_dir, "dossier_edges.csv"), "dossier.md": os.path.join(out_dir, "dossier.md"), "dossier.html": os.path.join(out_dir, "dossier.html")}
