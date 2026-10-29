"""PersonaTrace v8.0.0 — Direct Profile Mode + power upgrades.

Built on v7 (features/v7.py is unchanged). Adds, in one module so the
pattern of v3..v7 is kept:

  #1  Direct Profile Mode (seed type "profile", --direct on url seeds):
      fetch THAT exact profile first (GitHub API with token + retry /
      backoff + public-web fallback — the GitHub-403 fix; GitLab,
      Bluesky, Mastodon-instance, YouTube oEmbed, Reddit .json, gated
      aggregator route, and a generic OpenGraph fetch for ANY other /
      unknown host), anchor it as status "confirmed_anchor" (the
      investigator supplied it), snapshot it with a SHA256, then expand
      with the normal username investigation and all dossier features.
  #2  The same GitHub helper is used by the free GitHub adapter.
  #3  verify_all_keys(): per-provider verified / invalid / blocked /
      present_unverified / not_checked harness (--verify-keys).
  #4  Gated full-data wiring: aggregator profile fetch requesting
      posts, comments, followers, following, stories, highlights.
  #5  Name search free fallbacks: SearXNG -> DuckDuckGo HTML, every
      result labelled search_snippet (fragile, honest).
  #6  Parallel adapter execution (ThreadPool) for v8 runs.
  #7  24 extra site-presence / archive entries (presence-check only
      unless a live check is explicitly run).
  #8  Company seed: staff/author leads from the site's own pages.
  #9  Email depth: Gravatar linked accounts expanded to URL leads.
  #10 Smarter matching signals (shared bio-link domain, website,
      language, posting-hours overlap, shared outbound links) on top
      of core confidence; style/timing cap rules unchanged.
  #11 Username variations + city / birth-years / initials / name swap.
  #12 Configurable comment limit (PERSONATRACE_COMMENT_LIMIT env,
      set by --comment-limit; wired into features/social.py).
  #13 Real follower/following overlap where a free source returns ID
      sets (GitHub), otherwise honest not_checked.
  #14 Video section: public captions via the existing timedtext
      route, transcription key / local Whisper detection, and the
      already-collected title/description text as topics. No fake
      transcripts, ever.
  #15 Photo variant checks: centre-crop + resized pHash variants —
      whole-image only, never face identification.
  #16 Stories/highlights: aggregator-key route only.
  #17 Archive diff with Wayback + archive.today as second source.
  #18 Watch alert delivery: webhook / SMTP email / Telegram senders,
      config-gated, not_configured when unset.
  #19 Network graph levels 1-4.
  #20 Coordinated check + shared-rare-follower signal.
  #21 Behaviour upgrade: reply-speed, posting gaps, topic/language
      shift, all with sample denominators.
  #22 Impersonation finder (leads, never assertions).
  #23 Scam/fraud signals from collected public text only.
  #24 Wallet seed (BTC/ETH format validation + public-post search +
      free public blockchain address basics — address data only).
  #25 Plate seed: public-post phrase search ONLY. No vehicle
      database, no owner lookup.
  #26 Case teamwork fields (assigned_to, lead_status) on the v5
      case registry.
  #27 Court-style report export (chronological, sourced, hashed).
  #28 Proof cards: Pillow PNG "snapshot proof card" per profile (NOT
      a browser screenshot) + proof_index.json.
  #29 Offline mode: rebuild dossier/exports from a saved case with
      zero network calls.
  #30 GUI: v8 seed types + direct toggle (server.py / static files).

Hard limits, unchanged from v6/v7: public data only; no private
accounts or DMs; no live location of a person; NO face identification;
no phone people-search; no password/breach data; no bulk personal-data
export; no CAPTCHA / rate-limit / login-wall bypass (a single request,
then stop and label); no active port scans. Keys are the
investigator's own, never bundled, never logged or exported. Key
routes are wired and mock-tested; without a real key they are
reported not_checked / gated_paid / present_unverified — never as
live-proven.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION = "8.0.0"

SEED_TYPES_V8 = ("profile", "company", "wallet", "plate")

INNOCENT_EXPLANATIONS = [
    "A different person with the same name / a common name",
    "A recycled or re-registered handle",
    "An impersonator or fan / parody account",
    "A namesake business, character, or organisation",
    "An old account the person no longer controls",
    "Coincidence: shared hashtag, phrase, or employer with no other link",
]

_UA = "PersonaTrace/8.0 (public-data lookup)"
_SNAPSHOT_CAP = 50_000


# ------------------------------------------------------------ http core
def _normalise_body(body):
    if body is None:
        return ""
    if isinstance(body, (dict, list)):
        return json.dumps(body)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)


def http_fetch(url, headers=None, fetcher=None, timeout=8):
    """One GET. Returns (status_or_None, body_text, final_url).

    fetcher (injectable, tests): (url, headers) -> (status, body).
    Never retries, never bypasses a block: the caller decides.
    """
    hdrs = {"User-Agent": _UA}
    if headers:
        hdrs.update(headers)
    if fetcher is not None:
        try:
            status, body = fetcher(url, hdrs)
            return status, _normalise_body(body), url
        except Exception as exc:
            return None, "", url
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl() if hasattr(resp, "geturl") else url
            return resp.status, resp.read().decode("utf-8", errors="replace"), final
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body, url
    except Exception:
        return None, "", url


def http_json(url, headers=None, fetcher=None, timeout=8):
    status, text, final = http_fetch(url, headers=headers, fetcher=fetcher, timeout=timeout)
    data = None
    if text:
        try:
            data = json.loads(text)
        except Exception:
            data = None
    return status, data, text, final


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


# ------------------------------------------------------- OpenGraph parse
_META_RE = re.compile(r"<meta[^>]+>", re.I)
_ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*\"([^\"]*)\"|([\w:-]+)\s*=\s*'([^']*)'")


def parse_opengraph(html_text: str) -> dict:
    """Extract og:/twitter:/description meta + <title> from a page."""
    out = {}
    if not html_text:
        return out
    for tag in _META_RE.findall(html_text):
        attrs = {}
        for m in _ATTR_RE.finditer(tag):
            key = m.group(1) or m.group(3)
            val = m.group(2) if m.group(2) is not None else m.group(4)
            if key:
                attrs[key.lower()] = _html.unescape(val or "")
        prop = attrs.get("property") or attrs.get("name") or ""
        content = attrs.get("content")
        if prop and content is not None:
            out[prop] = content
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    if m:
        out["<title>"] = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    link = re.search(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)", html_text, re.I)
    if link:
        out["canonical"] = link.group(1)
    return out


def _og_fields(og: dict) -> dict:
    title = og.get("og:title") or og.get("<title>") or ""
    return {
        "display_name": title,
        "bio": og.get("og:description") or og.get("description") or og.get("twitter:description") or "",
        "avatar_url": og.get("og:image") or og.get("twitter:image") or "",
        "site_name": og.get("og:site_name") or "",
        "page_title": title,
    }


# ------------------------------------------------------------ GitHub fix
def github_profile_fetch(username, keys=None, fetcher=None, sleeper=None):
    """GitHub profile with token support, 403/429 retry+backoff, and a
    public-web OpenGraph fallback. Shared by Direct Profile Mode and
    (via adapters/free.py) the normal username adapter.

    sleeper is injectable so tests never actually wait.
    """
    keys = dict(keys or {})
    sleep = sleeper if sleeper is not None else time.sleep
    token = keys.get("github_token") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api_url = f"https://api.github.com/users/{urllib.parse.quote(username)}"
    routes = []
    status, data, _text, _f = (None, None, "", "")
    for attempt in range(3):
        status, data, _text, _f = http_json(api_url, headers=headers, fetcher=fetcher)
        routes.append({"route": "github_api", "attempt": attempt + 1, "status": status})
        if status == 200 and isinstance(data, dict):
            return {
                "status": "found", "route": "github_api", "routes": routes,
                "username": data.get("login", username),
                "display_name": data.get("name") or "",
                "bio": data.get("bio") or "",
                "bio_links": [data["blog"]] if data.get("blog") else [],
                "follower_count": data.get("followers"),
                "following_count": data.get("following"),
                "created_at": data.get("created_at") or "",
                "avatar_url": data.get("avatar_url") or "",
                "profile_url": data.get("html_url") or f"https://github.com/{username}",
                "company": data.get("company") or "", "location": data.get("location") or "",
                "method": "public_api", "snapshot_text": json.dumps(data)[:_SNAPSHOT_CAP],
                "note": "GitHub public API" + (" (authenticated with the investigator's token)" if token else "") + ".",
            }
        if status == 404:
            return {"status": "not_found", "route": "github_api", "routes": routes,
                    "username": username, "profile_url": f"https://github.com/{username}",
                    "note": "GitHub API returned 404 for this exact username."}
        if status in (403, 429) and attempt < 2:
            sleep(2 if attempt == 0 else 5)
            continue
        break
    # Public-web fallback: fetch the exact public profile page once.
    web_url = f"https://github.com/{urllib.parse.quote(username)}"
    fb = github_web_fallback(username, fetcher=fetcher)
    routes.append({"route": "github_web", "status": fb.get("http_status")})
    if fb.get("status") == "found":
        return {**fb, "route": "github_web_fallback", "routes": routes,
                "note": "GitHub API was unavailable (see routes); fields are derived from the public profile page's OpenGraph/meta only — counts and dates are not available on this route."}
    return {"status": "degraded", "route": None, "routes": routes,
            "username": username, "profile_url": web_url,
            "note": f"GitHub API status {status} after retries and the public-web fallback returned {fb.get('http_status')}. No data was fabricated; re-run later or add a GitHub token."}


def github_web_fallback(username, fetcher=None):
    """The shared public-web fallback: one fetch of the exact public
    GitHub profile page, OpenGraph/meta fields only (derived). Used by
    github_profile_fetch and by the free GitHub adapter on API 403."""
    web_url = f"https://github.com/{urllib.parse.quote(username)}"
    wstatus, wtext, _wf = http_fetch(web_url, fetcher=fetcher)
    if wstatus == 200 and wtext:
        og = _og_fields(parse_opengraph(wtext))
        name = re.split(r"\s*[·(]", og["display_name"])[0].strip()
        return {"status": "found", "username": username, "display_name": name,
                "bio": og["bio"], "bio_links": [], "follower_count": None,
                "following_count": None, "created_at": "",
                "avatar_url": og["avatar_url"], "profile_url": web_url,
                "method": "public_web", "derived": True, "http_status": wstatus,
                "snapshot_text": wtext[:_SNAPSHOT_CAP]}
    return {"status": "blocked" if wstatus in (401, 403, 429) else "degraded",
            "http_status": wstatus, "username": username, "profile_url": web_url,
            "snapshot_text": ""}


def github_id_sets(username, keys=None, fetcher=None):
    """Follower/following login sets for one GitHub user (free API)."""
    keys = dict(keys or {})
    token = keys.get("github_token") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    out = {}
    for kind in ("followers", "following"):
        url = f"https://api.github.com/users/{urllib.parse.quote(username)}/{kind}?per_page=100"
        status, data, _t, _f = http_json(url, headers=headers, fetcher=fetcher)
        if status == 200 and isinstance(data, list):
            out[kind] = sorted({d.get("login") for d in data if isinstance(d, dict) and d.get("login")})
        else:
            out[kind] = None
            out[kind + "_status"] = status
    return out


def follower_overlap(anchor_user, other_user, keys=None, fetcher=None, id_sets=None):
    """#13: real overlap from GitHub ID sets; honest not_checked else."""
    if id_sets is None:
        a = github_id_sets(anchor_user, keys=keys, fetcher=fetcher)
        b = github_id_sets(other_user, keys=keys, fetcher=fetcher)
    else:
        a, b = id_sets
    if a.get("followers") is None or b.get("followers") is None:
        return {"status": "not_checked",
                "note": "Follower ID sets were not returned for both users on a free route; overlap is not guessed."}
    af, bf = set(a["followers"]), set(b["followers"])
    ag, bg = set(a.get("following") or []), set(b.get("following") or [])
    return {"status": "found", "source": "github public API (followers/following lists)",
            "anchor": anchor_user, "other": other_user,
            "common_followers": sorted(af & bf), "common_followers_count": len(af & bf),
            "common_following": sorted(ag & bg), "common_following_count": len(ag & bg),
            "anchor_followers_sample_n": len(af), "other_followers_sample_n": len(bf),
            "note": "First 100 entries per list (API page size). Overlap is computed from those collected sets only."}


