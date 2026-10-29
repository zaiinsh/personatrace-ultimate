"""PersonaTrace v3.0 features — finishing the v2 gaps, one by one.

Honest limits are kept in each docstring and return value:
- X / Instagram / TikTok without a paid key have no legitimate public
  API and their profile pages are JS/login-walled, so they stay
  not_checked without an aggregator key, never scraped.
- Reddit without a key: the public JSON/RSS endpoints returned 403 in
  live checks, so v3 tries the Arctic Shift public archive (historical,
  ~36h lag, not live current) and reports degraded if it is unreachable.
- Google Lens / Yandex have no direct public API, so v3 adds automated
  search only via a third-party search API key the investigator supplies
  (SerpApi, google_lens engine), plus the manual links from v2.
- True object recognition needs a vision model: v3 uses the
  investigator's own cloud AI key or local vision model, with a prompt
  that forbids identifying people. Without a model, it is not_checked.
- No face identification, no private data, no live person location,
  no login-wall or CAPTCHA bypass anywhere here.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

_UA = {"User-Agent": "PersonaTrace/3.0 (+public-osint)"}
_TIMEOUT = 10


def _get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or _UA)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read(), resp.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() if hasattr(exc, "read") else b"", url
    except Exception as exc:
        return None, str(exc).encode(), url


# ---------------------------------------------------------------- Reddit archive
def reddit_archive(seed: str, limit: int = 5) -> dict:
    """Public Reddit posts/comments by author via Arctic Shift.

    Arctic Shift is a public historical archive (2005–present, reported
    ~36h lag, no uptime guarantee). It is NOT live current Reddit, and
    it is NOT a substitute for the official Reddit API. If the archive
    is unreachable, the result is degraded, never empty.
    """
    posts = []
    for kind in ("posts", "comments"):
        url = (f"https://search.arctic-shift.com/search/reddit/{kind}?"
               f"author={urllib.parse.quote(seed)}&limit={limit}")
        code, body, _ = _get(url)
        if code != 200:
            continue
        try:
            data = json.loads(body.decode())
        except Exception:
            continue
        items = data.get("data") or data.get("results") or []
        if isinstance(items, dict):
            items = items.get("data") or []
        for item in items[:limit]:
            if isinstance(item, dict):
                posts.append({"kind": kind, "title": item.get("title") or item.get("body", "")[:200],
                              "subreddit": item.get("subreddit"), "created_utc": item.get("created_utc"),
                              "permalink": item.get("permalink") or ""})
    if posts:
        return {"status": "ok", "source": "arctic_shift_archive",
                "note": "Historical archive only, ~36h lag, not live current Reddit.",
                "posts": posts[:limit]}
    return {"status": "degraded", "source": "arctic_shift_archive",
            "reason": "Arctic Shift archive unreachable or no posts found for this author in the archive. This is not 'no Reddit account'.",
            "posts": []}


# ---------------------------------------------------------------- Archive.today
def archive_today(profile_url: str) -> dict:
    """Newest archive.today snapshot for a public profile URL.

    archive.today rate-limits aggressively (429 is common); a 429 is
    reported as degraded, never retried in a loop. A returned snapshot
    URL is a preserved copy, never presented as current.
    """
    if not profile_url:
        return {"status": "not_checked"}
    code, body, final_url = _get("https://archive.today/newest/" + urllib.parse.quote(profile_url, safe=""))
    if "archive.ph/" in final_url and "/http" in final_url:
        return {"status": "ok", "snapshot_url": final_url,
                "note": "archive.today snapshot — a preserved copy, not current data."}
    return {"status": "degraded", "code": code,
            "reason": "archive.today returned no snapshot URL (often rate-limited). Wayback is the primary archive; this is secondary."}


# ---------------------------------------------------------------- Censys (real API, key-gated)
def censys_search(domain: str, keys: dict | None = None) -> dict:
    """Real Censys host search, only with the investigator's own keys.

    Uses HTTP Basic auth (api_id:secret) against search.censys.io.
    No key = not_checked. Host data describes infrastructure, never a
    person's live location.
    """
    keys = keys or {}
    api_id = keys.get("censys_api_id") or ""
    secret = keys.get("censys_api_secret") or ""
    if not api_id or not secret:
        return {"status": "not_checked", "reason": "No Censys key supplied"}
    import base64
    token = base64.b64encode(f"{api_id}:{secret}".encode()).decode()
    payload = json.dumps({"q": f"dns.names: {domain}", "per_page": 5}).encode()
    req = urllib.request.Request(
        "https://search.censys.io/api/v2/hosts/search",
        data=payload, headers={"Authorization": f"Basic {token}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        hosts = data.get("result", {}).get("hosts", [])
        return {"status": "ok", "hosts": [{"ip": h.get("ip"), "services": [s.get("port") for s in h.get("services", [])]} for h in hosts],
                "note": "Censys host data describes infrastructure, never a person's location."}
    except urllib.error.HTTPError as exc:
        return {"status": "degraded", "code": exc.code, "reason": f"Censys HTTP {exc.code} — check your key and plan."}
    except Exception as exc:
        return {"status": "degraded", "reason": str(exc)}


# ---------------------------------------------------------------- SerpApi Lens / Yandex
def serpapi_reverse(image_url: str, keys: dict | None = None) -> dict:
    """Automated Lens/Yandex-style search via SerpApi, key-gated.

    Google Lens and Yandex Images offer no direct public API, so the
    only legitimate automated route is a third-party search API the
    investigator pays for with their own key. No key = not_checked,
    plus the manual links from v2.
    """
    keys = keys or {}
    api_key = keys.get("serpapi_api_key") or ""
    if not api_key or not image_url:
        return {"status": "not_checked", "reason": "No SerpApi key supplied for automated Lens/Yandex search. Manual links are in manual_reverse_links."}
    out = {}
    for engine in ("google_lens", "yandex_images"):
        url = ("https://serpapi.com/search.json?engine=" + engine
               + "&url=" + urllib.parse.quote(image_url)
               + "&api_key=" + urllib.parse.quote(api_key))
        code, body, _ = _get(url)
        if code == 200:
            try:
                data = json.loads(body.decode())
                matches = data.get("visual_matches") or data.get("image_results") or []
                out[engine] = {"status": "ok", "matches": [{"title": m.get("title"), "link": m.get("link"), "source": m.get("source")} for m in matches[:10]]}
            except Exception:
                out[engine] = {"status": "degraded"}
        else:
            out[engine] = {"status": "degraded", "code": code}
    return {"status": "ok", "engines": out}


# ---------------------------------------------------------------- Vision (AI, user-supplied)
def vision_description(image_url: str, image_bytes: bytes | None = None, keys: dict | None = None) -> dict:
    """Describe what is shown in a public image, using the investigator's
    own AI key or local vision model. The prompt forbids identifying
    people and forbids face identification: it asks for objects, scene,
    text and setting only. No model = not_checked."""
    keys = keys or {}
    prompt = ("Describe only what is shown in this image: objects, scene, "
              "setting and any visible text. Do NOT identify any person, "
              "do NOT guess who anyone is, do NOT use face recognition.")
    # Cloud vision (OpenAI-compatible, image_url).
    api_key = keys.get("llm_api_key") or keys.get("openai_api_key") or ""
    base_url = (keys.get("llm_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = keys.get("llm_model") or "gpt-4o-mini"
    if api_key and image_url:
        payload = json.dumps({"model": model, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}}]}]}).encode()
        req = urllib.request.Request(base_url + "/chat/completions", data=payload,
                                     headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                text = data["choices"][0]["message"]["content"]
                return {"status": "ok", "model": model, "description": text,
                        "note": "AI vision description — objects/scene only, never person identification."}
        except Exception as exc:
            return {"status": "degraded", "reason": str(exc)}
    # Local vision model (Ollama, e.g. llava, with base64 image).
    local_url = keys.get("local_model_url") or ""
    if local_url and image_bytes:
        import base64
        payload = json.dumps({"model": keys.get("local_model_name") or "llava",
                              "prompt": prompt, "stream": False,
                              "images": [base64.b64encode(image_bytes).decode()]}).encode()
        req = urllib.request.Request(local_url.rstrip("/") + "/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return {"status": "ok", "model": keys.get("local_model_name") or "llava",
                        "description": data.get("response"),
                        "note": "Local vision model — case data stayed on this machine when the endpoint is localhost."}
        except Exception as exc:
            return {"status": "degraded", "reason": str(exc)}
    return {"status": "not_checked",
            "reason": "No AI key or local vision model supplied for object description. Machine picture description (size, colours, brightness) is in photo_descriptions."}


# ---------------------------------------------------------------- Native NER (heuristic + optional AI)
_ORG_SUFFIXES = ("Inc", "Ltd", "LLC", "GmbH", "Corp", "Corporation", "Company", "Labs", "Security", "Technologies")
_COUNTRIES = {"Pakistan", "United States", "USA", "United Kingdom", "UK", "Germany", "France", "India", "China", "Canada", "Australia", "UAE", "Saudi Arabia", "Turkey", "Netherlands", "Spain", "Italy", "Brazil", "Russia", "Ukraine", "Poland", "Sweden", "Norway", "Denmark", "Finland", "Ireland", "Portugal", "Greece", "Egypt", "Nigeria", "Kenya", "Bangladesh", "Sri Lanka", "Nepal", "Afghanistan", "Iran", "Iraq", "Israel", "Japan", "Korea", "Thailand", "Vietnam", "Indonesia", "Malaysia", "Singapore", "Philippines", "Mexico", "Argentina", "Chile", "Colombia", "Peru"}
_CITIES = {"Islamabad", "Karachi", "Lahore", "London", "New York", "San Francisco", "Berlin", "Paris", "Toronto", "Sydney", "Dubai", "Mumbai", "Delhi", "Dhaka", "Kabul", "Tehran", "Baghdad", "Tokyo", "Seoul", "Bangkok", "Singapore", "Amsterdam", "Madrid", "Rome", "Moscow", "Kyiv", "Warsaw", "Stockholm", "Oslo", "Copenhagen", "Helsinki", "Dublin", "Lisbon", "Athens", "Cairo", "Lagos", "Nairobi", "Colombo", "Kathmandu"}


def native_ner(text: str) -> dict:
    """Heuristic native-language entity extraction from the original text.

    No translation first: capitalised phrases, organisation suffixes,
    and a small country/city list are extracted from the original
    wording, which is always preserved beside the result. This is a
    heuristic, not a trained NER model — a trained model is available
    only via the investigator's own AI key/local model (see
    vision_description for the AI route; NER via LLM is in analysis
    when a key is present).
    """
    text = text or ""
    capitalised = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+){1,3}\b", text)
    orgs = [p for p in capitalised if any(p.endswith(" " + s) or p.endswith(s) for s in _ORG_SUFFIXES)]
    places = [w for w in re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\b", text) if w in _COUNTRIES or w in _CITIES]
    # Non-Latin runs are entities in their own script, kept verbatim.
    non_latin = re.findall(r"[\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF\u0900-\u097F\u0E00-\u0E7F]+", text)
    persons = []
    for phrase in capitalised:
        if phrase not in orgs and phrase not in places and len(phrase.split()) == 2:
            persons.append(phrase)
    return {"organisations": sorted(set(orgs)), "places": sorted(set(places)),
            "person_like_phrases": sorted(set(persons))[:20],
            "non_latin_runs": non_latin, "original": text,
            "note": "Heuristic entities from the original text, not a trained NER model and not a confirmed identity."}


# ---------------------------------------------------------------- Coordinated v3
def coordinated_v3(accounts: list) -> dict:
    """Extra coordinated signals: star graphs, a link pushed within an
    hour, and identical bio templates. Each signal carries an innocent
    explanation that must be ruled out first. Pattern, not proof."""
    signals = []
    # Star graph: many accounts all linking to / following one centre.
    centres = {}
    for acc in accounts or []:
        for link in (acc.get("links") or []):
            centres[link] = centres.get(link, 0) + 1
    for link, count in centres.items():
        if count >= 3:
            signals.append({"signal": f"Star graph: {count} accounts all link to {link}",
                            "innocent": "A popular tool, news story or shared resource can produce the same star."})
    # One link pushed within an hour: posts with the same link and
    # timestamps within 60 minutes of each other.
    link_times = {}
    for acc in accounts or []:
        for post in (acc.get("posts") or []):
            if not isinstance(post, dict):
                continue
            for url in re.findall(r"https?://[^\s]+", post.get("text") or ""):
                link_times.setdefault(url, []).append(post.get("created_at") or "")
    for url, times in link_times.items():
        times = sorted(t for t in times if t)
        if len(times) >= 2:
            from datetime import datetime
            try:
                parsed = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times]
                if (max(parsed) - min(parsed)).total_seconds() <= 3600:
                    signals.append({"signal": f"Link pushed within an hour by multiple accounts: {url}",
                                    "innocent": "Breaking news or a viral post can be shared within an hour by unrelated accounts."})
            except Exception:
                pass
    # Identical bio templates: bios that are identical after removing names.
    bios = {}
    for acc in accounts or []:
        bio = (acc.get("bio") or "").strip()
        if bio:
            template = re.sub(r"@[A-Za-z0-9_]+", "@user", bio)
            bios.setdefault(template, []).append(acc.get("username") or "?")
    for template, users in bios.items():
        if len(users) >= 2:
            signals.append({"signal": f"Identical bio template used by: {', '.join(users)}",
                            "innocent": "A copied template, a course bio, or a team page can produce identical bios."})
    return {"signals": signals, "verdict": "pattern, not proof"}


# ---------------------------------------------------------------- Niche overlap
_CELEBRITY_HINTS = {"official", "news", "nasa", "github", "google", "microsoft", "apple", "elon", "barack", "taylor"}


def niche_overlap(shared_contacts: list, all_contacts: dict | None = None) -> dict:
    """Weight shared contacts by rarity, not by count alone.

    A shared contact whose handle is long/rare and is not a famous
    account counts more than a shared celebrity follow. Rarity here is
    a heuristic (handle length and absence of celebrity hints), because
    follower counts for contacts are not collected in this case.
    """
    niche = []
    celebrity = []
    for contact in shared_contacts or []:
        low = contact.lower()
        if any(h in low for h in _CELEBRITY_HINTS) or len(contact) <= 4:
            celebrity.append(contact)
        else:
            niche.append(contact)
    total = len(shared_contacts or [])
    return {"shared": shared_contacts or [], "niche_shared": niche,
            "celebrity_shared": celebrity,
            "niche_ratio": (len(niche) / total) if total else 0.0,
            "note": "Niche shared contacts weigh more than shared celebrity follows. This is a heuristic, not a relationship proof."}
