"""PersonaTrace v9.0.0 — the 16 no-key items from the 10/10 list.

Built on v8 (features/v8.py is unchanged). Everything here works
WITHOUT any API key; the 9 key-gated items from the 10/10 list keep
their v8 wiring and are out of scope for this module.

  #1  Name search without a key: one shared free search chain
      (SearXNG public instances -> DuckDuckGo lite -> DDG html ->
      Bing HTML -> Brave HTML, every result labelled search_snippet
      with the returning engine recorded) PLUS real free-API name
      candidates (GitHub user search, GitLab user search). Candidates
      keep the v7 rules: confidence <= 79, reasons, innocent
      explanations, human review queue, never asserted identity.
  #2  Dorking without a key: v7/v8 dork callers refactored onto the
      same shared chain (dork_v9); key route still wins when a search
      key exists.
  #3  Real adapters for the 24 v8 presence-only sites: each site is
      classified in code as data_adapter / meta_adapter /
      presence_only (with a written reason for every presence_only).
  #4  Verified site checks: a two-signal rule (HTTP status AND body
      signal must agree; disagreement = "uncertain", never "found")
      plus a live self-audit (--site-check-audit).
  #5  Backup routes + determinism: disk cache (24h TTL, labelled)
      behind GitHub / Wayback / crt.sh, DoH behind system DNS, a
      case run_fingerprint in dossier.json and --consistency-check
      (run twice, diff fingerprints, explain differences by source
      status — never hide them).
  #6  Real browser screenshots as proof (Playwright + Firefox):
      proof_shots/*.png + proof_index entries typed
      "browser_screenshot"; when no browser is available the v8
      snapshot-card path stays and is typed "snapshot_card".
  #7  Built-in transcription, no key: YouTube public captions
      (caption tracks from the watch page -> timedtext) and local
      Whisper detection (faster-whisper / openai-whisper) with a
      one-command setup script. Never a fake transcript.
  #8  Built-in local NLP pack (deterministic, offline, no cloud
      model): gazetteers + context rules for person/org/place,
      language ID, topic classification. spaCy + en_core_web_sm is
      auto-detected and used when the investigator installed it
      (scripts/setup_local_nlp.sh); a large trained model is NOT
      bundled in the ZIP (size) — that limit is stated, not hidden.
  #9  Speed: parallel execution is the v9 default, per-adapter soft
      timeouts + a global --time-budget mark slow optional sources
      degraded_timeout instead of blocking, and a 1-hour result
      cache serves repeated seeds (labelled).
  #10 Real 4-level graph: GitHub followers/following (public API,
      capped) are real level-3 nodes; level-4 = bio-link domains
      shared by level-3 accounts (their GitHub profiles fetched,
      capped). Every node carries its source.
  #11 Benchmark: scripts/benchmark.py runs 20+ real public seeds +
      nonexistent controls and writes BENCHMARK.md (shipped).
  #12 One-click installer: packaging/ (PyInstaller spec + build
      scripts) + run_personatrace.py launcher + INSTALL.md.
  #13 GUI dark theme to mockup level + v9 toggles.
  #14 GUI i18n: gui/static/i18n.json — en/ur/ar/es/fr/de, full key
      parity, RTL switching for ur/ar, localStorage persistence.
      Only UI chrome is translated; live content stays as-is.

Hard limits, unchanged: public data only; no face identification;
no private accounts/DMs; no live location; no phone people-search;
no password/breach data; no bulk personal-data export; no CAPTCHA /
rate-limit / login-wall bypass (single requests, stop and label);
no active port scans. No keys are bundled, logged or exported.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

VERSION = "9.0.0"

from .v7 import INNOCENT_EXPLANATIONS  # noqa: E402  (re-exported)
from .v8 import http_fetch, http_json, parse_opengraph, sha256_text  # noqa: E402

_BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
               "Gecko/20100101 Firefox/128.0")
_UA = "PersonaTrace/9.0 (public-data lookup)"


def _now_iso():
    from ..core.provenance import utc_now_iso
    return utc_now_iso()


# ============================================================ #1/#2 search
SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://search.bus-hit.me",
    "https://searxng.site",
    "https://search.inetol.net",
    "https://opnxng.com",
]


def _strip_tags(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _blocked_page(status, text):
    # NOTE: a bare "captcha" substring is NOT a block signal — normal
    # pages mention captcha in scripts/feature flags (GitHub ships an
    # "octocaptcha" flag on every profile page; verified live
    # 2026-10-29). Only robot-wall phrases or a block status count.
    low = (text or "").lower()
    return status in (401, 403, 429) or "are you a robot" in low or \
        "unusual traffic" in low or "verify you are human" in low or \
        "g-recaptcha" in low or "hcaptcha" in low


def _searxng_v9(query, fetcher=None, bases=None):
    bases = bases or SEARXNG_INSTANCES
    env_base = os.environ.get("SEARXNG_BASE_URL")
    if env_base:
        bases = [env_base.rstrip("/")] + [b for b in bases if b != env_base]
    for base in bases:
        url = (f"{base.rstrip('/')}/search?q={urllib.parse.quote(query)}"
               f"&format=json")
        status, data, _t, _f = http_json(url, fetcher=fetcher, timeout=6)
        if status == 200 and isinstance(data, dict) and data.get("results"):
            return [{"title": r.get("title", ""), "url": r.get("url", ""),
                     "snippet": r.get("content", ""), "engine": "searxng",
                     "engine_instance": base, "status": "search_snippet"}
                    for r in data["results"][:5]]
    return []


def _ddg_lite_results(query, fetcher=None):
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    status, text, _f = http_fetch(url, headers={"User-Agent": _BROWSER_UA},
                                  fetcher=fetcher, timeout=8)
    if status != 200 or not text or _blocked_page(status, text):
        return []
    out = []
    for m in re.finditer(r"<a[^>]+href=\"([^\"]+)\"[^>]*class=\"[^\"]*result-link"
                         r"|<a[^>]+class='result-link'[^>]+href='([^']+)'", text):
        href = _html.unescape(m.group(1) or m.group(2) or "")
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        seg = text[m.end():m.end() + 400]
        title = _strip_tags(re.search(r">(.*?)</a>", text[max(0, m.start() - 0):m.end()], re.S).group(1)) if False else ""
        out.append({"title": title, "url": href, "snippet": "",
                    "engine": "duckduckgo_lite", "status": "search_snippet"})
        if len(out) >= 5:
            break
    if not out:  # simpler lite layout: result-link anchors in order
        for m in re.finditer(r"class=\"result-link\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", text, re.S):
            href = _html.unescape(m.group(1))
            if "uddg=" in href:
                href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
            out.append({"title": _strip_tags(m.group(2)), "url": href,
                        "snippet": "", "engine": "duckduckgo_lite",
                        "status": "search_snippet"})
            if len(out) >= 5:
                break
    return out


def _ddg_html_results_v9(query, fetcher=None):
    from .v8 import _ddg_html_results
    raw = _ddg_html_results(query, fetcher=fetcher)
    return [{**r, "engine": "duckduckgo_html", "status": "search_snippet"}
            for r in raw]


def _bing_unwrap(href):
    """Bing result links are ck/a redirects carrying the real URL in
    the u=a1<base64> parameter — unwrap to the destination."""
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        u = (qs.get("u") or [""])[0]
        if u.startswith("a1"):
            import base64
            raw = u[2:]
            raw += "=" * (-len(raw) % 4)
            return base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")
    except Exception:
        pass
    return href


def _bing_html_results(query, fetcher=None):
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    status, text, _f = http_fetch(url, headers={"User-Agent": _BROWSER_UA},
                                  fetcher=fetcher, timeout=8)
    if status != 200 or not text or _blocked_page(status, text):
        return []
    out = []
    for block in re.finditer(r"<li class=\"b_algo\".*?</li>", text, re.S):
        seg = block.group(0)
        m = re.search(r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", seg, re.S)
        if not m:
            continue
        snip = re.search(r"<p[^>]*>(.*?)</p>", seg, re.S)
        out.append({"title": _strip_tags(m.group(2)),
                    "url": _bing_unwrap(_html.unescape(m.group(1))),
                    "snippet": _strip_tags(snip.group(1)) if snip else "",
                    "engine": "bing_html", "status": "search_snippet"})
        if len(out) >= 5:
            break
    return out


def _brave_html_results(query, fetcher=None):
    url = "https://search.brave.com/search?q=" + urllib.parse.quote(query)
    status, text, _f = http_fetch(url, headers={"User-Agent": _BROWSER_UA},
                                  fetcher=fetcher, timeout=8)
    if status != 200 or not text or _blocked_page(status, text):
        return []
    out = []
    for m in re.finditer(r"<a[^>]+href=\"(https?://[^\"]+)\"[^>]*class=\"[^\"]*"
                         r"result-header|<a[^>]+class=\"[^\"]*\"[^>]+href=\"(https?://[^\"]+)\"[^>]*>\s*<span[^>]*>(.*?)</span>", text, re.S):
        href = m.group(1) or m.group(2) or ""
        if any(d in href for d in ("brave.com", "cdn.search.brave.com")):
            continue
        out.append({"title": _strip_tags(m.group(3) or ""), "url": href,
                    "snippet": "", "engine": "brave_html",
                    "status": "search_snippet"})
        if len(out) >= 5:
            break
    if not out:  # fallback: snippet blocks carry data in div.snippet
        for m in re.finditer(r"<div class=\"snippet[^\"]*\"[^>]*>.*?<a[^>]+href=\"(https?://[^\"]+)\"", text, re.S):
            href = m.group(1)
            if "brave.com" in href:
                continue
            out.append({"title": "", "url": href, "snippet": "",
                        "engine": "brave_html", "status": "search_snippet"})
            if len(out) >= 5:
                break
    return out


_SEARCH_ENGINES = ("searxng", "duckduckgo_lite", "duckduckgo_html",
                   "bing_html", "brave_html")


def free_search_chain_v9(query, fetcher=None, engines=None):
    """The one shared no-key web search chain (#1/#2).

    Tries engines in order, one quick attempt each, moves on fast on
    failure/block. Returns {status, engine, engines_tried, results}
    where every result is labelled search_snippet and carries the
    engine that returned it. 0 results = not_checked, never not_found.
    """
    engines = list(engines or _SEARCH_ENGINES)
    tried = []
    fns = {"searxng": _searxng_v9, "duckduckgo_lite": _ddg_lite_results,
           "duckduckgo_html": _ddg_html_results_v9,
           "bing_html": _bing_html_results, "brave_html": _brave_html_results}
    for name in engines:
        fn = fns.get(name)
        if fn is None:
            continue
        tried.append(name)
        try:
            results = fn(query, fetcher=fetcher)
        except Exception:
            results = []
        if results:
            return {"status": "search_snippet", "engine": name,
                    "engines_tried": tried, "results": results}
    return {"status": "not_checked", "engine": None, "engines_tried": tried,
            "results": [],
            "note": "Every free engine in the chain failed, blocked, or "
                    "returned nothing for this query. That is not_checked, "
                    "not evidence the person/content is absent."}


def _candidate_from_result(name, context, result):
    blob = ((result.get("title") or "") + " " + (result.get("snippet") or "")).lower()
    score = 40
    reasons = ["name appears in a public search result (snippet)"]
    if name.lower() in blob:
        score += 20
        reasons.append("full name in title/snippet text")
    ctx_terms = [t.lower() for t in re.split(r"[,\s]+", context or "") if len(t) > 2]
    for t in ctx_terms:
        if t in blob:
            score += 15
            reasons.append(f"context term matched: {t}")
    return {"title": result.get("title"), "url": result.get("url"),
            "snippet": result.get("snippet"), "status": "search_snippet",
            "engine": result.get("engine"), "confidence": min(score, 79),
            "reasons": reasons, "innocent_explanations": INNOCENT_EXPLANATIONS,
            "review_status": "pending"}


def name_api_candidates(name, fetcher=None):
    """Real free-API name candidates: GitHub user search + GitLab
    user search. These are real profile records (public_api), still
    capped at 79 and queued for human review — a name match on a
    code platform is a lead, not an identity."""
    out = []
    q = urllib.parse.quote(name)
    status, data, _t, _f = http_json(
        f"https://api.github.com/search/users?q={q}&per_page=5",
        headers={"Accept": "application/vnd.github+json"}, fetcher=fetcher)
    if status == 200 and isinstance(data, dict):
        for item in (data.get("items") or [])[:5]:
            login = item.get("login")
            if not login:
                continue
            out.append({"title": f"{login} · GitHub", "url": item.get("html_url") or f"https://github.com/{login}",
                        "snippet": "", "status": "candidate", "source": "github_user_search_api",
                        "platform": "github", "username": login, "confidence": 55,
                        "reasons": ["GitHub user search returned this login for the exact name query",
                                    "code-platform accounts often use real names, but logins also collide"],
                        "innocent_explanations": INNOCENT_EXPLANATIONS,
                        "review_status": "pending"})
    status, data, _t, _f = http_json(
        f"https://gitlab.com/api/v4/users?search={q}&per_page=5",
        fetcher=fetcher)
    if status == 200 and isinstance(data, list):
        for item in data[:5]:
            uname = item.get("username")
            if not uname:
                continue
            disp = item.get("name") or ""
            score = 65 if disp.lower() == name.lower() else 50
            out.append({"title": f"{disp or uname} · GitLab", "url": item.get("web_url") or f"https://gitlab.com/{uname}",
                        "snippet": disp, "status": "candidate", "source": "gitlab_user_search_api",
                        "platform": "gitlab", "username": uname, "confidence": min(score, 79),
                        "reasons": [f"GitLab user search returned display name {disp!r} for the name query"] if disp else ["GitLab user search returned this username for the name query"],
                        "innocent_explanations": INNOCENT_EXPLANATIONS,
                        "review_status": "pending"})
    return out


def name_search_v9(name, context="", keys=None, search_fetcher=None, fetcher=None):
    """#1: name search that returns real candidates without a key.

    Web chain (shared with dorking) + free-API candidates, deduped
    by URL. With a Brave key or an injected search_fetcher the v7
    keyed/tested path still runs first, then API candidates merge.
    """
    from .v7 import name_queries
    n = (name or "").strip()
    if len(n) < 3 or " " not in n:
        return {"status": "not_found", "candidates": [], "queries": [],
                "note": "A name seed needs a full name (at least two words). "
                        "A single word is a username — run it as a username seed instead."}
    keys = dict(keys or {})
    qs = name_queries(n, context)
    candidates, engines_tried, engines_used = [], [], set()
    have_key = bool(keys.get("brave_search_key") or os.environ.get("BRAVE_SEARCH_KEY"))
    if search_fetcher is not None or have_key:
        from .v7 import name_search as _v7_name
        base = _v7_name(n, context=context, keys=keys, search_fetcher=search_fetcher)
        candidates.extend(base.get("candidates", []))
        engines_used.add("brave_api" if have_key else "injected_search_fetcher")
    else:
        for q in qs[:3]:
            chain = free_search_chain_v9(q, fetcher=fetcher)
            engines_tried.extend(chain.get("engines_tried", []))
            if chain.get("engine"):
                engines_used.add(chain["engine"])
            for r in chain.get("results", []):
                candidates.append(_candidate_from_result(n, context, r))
    try:
        candidates.extend(name_api_candidates(n, fetcher=fetcher))
        engines_used.add("github_user_search_api+gitlab_user_search_api")
    except Exception:
        pass
    seen, deduped = set(), []
    for c in candidates:
        u = (c.get("url") or "").rstrip("/").lower()
        if not u or u in seen:
            continue
        seen.add(u)
        deduped.append(c)
    return {"status": "search_snippet" if deduped else "not_checked",
            "candidates": deduped, "queries": qs,
            "engines_tried": engines_tried, "engines_used": sorted(engines_used),
            "note": "Name results are candidates for human review only — never a certain "
                    "identity (common names, namesakes, impersonators; see "
                    "innocent_explanations). Web results are search_snippet until opened. "
                    "Free web engines are fragile; 0 web results means not_checked. "
                    "GitHub/GitLab API candidates are real profile records returned for "
                    "the name query, still leads only."}


def dork_v9(queries, keys=None, search_fetcher=None, fetcher=None):
    """#2: dorking on the shared chain. Key/injected routes win;
    otherwise every query runs through free_search_chain_v9 and
    results keep their returning engine."""
    keys = dict(keys or {})
    have_key = bool(keys.get("brave_search_key") or os.environ.get("BRAVE_SEARCH_KEY"))
    if search_fetcher is not None or have_key:
        from .v7 import _dork_search
        return _dork_search(list(queries), keys=keys, search_fetcher=search_fetcher)
    results, engines_used = [], set()
    for q in list(queries)[:4]:
        chain = free_search_chain_v9(q, fetcher=fetcher)
        if chain.get("engine"):
            engines_used.add(chain["engine"])
        for r in chain.get("results", []):
            results.append({"query": q, "title": r.get("title", ""),
                            "url": r.get("url", ""), "snippet": r.get("snippet", ""),
                            "engine": r.get("engine"), "status": "search_snippet"})
    return {"status": "search_snippet" if results else "not_checked",
            "queries": list(queries), "results": results,
            "engines_used": sorted(engines_used),
            "note": "Free search chain (SearXNG -> DDG lite -> DDG html -> Bing -> "
                    "Brave HTML). Snippets are unverified until the source URL is "
                    "opened; 0 results = not_checked, never not_found."}


# ============================================================ #3 site adapters
# Classification of the 24 v8 presence entries. data_adapter = a real
# free route returns profile fields; meta_adapter = a real public
# page/oEmbed fetch returns OG/oEmbed fields (derived); presence_only
# = no trustworthy public data route exists (reason stated) — only
# the two-signal presence check (#4) runs for those.
SITE_ADAPTERS_V9 = [
    {"service": "devto", "classification": "data_adapter",
     "route": "Forem API /api/articles + /api/users/by_username",
     "url": "https://dev.to/{u}"},
    {"service": "lemmy", "classification": "data_adapter",
     "route": "public instance /api/v3/user?username=",
     "url": "https://lemmy.world/u/{u}"},
    {"service": "dailymotion", "classification": "data_adapter",
     "route": "public API /user/<username>",
     "url": "https://www.dailymotion.com/{u}"},
    {"service": "medium", "classification": "data_adapter",
     "route": "RSS feed medium.com/feed/@<user> (existence + posts)",
     "url": "https://medium.com/@{u}"},
    {"service": "keybase", "classification": "data_adapter",
     "route": "public lookup API /_/api/1.0/user/lookup.json",
     "url": "https://keybase.io/{u}"},
    {"service": "gravatar", "classification": "data_adapter",
     "route": "public profile JSON gravatar.com/<user>.json",
     "url": "https://gravatar.com/{u}"},
    {"service": "reddit_archive", "classification": "data_adapter",
     "route": "Arctic Shift public archive search API (historical posts)",
     "url": "https://arctic-shift.photon-reddit.com/search?author={u}"},
    {"service": "soundcloud", "classification": "data_adapter",
     "route": "oEmbed for the public profile URL (author + title)",
     "url": "https://soundcloud.com/{u}"},
    {"service": "vimeo", "classification": "data_adapter",
     "route": "oEmbed for the public profile URL (author + title)",
     "url": "https://vimeo.com/{u}"},
    {"service": "substack", "classification": "meta_adapter",
     "route": "publication feed, then profile/publication page OG meta",
     "url": "https://{u}.substack.com"},
    {"service": "flickr", "classification": "meta_adapter",
     "route": "public photostream page OG meta (RSS needs an NSID, not a username)",
     "url": "https://www.flickr.com/photos/{u}/"},
    {"service": "twitch", "classification": "meta_adapter",
     "route": "public channel page OG meta (official API needs a client id)",
     "url": "https://www.twitch.tv/{u}"},
    {"service": "steam", "classification": "meta_adapter",
     "route": "public profile page OG meta (only when the custom URL resolves)",
     "url": "https://steamcommunity.com/id/{u}"},
    {"service": "producthunt", "classification": "meta_adapter",
     "route": "public profile page OG meta (GraphQL API needs a token)",
     "url": "https://www.producthunt.com/@{u}"},
    {"service": "spotify", "classification": "meta_adapter",
     "route": "public user page OG meta (Web API needs a token)",
     "url": "https://open.spotify.com/user/{u}"},
    {"service": "goodreads", "classification": "meta_adapter",
     "route": "public profile page OG meta (API was retired by Goodreads)",
     "url": "https://www.goodreads.com/{u}"},
    {"service": "quora", "classification": "presence_only",
     "route": "none — Quora serves bot walls / login prompts to unauthenticated fetches and has no public profile API",
     "url": "https://www.quora.com/profile/{u}"},
    {"service": "pinterest", "classification": "presence_only",
     "route": "none — Pinterest profile data is JS-rendered behind bot checks; no public API without an app token",
     "url": "https://www.pinterest.com/{u}/"},
    {"service": "snapchat", "classification": "presence_only",
     "route": "none — Snapchat web profiles expose no public profile data route (add-page only)",
     "url": "https://www.snapchat.com/add/{u}"},
    {"service": "kick", "classification": "presence_only",
     "route": "none — Kick's channel API is behind Cloudflare bot checks for unauthenticated fetches",
     "url": "https://kick.com/{u}"},
    {"service": "xbox", "classification": "presence_only",
     "route": "none — Xbox profile APIs require Microsoft authentication (XBL tokens)",
     "url": "https://account.xbox.com/en-us/profile?gamertag={u}"},
    {"service": "playstation", "classification": "presence_only",
     "route": "none — the PSN API requires a Sony account NPSSO token; third-party trackers are not an official route",
     "url": "https://psnprofiles.com/{u}"},
    {"service": "strava", "classification": "presence_only",
     "route": "none — Strava athlete pages require login for profile data and the API needs OAuth",
     "url": "https://www.strava.com/athletes/{u}"},
    {"service": "angellist", "classification": "presence_only",
     "route": "none — AngelList/Wellfound profiles are JS-rendered behind bot checks; the old public API is retired",
     "url": "https://angel.co/u/{u}"},
]


def _adapter_result(entry, username, status, profile=None, source_url="", note=""):
    return {"service": entry["service"], "classification": entry["classification"],
            "route": entry["route"], "status": status,
            "profile": profile or {}, "source_url": source_url, "note": note}


def _oembed_profile(entry, username, fetcher=None):
    page = entry["url"].format(u=urllib.parse.quote(str(username)))
    api = ("https://%s/oembed?url=%s&format=json" %
           ("soundcloud.com" if entry["service"] == "soundcloud" else "vimeo.com",
            urllib.parse.quote(page, safe="")))
    if entry["service"] == "vimeo":
        api = "https://vimeo.com/api/oembed.json?url=" + urllib.parse.quote(page, safe="")
    status, data, _t, _f = http_json(api, fetcher=fetcher)
    if status == 200 and isinstance(data, dict) and (data.get("author_name") or data.get("title")):
        return _adapter_result(entry, username, "found",
                               {"display_name": data.get("author_name") or "",
                                "page_title": data.get("title") or "",
                                "profile_url": data.get("author_url") or page},
                               source_url=page, note="oEmbed record for the public profile URL.")
    if status == 404:
        return _adapter_result(entry, username, "not_found", source_url=page,
                               note="oEmbed returned 404 for this profile URL.")
    return _adapter_result(entry, username, "blocked" if status in (401, 403, 429) else "not_checked",
                           source_url=page, note=f"oEmbed returned HTTP {status}.")


def _meta_profile(entry, username, fetcher=None):
    from .v8 import _og_fields
    url = entry["url"].format(u=urllib.parse.quote(str(username)))
    status, text, _f = http_fetch(url, headers={"User-Agent": _BROWSER_UA}, fetcher=fetcher)
    if status == 200 and text:
        og = _og_fields(parse_opengraph(text))
        # The meta must actually mention this username — generic site
        # meta (e.g. a platform homepage title) is NOT a profile.
        mentions_user = str(username).lower() in (
            (og.get("display_name") or "") + " " + (og.get("bio") or "")).lower()
        if (og.get("display_name") or og.get("bio")) and mentions_user:
            return _adapter_result(entry, username, "found",
                                   {"display_name": og["display_name"], "bio": og["bio"],
                                    "avatar_url": og["avatar_url"], "profile_url": url},
                                   source_url=url,
                                   note="Fields are derived from the public page's OpenGraph/meta only.")
        return _adapter_result(entry, username, "uncertain", source_url=url,
                               note="Page returned 200 but its meta does not mention this username "
                                    "(generic site page or soft-404) — not counted as a profile.")
    if status == 404:
        return _adapter_result(entry, username, "not_found", source_url=url)
    return _adapter_result(entry, username, "blocked" if status in (401, 403, 429) else "not_checked",
                           source_url=url, note=f"Public page returned HTTP {status}.")


def site_adapter_fetch(service, username, fetcher=None):
    """Fetch one of the 24 v8 sites through its v9 route. Returns a
    classified result dict; presence_only sites run the two-signal
    presence check (#4) instead of a data fetch."""
    entry = next((e for e in SITE_ADAPTERS_V9 if e["service"] == service), None)
    if entry is None:
        return {"service": service, "classification": "unknown", "status": "not_checked",
                "profile": {}, "note": "Not one of the 24 v9 site adapters."}
    u = str(username)
    if entry["classification"] == "presence_only":
        chk = check_site_two_signal(entry, u, fetcher=fetcher)
        return _adapter_result(entry, u, chk["status"], source_url=chk["url"],
                               note="presence_only: " + entry["route"] +
                                    " Two-signal presence check result only — no profile data claimed.")
    if service == "devto":
        status, data, _t, _f = http_json(
            f"https://dev.to/api/users/by_username?url={urllib.parse.quote(u)}", fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and data.get("username"):
            return _adapter_result(entry, u, "found",
                                   {"username": data.get("username"), "display_name": data.get("name") or "",
                                    "bio": data.get("summary") or "", "profile_url": f"https://dev.to/{u}",
                                    "twitter": data.get("twitter_username") or "",
                                    "github": data.get("github_username") or "",
                                    "website": data.get("website_url") or ""},
                                   source_url=f"https://dev.to/{u}", note="Forem public API user record.")
        return _adapter_result(entry, u, "not_found" if status == 404 else "not_checked",
                               source_url=f"https://dev.to/{u}", note=f"Forem API returned HTTP {status}.")
    if service == "lemmy":
        for inst in ("lemmy.world", "lemmy.ml", "sh.itjust.works"):
            status, data, _t, _f = http_json(
                f"https://{inst}/api/v3/user?username={urllib.parse.quote(u)}", fetcher=fetcher)
            if status == 200 and isinstance(data, dict) and data.get("person_view"):
                p = data["person_view"]["person"]
                counts = data["person_view"].get("counts") or {}
                return _adapter_result(entry, u, "found",
                                       {"username": p.get("name"), "display_name": p.get("display_name") or "",
                                        "bio": p.get("bio") or "", "created_at": p.get("published") or "",
                                        "post_count": counts.get("post_count"), "comment_count": counts.get("comment_count"),
                                        "profile_url": p.get("actor_id") or f"https://{inst}/u/{u}"},
                                       source_url=f"https://{inst}/u/{u}",
                                       note=f"Lemmy public API on {inst}.")
        return _adapter_result(entry, u, "not_checked", source_url=f"https://lemmy.world/u/{u}",
                               note="No sampled Lemmy instance returned a user record (the account may live on another instance).")
    if service == "dailymotion":
        status, data, _t, _f = http_json(
            f"https://api.dailymotion.com/user/{urllib.parse.quote(u)}?fields=id,username,screenname,description,followers_total,videos_total,url,created_time",
            fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and (data.get("username") or data.get("id")):
            return _adapter_result(entry, u, "found",
                                   {"username": data.get("username"), "display_name": data.get("screenname") or "",
                                    "bio": data.get("description") or "", "follower_count": data.get("followers_total"),
                                    "profile_url": data.get("url") or f"https://www.dailymotion.com/{u}"},
                                   source_url=f"https://www.dailymotion.com/{u}", note="Dailymotion public API user record.")
        return _adapter_result(entry, u, "not_found" if status in (400, 404) else "not_checked",
                               source_url=f"https://www.dailymotion.com/{u}",
                               note=f"Dailymotion API returned HTTP {status}.")
    if service == "medium":
        feed = f"https://medium.com/feed/@{urllib.parse.quote(u)}"
        status, text, _f = http_fetch(feed, fetcher=fetcher)
        if status == 200 and text and "<rss" in text[:2000].lower():
            titles = re.findall(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", text, re.S)
            return _adapter_result(entry, u, "found",
                                   {"username": u, "profile_url": f"https://medium.com/@{u}",
                                    "recent_post_titles": [_html.unescape(_strip_tags(t))[:140] for t in titles[:5]],
                                    "post_count_in_feed": len(titles)},
                                   source_url=feed, note="Medium RSS feed exists and lists posts.")
        return _adapter_result(entry, u, "not_found" if status == 404 else "not_checked",
                               source_url=feed, note=f"Medium feed returned HTTP {status}.")
    if service == "keybase":
        status, data, _t, _f = http_json(
            f"https://keybase.io/_/api/1.0/user/lookup.json?username={urllib.parse.quote(u)}", fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and (data.get("them") or {}).get("id"):
            them = data["them"]
            basics = (them.get("profile") or {})
            return _adapter_result(entry, u, "found",
                                   {"username": (them.get("basics") or {}).get("username"),
                                    "display_name": basics.get("full_name") or "",
                                    "bio": basics.get("bio") or "",
                                    "profile_url": f"https://keybase.io/{u}"},
                                   source_url=f"https://keybase.io/{u}", note="Keybase public lookup API.")
        return _adapter_result(entry, u, "not_found" if status == 200 else "not_checked",
                               source_url=f"https://keybase.io/{u}", note="Keybase lookup returned no user.")
    if service == "gravatar":
        status, data, _t, _f = http_json(f"https://gravatar.com/{urllib.parse.quote(u)}.json", fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and data.get("entry"):
            e0 = data["entry"][0]
            return _adapter_result(entry, u, "found",
                                   {"username": e0.get("preferredUsername"), "display_name": e0.get("displayName") or "",
                                    "profile_url": e0.get("profileUrl") or f"https://gravatar.com/{u}"},
                                   source_url=f"https://gravatar.com/{u}", note="Gravatar public profile JSON by username.")
        return _adapter_result(entry, u, "not_found" if status == 404 else "not_checked",
                               source_url=f"https://gravatar.com/{u}", note=f"Gravatar profile JSON returned HTTP {status}.")
    if service == "reddit_archive":
        url = (f"https://arctic-shift.photon-reddit.com/api/posts/search?"
               f"author={urllib.parse.quote(u)}&limit=5")
        status, data, _t, _f = http_json(url, fetcher=fetcher)
        if status == 200 and isinstance(data, dict):
            posts = data.get("data") or []
            return _adapter_result(entry, u, "found" if posts else "not_found",
                                   {"username": u, "archived_post_count_sample": len(posts),
                                    "profile_url": f"https://www.reddit.com/user/{u}"},
                                   source_url=url,
                                   note="Arctic Shift archive (historical, ~36h lag in v3 notes) — archived posts only, not live Reddit.")
        return _adapter_result(entry, u, "not_checked", source_url=url,
                               note=f"Arctic Shift API returned HTTP {status}.")
    if service in ("soundcloud", "vimeo"):
        return _oembed_profile(entry, u, fetcher=fetcher)
    if service == "substack":
        feed = f"https://{urllib.parse.quote(u)}.substack.com/feed"
        status, text, _f = http_fetch(feed, fetcher=fetcher)
        if status == 200 and text and "<rss" in text[:2000].lower():
            titles = re.findall(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", text, re.S)
            return _adapter_result(entry, u, "found",
                                   {"username": u, "profile_url": f"https://{u}.substack.com",
                                    "recent_post_titles": [_html.unescape(_strip_tags(t))[:140] for t in titles[:5]]},
                                   source_url=feed, note="Substack publication RSS feed exists.")
        return _meta_profile(entry, u, fetcher=fetcher)
    # remaining meta_adapter services
    return _meta_profile(entry, u, fetcher=fetcher)


def site_adapters_v9(username, fetcher=None, services=None):
    """Run the 24 classified site adapters for one username."""
    rows = []
    for entry in SITE_ADAPTERS_V9:
        if services and entry["service"] not in services:
            continue
        try:
            rows.append(site_adapter_fetch(entry["service"], username, fetcher=fetcher))
        except Exception as exc:
            rows.append(_adapter_result(entry, username, "degraded", note=str(exc)[:140]))
    counts = Counter(r["status"] for r in rows)
    return {"status": "found", "count": len(rows), "status_counts": dict(counts),
            "classifications": {e["service"]: e["classification"] for e in SITE_ADAPTERS_V9},
            "checks": rows,
            "note": "data_adapter rows carry real profile fields from a free route; "
                    "meta_adapter rows carry OpenGraph/oEmbed-derived fields; "
                    "presence_only rows carry no profile data — see each row's route reason."}


# ============================================================ #4 two-signal
_NOT_FOUND_PHRASES_V9 = (
    "user not found", "page not found", "profile not found",
    "this account doesn't exist", "does not exist", "doesn't exist",
    "not found", "no such user", "couldn't find", "could not be found",
    "this page is no longer available", "account suspended",
)


def check_site_two_signal(entry, username, fetcher=None):
    """Two-signal site check: HTTP status and body signal must AGREE.

    found     = 2xx AND a profile marker (username / OG profile data)
                AND no not-found phrase.
    not_found = 404, OR (2xx AND a not-found phrase AND no marker).
    uncertain = the signals disagree — never reported as found.
    blocked   = 401/403/429 or a CAPTCHA/robot page.
    """
    site = entry.get("service") or entry.get("site") or "site"
    template = entry.get("url") or ""
    url = template.format(u=urllib.parse.quote(str(username)))
    status, text, _f = http_fetch(url, headers={"User-Agent": _BROWSER_UA},
                                  fetcher=fetcher)
    body = (text or "")
    low = body.lower()
    if status in (401, 403, 429) or _blocked_page(status, body):
        return {"site": site, "url": url, "status": "blocked", "http_status": status,
                "signals": {"http": status, "body": "blocked"}}
    nf_phrase = any(p in low for p in _NOT_FOUND_PHRASES_V9)
    og = parse_opengraph(body) if body else {}
    marker = bool(og.get("og:title") or og.get("profile:username")) and \
        (str(username).lower() in low or bool(og.get("og:image")))
    if status == 404:
        verdict = "uncertain" if marker else "not_found"
    elif status is not None and 200 <= status < 300:
        if nf_phrase and marker:
            verdict = "uncertain"
        elif nf_phrase:
            verdict = "not_found"
        elif marker:
            verdict = "found"
        else:
            verdict = "uncertain"
    elif status is None:
        verdict = "not_checked"
    else:
        verdict = "uncertain"
    return {"site": site, "url": url, "status": verdict, "http_status": status,
            "signals": {"http": status, "not_found_phrase": nf_phrase,
                        "profile_marker": marker}}


# Known-existing handles per sampled site for the self-audit. These
# are the sites' own / canonical accounts where one exists.
_AUDIT_KNOWN_EXISTING = {
    "github": "octocat", "dev.to": "devteam", "soundcloud": "soundcloud",
    "producthunt": "producthunt", "kaggle": "kaggle", "codepen": "codepen",
    "dribbble": "dribbble", "behance": "behance", "spotify": "spotify",
    "gitlab": "gitlab", "stackoverflow": "1",
}
_AUDIT_NONEXISTENT = "pt-no-such-user-9f3k2x7q"


def site_check_audit(existing=None, nonexistent=None, fetcher=None, sites=None):
    """Live self-audit of the two-signal checker over the v2 reliable
    site templates: one known-existing + one known-nonexisting handle
    per sampled site. false_positive = a nonexistent handle called
    found; false_negative = an existing handle called not_found;
    'uncertain' is counted separately (it is the safe outcome)."""
    from .v2 import SITE_CHECKS
    existing = existing or _AUDIT_KNOWN_EXISTING
    nonexistent = nonexistent or _AUDIT_NONEXISTENT
    rows, fp, fn, uncertain = [], 0, 0, 0
    for entry in SITE_CHECKS:
        site = entry["site"]
        if sites and site not in sites:
            continue
        handle = existing.get(site)
        if not handle:
            continue
        ent = {"service": site, "url": entry["url"]}
        got = check_site_two_signal(ent, handle, fetcher=fetcher)
        exp = check_site_two_signal(ent, nonexistent, fetcher=fetcher)
        if exp["status"] == "found":
            fp += 1
        if got["status"] == "not_found":
            fn += 1
        uncertain += (got["status"] == "uncertain") + (exp["status"] == "uncertain")
        rows.append({"site": site, "existing_handle": handle,
                     "existing_result": got["status"],
                     "nonexistent_handle": nonexistent,
                     "nonexistent_result": exp["status"]})
    return {"status": "found", "sampled_sites": len(rows),
            "checks_run": len(rows) * 2, "false_positives": fp,
            "false_negatives": fn, "uncertain": uncertain, "rows": rows,
            "note": "Live self-audit of the two-signal rule. uncertain is the "
                    "designed safe outcome when status and body disagree — it is "
                    "counted separately, never as found."}


# ============================================================ #5 cache/routes
def _cache_dir():
    d = os.environ.get("PERSONATRACE_CACHE_DIR") or str(Path.home() / ".cache" / "personatrace-v9")
    os.makedirs(d, exist_ok=True)
    return d


def disk_cache_get(key, ttl_seconds=86400):
    """Return (payload, age_seconds) for a fresh-enough entry, else
    (None, None). Corrupt entries are ignored, never raised."""
    try:
        path = os.path.join(_cache_dir(), sha256_text(key) + ".json")
        if not os.path.isfile(path):
            return None, None
        with open(path, encoding="utf-8") as fh:
            row = json.load(fh)
        age = time.time() - float(row.get("ts", 0))
        if age > ttl_seconds:
            return None, None
        return row.get("payload"), age
    except Exception:
        return None, None


def disk_cache_put(key, payload):
    try:
        path = os.path.join(_cache_dir(), sha256_text(key) + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"ts": time.time(), "key": key, "payload": payload}, fh, default=str)
        return path
    except Exception:
        return None


def github_profile_cached(username, keys=None, fetcher=None, sleeper=None):
    """GitHub with the v8 chain (token -> retry/backoff -> web
    fallback) and the v9 disk cache as the last route. A cache hit
    used after a live failure is labelled with its age."""
    from .v8 import github_profile_fetch
    res = github_profile_fetch(username, keys=keys, fetcher=fetcher, sleeper=sleeper)
    if res.get("status") == "found":
        disk_cache_put(f"github:{username.lower()}", res)
        return res
    cached, age = disk_cache_get(f"github:{username.lower()}")
    if cached:
        out = dict(cached)
        out["route"] = "disk_cache"
        out["cache_age_seconds"] = int(age)
        out["note"] = (out.get("note", "") + f" Live routes failed this run; this is a "
                       f"cached successful payload, {int(age)}s old (TTL 24h), labelled as cache.").strip()
        return out
    return res


def wayback_snapshots_v9(url, fetcher=None):
    """Wayback CDX -> archive.today newest -> disk cache."""
    from .v6 import wayback_cdx
    primary = wayback_cdx(url, fetcher=fetcher)
    if primary.get("status") == "found" and primary.get("snapshots"):
        disk_cache_put(f"wayback:{url}", primary)
        return {"status": "found", "route": "wayback_cdx", **primary}
    at_url = "https://archive.ph/newest/" + urllib.parse.quote(url, safe="")
    status, text, final = http_fetch(at_url, fetcher=fetcher)
    if status in (200, 301, 302) and final and "archive.ph" in final:
        out = {"status": "found", "route": "archive_today", "snapshots": [],
               "archive_today_url": final if final != at_url else at_url,
               "note": "Wayback CDX returned nothing usable; archive.today has a capture of this URL (newest link resolved). Snapshot list detail is not available from this route."}
        disk_cache_put(f"wayback:{url}", out)
        return out
    cached, age = disk_cache_get(f"wayback:{url}")
    if cached:
        return {**cached, "route": "disk_cache", "cache_age_seconds": int(age),
                "note": f"Live archive routes failed; cached result {int(age)}s old (TTL 24h)."}
    return {"status": primary.get("status", "not_checked"), "route": None,
            "snapshots": [], "note": "Wayback CDX and archive.today both returned nothing usable, and no fresh cache entry exists."}


def crtsh_v9(domain, fetcher=None):
    """crt.sh JSON -> one retry with a longer timeout -> disk cache."""
    url = f"https://crt.sh/?q=%25.{urllib.parse.quote(domain)}&output=json"
    for attempt, timeout in ((1, 8), (2, 15)):
        status, data, _t, _f = http_json(url, fetcher=fetcher, timeout=timeout)
        if status == 200 and isinstance(data, list):
            names = sorted({n.strip().lower() for row in data
                            for n in str(row.get("name_value", "")).split("\n") if n.strip()})
            out = {"status": "found", "route": "crtsh", "attempt": attempt,
                   "domain": domain, "names": names[:200], "cert_count": len(data)}
            disk_cache_put(f"crtsh:{domain.lower()}", out)
            return out
    cached, age = disk_cache_get(f"crtsh:{domain.lower()}")
    if cached:
        return {**cached, "route": "disk_cache", "cache_age_seconds": int(age),
                "note": f"crt.sh failed twice this run; cached result {int(age)}s old (TTL 24h)."}
    return {"status": "degraded", "route": None, "domain": domain, "names": [],
            "note": "crt.sh returned no usable JSON on either attempt and no fresh cache entry exists."}


def dns_lookup_v9(hostname, fetcher=None):
    """System resolver -> DNS-over-HTTPS (Cloudflare, then Google)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
        ips = sorted({i[4][0] for i in infos})
        if ips:
            return {"status": "found", "route": "system_resolver", "hostname": hostname, "addresses": ips}
    except Exception:
        pass
    for name, url in (("cloudflare_doh", f"https://cloudflare-dns.com/dns-query?name={urllib.parse.quote(hostname)}&type=A"),
                      ("google_doh", f"https://dns.google/resolve?name={urllib.parse.quote(hostname)}&type=A")):
        status, data, _t, _f = http_json(url, headers={"Accept": "application/dns-json"},
                                         fetcher=fetcher)
        if status == 200 and isinstance(data, dict) and data.get("Answer"):
            ips = sorted({a.get("data") for a in data["Answer"] if a.get("type") == 1 and a.get("data")})
            if ips:
                return {"status": "found", "route": name, "hostname": hostname, "addresses": ips}
    return {"status": "not_found", "route": None, "hostname": hostname, "addresses": [],
            "note": "System resolver and both DoH fallbacks returned no A records."}


def run_fingerprint(profiles):
    """Deterministic fingerprint of a run: the sorted set of
    platform:username:status across collected profiles + its hash."""
    items = sorted({f"{(p.get('platform') or '').lower()}:{(p.get('username') or '').lower()}:{(p.get('status') or '')}"
                    for p in (profiles or []) if isinstance(p, dict) and p.get("platform")})
    return {"profiles": items, "count": len(items),
            "sha256": sha256_text("\n".join(items))}


def diff_fingerprints(fp_a, fp_b, audit_a=None, audit_b=None):
    """Explain a fingerprint difference by source status changes."""
    a, b = set(fp_a.get("profiles", [])), set(fp_b.get("profiles", []))
    changed_sources = []
    def _statuses(audit):
        out = {}
        for row in (audit or []):
            if isinstance(row, dict) and row.get("action") == "adapter_search":
                d = row.get("detail", {})
                out[d.get("platform")] = d.get("status")
        return out
    sa, sb = _statuses(audit_a), _statuses(audit_b)
    for plat in sorted(set(sa) | set(sb)):
        if sa.get(plat) != sb.get(plat):
            changed_sources.append({"platform": plat, "run_a": sa.get(plat), "run_b": sb.get(plat)})
    return {"match": a == b, "only_in_a": sorted(a - b), "only_in_b": sorted(b - a),
            "changed_source_statuses": changed_sources,
            "note": "Differences are explained by the per-source statuses above "
                    "(degraded / not_checked / blocked sources change the profile "
                    "set between runs). Nothing is hidden or normalised away."}


# ============================================================ #6 screenshots
def capture_screenshots(urls, out_dir, cap=5, playwright_factory=None, timeout_ms=20000):
    """Real browser screenshots via Playwright (Firefox).

    playwright_factory (tests): callable returning a context-manager
    sync_playwright-like object. Without Playwright/a browser the
    function returns proof_type snapshot_card guidance — it never
    fabricates a screenshot."""
    os.makedirs(out_dir, exist_ok=True)
    targets = [u for u in (urls or []) if u][:cap]
    def _record(url, path):
        data = Path(path).read_bytes()
        return {"url": url, "file": os.path.basename(path), "path": str(path),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "captured_at_utc": _now_iso(), "proof_type": "browser_screenshot"}
    rows = []
    pw = None
    try:
        if playwright_factory is not None:
            pw_ctx = playwright_factory()
        else:
            from playwright.sync_api import sync_playwright
            pw_ctx = sync_playwright()
    except Exception as exc:
        return {"status": "not_available", "proof_type": "snapshot_card",
                "screenshots": [],
                "note": f"Playwright is not available in this runtime ({str(exc)[:120]}). "
                        "Use the v8 snapshot proof cards (proof/) instead — they are "
                        "labelled snapshot_card, never browser_screenshot."}
    try:
        with pw_ctx as p:
            browser = p.firefox.launch()
            # ignore_https_errors: some investigator networks route TLS
            # through a local proxy whose cert Firefox rejects
            # (SEC_ERROR_UNKNOWN_ISSUER) — screenshots of public pages
            # must still work there. This affects only the proof
            # browser, never the data routes.
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True)
                page = context.new_page()
            except TypeError:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
            for i, url in enumerate(targets):
                path = os.path.join(out_dir, f"shot_{i + 1}.png")
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(800)
                    page.screenshot(path=path)
                    rows.append(_record(url, path))
                except Exception as exc:
                    rows.append({"url": url, "proof_type": "browser_screenshot",
                                 "status": "degraded", "note": str(exc)[:160]})
            browser.close()
    except Exception as exc:
        return {"status": "degraded", "proof_type": "snapshot_card", "screenshots": rows,
                "note": f"Browser run failed ({str(exc)[:140]}); fall back to snapshot cards."}
    ok = [r for r in rows if r.get("sha256")]
    return {"status": "found" if ok else "not_checked",
            "proof_type": "browser_screenshot", "screenshots": rows,
            "count": len(ok),
            "note": "Real browser screenshots (Playwright/Firefox) of the public "
                    "pages, captured at the recorded UTC times." if ok else
                    "No page could be captured this run — see each row's note. "
                    "The v8 snapshot proof cards remain the fallback proof."}


def write_proof_index(rows, out_dir, index_name="proof_index.json"):
    path = os.path.join(out_dir, index_name)
    existing = []
    if os.path.isfile(path):
        try:
            existing = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing = existing.get("proof", [])
        except Exception:
            existing = []
    merged = existing + [r for r in rows if isinstance(r, dict)]
    Path(path).write_text(json.dumps({"proof": merged}, indent=2, default=str), encoding="utf-8")
    return path


# ============================================================ #7 transcription
def youtube_video_id(value):
    if not value:
        return None
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", str(value))
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", str(value).strip()):
        return str(value).strip()
    return None


def youtube_captions(video, fetcher=None):
    """Public captions for one YouTube video: watch page -> caption
    track list -> timedtext (json3). Real and free when the video
    has public (incl. auto) captions; honest not_checked otherwise."""
    vid = youtube_video_id(video)
    if not vid:
        return {"status": "not_checked", "note": "Not a recognisable YouTube video URL/ID."}
    watch = f"https://www.youtube.com/watch?v={vid}"
    status, text, _f = http_fetch(watch, headers={"User-Agent": _BROWSER_UA}, fetcher=fetcher)
    if status != 200 or not text:
        return {"status": "blocked" if status in (401, 403, 429) else "not_checked",
                "video_id": vid, "note": f"Watch page returned HTTP {status}."}
    urls = re.findall(r'"baseUrl":"(https://www\.youtube\.com/api/timedtext[^"]+)"', text)
    langs = re.findall(r'"languageCode":"([a-zA-Z-]+)"', text)
    if not urls:
        return {"status": "not_checked", "video_id": vid,
                "note": "No caption tracks are listed on the public watch page for this video."}
    track_url = urls[0].replace("\\u0026", "&")
    lang = langs[0] if langs else ""
    kind = "asr" if "kind=asr" in track_url or '"kind":"asr"' in text else "manual"
    sep = "&" if "?" in track_url else "?"
    status, data, _t, _f = http_json(track_url + sep + "fmt=json3", fetcher=fetcher)
    plain = ""
    if status == 200 and isinstance(data, dict):
        parts = []
        for ev in data.get("events", []):
            for seg in ev.get("segs", []) or []:
                parts.append(seg.get("utf8", ""))
            parts.append(" ")
        plain = re.sub(r"\s+", " ", "".join(parts)).strip()
    if not plain:  # fall back to the XML timedtext format
        s2, text2, _f2 = http_fetch(track_url, fetcher=fetcher)
        if s2 == 200 and text2:
            plain = re.sub(r"\s+", " ", _html.unescape(_strip_tags(
                text2.replace("</text>", " </text>")))).strip()
    if not plain:
        # Second route: yt-dlp (when installed) fetches the same public
        # caption track through YouTube's player API — the raw
        # timedtext URLs from the watch page currently return empty
        # bodies from many networks (verified live 2026-10-29).
        alt = _youtube_captions_ytdlp(vid)
        if alt:
            return alt
        return {"status": "not_checked", "video_id": vid,
                "note": "Caption track is listed but its timedtext payload was empty/unreadable "
                        "and the yt-dlp route is unavailable or also returned nothing. "
                        "Optional setup: pip install yt-dlp."}
    return {"status": "found", "video_id": vid, "source": "youtube_captions",
            "language": lang, "track_kind": kind, "chars": len(plain),
            "transcript": plain[:20000],
            "note": "Plain text of the video's public caption track "
                    "(auto captions are machine-generated by YouTube)."}


def _youtube_captions_ytdlp(vid):
    """Optional yt-dlp route to the same public captions. Returns a
    found dict or None. yt-dlp is an optional dependency — absent is
    a normal, honestly reported outcome, never an error."""
    try:
        import yt_dlp  # type: ignore
    except Exception:
        return None
    import glob
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            opts = {"skip_download": True, "writeautomaticsub": True,
                    "writesubtitles": True, "subtitleslangs": ["en"],
                    "subtitlesformat": "json3", "quiet": True,
                    "no_warnings": True, "ignoreerrors": True,
                    "outtmpl": os.path.join(td, "%(id)s.%(ext)s")}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            files = glob.glob(os.path.join(td, "*.json3"))
            if not files:
                return None
            data = json.loads(Path(files[0]).read_text(encoding="utf-8", errors="replace"))
            parts = []
            for ev in data.get("events", []):
                for seg in ev.get("segs", []) or []:
                    parts.append(seg.get("utf8", ""))
                parts.append(" ")
            plain = re.sub(r"\s+", " ", "".join(parts)).strip()
            if not plain:
                return None
            return {"status": "found", "video_id": vid,
                    "source": "youtube_captions_yt_dlp", "language": "en",
                    "track_kind": "captions", "chars": len(plain),
                    "transcript": plain[:20000],
                    "note": "Plain text of the video's public caption track, fetched "
                            "with yt-dlp (the raw timedtext route returned an empty "
                            "body from this network). Auto captions are "
                            "machine-generated by YouTube."}
    except Exception:
        return None


def whisper_status():
    import importlib.util
    for mod, label in (("faster_whisper", "faster-whisper"), ("whisper", "openai-whisper")):
        if importlib.util.find_spec(mod) is not None:
            return {"status": "available", "engine": label,
                    "note": f"{label} is installed; local audio transcription can run offline."}
    return {"status": "not_installed", "engine": None,
            "note": "No local Whisper engine installed. One-command setup: "
                    "scripts/setup_whisper.sh (installs faster-whisper + the tiny model; "
                    "the model download is a one-time ~75 MB fetch)."}


def video_transcripts_v9(items, fetcher=None):
    """Captions first for YouTube items; Whisper detection reported
    for everything else. Never invents a transcript."""
    rows, found = [], 0
    for item in (items or [])[:10]:
        url = item.get("url") or item.get("video_url") or ""
        vid = youtube_video_id(url) or (youtube_video_id(item.get("id")) if item.get("platform") == "youtube" else None)
        if vid:
            cap = youtube_captions(vid, fetcher=fetcher)
            cap["url"] = url
            rows.append(cap)
            found += cap.get("status") == "found"
        else:
            rows.append({"status": "not_checked", "url": url,
                         "note": "Not a YouTube item; audio transcription needs a local Whisper engine (see whisper_status)."})
    return {"status": "found" if found else "not_checked", "items": rows,
            "whisper": whisper_status(),
            "note": "Transcripts come only from public YouTube caption tracks or a "
                    "locally installed Whisper engine. Absence is not_checked, never faked."}


# ============================================================ #8 local NLP
_COUNTRIES = set("pakistan india qatar kuwait oman bahrain bangladesh nepal "
                 "afghanistan iran iraq turkey egypt nigeria kenya germany "
                 "france spain italy netherlands canada australia japan china "
                 "singapore malaysia indonesia brazil mexico argentina russia "
                 "ukraine poland sweden norway".split())
_CITIES = set("karachi lahore islamabad rawalpindi faisalabad multan peshawar "
              "quetta hyderabad sukkur london chicago houston toronto dubai "
              "sharjah doha riyadh jeddah delhi mumbai bangalore chennai "
              "kolkata pune paris berlin madrid rome amsterdam sydney "
              "melbourne tokyo jakarta cairo lagos nairobi istanbul tehran "
              "baghdad kabul dhaka colombo kathmandu".split())
_PLACES = _COUNTRIES | _CITIES | {
    "united states", "united kingdom", "united arab emirates", "saudi arabia",
    "south africa", "new zealand", "sri lanka", "new york", "los angeles",
    "abu dhabi", "kuala lumpur", "san francisco", "new delhi"}
_ORG_SUFFIXES = ("inc", "llc", "ltd", "limited", "corp", "corporation", "gmbh",
                 "labs", "lab", "systems", "technologies", "technology", "tech",
                 "software", "security", "digital", "media", "group", "holdings",
                 "university", "institute", "college", "school", "foundation",
                 "network", "studio", "agency", "ventures", "capital")
_COMMON_WORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
                 "with", "by", "at", "from", "is", "are", "was", "were", "i",
                 "my", "we", "our", "you", "your", "it", "its", "this", "that",
                 "how", "what", "why", "when", "who", "january", "february",
                 "march", "april", "may", "june", "july", "august", "september",
                 "october", "november", "december", "monday", "tuesday",
                 "wednesday", "thursday", "friday", "saturday", "sunday"}
_STOPWORDS = {
    "en": set("the of and to in is you that it he was for on are as with his they i at be this have from or one had by word but not what all were we when your can said there use an each which she do how their if will up other about out many then them these so some her would make like him into time has look two more write go see number no way could people my than first water been call who oil its now find long down day did get come made may part".split()),
    "es": set("el la de que y en los del se las por un para con no una su al es lo como más pero sus ya o este sí porque esta cuando muy sin sobre también me hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante ellos esto mí antes algunos qué unos yo otro otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas mis algunas algo nosotros".split()),
    "fr": set("le la de des et les à un une du en dans qui que au pour pas plus par sur ce cette sont avec aux il ils elle nous vous être ont été comme tout tous aussi ou où si son sa ses leur leurs même après cet ces est ceci auxquel".split()),
    "de": set("der die und in den von zu mit sich des auf für ist im dem nicht ein eine als auch es an werden aus er hat dass sie nach wird bei einer um am sind noch wie einem über einen so zum haben nur oder aber vor seiner bis mehr durch man sein war sei ich mich dir uns".split()),
    "ur": set("کا کی کے ہے ہیں تھا تھی اور میں نے کو سے پر یہ وہ جو بھی نہیں ایک اس ان ہم تم آپ کیا ہو کر اسے اس کا کی کے تو بھی ہی ميرے".split()),
}


def detect_language(text):
    """Deterministic language ID: script first, then stopword vote."""
    t = text or ""
    if re.search(r"[\u0600-\u06FF]", t):
        # Arabic script: Urdu vs Arabic by characteristic letters/words
        if re.search(r"[\u0679\u067E\u0688\u0691\u06BE\u06CC\u06D2]", t) or \
                any(w in t.split() for w in ("کا", "کی", "کے", "ہے", "ہیں", "نہیں")):
            return "ur"
        return "ar"
    if re.search(r"[\u0400-\u04FF]", t):
        return "ru-or-cyrillic"
    if re.search(r"[\u4E00-\u9FFF]", t):
        return "zh"
    if re.search(r"[\u3040-\u30FF]", t):
        return "ja"
    if re.search(r"[\u0900-\u097F]", t):
        return "hi"
    words = re.findall(r"[a-zà-ÿ']+", t.lower())
    if not words:
        return "unknown"
    scores = {}
    for lang in ("en", "es", "fr", "de"):
        scores[lang] = sum(1 for w in words if w in _STOPWORDS[lang])
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "en"


_TOPIC_KEYWORDS = {
    "security": ("security", "pentest", "penetration", "vulnerability", "exploit", "hacking", "hacker", "osint", "malware", "phishing", "soc", "threat", "infosec", "cyber"),
    "ai_ml": ("ai", "ml", "machine learning", "llm", "gpt", "neural", "model", "dataset", "prompt"),
    "web_dev": ("javascript", "typescript", "react", "python", "api", "frontend", "backend", "developer", "coding", "software", "opensource", "open source", "github"),
    "finance": ("crypto", "bitcoin", "trading", "stocks", "invest", "finance", "money", "bank"),
    "gaming": ("gaming", "game", "esports", "twitch", "steam", "xbox", "playstation"),
    "music": ("music", "song", "album", "spotify", "concert", "band"),
    "sports": ("football", "cricket", "soccer", "nba", "tennis", "sport", "match"),
    "politics": ("election", "government", "policy", "president", "parliament", "politics"),
    "science": ("research", "science", "study", "paper", "physics", "biology", "space", "nasa"),
}


def _cap_sequences(text):
    seqs = []
    for segment in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        for m in re.finditer(r"\b([A-Z][a-zA-Z'’-]+(?:\s+(?:[A-Z][a-zA-Z'’-]+|of|the|de|&)){0,3})", segment):
            seq = m.group(1).strip()
            if len(seq.split()) >= 2:
                seqs.append(seq)
    return seqs


def local_nlp(texts, use_spacy=True):
    """Built-in local NLP (deterministic, offline). When spaCy +
    en_core_web_sm are installed they are used for NER and labelled;
    otherwise the gazetteer/rule pack runs. Never a cloud model."""
    texts = [t for t in (texts or []) if t and str(t).strip()]
    joined = "\n".join(str(t) for t in texts)
    langs = Counter(detect_language(t) for t in texts)
    topics = Counter()
    low = joined.lower()
    for topic, kws in _TOPIC_KEYWORDS.items():
        topics[topic] = sum(low.count(k) for k in kws)
    topics = {k: v for k, v in topics.most_common() if v > 0}
    spacy_info = {"used": False, "model": None}
    persons, orgs, places = Counter(), Counter(), Counter()
    if use_spacy:
        try:
            import importlib.util
            if importlib.util.find_spec("spacy") is not None:
                import spacy
                try:
                    nlp = spacy.load("en_core_web_sm")
                    spacy_info = {"used": True, "model": "en_core_web_sm"}
                    for t in texts:
                        doc = nlp(str(t)[:10000])
                        for ent in doc.ents:
                            if ent.label_ == "PERSON":
                                persons[ent.text] += 1
                            elif ent.label_ == "ORG":
                                orgs[ent.text] += 1
                            elif ent.label_ in ("GPE", "LOC"):
                                places[ent.text] += 1
                except OSError:
                    spacy_info = {"used": False, "model": None,
                                  "note": "spaCy installed but en_core_web_sm is not — run scripts/setup_local_nlp.sh"}
        except Exception:
            spacy_info = {"used": False, "model": None}
    if not spacy_info["used"]:
        for seq in _cap_sequences(joined):
            low_seq = seq.lower()
            words = seq.split()
            if low_seq in _PLACES:
                places[seq] += 1
            elif words[-1].lower().strip(".,") in _ORG_SUFFIXES or \
                    any(w.lower() in _ORG_SUFFIXES for w in words):
                orgs[seq] += 1
            elif all(w.lower().strip(".,'") not in _COMMON_WORDS for w in words):
                persons[seq] += 1
        for place in _PLACES:
            for m in re.finditer(r"\b" + re.escape(place) + r"\b", low):
                places[place.title()] += 1
    return {"status": "found", "engine": "spacy" if spacy_info["used"] else "built-in local NLP (deterministic, no cloud model)",
            "spacy": spacy_info, "sample_texts_n": len(texts),
            "languages": dict(langs),
            "persons": [p for p, _ in persons.most_common(20)],
            "organisations": [o for o, _ in orgs.most_common(20)],
            "places": [p for p, _ in places.most_common(20)],
            "topics": topics,
            "note": "Entities are extracted from the collected public texts only "
                    "(sample size stated). Deterministic rules / a local model — "
                    "never a cloud AI, never an identity claim."}


# ============================================================ #9 speed/cache
def run_parallel_timed(seed, keys=None, parallel=6, seed_type="username",
                       time_budget=30, progress=True, adapters=None, analyse=True):
    """Parallel adapter run with per-adapter soft timeouts: adapters
    not finished when the global budget expires are reported
    degraded_timeout and do not block the case."""
    from ..core.engine import run_investigation
    from ..adapters.base import AdapterResult
    from .v8 import _CachedAdapter
    keys = dict(keys or {})
    if adapters is None:
        from ..adapters.registry import ADAPTERS
        adapter_list = list(ADAPTERS.values())
    else:
        adapter_list = list(adapters.values()) if isinstance(adapters, dict) else list(adapters)
    started = time.time()
    results = {}

    def _one(ad):
        try:
            return ad.search(seed, keys)
        except Exception as exc:
            return AdapterResult(profiles=[], status="degraded", message=str(exc)[:160])

    timed_out = []
    ex = ThreadPoolExecutor(max_workers=int(parallel))
    futs = {ex.submit(_one, ad): ad for ad in adapter_list}
    try:
        for fut in as_completed(futs, timeout=max(1, int(time_budget))):
            ad = futs[fut]
            results[id(ad)] = fut.result()
            if progress:
                r = results[id(ad)]
                print(f"  [v9] {getattr(ad, 'platform', '?')}: "
                      f"{getattr(r, 'status', '?')} — {len(getattr(r, 'profiles', []) or [])} profile(s)")
    except TimeoutError:
        pass
    # Do not wait for timed-out adapter threads: their results are
    # discarded and the adapters are reported degraded_timeout.
    ex.shutdown(wait=False, cancel_futures=True)
    for ad in adapter_list:
        if id(ad) not in results:
            timed_out.append(getattr(ad, "platform", getattr(ad, "name", "?")))
            results[id(ad)] = AdapterResult(
                profiles=[], status="degraded_timeout",
                message=f"Adapter did not finish inside the {time_budget}s time budget; marked degraded_timeout instead of blocking the case.")
    wrapped = [_CachedAdapter(ad, results[id(ad)]) for ad in adapter_list]
    adapter_phase = round(time.time() - started, 2)
    inv = run_investigation(seed, adapters=wrapped, keys=keys, seed_type=seed_type,
                            analyse=analyse)
    wall = round(time.time() - started, 2)
    return inv, {"wall_seconds": wall, "time_budget_seconds": time_budget,
                 "adapter_phase_seconds": adapter_phase,
                 "engine_and_analysis_seconds": round(wall - adapter_phase, 2),
                 "timed_out_adapters": timed_out, "parallel": int(parallel),
                 "over_budget": wall > time_budget,
                 "note": "The soft budget bounds adapter collection. The engine's "
                         "live analysis phase (activity/snapshot/infrastructure "
                         "lookups with per-source pacing) runs after collection "
                         "and is reported separately above — it is the usual "
                         "reason a full case exceeds the budget."}


def _result_cache_key(seed, seed_type):
    return f"result:{seed_type}:{(seed or '').strip().lower()}"


def _inv_from_payload(payload):
    from ..core.models import Investigation, Edge
    from ..core.engine import _coerce_profile
    inv = Investigation(case_id=payload.get("case_id", "case_cached"),
                        seed=payload.get("seed", ""), seed_type=payload.get("seed_type", "username"))
    inv.profiles = [p for p in (_coerce_profile(x) for x in payload.get("profiles", [])) if p]
    edges = []
    for e in payload.get("edges", []):
        if isinstance(e, dict):
            try:
                edges.append(Edge(from_id=e["from_id"], to_id=e["to_id"], kind=e["kind"],
                                  confidence=e.get("confidence", 0), band=e.get("band", "Low"),
                                  evidence=e.get("evidence", [])))
            except Exception:
                pass
    inv.edges = edges
    for attr in ("notes", "checklist", "possible_matches", "alerts", "audit", "timeline", "purpose"):
        setattr(inv, attr, payload.get(attr, [] if attr != "purpose" else ""))
    if payload.get("analysis") is not None:
        inv.analysis = payload["analysis"]
    return inv


# ============================================================ #10 graph real
def graph_levels_real(anchor_username, keys=None, fetcher=None, cap=30, profile_cap=8):
    """Real GitHub contact graph: anchor (1) -> anchor's platform
    profile (2) -> real followers/following (3, capped) -> bio-link
    domains shared across level-3 accounts (4)."""
    from .v8 import github_id_sets, github_profile_fetch
    a = github_id_sets(anchor_username, keys=keys, fetcher=fetcher)
    followers = (a.get("followers") or [])[:cap]
    following = (a.get("following") or [])[:cap]
    if a.get("followers") is None and a.get("following") is None:
        return {"status": "not_checked", "anchor": anchor_username,
                "note": "GitHub did not return follower/following sets for this anchor (rate limit or missing user); levels 3-4 stay empty rather than being invented."}
    level3 = sorted(set(followers) | set(following))
    nodes = [{"id": f"github:{anchor_username}", "level": 1, "kind": "anchor",
              "source": "investigator-supplied seed"},
             {"id": f"github:{anchor_username}", "level": 2, "kind": "profile",
              "source": "github public API"}]
    edges = []
    for login in level3:
        nodes.append({"id": f"github:{login}", "level": 3, "kind": "contact",
                      "relation": "follower" if login in followers else "following",
                      "source": "github public API followers/following list"})
        edges.append({"from": f"github:{anchor_username}", "to": f"github:{login}",
                      "kind": "follower" if login in followers else "following"})
    domains = Counter()
    for login in level3[:profile_cap]:
        prof = github_profile_fetch(login, keys=keys, fetcher=fetcher, sleeper=lambda s: None)
        for link in (prof.get("bio_links") or []):
            d = urllib.parse.urlparse(link if "://" in link else "https://" + link).netloc.lower().removeprefix("www.")
            if d:
                domains[d] += 1
    shared = [d for d, n in domains.items() if n >= 2]
    for d in shared:
        nodes.append({"id": f"domain:{d}", "level": 4, "kind": "shared_website",
                      "shared_by_count": domains[d], "source": "github public API bio links of level-3 accounts"})
    return {"status": "found", "anchor": anchor_username, "source": "github public API",
            "caps": {"contacts_cap": cap, "level3_profiles_fetched": min(len(level3), profile_cap)},
            "level_counts": {"1": 1, "2": 1, "3": len(level3), "4": len(shared)},
            "followers_sample": followers, "following_sample": following,
            "shared_domains": shared, "nodes": nodes, "edges": edges,
            "note": "Levels are built from real collected GitHub contact lists only. "
                    "Level-3 is a capped sample (counts stated); level-4 lists only "
                    "domains shared by >=2 sampled level-3 accounts."}


# ============================================================ dispatch/dossier
def investigate_v9(seed, seed_type="username", keys=None, context="", parallel=6,
                   direct=False, fetcher=None, sleeper=None, progress=True,
                   variation_city="", variation_years=None, time_budget=30,
                   use_cache=True, live_extras=True):
    """Single v9 entry point for CLI + GUI. Returns
    (Investigation, v7_section, v8_section, v9_section).

    Username runs use the timed parallel path (#9) and the 1-hour
    result cache; name runs use name_search_v9 (#1); everything else
    delegates to the v8 dispatch. v9 extras (real graph levels, site
    adapter classification, NLP over collected texts) are computed
    here and carried in the v9 section."""
    from dataclasses import asdict
    keys = dict(keys or {})
    st = (seed_type or "username").lower()
    section = {"seed_type_resolved": st, "version": VERSION}
    # 1-hour result cache (#9) — labelled when it serves a run.
    if use_cache and fetcher is None and st in ("username", "domain"):
        cached, age = disk_cache_get(_result_cache_key(seed, st), ttl_seconds=3600)
        if cached and isinstance(cached, dict) and cached.get("payload"):
            inv = _inv_from_payload(cached["payload"])
            section["result_cache"] = {"status": "hit", "age_seconds": int(age),
                                        "note": "Served from the 1-hour result cache; no network calls were made for the base investigation."}
            section["timing"] = {"wall_seconds": 0.0, "served_from_cache": True}
            return inv, None, cached.get("v8_section"), section
    started = time.time()
    v7_section = v8_section = None
    inv = None
    if st == "name":
        from .v7 import _blank_investigation
        inv = _blank_investigation(seed, "name", keys)
        sec_name = name_search_v9(seed, context=context, keys=keys, fetcher=fetcher)
        section["name"] = sec_name
        inv.audit.append({"ts_utc": _now_iso(), "actor": "features.v9", "action": "name_seed_v9",
                          "detail": {"candidates": len(sec_name.get("candidates", [])),
                                     "status": sec_name.get("status"),
                                     "engines_used": sec_name.get("engines_used")}})
    elif st == "username" and fetcher is None:
        inv, timing = run_parallel_timed(seed, keys=keys, parallel=int(parallel),
                                         seed_type="username", time_budget=int(time_budget),
                                         progress=progress)
        section["timing"] = timing
        from .v8 import variations_v8
        var = variations_v8(seed, city=variation_city, years=variation_years)
        v8_section = {"seed_type_resolved": "username", "username_variations": var}
        inv.audit.append({"ts_utc": _now_iso(), "actor": "features.v9",
                          "action": "timed_parallel_run", "detail": timing})
    else:
        from .v8 import investigate_v8
        inv, v7_section, v8_section = investigate_v8(
            seed, seed_type, keys=keys, context=context, parallel=int(parallel),
            direct=direct, fetcher=fetcher, sleeper=sleeper, progress=progress,
            variation_city=variation_city, variation_years=variation_years)
        if st == "name" and v8_section and v8_section.get("name"):
            section["name"] = v8_section["name"]
        if st in ("phrase", "email"):
            # #2: dorking for these seeds runs on the shared v9 chain.
            section["dork_v9"] = dork_v9([f'"{seed}"'], keys=keys, fetcher=fetcher)
    if section.get("timing") is None:
        section["timing"] = {"wall_seconds": round(time.time() - started, 2),
                             "time_budget_seconds": int(time_budget)}
    # v9 extras from collected data (no extra network unless live_extras
    # and a GitHub anchor exists).
    try:
        payload_profiles = []
        for p in inv.profiles:
            d = asdict(p) if not isinstance(p, dict) else p
            payload_profiles.append(d)
        section["run_fingerprint"] = run_fingerprint(payload_profiles)
        texts = []
        for d in payload_profiles:
            for val in (d.get("display_name"), d.get("bio")):
                if val:
                    texts.append(str(val))
        if texts:
            section["local_nlp"] = local_nlp(texts)
        section["site_adapters"] = {
            "classifications": {e["service"]: e["classification"] for e in SITE_ADAPTERS_V9},
            "note": "Classification of the 24 sites (#3). Live rows are produced by "
                    "site_adapters_v9() / the CLI --site-adapters flag."}
        if live_extras and fetcher is None and st == "username":
            if any((d.get("platform") == "github") for d in payload_profiles):
                section["graph_levels_real"] = graph_levels_real(seed, keys=keys)
    except Exception as exc:
        section["extras_error"] = str(exc)[:160]
    if use_cache and fetcher is None and st in ("username", "domain"):
        try:
            payload = asdict(inv)
            if getattr(inv, "analysis", None) is not None:
                payload["analysis"] = inv.analysis
            disk_cache_put(_result_cache_key(seed, st),
                           {"payload": payload, "v8_section": v8_section})
            section.setdefault("result_cache", {"status": "stored",
                                                "note": "Result stored in the 1-hour cache for repeat seeds."})
        except Exception:
            pass
    return inv, v7_section, v8_section, section


def consistency_check(seed, seed_type="username", keys=None, fetcher=None, progress=False):
    """Run a seed twice (cache off) and diff the run fingerprints."""
    inv_a, _7a, _8a, sec_a = investigate_v9(seed, seed_type, keys=keys, fetcher=fetcher,
                                            use_cache=False, live_extras=False, progress=progress)
    inv_b, _7b, _8b, sec_b = investigate_v9(seed, seed_type, keys=keys, fetcher=fetcher,
                                            use_cache=False, live_extras=False, progress=progress)
    from dataclasses import asdict
    fp_a = run_fingerprint([asdict(p) if not isinstance(p, dict) else p for p in inv_a.profiles])
    fp_b = run_fingerprint([asdict(p) if not isinstance(p, dict) else p for p in inv_b.profiles])
    diff = diff_fingerprints(fp_a, fp_b, audit_a=inv_a.audit, audit_b=inv_b.audit)
    return {"status": "found", "seed": seed, "seed_type": seed_type,
            "run_a": fp_a, "run_b": fp_b, **diff}


def build_v9_sections(dossier, payload=None, v9_section=None):
    """Attach the v9 section + run_fingerprint to a v8 dossier."""
    dossier = dict(dossier or {})
    v9 = dict(v9_section or {})
    profiles = dossier.get("profile_summary") or []
    fp = v9.get("run_fingerprint") or run_fingerprint(profiles)
    dossier["run_fingerprint"] = fp
    if payload and payload.get("analysis"):
        texts = []
        a = payload["analysis"]
        for key in ("bio_domains",):
            pass
        for p in profiles:
            for val in (p.get("display_name"), p.get("bio")):
                if val:
                    texts.append(str(val))
        if texts and "local_nlp" not in v9:
            v9["local_nlp"] = local_nlp(texts)
    dossier["v9"] = v9
    return dossier


def build_v9_dossier(payload, seed, seed_type="username", keys=None, v7_section=None,
                     v8_section=None, v9_section=None, include_dorks=True):
    from .v8 import build_v8_dossier
    from .v6 import strip_keys
    dossier = build_v8_dossier(payload, seed, seed_type=seed_type, keys=keys,
                               v7_section=v7_section, v8_section=v8_section,
                               include_dorks=include_dorks)
    dossier["version"] = VERSION
    dossier = build_v9_sections(dossier, payload, v9_section=v9_section)
    return strip_keys(dossier)


def export_v9(dossier, out_dir):
    """v8 exports; dossier.json already carries version 9.0.0 +
    the v9 section + run_fingerprint."""
    from .v8 import export_v8
    return export_v8(dossier, out_dir)