# ------------------------------------------------- gated full-data route
GATED_FIELDS_REQUESTED = ["profile", "posts", "comments", "followers",
                          "following", "likers", "stories", "highlights"]


def gated_full_fetch(platform, username, keys=None, fetcher=None):
    """#4/#16: one aggregator profile call requesting the full field
    set. Without key+base URL: honest not_checked / degraded and the
    list of fields that WOULD be requested. Mock-tested only — this
    route has never been live-proven (no key was supplied)."""
    keys = dict(keys or {})
    from ..adapters.gated import _find_base_url, _find_key
    key = _find_key(platform, keys)
    base = _find_base_url(keys)
    if not key:
        return {"status": "not_checked", "platform": platform, "username": username,
                "fields_requested": GATED_FIELDS_REQUESTED, "posts": [], "comments": [],
                "followers": [], "following": [], "stories": [], "highlights": [],
                "note": f"No licensed aggregator key configured for {platform}; full data (posts/comments/followers/following/stories/highlights) is gated_paid and was not fetched."}
    if not base:
        return {"status": "degraded", "platform": platform, "username": username,
                "fields_requested": GATED_FIELDS_REQUESTED, "posts": [], "comments": [],
                "followers": [], "following": [], "stories": [], "highlights": [],
                "note": "Aggregator key present but no aggregator base URL configured; no call was made."}
    include = ",".join(GATED_FIELDS_REQUESTED[1:])
    url = (f"{base}/v1/profile?platform={urllib.parse.quote(platform)}"
           f"&username={urllib.parse.quote(username)}&include={urllib.parse.quote(include)}")
    status, data, _t, _f = http_json(url, headers={"Authorization": f"Bearer {key}"}, fetcher=fetcher)
    if status != 200 or not isinstance(data, dict):
        return {"status": "degraded" if status != 404 else "not_found", "platform": platform,
                "username": username, "fields_requested": GATED_FIELDS_REQUESTED,
                "posts": [], "comments": [], "followers": [], "following": [],
                "stories": [], "highlights": [],
                "note": f"Aggregator returned HTTP {status}; no full data was used."}
    cand = data
    if isinstance(data.get("profile"), dict):
        cand = {**data["profile"]}
        for k in GATED_FIELDS_REQUESTED[1:]:
            if k in data:
                cand[k] = data[k]
    def _lst(v):
        return v if isinstance(v, list) else []
    return {"status": "found", "platform": platform,
            "username": str(cand.get("username") or cand.get("handle") or username),
            "display_name": str(cand.get("display_name") or ""),
            "bio": str(cand.get("bio") or cand.get("description") or ""),
            "follower_count": cand.get("followers_count") or cand.get("followers"),
            "following_count": cand.get("following_count") or cand.get("following"),
            "profile_url": str(cand.get("url") or cand.get("profile_url") or ""),
            "fields_requested": GATED_FIELDS_REQUESTED,
            "posts": _lst(cand.get("posts")), "comments": _lst(cand.get("comments")),
            "followers": _lst(cand.get("followers")) if not isinstance(cand.get("followers"), int) else [],
            "following": _lst(cand.get("following")) if not isinstance(cand.get("following"), int) else [],
            "stories": _lst(cand.get("stories")), "highlights": _lst(cand.get("highlights")),
            "method": "licensed_aggregator",
            "note": "Full data returned by the investigator's licensed aggregator for this exact profile. Route is mock-tested; verify the provider's field names on first live use."}


def stories_highlights_section(platform, username, keys=None, fetcher=None):
    """#16: stories/highlights exist only behind the aggregator key."""
    r = gated_full_fetch(platform, username, keys=keys, fetcher=fetcher)
    if r["status"] != "found":
        return {"status": "gated_paid" if r["status"] == "not_checked" else r["status"],
                "platform": platform, "stories": [], "highlights": [], "note": r["note"]}
    return {"status": "found" if (r["stories"] or r["highlights"]) else "not_checked",
            "platform": platform, "stories": r["stories"], "highlights": r["highlights"],
            "note": "Stories/highlights returned by the aggregator for this profile." if (r["stories"] or r["highlights"]) else "Aggregator returned no stories/highlights fields for this profile."}


# ------------------------------------------------------- key verify (#3)
def verify_all_keys(keys=None, fetcher=None):
    """Verify every catalogued provider. No keys -> all not_checked
    (that IS the honest live result without keys)."""
    keys = dict(keys or {})
    from .v6 import verify_key, PROVIDERS
    from .v7 import providers_v7
    catalog = providers_v7()
    rows, counts = [], Counter()
    for name in sorted(catalog):
        value = keys.get(name) or os.environ.get(catalog[name].get("env", ""), "")
        if not value:
            rows.append({"provider": name, "status": "not_checked", "verified": False,
                         "note": f"No key supplied. Unlocks: {catalog[name].get('unlocks', '')}"})
            counts["not_checked"] += 1
            continue
        if name in PROVIDERS and catalog[name].get("verify_url"):
            r = verify_key(name, value, fetcher=fetcher)
            nxt = r.get("next_step", "")
            if r.get("verified"):
                st = "verified"
            elif "rejected" in nxt:
                st = "invalid"
            elif "rate-limited" in nxt:
                st = "blocked"
            else:
                st = "present_unverified"
            rows.append({"provider": name, "status": st, "verified": bool(r.get("verified")), "note": nxt})
        else:
            rows.append({"provider": name, "status": "present_unverified", "verified": False,
                         "note": "Key present; provider has no cheap verification endpoint, so it is not claimed verified. It will be tried on the first real run."})
            st = "present_unverified"
        counts[st] += 1
    return {"status": "found" if any(k for k in keys.values()) else "not_checked",
            "providers": rows, "counts": dict(counts),
            "note": "Verified = the provider's cheap endpoint returned 200 for this key just now. present_unverified is never reported as verified."}


# -------------------------------------------- name free fallbacks (#5)
SEARXNG_DEFAULT_BASES = ["https://searx.be", "https://search.bus-hit.me"]


def _searxng_results(query, fetcher=None, bases=None):
    for base in (bases or SEARXNG_DEFAULT_BASES):
        base = (os.environ.get("SEARXNG_BASE_URL") or base).rstrip("/")
        status, data, _t, _f = http_json(f"{base}/search?q={urllib.parse.quote(query)}&format=json",
                                         fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and data.get("results"):
            return [{"title": r.get("title", ""), "url": r.get("url", ""),
                     "snippet": r.get("content", "")} for r in data["results"][:5]]
    return []


def _ddg_html_results(query, fetcher=None):
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    status, text, _f = http_fetch(url, fetcher=fetcher)
    if status != 200 or not text:
        return []
    out = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
        href = _html.unescape(m.group(1))
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        out.append({"title": re.sub(r"<[^>]+>", "", m.group(2)).strip(), "url": href, "snippet": ""})
        if len(out) >= 5:
            break
    return out


def free_search_chain(query, fetcher=None):
    """SearXNG public instance(s), then DuckDuckGo HTML. Snippets only."""
    results = _searxng_results(query, fetcher=fetcher)
    if results:
        return results
    return _ddg_html_results(query, fetcher=fetcher)


def name_search_v8(name, context="", keys=None, search_fetcher=None, fetcher=None):
    from .v7 import name_search
    keys = dict(keys or {})
    if search_fetcher is not None:
        return name_search(name, context=context, keys=keys, search_fetcher=search_fetcher)
    if keys.get("brave_search_key") or os.environ.get("BRAVE_SEARCH_KEY"):
        return name_search(name, context=context, keys=keys)
    out = name_search(name, context=context, keys={},
                      search_fetcher=lambda q: free_search_chain(q, fetcher=fetcher))
    out["engine_chain"] = ["searxng_public", "duckduckgo_html"]
    out["note"] = (out.get("note", "") + " Free fallback chain used (no search key): "
                   "SearXNG public instance, then DuckDuckGo HTML. This chain is fragile — "
                   "instances rate-limit and HTML layouts change; 0 results here means "
                   "not_checked, not that the person is absent.").strip()
    if out.get("status") == "not_checked" and not out.get("candidates"):
        out["status"] = "not_checked"
    return out


# ------------------------------------------------------ parallel run (#6)
class _CachedAdapter:
    def __init__(self, orig, result):
        self._orig = orig
        self._result = result
        self.name = getattr(orig, "name", type(orig).__name__)
        self.platform = getattr(orig, "platform", self.name)

    def status(self, keys):
        return "active"

    def search(self, seed, keys):
        return self._result


def run_parallel_investigation(seed, keys=None, parallel=4, seed_type="username",
                               progress=True, adapters=None):
    """Pre-run adapter searches in a ThreadPool, then hand cached
    results to the normal engine (resolution/analysis unchanged)."""
    from ..core.engine import run_investigation
    keys = dict(keys or {})
    if not parallel or int(parallel) <= 1:
        return run_investigation(seed, keys=keys, seed_type=seed_type)
    if adapters is None:
        from ..adapters.registry import ADAPTERS
        adapter_list = list(ADAPTERS.values())
    else:
        adapter_list = list(adapters.values()) if isinstance(adapters, dict) else list(adapters)
    cached = {}

    def _one(ad):
        try:
            return ad.search(seed, keys)
        except Exception as exc:
            from ..adapters.base import AdapterResult
            return AdapterResult(profiles=[], status="degraded", message=str(exc)[:160])

    with ThreadPoolExecutor(max_workers=int(parallel)) as ex:
        futs = {ex.submit(_one, ad): ad for ad in adapter_list}
        for fut in as_completed(futs):
            ad = futs[fut]
            res = fut.result()
            cached[id(ad)] = res
            if progress:
                n = len(getattr(res, "profiles", []) or [])
                print(f"  [parallel] {getattr(ad, 'platform', '?')}: "
                      f"{getattr(res, 'status', '?')} — {n} profile(s)")
    wrapped = [_CachedAdapter(ad, cached[id(ad)]) for ad in adapter_list]
    return run_investigation(seed, adapters=wrapped, keys=keys, seed_type=seed_type)


# -------------------------------------------------- site presence (#7)
SITE_CHECKS_V8 = [
    {"service": "lemmy", "url": "https://lemmy.world/u/{u}", "kind": "presence"},
    {"service": "medium", "url": "https://medium.com/@{u}", "kind": "presence"},
    {"service": "substack", "url": "https://{u}.substack.com", "kind": "presence"},
    {"service": "devto", "url": "https://dev.to/{u}", "kind": "presence"},
    {"service": "quora", "url": "https://www.quora.com/profile/{u}", "kind": "presence"},
    {"service": "pinterest", "url": "https://www.pinterest.com/{u}/", "kind": "presence"},
    {"service": "snapchat", "url": "https://www.snapchat.com/add/{u}", "kind": "presence"},
    {"service": "twitch", "url": "https://www.twitch.tv/{u}", "kind": "presence"},
    {"service": "kick", "url": "https://kick.com/{u}", "kind": "presence"},
    {"service": "steam", "url": "https://steamcommunity.com/id/{u}", "kind": "presence"},
    {"service": "xbox", "url": "https://account.xbox.com/en-us/profile?gamertag={u}", "kind": "presence"},
    {"service": "playstation", "url": "https://psnprofiles.com/{u}", "kind": "presence"},
    {"service": "spotify", "url": "https://open.spotify.com/user/{u}", "kind": "presence"},
    {"service": "soundcloud", "url": "https://soundcloud.com/{u}", "kind": "presence"},
    {"service": "vimeo", "url": "https://vimeo.com/{u}", "kind": "presence"},
    {"service": "dailymotion", "url": "https://www.dailymotion.com/{u}", "kind": "presence"},
    {"service": "flickr", "url": "https://www.flickr.com/photos/{u}/", "kind": "presence"},
    {"service": "goodreads", "url": "https://www.goodreads.com/{u}", "kind": "presence"},
    {"service": "strava", "url": "https://www.strava.com/athletes/{u}", "kind": "presence"},
    {"service": "producthunt", "url": "https://www.producthunt.com/@{u}", "kind": "presence"},
    {"service": "angellist", "url": "https://angel.co/u/{u}", "kind": "presence"},
    {"service": "keybase", "url": "https://keybase.io/{u}", "kind": "presence"},
    {"service": "gravatar", "url": "https://gravatar.com/{u}", "kind": "presence"},
    {"service": "reddit_archive", "url": "https://arctic-shift.photon-reddit.com/search?author={u}", "kind": "archive"},
]


def site_presence_checks(username, live=False, fetcher=None):
    """Presence-check entries. Default: URL patterns only, labelled
    presence_check_only (a constructed URL is never a claim). With
    live=True each URL gets ONE request: 404=not_found, 200=candidate
    (open to verify), 403/429=blocked."""
    out = []
    for entry in SITE_CHECKS_V8:
        url = entry["url"].format(u=urllib.parse.quote(str(username)))
        row = {"service": entry["service"], "url": url, "kind": entry["kind"],
               "status": "presence_check_only"}
        if live:
            status, _t, _f = http_fetch(url, fetcher=fetcher)
            row["status"] = ("candidate_open_to_verify" if status == 200 else
                             "not_found" if status == 404 else
                             "blocked" if status in (401, 403, 429) else "not_checked")
            row["http_status"] = status
        out.append(row)
    return {"status": "found", "count": len(out), "checks": out,
            "note": "Lightweight presence checks via the site-list machinery. A candidate is not a confirmed account — open the link and verify. Services without a reliable not-found signal are presence-check only."}


# ------------------------------------------------------- company (#8)
_COMPANY_PATHS = ["/", "/about", "/about-us", "/team", "/our-team", "/company", "/people"]


def _extract_links(html_text, base_url):
    links = []
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text or "", re.S | re.I):
        clean = re.sub(r"<[^>]+>", "", text or "").strip()
        links.append({"url": urllib.parse.urljoin(base_url, href), "text": clean[:80]})
    return links


def company_seed(domain, keys=None, fetcher=None):
    """Fetch the site's own public pages (single hop) and collect
    staff/author LEADS: external profile links published on those
    pages, and the team/about pages themselves. A lead is never
    asserted to be an employee without the source page saying so."""
    d = (domain or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if not d or "." not in d:
        return {"status": "not_found", "domain": d, "staff_candidates": [],
                "note": "A company seed needs a domain, e.g. example.com."}
    pages, candidates, seen = [], [], set()
    for path in _COMPANY_PATHS:
        url = f"https://{d}{path}"
        status, text, _f = http_fetch(url, fetcher=fetcher)
        page = {"url": url, "status": "found" if status == 200 else
                ("not_found" if status == 404 else "not_checked"), "http_status": status}
        pages.append(page)
        if status != 200 or not text:
            continue
        for link in _extract_links(text, url):
            u = link["url"]
            if u in seen:
                continue
            host = (urllib.parse.urlparse(u).hostname or "").lower()
            if any(h in host for h in ("linkedin.com", "github.com", "x.com", "twitter.com")) and len(urllib.parse.urlparse(u).path.strip("/").split("/")) >= 1 and link["text"]:
                seen.add(u)
                candidates.append({"label": link["text"], "url": u, "source_url": url,
                                   "status": "lead",
                                   "note": "Profile link published on the company's own public page. A lead only — the page context decides whether this person is staff, an author, a partner, or a testimonial."})
            elif any(seg in u for seg in ("/team", "/about")) and host.endswith(d):
                seen.add(u)
                candidates.append({"label": link["text"] or u, "url": u, "source_url": url,
                                   "status": "lead",
                                   "note": "Team/about page on the company site itself; open it for the staff/author list the company publishes."})
    return {"status": "found" if candidates else ("found" if any(p["status"] == "found" for p in pages) else "not_checked"),
            "domain": d, "pages_fetched": pages, "staff_candidates": candidates[:40],
            "note": "Single-hop fetch of the company's own public pages only. Staff candidates are leads with source URLs, never asserted employees."}


# --------------------------------------------------------- email (#9)
def gravatar_linked_leads(gravatar_result):
    """Expand a found Gravatar profile's public linked accounts one
    hop: each linked URL becomes a parsed URL-seed lead."""
    from .v7 import parse_url_seed
    grav = gravatar_result or {}
    if grav.get("status") != "found":
        return {"status": "not_checked", "leads": [],
                "note": "No public Gravatar profile was found for the seed email, so there are no linked accounts to expand."}
    linked = ((grav.get("fields") or {}).get("linked_accounts") or {}).get("value") or []
    leads = []
    for u in linked:
        parsed = parse_url_seed(u)
        leads.append({"url": u, "platform": parsed.get("platform"),
                      "username": parsed.get("username"), "kind": parsed.get("kind"),
                      "status": "lead",
                      "note": "Public linked account published inside the Gravatar entry. A lead — run it as a profile/url seed to verify."})
    return {"status": "found" if leads else "not_found", "leads": leads,
            "note": "One hop only, from URLs the Gravatar profile itself publishes."}


# ------------------------------------------------------- matching (#10)
def _domain_of(url):
    try:
        return (urllib.parse.urlparse(str(url)).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def score_pair_v8(a: dict, b: dict) -> dict:
    """Extended explained scoring on top of core edge_confidence.
    Extra signals: shared bio-link domain, shared website, shared
    language, shared outbound links. Posting-hours overlap is fed in
    as the 'timing' signal, so the core 25-point style/timing cap
    still applies to it."""
    from ..core.confidence import edge_confidence, classify_merge
    a = a or {}; b = b or {}
    signals = []
    if (a.get("username") or "").lower() and (a.get("username") or "").lower() == (b.get("username") or "").lower():
        signals.append(("exact_username", 0.40, 1.0))
    a_domains = {_domain_of(u) for u in (a.get("bio_links") or [])}
    b_domains = {_domain_of(u) for u in (b.get("bio_links") or [])}
    shared_domains = sorted(x for x in (a_domains & b_domains) if x)
    if shared_domains:
        signals.append(("bio_link", 0.30, 1.0))
    aw, bw = _domain_of(a.get("website") or ""), _domain_of(b.get("website") or "")
    if aw and aw == bw:
        signals.append(("shared_website", 0.20, 1.0))
    if a.get("language") and a.get("language") == b.get("language"):
        signals.append(("shared_language", 0.10, 1.0))
    a_out = {str(u) for u in (a.get("outbound_links") or [])}
    b_out = {str(u) for u in (b.get("outbound_links") or [])}
    if a_out and b_out and (a_out & b_out):
        signals.append(("shared_outbound_links", 0.15, min(1.0, len(a_out & b_out) / 3.0)))
    ah, bh = set(a.get("posting_hours") or []), set(b.get("posting_hours") or [])
    if ah and bh:
        overlap = len(ah & bh) / max(len(ah | bh), 1)
        if overlap > 0:
            signals.append(("timing", 0.25, round(overlap, 3)))
    if a.get("avatar_hash") and a.get("avatar_hash") == b.get("avatar_hash"):
        signals.append(("avatar_reuse", 0.30, 1.0))
    score, band, drivers = edge_confidence(signals)
    return {"score": score, "band": band, "drivers": drivers,
            "signals": [s[0] for s in signals], "shared_bio_link_domains": shared_domains,
            "decision": classify_merge(score),
            "note": "Explained signals only. Style/timing (including posting-hours overlap) is capped at a combined 25 points by the core scorer and can never be the sole merge basis."}


# ----------------------------------------------------- variations (#11)
def variations_v8(seed, city="", years=None, limit=90):
    from ..core.variations import generate_variations
    base = generate_variations(seed, limit=limit)
    out = list(base)

    def add(v):
        if v and v not in out:
            out.append(v)
    s = (seed or "").strip().lower()
    if city:
        c = re.sub(r"[^a-z0-9]", "", city.lower())
        if c:
            add(s + c); add(s + "_" + c); add(c + s)
    for y in (years or []):
        add(s + str(y)); add(s + "_" + str(y))
    parts = [p for p in re.split(r"[._\-\s]+", s) if p]
    if len(parts) == 2:
        first, last = parts
        for delim in ("", "_", "."):
            add(delim.join([last, first]))
        add(first[0] + last)
        add(first + last[0])
        add(first[0] + "_" + last)
    out = out[: int(limit) if limit else 90]
    return {"variations": out, "count": len(out),
            "params": {"city": city or "", "years": [str(y) for y in (years or [])]},
            "history_note": "Every variation checked in a run is recorded in the case audit (variations_history), so old/handle variants tried are never silently forgotten or re-claimed as new."}


# ------------------------------------------------------- comments (#12)
SOURCE_COMMENT_NOTES = {
    "hackernews": "HN Algolia returns comment hits per page; the tool limit applies on top.",
    "bluesky": "Bluesky thread replies are collected per collected post; the source caps thread depth.",
    "mastodon": "Mastodon context replies are collected per collected status.",
    "github": "GitHub comments come from collected public activity where returned.",
    "reddit": "Reddit archive (Arctic Shift) is historical (~36h lag reported), not live.",
    "youtube": "YouTube commentThreads caps at 50 results per call and needs a key.",
}


def apply_comment_limit(comments, limit=100):
    comments = list(comments or [])
    try:
        limit = int(limit)
    except Exception:
        limit = 100
    return {"status": "found" if comments else "not_checked",
            "limit": limit, "collected": len(comments),
            "items": comments[:limit], "truncated": len(comments) > limit,
            "per_source_notes": SOURCE_COMMENT_NOTES,
            "note": "The limit is configurable (--comment-limit / PERSONATRACE_COMMENT_LIMIT). The collection in features/social.py honours it for HN/YouTube page sizes and final caps; a source's own cap is labelled per source above."}


# ------------------------------------------------------------ video (#14)
def video_section(items, keys=None, fetcher=None):
    """items: collected video dicts {video_id?, url?, title?, description?}.
    Captions via the existing public timedtext route for YouTube IDs;
    transcription only via an investigator key or a local Whisper
    install — detected, never faked."""
    keys = dict(keys or {})
    out_items = []
    whisper = False
    try:
        import shutil
        whisper = bool(shutil.which("whisper"))
    except Exception:
        whisper = False
    has_key = bool(keys.get("transcription_api_key") or keys.get("openai_api_key")
                   or os.environ.get("TRANSCRIPTION_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    for it in (items or [])[:10]:
        row = {"url": it.get("url") or it.get("source_url") or "",
               "title": it.get("title") or "", "description": it.get("description") or it.get("text") or "",
               "text_topics_status": "derived" if (it.get("title") or it.get("text")) else "not_checked",
               "transcript": {"status": "not_checked"}}
        vid = it.get("video_id") or ""
        if not vid and "watch?v=" in row["url"]:
            vid = row["url"].split("watch?v=", 1)[1].split("&", 1)[0]
        if vid:
            try:
                from .transcript import fetch_transcript
                tr = fetch_transcript(vid)
                row["transcript"] = {"status": tr.get("status"), "lang": tr.get("lang"),
                                     "text": (tr.get("text") or "")[:2000] or None,
                                     "note": "Public captions published for this video (timedtext route)." if tr.get("text") else tr.get("message", "")}
            except Exception as exc:
                row["transcript"] = {"status": "not_checked", "note": str(exc)[:120]}
        elif has_key or whisper:
            row["transcript"] = {"status": "not_checked",
                                 "note": "A transcription key / local Whisper is configured, but this item has no YouTube video ID and no downloadable audio route was run in this build; no transcript was fabricated."}
        else:
            row["transcript"] = {"status": "not_checked",
                                 "note": "No captions route, no transcription key, and no local Whisper install detected."}
        out_items.append(row)
    return {"status": "found" if out_items else "not_checked", "items": out_items,
            "whisper_detected": whisper, "transcription_key_present": has_key,
            "note": "Title/description text is used as topics and is labelled derived; it is never presented as a transcript."}


# ------------------------------------------------------------ photo (#15)
def photo_variant_check(image_bytes, collected: list, fetcher=None):
    """Compare the seed image against collected images using the
    original, a centre-crop, and a resized variant (whole-image pHash
    only — never face identification)."""
    from .phash import ahash, hamming, is_image_bytes
    if not image_bytes or not is_image_bytes(image_bytes):
        return {"status": "not_checked", "matches": [],
                "note": "Seed bytes are not a supported image; no variant check was run."}
    variants = {"original": image_bytes}
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as im:
            im = im.convert("RGB")
            w, h = im.size
            crop = im.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
            buf = io.BytesIO(); crop.save(buf, format="PNG")
            variants["centre_crop"] = buf.getvalue()
            small = im.resize((max(8, w // 4), max(8, h // 4)))
            buf = io.BytesIO(); small.save(buf, format="PNG")
            variants["resized"] = buf.getvalue()
    except Exception as exc:
        return {"status": "not_checked", "matches": [], "note": f"Variant generation failed ({str(exc)[:100]}); Pillow is required."}
    hashes = {name: ahash(data) for name, data in variants.items()}
    matches = []
    for i, other in enumerate(collected or []):
        if not other or not is_image_bytes(other):
            continue
        oh = ahash(other)
        dists = {name: hamming(hv, oh) for name, hv in hashes.items()}
        best = min(dists.values())
        if best <= 10:
            matches.append({"collected_index": i, "distances": dists, "best_distance": best,
                            "status": "derived",
                            "note": "Whole-image pHash match (original/crop/resize variant). Photo reuse only — not face identification."})
    return {"status": "found", "variants": list(variants.keys()), "matches": matches,
            "threshold": 10, "note": "Hamming distance <= 10 on any whole-image variant counts as a reuse lead for human review."}


# ---------------------------------------------------------- archive (#17)
def archive_diff(url, fetcher=None):
    """Wayback snapshot list + archive.today newest, compared."""
    from .v6 import wayback_cdx
    from .v3 import archive_today
    wb = wayback_cdx(url, limit=20, fetcher=fetcher)
    at = archive_today(url) if fetcher is None else {"status": "not_checked", "note": "archive.today skipped when a test fetcher is injected (its route follows redirects)."}
    snaps = wb.get("snapshots") or []
    return {"status": "found" if snaps or at.get("status") == "ok" else wb.get("status", "not_checked"),
            "url": url, "wayback": wb, "archive_today": at,
            "snapshot_count_wayback": len(snaps),
            "changed_tracking": "Compare snapshot digests/timestamps across runs (monitor) to spot deleted or changed posts/pages; a missing snapshot is not proof of deletion.",
            "note": "Two independent archive sources. Snapshots are preserved copies, not current data."}


# ------------------------------------------------------------ alerts (#18)
def send_watch_alert(message, keys=None, fetcher=None, webhook_sender=None,
                     smtp_sender=None, telegram_sender=None):
    """Deliver a watch alert via whichever channels are configured.
    Every unconfigured channel returns not_configured — nothing is
    silently dropped and nothing is faked as sent."""
    keys = dict(keys or {})
    out = {}
    # Webhook
    webhook = keys.get("alert_webhook_url") or os.environ.get("PERSONATRACE_ALERT_WEBHOOK_URL")
    if webhook_sender is not None:
        out["webhook"] = webhook_sender(webhook, message) if webhook else {"status": "not_configured"}
    elif webhook:
        status, _t, _f = http_fetch(webhook, headers={"Content-Type": "application/json"}, fetcher=fetcher)
        # http_fetch is GET-only by design; a real POST happens here:
        if fetcher is None:
            try:
                req = urllib.request.Request(webhook, data=json.dumps({"text": message}).encode(),
                                             headers={"Content-Type": "application/json", "User-Agent": _UA}, method="POST")
                with urllib.request.urlopen(req, timeout=6) as resp:
                    out["webhook"] = {"status": "sent" if resp.status < 300 else "degraded", "http_status": resp.status}
            except Exception as exc:
                out["webhook"] = {"status": "degraded", "note": str(exc)[:120]}
        else:
            out["webhook"] = {"status": "sent" if status and status < 300 else "degraded", "http_status": status}
    else:
        out["webhook"] = {"status": "not_configured", "note": "Set PERSONATRACE_ALERT_WEBHOOK_URL or keys['alert_webhook_url']."}
    # Email via SMTP env config
    smtp_host = os.environ.get("PERSONATRACE_SMTP_HOST")
    smtp_to = os.environ.get("PERSONATRACE_ALERT_EMAIL_TO")
    if smtp_sender is not None:
        out["email"] = smtp_sender(message) if (smtp_host and smtp_to) else {"status": "not_configured"}
    elif smtp_host and smtp_to:
        try:
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["From"] = os.environ.get("PERSONATRACE_SMTP_FROM", smtp_to)
            msg["To"] = smtp_to
            msg["Subject"] = "PersonaTrace watch alert"
            msg.set_content(str(message))
            with smtplib.SMTP(smtp_host, int(os.environ.get("PERSONATRACE_SMTP_PORT", "587")), timeout=10) as s:
                if os.environ.get("PERSONATRACE_SMTP_USER"):
                    s.starttls()
                    s.login(os.environ["PERSONATRACE_SMTP_USER"], os.environ.get("PERSONATRACE_SMTP_PASSWORD", ""))
                s.send_message(msg)
            out["email"] = {"status": "sent", "to": smtp_to}
        except Exception as exc:
            out["email"] = {"status": "degraded", "note": str(exc)[:120]}
    else:
        out["email"] = {"status": "not_configured", "note": "Set PERSONATRACE_SMTP_HOST and PERSONATRACE_ALERT_EMAIL_TO."}
    # Telegram via bot token + chat id (keys or env)
    tg_token = keys.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = keys.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
    if telegram_sender is not None:
        out["telegram"] = telegram_sender(message) if (tg_token and tg_chat) else {"status": "not_configured"}
    elif tg_token and tg_chat:
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        if fetcher is not None:
            status, _b = fetcher(url, {"chat_id": tg_chat, "text": str(message)})
            out["telegram"] = {"status": "sent" if status == 200 else "degraded", "http_status": status}
        else:
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"chat_id": tg_chat, "text": str(message)}).encode(),
                                             headers={"User-Agent": _UA}, method="POST")
                with urllib.request.urlopen(req, timeout=6) as resp:
                    out["telegram"] = {"status": "sent" if resp.status == 200 else "degraded", "http_status": resp.status}
            except Exception as exc:
                out["telegram"] = {"status": "degraded", "note": str(exc)[:120]}
    else:
        out["telegram"] = {"status": "not_configured", "note": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or keys telegram_bot_token/telegram_chat_id)."}
    sent = [k for k, v in out.items() if v.get("status") == "sent"]
    out["summary"] = {"sent_channels": sent, "status": "sent" if sent else "not_configured"}
    return out


# ------------------------------------------------------------- graph (#19)
def graph_levels(dossier_profiles, edges, contacts_of_contacts=None, anchor_id=None):
    """Assign graph levels: 1 anchor, 2 collected profiles, 3
    contacts-of-contacts leads, 4 shared websites/domains. Computed
    from collected data only."""
    nodes = []
    anchor_id = anchor_id or (f"{dossier_profiles[0].get('platform')}:{dossier_profiles[0].get('username')}"
                              if dossier_profiles else None)
    seen = set()
    for p in dossier_profiles or []:
        nid = f"{p.get('platform')}:{p.get('username')}"
        if nid in seen:
            continue
        seen.add(nid)
        nodes.append({"id": nid, "platform": p.get("platform"), "username": p.get("username"),
                      "level": 1 if nid == anchor_id else 2,
                      "centre": nid == anchor_id, "status": p.get("status")})
    for name, contacts in (contacts_of_contacts or {}).items():
        for c in contacts or []:
            nid = f"lead:{c}"
            if nid not in seen:
                seen.add(nid)
                nodes.append({"id": nid, "username": c, "level": 3, "status": "lead",
                              "note": f"Contact of {name} (collected public following data). A lead, not a collected profile."})
    domains = set()
    for p in dossier_profiles or []:
        for link in (p.get("bio_links") or []):
            d = _domain_of(link)
            if d:
                domains.add(d)
    for d in sorted(domains):
        nodes.append({"id": f"domain:{d}", "domain": d, "level": 4, "status": "derived",
                      "note": "Shared website/domain from collected bio links."})
    return {"nodes": nodes, "edges": edges or [],
            "levels": {"1": "anchor (investigator-supplied / seed profile)",
                       "2": "collected profiles", "3": "contacts-of-contacts leads",
                       "4": "shared websites/domains"},
            "note": "Levels are computed from collected data only; level-3 entries are leads, never merged identities."}


# ------------------------------------------------------- coordinated (#20)
def coordinated_v8(accounts, follower_sets=None):
    """Existing crowd check + shared-rare-follower signal. A follower
    is 'rare' here if it appears in at most 2 of the collected sets
    and the sets are small enough for rarity to mean anything."""
    from .coordinated import crowd_check
    base = crowd_check(accounts or [])
    signals = list(base.get("signals") or [])
    rare = []
    if follower_sets and len(follower_sets) >= 2:
        counts = Counter()
        for s in follower_sets:
            for f in set(s or []):
                counts[f] += 1
        total_accounts = len(follower_sets)
        rare = sorted(f for f, c in counts.items() if 2 <= c <= max(2, total_accounts // 2))
        if rare:
            signals.append(f"Shared rare follower(s) across collected sets ({len(rare)}): "
                           + ", ".join(rare[:10]) + ".")
    return {"accounts_checked": base.get("accounts_checked", 0), "signals": signals,
            "shared_rare_followers": rare,
            "innocent_explanations": list(base.get("innocent_explanations") or []) + [
                "Shared rare followers can be a small community, a class, a workplace, or a local scene — not proof of coordination."],
            "verdict": "pattern, not proof"}


# --------------------------------------------------------- behaviour (#21)
def _parse_ts(v):
    from datetime import datetime
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def behaviour_v8(items):
    """items: collected activity dicts {created_at, text, kind?,
    reply_to_created_at?, language?}. All stats carry denominators."""
    items = list(items or [])
    stamps = sorted(t for t in (_parse_ts(i.get("created_at")) for i in items) if t)
    gaps = []
    for a, b in zip(stamps, stamps[1:]):
        gaps.append((b - a).total_seconds() / 3600.0)
    reply_speeds = []
    for i in items:
        a, b = _parse_ts(i.get("reply_to_created_at")), _parse_ts(i.get("created_at"))
        if a and b and b >= a:
            reply_speeds.append((b - a).total_seconds() / 60.0)
    topic_first, topic_second = Counter(), Counter()
    lang_first, lang_second = Counter(), Counter()
    if items:
        mid = len(items) // 2
        for idx, i in enumerate(items):
            tgt_t = topic_first if idx < mid else topic_second
            tgt_l = lang_first if idx < mid else lang_second
            for w in re.findall(r"#(\w+)", i.get("text") or ""):
                tgt_t[w.lower()] += 1
            if i.get("language"):
                tgt_l[i["language"]] += 1
    return {"status": "found" if items else "not_checked", "sample_n": len(items),
            "posting_gap_hours": {"count": len(gaps),
                                  "median": sorted(gaps)[len(gaps) // 2] if gaps else None,
                                  "max": max(gaps) if gaps else None},
            "reply_speed_minutes": {"count": len(reply_speeds),
                                    "median": sorted(reply_speeds)[len(reply_speeds) // 2] if reply_speeds else None,
                                    "note": "Only items carrying both a parent timestamp and a reply timestamp count; denominator is the count shown."},
            "topic_shift": {"first_half_top": topic_first.most_common(5), "second_half_top": topic_second.most_common(5)},
            "language_shift": {"first_half": lang_first.most_common(3), "second_half": lang_second.most_common(3)},
            "note": "Derived from the collected sample only (sample_n shown). Behaviour in a sample is not a persona and proves nothing alone."}


# ---------------------------------------------------- impersonation (#22)
def impersonation_finder(anchor: dict, profiles: list):
    """Flag collected profiles sharing the anchor's display name +
    avatar hash, or display name + bio template. Leads with reasons
    and innocent explanations — never an assertion."""
    anchor = anchor or {}
    out = []
    a_name = (anchor.get("display_name") or "").strip().lower()
    a_hash = anchor.get("avatar_hash") or ""
    a_bio = re.sub(r"\s+", " ", (anchor.get("bio") or "").strip().lower())
    for p in profiles or []:
        if p is anchor:
            continue
        reasons = []
        name_same = a_name and (p.get("display_name") or "").strip().lower() == a_name
        hash_same = a_hash and (p.get("avatar_hash") or "") == a_hash
        bio_same = a_bio and re.sub(r"\s+", " ", (p.get("bio") or "").strip().lower()) == a_bio
        if name_same and hash_same:
            reasons.append("Same display name AND same avatar image hash as the anchor")
        if name_same and bio_same:
            reasons.append("Same display name AND identical bio text as the anchor")
        if reasons:
            out.append({"platform": p.get("platform"), "username": p.get("username"),
                        "reasons": reasons, "status": "lead",
                        "innocent_explanations": [
                            "The person's own second / backup / platform-mirror account",
                            "A fan, tribute, or parody account",
                            "A namesake with a copied profile template",
                            "An impersonator — possible, but not proven by similarity alone"]})
    return {"status": "found" if out else "not_found", "candidates": out,
            "note": "Possible impersonators are leads for human review. Similarity is not proof of impersonation, and the anchor's own alt accounts are the most common innocent explanation."}


# ------------------------------------------------------------- scam (#23)
_BTC_RE = re.compile(r"\b(?:bc1[a-z0-9]{39,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_URL_RE = re.compile(r"https?://[^\s)<\]]+")


def scam_signals(profiles):
    """Scan collected public bio/post text for wallet addresses and
    for shop/contact links repeated across DIFFERENT accounts."""
    wallets, link_accounts = [], {}
    for p in profiles or []:
        pid = f"{p.get('platform')}:{p.get('username')}"
        text = " ".join([p.get("bio") or ""] + [str(t) for t in (p.get("texts") or p.get("posts") or [])])
        for m in _BTC_RE.findall(text):
            wallets.append({"kind": "btc_address", "value": m, "account": pid, "status": "found"})
        for m in _ETH_RE.findall(text):
            wallets.append({"kind": "eth_address", "value": m, "account": pid, "status": "found"})
        for u in _URL_RE.findall(text):
            host = _domain_of(u)
            if host:
                link_accounts.setdefault(u.rstrip(".,)"), set()).add(pid)
    repeated_links = [{"url": u, "accounts": sorted(accts), "status": "derived"}
                      for u, accts in link_accounts.items() if len(accts) >= 2]
    wallet_accounts = {}
    for w in wallets:
        wallet_accounts.setdefault(w["value"], set()).add(w["account"])
    repeated_wallets = [{"value": v, "accounts": sorted(a)} for v, a in wallet_accounts.items() if len(a) >= 2]
    return {"status": "found" if (wallets or repeated_links) else "not_found",
            "wallet_addresses": wallets, "repeated_wallets_across_accounts": repeated_wallets,
            "repeated_links_across_accounts": repeated_links,
            "innocent_explanations": [
                "A public donation / payment address the person publishes openly",
                "A shared employer / project / community shop or contact link",
                "A copied bio template or a quoted post"],
            "note": "Signals from collected public text only. A wallet address or repeated link is a lead, not proof of fraud."}


# ------------------------------------------------------ wallet seed (#24)
def validate_wallet(address):
    a = (address or "").strip()
    if _ETH_RE.fullmatch(a):
        return {"valid": True, "kind": "eth", "address": a}
    if re.fullmatch(r"(?:bc1[a-z0-9]{39,59}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})", a):
        return {"valid": True, "kind": "btc", "address": a}
    return {"valid": False, "kind": None, "address": a}


def wallet_seed(address, keys=None, fetcher=None, search_fetcher=None):
    """Public-post search for the exact address + free public
    blockchain address basics. Address data only — a wallet is never
    labelled as belonging to a named person from this alone."""
    v = validate_wallet(address)
    if not v["valid"]:
        return {"status": "not_found", "validation": v,
                "note": "Not a recognisable BTC or ETH address format; no lookup was run."}
    from .v7 import phrase_search
    posts = phrase_search(address, fetcher=fetcher, keys=keys, search_fetcher=search_fetcher)
    chain = {"status": "not_checked"}
    if v["kind"] == "eth":
        status, data, _t, _f = http_json(
            f"https://api.blockcypher.com/v1/eth/main/addrs/{address}/balance", fetcher=fetcher)
        if status == 200 and isinstance(data, dict):
            chain = {"status": "found", "source": "blockcypher public API",
                     "balance": data.get("balance"), "total_received": data.get("total_received"),
                     "n_tx": data.get("n_tx"),
                     "note": "Public blockchain address data. It describes the address, not a person."}
        else:
            chain = {"status": "not_checked", "note": f"Blockcypher returned HTTP {status}."}
    else:
        status, text, _f = http_fetch(f"https://blockstream.info/api/address/{address}", fetcher=fetcher)
        if status == 200 and text:
            try:
                data = json.loads(text)
                stats = (data.get("chain_stats") or {})
                chain = {"status": "found", "source": "blockstream.info public API",
                         "tx_count": stats.get("tx_count"),
                         "funded_satoshi": stats.get("funded_txo_sum"),
                         "spent_satoshi": stats.get("spent_txo_sum"),
                         "note": "Public blockchain address data. It describes the address, not a person."}
            except Exception:
                chain = {"status": "not_checked", "note": "Blockstream response was not parseable."}
        else:
            chain = {"status": "not_checked", "note": f"Blockstream returned HTTP {status}."}
    return {"status": "found" if chain.get("status") == "found" or posts.get("posts") else "not_checked",
            "validation": v, "public_posts": posts, "chain_basics": chain,
            "note": "Wallet seed = public posts mentioning the exact address (labelled search_snippet/public_api) plus public chain basics. No balance-to-person or identity claim is made."}


# ------------------------------------------------------- plate seed (#25)
def plate_seed(plate, keys=None, fetcher=None, search_fetcher=None):
    """Public-post phrase search ONLY for the exact plate string.
    There is deliberately no vehicle database and no owner lookup."""
    p = (plate or "").strip().upper()
    if len(p) < 4:
        return {"status": "not_found", "note": "A plate seed needs at least 4 characters."}
    from .v7 import phrase_search
    posts = phrase_search(p, fetcher=fetcher, keys=keys, search_fetcher=search_fetcher)
    return {"status": posts.get("status", "not_checked"), "plate": p, "public_posts": posts,
            "note": "PUBLIC-POST SEARCH ONLY: this finds public posts that contain the exact plate string (labelled search_snippet). No vehicle database was queried and no owner lookup exists in this tool."}


# --------------------------------------------------------- teamwork (#26)
def set_case_team(base, seed, assigned_to=None, lead_status=None):
    """Set assigned_to / lead_status on a v5-registry case (by seed)."""
    from .v5 import cases_registry_path
    path = cases_registry_path(base)
    if not os.path.exists(path):
        return {"status": "not_found", "note": "No case registry yet (cases.json). Register the case first."}
    registry = json.load(open(path))
    hit = None
    for entry in registry:
        if entry.get("seed") == seed:
            if assigned_to is not None:
                entry["assigned_to"] = assigned_to
            if lead_status is not None:
                entry["lead_status"] = lead_status
            hit = entry
    if hit is None:
        return {"status": "not_found", "note": f"No registered case for seed {seed!r}."}
    json.dump(registry, open(path, "w"), indent=2)
    return {"status": "found", "case": hit,
            "note": "Team fields are case-management metadata only; they carry no evidence and are stripped from exports like other internal fields."}


# ---------------------------------------------------- court report (#27)
def _evidence_rows(dossier):
    rows = []
    for p in dossier.get("profile_summary", []) or []:
        for e in p.get("evidence") or []:
            if isinstance(e, dict):
                rows.append({
                    "platform": p.get("platform"), "username": p.get("username"),
                    "field": e.get("field"), "value": str(e.get("value"))[:300],
                    "source_url": e.get("source_url"), "captured_at_utc": e.get("captured_at_utc"),
                    "method": e.get("method"), "confidence": e.get("confidence"),
                    "evidence_sha256": sha256_text("|".join(str(e.get(k, "")) for k in ("source_url", "field", "value", "captured_at_utc"))),
                })
    rows.sort(key=lambda r: str(r.get("captured_at_utc") or ""))
    return rows


def court_report(dossier, fmt="md"):
    """Chronological report: every fact with source, capture time,
    method and an evidence hash. Keys are stripped (build order:
    pass an already-stripped dossier)."""
    from .v6 import strip_keys
    dossier = strip_keys(dossier or {})
    rows = _evidence_rows(dossier)
    seed = dossier.get("seed", "")
    if fmt == "html":
        trs = "".join(
            "<tr><td>{}</td><td>{}:{}</td><td>{}</td><td>{}</td><td><a href=\"{}\">{}</a></td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _html.escape(str(r["captured_at_utc"] or "")), _html.escape(str(r["platform"])),
                _html.escape(str(r["username"])), _html.escape(str(r["field"])),
                _html.escape(str(r["value"])), _html.escape(str(r["source_url"] or "")),
                _html.escape(str(r["source_url"] or "")), _html.escape(str(r["method"])),
                _html.escape(str(r["confidence"])), _html.escape(r["evidence_sha256"][:16]))
            for r in rows)
        return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>Court-style report — {seed}</title></head><body>"
                f"<h1>PersonaTrace court-style report — {seed}</h1>"
                f"<p>Version {VERSION}. Chronological. Every fact carries its source URL, capture time (UTC), method, confidence, and the SHA256 of its evidence record (truncated in this view, full in court_report.md). Keys are stripped.</p>"
                "<table><tr><th>Captured (UTC)</th><th>Profile</th><th>Field</th><th>Value</th><th>Source</th><th>Method</th><th>Conf.</th><th>Evidence SHA256[:16]</th></tr>"
                f"{trs}</table></body></html>")
    lines = [f"# PersonaTrace court-style report — {seed}", "",
             f"Version {VERSION}. Chronological order. Every fact: source URL, capture UTC, method, confidence, evidence SHA256. Keys stripped.", ""]
    if not rows:
        lines.append("No evidence records were collected in this case.")
    for r in rows:
        lines.append(f"- {r['captured_at_utc']} · {r['platform']}:{r['username']} · {r['field']} = {r['value']}")
        lines.append(f"  source: {r['source_url']} · method: {r['method']} · confidence: {r['confidence']} · sha256: {r['evidence_sha256']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------- proof (#28)
def proof_card_png(profile: dict, out_path: str):
    """Render a simple Pillow proof card. This is a snapshot proof
    card generated from collected fields — it is NOT a browser
    screenshot and is never labelled as one."""
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        return {"status": "not_checked", "note": f"Pillow unavailable ({exc}); JSON snapshot proof is used instead."}
    lines = [
        "PersonaTrace snapshot proof card (NOT a browser screenshot)",
        f"Platform: {profile.get('platform', '')}",
        f"Username: {profile.get('username', '')}",
        f"Display name: {profile.get('display_name', '')}",
        f"Status: {profile.get('status', '')}",
        f"Source: {(profile.get('evidence') or [{}])[0].get('source_url', '') if profile.get('evidence') else ''}",
        f"Captured (UTC): {(profile.get('evidence') or [{}])[0].get('captured_at_utc', '') if profile.get('evidence') else ''}",
        f"Evidence SHA256: {sha256_text(json.dumps(profile, default=str, sort_keys=True))}",
    ]
    img = Image.new("RGB", (900, 60 + 26 * len(lines)), (13, 20, 36))
    draw = ImageDraw.Draw(img)
    y = 24
    for ln in lines:
        draw.text((20, y), ln[:110], fill=(232, 238, 248))
        y += 26
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    with open(out_path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {"status": "found", "path": out_path, "kind": "proof_card_png",
            "sha256": digest}


def build_proof_folder(dossier, out_dir):
    """proof/ folder: one proof card (or JSON snapshot) per profile +
    proof_index.json."""
    proof_dir = os.path.join(out_dir, "proof")
    os.makedirs(proof_dir, exist_ok=True)
    index = []
    for p in dossier.get("profile_summary", []) or []:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{p.get('platform')}-{p.get('username')}")[:80]
        snap = {"profile": p, "sha256": sha256_text(json.dumps(p, default=str, sort_keys=True)),
                "kind": "json_snapshot"}
        png_path = os.path.join(proof_dir, safe + ".png")
        card = proof_card_png(p, png_path)
        if card.get("status") == "found":
            snap["kind"] = "proof_card_png"
            snap["file"] = safe + ".png"
            snap["sha256"] = card["sha256"]
        else:
            with open(os.path.join(proof_dir, safe + ".json"), "w") as fh:
                json.dump(snap, fh, indent=2, default=str)
            snap["file"] = safe + ".json"
        index.append(snap)
    with open(os.path.join(proof_dir, "proof_index.json"), "w") as fh:
        json.dump(index, fh, indent=2, default=str)
    with open(os.path.join(out_dir, "proof_index.json"), "w") as fh:
        json.dump(index, fh, indent=2, default=str)
    return {"status": "found", "count": len(index), "proof_dir": proof_dir, "index": index,
            "note": "Proof cards are generated snapshot cards (Pillow), not browser screenshots. Each entry is hashed in proof_index.json."}


# ---------------------------------------------------------- offline (#29)
def offline_rebuild(case_dir, out_dir=None):
    """Rebuild dossier + exports from a saved investigation.json with
    ZERO network calls: dorks and public-web collectors are disabled
    and every adapter route is skipped by construction (this function
    never calls one)."""
    src = os.path.join(case_dir, "investigation.json")
    if not os.path.exists(src):
        return {"status": "not_found", "note": f"No investigation.json in {case_dir}."}
    payload = json.load(open(src))
    out_dir = out_dir or case_dir
    from .v7 import build_v7_dossier
    # Zero-network guarantee: the v6 dossier builder disables its
    # dork/public-web collectors in demo mode, so force that switch
    # for the duration of the rebuild (restored afterwards). No
    # adapter is constructed on this path at all.
    _prev_demo = os.environ.get("PERSONATRACE_DEMO")
    os.environ["PERSONATRACE_DEMO"] = "1"
    try:
        dossier = build_v7_dossier(payload, payload.get("seed", ""), seed_type=payload.get("seed_type", "username"),
                                   keys={}, v7_section=payload.get("v7"), include_dorks=False)
        dossier["version"] = VERSION
        dossier = build_v8_sections(dossier, payload)
        dossier["v8"] = {**(dossier.get("v8") or {}),
                         "offline": {"status": "found", "source_case": case_dir,
                                     "note": "Rebuilt offline from the saved case. Zero network calls were made."}}
        paths = export_v8(dossier, out_dir)
    finally:
        if _prev_demo is None:
            os.environ.pop("PERSONATRACE_DEMO", None)
        else:
            os.environ["PERSONATRACE_DEMO"] = _prev_demo
    return {"status": "found", "dossier": dossier, "paths": paths,
            "note": "Offline rebuild complete; no network calls were made."}


# ------------------------------------------- Direct Profile Mode (#1)
_EXTRA_HOSTS = {
    "gitlab.com": "gitlab", "twitch.tv": "twitch", "kick.com": "kick",
    "medium.com": "medium", "substack.com": "substack", "dev.to": "devto",
    "soundcloud.com": "soundcloud", "vimeo.com": "vimeo",
    "flickr.com": "flickr", "steamcommunity.com": "steam",
    "keybase.io": "keybase", "producthunt.com": "producthunt",
    "psnprofiles.com": "playstation", "open.spotify.com": "spotify",
}


def parse_profile_url(seed):
    """v7 parse + extra hosts (GitLab etc.)."""
    from .v7 import parse_url_seed, _PLATFORM_HOSTS
    parsed = parse_url_seed(seed)
    try:
        host = (urllib.parse.urlparse(seed).hostname or "").lower().removeprefix("www.")
    except Exception:
        host = ""
    if host in _EXTRA_HOSTS and parsed.get("platform") in ("web", None):
        parts = [p for p in urllib.parse.urlparse(seed).path.split("/") if p]
        username = parts[0].lstrip("@") if parts else None
        parsed = {**parsed, "platform": _EXTRA_HOSTS[host], "host": host,
                  "username": username, "kind": "profile" if username else "page"}
    if host.endswith("mastodon.social") or (parsed.get("platform") == "web" and "@" in (urllib.parse.urlparse(seed).path or "")):
        pass
    # Any mastodon instance: host not known, path /@user
    if parsed.get("platform") == "web":
        parts = [p for p in urllib.parse.urlparse(seed).path.split("/") if p]
        if parts and parts[0].startswith("@"):
            parsed = {**parsed, "platform": "mastodon", "host": host,
                      "username": parts[0][1:], "kind": "profile"}
    return parsed


def _profile_from_direct(parsed, fetched, snapshot_text):
    from ..core.models import Profile
    from ..core.provenance import utc_now_iso
    from ..adapters.base import Evidence
    url = parsed.get("url") or fetched.get("profile_url") or ""
    ev = [Evidence(source_url=url, captured_at_utc=utc_now_iso(),
                   method=fetched.get("method", "public_web"),
                   platform=fetched.get("platform") or parsed.get("platform", "web"),
                   field="profile_url", value=url, confidence=95)]
    prof = Profile(platform=fetched.get("platform") or parsed.get("platform", "web"),
                   username=fetched.get("username") or parsed.get("username") or "",
                   display_name=fetched.get("display_name", "") or "",
                   bio=fetched.get("bio", "") or "",
                   bio_links=fetched.get("bio_links", []) or [],
                   follower_count=fetched.get("follower_count"),
                   following_count=fetched.get("following_count"),
                   created_at=fetched.get("created_at", "") or "",
                   evidence=ev, status="confirmed_anchor", confidence=95)
    return prof


def _generic_web_profile(parsed, keys=None, fetcher=None):
    """Single public-web fetch of the exact URL; OpenGraph/meta only.
    Stops on 403/429/login walls and labels honestly."""
    url = parsed["url"]
    status, text, final = http_fetch(url, headers={"User-Agent": "Mozilla/5.0 (public-data lookup)"},
                                     fetcher=fetcher)
    if status in (401, 403, 429) or (final and ("login" in final or "signin" in final)):
        return {"status": "blocked", "route": "generic_web", "platform": parsed.get("platform"),
                "username": parsed.get("username"), "profile_url": url,
                "note": f"The exact page was blocked or login-walled (HTTP {status}); stopped, not bypassed. Without an aggregator key this profile is gated_paid.", "snapshot_text": ""}
    if status != 200 or not text:
        return {"status": "not_checked", "route": "generic_web", "platform": parsed.get("platform"),
                "username": parsed.get("username"), "profile_url": url,
                "note": f"The exact page returned HTTP {status}; no data was used.", "snapshot_text": ""}
    og = _og_fields(parse_opengraph(text))
    return {"status": "found", "route": "generic_web", "platform": parsed.get("platform"),
            "username": parsed.get("username"), "display_name": og["display_name"],
            "bio": og["bio"], "bio_links": [], "follower_count": None,
            "following_count": None, "created_at": "", "avatar_url": og["avatar_url"],
            "profile_url": url, "method": "public_web", "derived": True,
            "snapshot_text": text[:_SNAPSHOT_CAP],
            "note": "Derived fields only, from the exact page's OpenGraph/meta. Counts, posts and comments are not available on this route."}


def fetch_direct_profile(seed_url, keys=None, fetcher=None, sleeper=None):
    """Fetch THAT exact profile. Returns (section_dict, Profile|None).
    The section carries _snapshot_text for the CLI to save; dossier
    builders strip underscore keys."""
    keys = dict(keys or {})
    parsed = parse_profile_url(seed_url)
    platform = parsed.get("platform")
    username = parsed.get("username")
    fetched = None
    post_item = None

    if platform == "github" and username and parsed.get("kind") == "profile":
        r = github_profile_fetch(username, keys=keys, fetcher=fetcher, sleeper=sleeper)
        fetched = {**r, "platform": "github"}
    elif platform == "gitlab" and username:
        status, data, text, _f = http_json(
            "https://gitlab.com/api/v4/users?username=" + urllib.parse.quote(username), fetcher=fetcher)
        if status == 200 and isinstance(data, list) and data:
            d0 = data[0]
            fetched = {"status": "found", "route": "gitlab_api", "platform": "gitlab",
                       "username": d0.get("username", username), "display_name": d0.get("name", ""),
                       "bio": d0.get("bio", "") or "", "bio_links": [d0["web_url"]] if d0.get("web_url") else [],
                       "follower_count": None, "following_count": None, "created_at": "",
                       "avatar_url": d0.get("avatar_url", ""), "profile_url": d0.get("web_url", seed_url),
                       "method": "public_api", "snapshot_text": text[:_SNAPSHOT_CAP],
                       "note": "GitLab public API exact-username lookup."}
        else:
            fetched = {"status": "not_found" if status == 200 else "degraded", "route": "gitlab_api",
                       "platform": "gitlab", "username": username, "profile_url": seed_url,
                       "note": f"GitLab API returned HTTP {status} with no matching user.", "snapshot_text": ""}
    elif platform == "bluesky" and username:
        actor = username if "." in username else username + ".bsky.social"
        status, data, text, _f = http_json(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=" + urllib.parse.quote(actor),
            fetcher=fetcher)
        if status == 200 and isinstance(data, dict):
            fetched = {"status": "found", "route": "bluesky_api", "platform": "bluesky",
                       "username": data.get("handle", username), "display_name": data.get("displayName", ""),
                       "bio": data.get("description", "") or "", "bio_links": [],
                       "follower_count": data.get("followersCount"),
                       "following_count": data.get("followsCount"),
                       "created_at": data.get("createdAt", ""), "avatar_url": data.get("avatar", ""),
                       "profile_url": f"https://bsky.app/profile/{data.get('handle', username)}",
                       "method": "public_api", "snapshot_text": text[:_SNAPSHOT_CAP],
                       "note": "Bluesky public API exact profile."}
        else:
            fetched = {"status": "not_found" if status == 400 else "degraded", "route": "bluesky_api",
                       "platform": "bluesky", "username": username, "profile_url": seed_url,
                       "note": f"Bluesky API returned HTTP {status}.", "snapshot_text": ""}
    elif platform == "mastodon" and username:
        host = parsed.get("host") or "mastodon.social"
        status, data, text, _f = http_json(
            f"https://{host}/api/v1/accounts/lookup?acct={urllib.parse.quote(username)}", fetcher=fetcher)
        if status == 200 and isinstance(data, dict):
            fetched = {"status": "found", "route": "mastodon_api", "platform": "mastodon",
                       "username": data.get("acct", username), "display_name": data.get("display_name", ""),
                       "bio": re.sub(r"<[^>]+>", " ", data.get("note", "") or "").strip(),
                       "bio_links": [], "follower_count": data.get("followers_count"),
                       "following_count": data.get("following_count"),
                       "created_at": data.get("created_at", ""), "avatar_url": data.get("avatar", ""),
                       "profile_url": data.get("url", seed_url), "method": "public_api",
                       "snapshot_text": text[:_SNAPSHOT_CAP], "note": "Mastodon instance public API exact lookup."}
        else:
            fetched = {"status": "degraded", "route": "mastodon_api", "platform": "mastodon",
                       "username": username, "profile_url": seed_url,
                       "note": f"Mastodon instance API returned HTTP {status}.", "snapshot_text": ""}
    elif platform == "youtube":
        if parsed.get("kind") == "post":
            from .v6 import youtube_oembed
            try:
                oe = youtube_oembed(seed_url)
            except Exception as exc:
                oe = {"status": "not_checked", "note": str(exc)[:120]}
            fetched = {"status": oe.get("status", "not_checked"), "route": "youtube_oembed",
                       "platform": "youtube", "username": oe.get("author_name", "") or username or "",
                       "display_name": oe.get("author_name", ""), "bio": "",
                       "bio_links": [], "profile_url": oe.get("author_url", seed_url),
                       "method": "public_api", "snapshot_text": json.dumps(oe)[:_SNAPSHOT_CAP],
                       "note": "YouTube oEmbed for the exact video URL."}
            post_item = {"url": seed_url, "item_id": parsed.get("item_id"),
                         "title": oe.get("title"), "status": oe.get("status", "not_checked"),
                         "source": "youtube oEmbed"}
        else:
            fetched = _generic_web_profile(parsed, keys=keys, fetcher=fetcher)
            fetched["platform"] = "youtube"
            if username:
                fetched["username"] = username
    elif platform == "reddit" and username:
        status, data, text, _f = http_json(f"https://www.reddit.com/user/{urllib.parse.quote(username)}/about.json",
                                           fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and isinstance(data.get("data"), dict):
            d0 = data["data"]
            fetched = {"status": "found", "route": "reddit_json", "platform": "reddit",
                       "username": d0.get("name", username), "display_name": d0.get("name", ""),
                       "bio": (d0.get("subreddit") or {}).get("public_description", "") or "",
                       "bio_links": [], "follower_count": None, "following_count": None,
                       "created_at": "", "avatar_url": d0.get("icon_img", ""),
                       "profile_url": f"https://www.reddit.com/user/{username}",
                       "method": "public_api", "snapshot_text": text[:_SNAPSHOT_CAP],
                       "note": "Reddit public .json exact profile."}
        elif status in (401, 403, 429):
            fetched = {"status": "blocked", "route": "reddit_json", "platform": "reddit",
                       "username": username, "profile_url": seed_url,
                       "note": f"Reddit blocked the public .json route (HTTP {status}); stopped, not bypassed. Full Reddit data is gated_paid without an aggregator key.", "snapshot_text": ""}
        else:
            fetched = {"status": "degraded", "route": "reddit_json", "platform": "reddit",
                       "username": username, "profile_url": seed_url,
                       "note": f"Reddit .json returned HTTP {status}.", "snapshot_text": ""}
    elif platform in ("instagram", "tiktok", "x", "linkedin"):
        from ..adapters.gated import _find_key
        if _find_key(platform if platform != "linkedin" else "instagram", keys) or _find_key("instagram", keys):
            full = gated_full_fetch(platform if platform in ("instagram", "tiktok", "x") else "instagram",
                                    username or "", keys=keys, fetcher=fetcher)
            if full.get("status") == "found":
                fetched = {**full, "route": "aggregator", "platform": platform,
                           "profile_url": full.get("profile_url") or seed_url,
                           "method": "licensed_aggregator", "snapshot_text": json.dumps(full)[:_SNAPSHOT_CAP],
                           "note": "Exact profile via the investigator's licensed aggregator (full-data route)."}
            else:
                fetched = {**full, "route": "aggregator", "platform": platform,
                           "profile_url": seed_url, "snapshot_text": ""}
        if fetched is None:
            fetched = _generic_web_profile(parsed, keys=keys, fetcher=fetcher)
            if fetched.get("status") == "found":
                fetched["full_data_status"] = "gated_paid"
                fetched["note"] += " Full posts/comments/followers for this platform need an aggregator key (gated_paid)."
            elif fetched.get("status") == "blocked":
                fetched["status"] = "blocked"
                fetched["full_data_status"] = "gated_paid"
    else:
        fetched = _generic_web_profile(parsed, keys=keys, fetcher=fetcher)

    # Post URLs on non-YouTube platforms: fetch the exact post page too.
    if parsed.get("kind") == "post" and platform != "youtube":
        pstatus, ptext, _pf = http_fetch(seed_url, headers={"User-Agent": "Mozilla/5.0 (public-data lookup)"},
                                         fetcher=fetcher)
        if pstatus == 200 and ptext:
            og = _og_fields(parse_opengraph(ptext))
            post_item = {"url": seed_url, "item_id": parsed.get("item_id"),
                         "title": og["page_title"], "description": og["bio"],
                         "image": og["avatar_url"], "status": "found",
                         "sha256": sha256_text(ptext[:_SNAPSHOT_CAP]),
                         "source": "exact post page (OpenGraph/meta)",
                         "note": "Post page fields only. Comments/likers were NOT fetched on this route unless an aggregator key returned them."}
            if fetched is None or fetched.get("status") not in ("found",):
                fetched = {"status": "found", "route": "generic_web_post", "platform": platform,
                           "username": username, "display_name": "", "bio": "",
                           "profile_url": seed_url, "method": "public_web", "derived": True,
                           "snapshot_text": ptext[:_SNAPSHOT_CAP],
                           "note": "Anchor built from the exact post page (derived). This is a post anchor, not a fetched profile."}
        else:
            post_item = {"url": seed_url, "item_id": parsed.get("item_id"), "status": "blocked" if pstatus in (401, 403, 429) else "not_checked",
                         "note": f"Exact post page returned HTTP {pstatus}; stopped, not bypassed."}

    snapshot_text = (fetched or {}).get("snapshot_text", "") or ""
    section = {
        "parsed": parsed,
        "fetched": {k: (fetched or {}).get(k) for k in (
            "platform", "username", "display_name", "bio", "bio_links",
            "follower_count", "following_count", "created_at", "avatar_url",
            "profile_url", "method", "derived", "full_data_status")},
        "fetch_route": (fetched or {}).get("route"),
        "fetch_status": (fetched or {}).get("status"),
        "status": (fetched or {}).get("status", "not_checked"),
        "profile": None, "post_item": post_item,
        "snapshot": {"sha256": sha256_text(snapshot_text) if snapshot_text else None,
                     "bytes": len(snapshot_text.encode("utf-8", errors="replace")) if snapshot_text else 0,
                     "note": "SHA256 of the fetched profile payload/page (truncated snapshot saved as direct_profile_snapshot.json/.html in the case folder)."},
        "anchor_semantics": "The investigator supplied this exact profile, so its EXISTENCE is confirmed_anchor. Whether it belongs to the same person as any other profile still goes through normal confidence scoring and human review.",
        "note": (fetched or {}).get("note", ""),
        "_snapshot_text": snapshot_text,
        "_snapshot_kind": "json" if (fetched or {}).get("route", "").endswith("_api") or (fetched or {}).get("route") in ("aggregator", "youtube_oembed", "reddit_json") else "html",
    }
    prof = None
    if fetched and fetched.get("status") == "found" and (fetched.get("username") or parsed.get("kind") == "post"):
        prof = _profile_from_direct(parsed, fetched, snapshot_text)
        section["profile"] = {"platform": prof.platform, "username": prof.username,
                              "display_name": prof.display_name, "bio": prof.bio,
                              "bio_links": prof.bio_links, "follower_count": prof.follower_count,
                              "following_count": prof.following_count, "created_at": prof.created_at,
                              "status": prof.status, "profile_url": parsed.get("url")}
    return section, prof


def investigate_direct_profile(seed_url, keys=None, parallel=4, fetcher=None,
                               sleeper=None, progress=True):
    """Direct Profile Mode: fetch the anchor, then expand by username
    through the normal investigation (parallel in v8 by default)."""
    from ..core.engine import cluster_discovered_profiles, run_investigation
    from ..core.provenance import utc_now_iso
    keys = dict(keys or {})
    section_direct, anchor = fetch_direct_profile(seed_url, keys=keys, fetcher=fetcher, sleeper=sleeper)
    parsed = section_direct["parsed"]
    username = parsed.get("username") or (anchor.username if anchor else None)
    if username:
        if fetcher is None and parallel and int(parallel) > 1:
            inv = run_parallel_investigation(username, keys=keys, parallel=int(parallel), progress=progress)
        else:
            inv = run_investigation(username, keys=keys, seed_type="username")
        inv = cluster_discovered_profiles(inv)
    else:
        from ..core.engine import run_investigation as _run
        inv = _run(seed_url, adapters=[], keys=keys, seed_type="profile", analyse=False)
    if anchor is not None:
        existing = None
        for p in inv.profiles:
            if p.platform == anchor.platform and (p.username or "").lower() == (anchor.username or "").lower():
                existing = p
                break
        if existing is not None:
            existing.status = "confirmed_anchor"
            existing.confidence = 95
        else:
            inv.profiles.insert(0, anchor)
    inv.seed, inv.seed_type = seed_url, "profile"
    inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v8",
                      "action": "direct_profile",
                      "detail": {"url": seed_url, "platform": parsed.get("platform"),
                                 "username": username, "route": section_direct.get("fetch_route"),
                                 "status": section_direct.get("fetch_status"),
                                 "snapshot_sha256": (section_direct.get("snapshot") or {}).get("sha256")}})
    section = {"seed_type_resolved": "profile", "direct_profile": section_direct}
    return inv, section


# --------------------------------------------- dossier sections (no net)
def build_v8_sections(dossier, payload=None, v8_section=None):
    """Compute the network-free v8 dossier sections from collected
    data only. Safe for offline rebuilds."""
    payload = payload if isinstance(payload, dict) else {}
    v8_section = v8_section or {}
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    summary = dossier.get("profile_summary", []) or []
    sections = dict(v8_section)
    # Never let snapshot payloads leak into the dossier JSON.
    if isinstance(sections.get("direct_profile"), dict):
        dp = dict(sections["direct_profile"])
        dp.pop("_snapshot_text", None)
        dp.pop("_snapshot_kind", None)
        sections["direct_profile"] = dp
    # Graph levels 1-4 (#19) + centre marker for the anchor
    anchor_id = None
    direct = sections.get("direct_profile") or {}
    if direct.get("profile"):
        anchor_id = f"{direct['profile'].get('platform')}:{direct['profile'].get('username')}"
    elif summary:
        anchor_id = f"{summary[0].get('platform')}:{summary[0].get('username')}"
    graph = dossier.get("network_graph", {}) or {}
    levels = graph_levels(summary, graph.get("edges", []),
                          contacts_of_contacts=analysis.get("contacts_of_contacts"),
                          anchor_id=anchor_id)
    dossier["network_graph"] = {**graph, "nodes": levels["nodes"], "levels": levels["levels"],
                                "centre": anchor_id,
                                "note": graph.get("note", "") + " " + levels["note"]}
    sections["graph_levels"] = {"levels": levels["levels"], "centre": anchor_id,
                                "node_count": len(levels["nodes"])}
    # Impersonation (#22)
    if summary:
        anchor = summary[0]
        sections["impersonation"] = impersonation_finder(anchor, summary[1:])
    # Scam signals (#23) — bios + collected comment/activity texts
    _ac = analysis.get("comments")
    if isinstance(_ac, dict):
        _comments_list = _ac.get("items") or _ac.get("comments") or []
    elif isinstance(_ac, list):
        _comments_list = _ac
    else:
        _comments_list = []
    _comments_list = [c for c in _comments_list if isinstance(c, dict)]
    texts_by_profile = []
    for p in summary:
        texts_by_profile.append({**p, "texts": [c.get("text", "") for c in _comments_list if c.get("platform") == p.get("platform")]})
    sections["scam_signals"] = scam_signals(texts_by_profile)
    # Behaviour upgrade (#21)
    items = []
    for it in (analysis.get("timeline") or []):
        if isinstance(it, dict):
            items.append({"created_at": it.get("date") or it.get("created_at") or "",
                          "text": it.get("title") or it.get("text") or "",
                          "language": it.get("language")})
    sections["behaviour_v8"] = behaviour_v8(items)
    # Coordinated upgrade (#20)
    accounts = [{"bio": p.get("bio") or "", "created_at": p.get("created_at") or "", "posts": []} for p in summary]
    sections["coordinated_v8"] = coordinated_v8(accounts)
    # Comments with configurable limit (#12)
    limit = int(os.environ.get("PERSONATRACE_COMMENT_LIMIT", "100") or 100)
    sections["comments_v8"] = apply_comment_limit(_comments_list, limit=limit)
    # Video (#14) — items from collected YouTube profiles / direct post
    vitems = []
    for p in summary:
        if p.get("platform") == "youtube":
            ev = (p.get("evidence") or [{}])
            vitems.append({"url": (ev[0].get("source_url") if ev and isinstance(ev[0], dict) else "") or "",
                           "title": p.get("display_name") or "", "text": p.get("bio") or ""})
    if direct.get("post_item"):
        vitems.append({"url": direct["post_item"].get("url", ""), "title": direct["post_item"].get("title") or "",
                       "video_id": direct["post_item"].get("item_id")})
    if os.environ.get("PERSONATRACE_DEMO") == "1":
        sections["video"] = {"status": "not_checked", "items": [], "note": "Demo mode: no video routes run."}
    else:
        sections["video"] = video_section(vitems)
    # Stories/highlights (#16): gated only — status section, no data without a key
    gated_present = [p for p in summary if p.get("platform") in ("instagram", "tiktok", "x")]
    if gated_present:
        p0 = gated_present[0]
        sections["stories_highlights"] = {"status": "gated_paid", "platform": p0.get("platform"),
                                          "stories": [], "highlights": [],
                                          "note": "Stories/highlights are available only via the investigator's aggregator key (see gated_full_fetch). Without a key they are gated_paid, never scraped."}
    # Site presence (#7) for username-like cases
    seed_val = dossier.get("seed", "")
    if seed_val and " " not in str(seed_val) and "/" not in str(seed_val) and "@" not in str(seed_val):
        sections["site_presence_v8"] = site_presence_checks(str(seed_val), live=False)
    dossier["v8"] = sections
    return dossier


def build_v8_dossier(payload, seed, seed_type="username", keys=None, v7_section=None,
                     v8_section=None, include_dorks=True):
    from .v7 import build_v7_dossier
    from .v6 import strip_keys
    dossier = build_v7_dossier(payload, seed, seed_type=seed_type, keys=keys,
                               v7_section=v7_section, include_dorks=include_dorks)
    dossier["version"] = VERSION
    dossier = build_v8_sections(dossier, payload, v8_section=v8_section)
    return strip_keys(dossier)


def export_v8(dossier, out_dir):
    """v7 exports + court report + proof folder + direct snapshot."""
    from .v7 import export_v7_dossier
    os.makedirs(out_dir, exist_ok=True)
    dossier = json.loads(json.dumps(dossier, default=str))  # detach
    direct = (dossier.get("v8") or {}).get("direct_profile") or {}
    snapshot_text = direct.pop("_snapshot_text", "") if isinstance(direct, dict) else ""
    snapshot_kind = direct.pop("_snapshot_kind", "html") if isinstance(direct, dict) else "html"
    paths = export_v7_dossier(dossier, out_dir)
    # Re-write dossier.json so the version reads 8.0.0 (export chain
    # already wrote it from this dict, which carries version=8.0.0).
    if snapshot_text:
        ext = "json" if snapshot_kind == "json" else "html"
        snap_path = os.path.join(out_dir, f"direct_profile_snapshot.{ext}")
        with open(snap_path, "w", encoding="utf-8") as fh:
            fh.write(snapshot_text)
        paths["direct_profile_snapshot"] = snap_path
        if direct.get("profile"):
            card_path = os.path.join(out_dir, "profile_proof.png")
            card = proof_card_png({**direct["profile"],
                                   "evidence": [{"source_url": (direct.get("parsed") or {}).get("url", ""),
                                                 "captured_at_utc": ""}]}, card_path)
            if card.get("status") == "found":
                paths["profile_proof.png"] = card_path
    with open(os.path.join(out_dir, "court_report.md"), "w", encoding="utf-8") as fh:
        fh.write(court_report(dossier, fmt="md"))
    with open(os.path.join(out_dir, "court_report.html"), "w", encoding="utf-8") as fh:
        fh.write(court_report(dossier, fmt="html"))
    paths["court_report.md"] = os.path.join(out_dir, "court_report.md")
    paths["court_report.html"] = os.path.join(out_dir, "court_report.html")
    proof = build_proof_folder(dossier, out_dir)
    paths["proof_index.json"] = os.path.join(out_dir, "proof_index.json")
    paths["proof_dir"] = proof["proof_dir"]
    return paths


# ------------------------------------------------------ v8 dispatch
def investigate_v8(seed, seed_type="username", keys=None, context="", parallel=4,
                   direct=False, fetcher=None, sleeper=None, progress=True,
                   variation_city="", variation_years=None):
    """Single v8 entry point for CLI + GUI. Returns
    (Investigation, v7_section_or_None, v8_section)."""
    from ..core.engine import run_investigation
    from ..core.provenance import utc_now_iso
    keys = dict(keys or {})
    st = (seed_type or "username").lower()
    if st == "auto":
        from .v7 import detect_seed_type
        st = detect_seed_type(seed)
        if st == "url" and direct:
            st = "profile"
    if st == "profile" or (st == "url" and direct):
        inv, section = investigate_direct_profile(seed, keys=keys, parallel=parallel,
                                                  fetcher=fetcher, sleeper=sleeper, progress=progress)
        return inv, None, section
    if st == "company":
        comp = company_seed(seed, fetcher=fetcher)
        inv = run_investigation(comp.get("domain") or seed, keys=keys, seed_type="domain")
        inv.seed, inv.seed_type = seed, "company"
        inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v8", "action": "company_seed",
                          "detail": {"domain": comp.get("domain"), "candidates": len(comp.get("staff_candidates", []))}})
        return inv, None, {"seed_type_resolved": "company", "company": comp}
    if st == "wallet":
        from .v7 import _blank_investigation
        inv = _blank_investigation(seed, "wallet", keys)
        sec = {"seed_type_resolved": "wallet", "wallet": wallet_seed(seed, keys=keys, fetcher=fetcher)}
        inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v8", "action": "wallet_seed",
                          "detail": {"status": sec["wallet"].get("status")}})
        return inv, None, sec
    if st == "plate":
        from .v7 import _blank_investigation
        inv = _blank_investigation(seed, "plate", keys)
        sec = {"seed_type_resolved": "plate", "plate": plate_seed(seed, keys=keys, fetcher=fetcher)}
        inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v8", "action": "plate_seed",
                          "detail": {"status": sec["plate"].get("status")}})
        return inv, None, sec
    if st == "name":
        from .v7 import _blank_investigation
        inv = _blank_investigation(seed, "name", keys)
        sec_name = name_search_v8(seed, context=context, keys=keys, fetcher=fetcher)
        inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v8", "action": "name_seed_v8",
                          "detail": {"candidates": len(sec_name.get("candidates", [])), "status": sec_name.get("status")}})
        return inv, None, {"seed_type_resolved": "name", "name": sec_name}
    if st in ("username", "domain"):
        if fetcher is None and parallel and int(parallel) > 1 and st == "username":
            inv = run_parallel_investigation(seed, keys=keys, parallel=int(parallel), progress=progress)
        else:
            inv = run_investigation(seed, keys=keys, seed_type=st)
        v8sec = {"seed_type_resolved": st}
        if st == "username":
            var = variations_v8(seed, city=variation_city, years=variation_years)
            v8sec["username_variations"] = var
            inv.audit.append({"ts_utc": utc_now_iso(), "actor": "features.v8",
                              "action": "variations_history",
                              "detail": {"seed": seed, "params": var["params"], "count": var["count"],
                                         "variations": var["variations"]}})
        return inv, None, v8sec
    # Everything else keeps the v7 dispatch, with email leads added.
    from .v7 import investigate_seed
    inv, v7sec = investigate_seed(seed, st, keys=keys, context=context, fetcher=fetcher)
    v8sec = {"seed_type_resolved": v7sec.get("seed_type_resolved", st)}
    if st == "email" and v7sec.get("gravatar"):
        v8sec["email_leads"] = gravatar_linked_leads(v7sec["gravatar"])
    if st == "url":
        v8sec["url"] = v7sec.get("url")
    return inv, v7sec, v8sec
