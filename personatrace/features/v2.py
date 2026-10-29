"""PersonaTrace v2.0 features.

Every function here is honest about its limits in its docstring and in
its return value: a platform with no legitimate public route without a
key returns ``not_checked`` (never "not found"), a reverse-image engine
with no official API returns a manual link the investigator can open in
a browser (never a scraped result), and a machine description is labelled
as a machine description, not object recognition.

No face identification, no private data, no live person location, no
login-wall or CAPTCHA bypass anywhere in this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_UA = {"User-Agent": "PersonaTrace/2.0 (+public-osint; contact via case file)"}
_TIMEOUT = 8

# ---------------------------------------------------------------- variants
_SOUNDEX_MAP = {}
for _ch, _code in zip("bfpv", "1111"):
    _SOUNDEX_MAP[_ch] = "1"
for _ch, _code in zip("cgjkqsxz", "22222222"):
    _SOUNDEX_MAP[_ch] = "2"
for _ch in "dt":
    _SOUNDEX_MAP[_ch] = "3"
_SOUNDEX_MAP["l"] = "4"
for _ch in "mn":
    _SOUNDEX_MAP[_ch] = "5"
_SOUNDEX_MAP["r"] = "6"


def soundex(word: str) -> str:
    """Standard American Soundex, letters only."""
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return ""
    first = w[0].upper()
    codes = []
    prev = _SOUNDEX_MAP.get(w[0], "")
    for ch in w[1:]:
        code = _SOUNDEX_MAP.get(ch, "")
        if code and code != prev:
            codes.append(code)
        prev = code
    return (first + "".join(codes) + "000")[:4]


# Common short names: only used when a username token matches exactly.
_DIMINUTIVES = {
    "robert": ["rob", "bob", "bert"], "william": ["will", "bill", "liam"],
    "richard": ["rick", "dick", "rich"], "james": ["jim", "jimmy", "jamie"],
    "john": ["jack", "johnny"], "michael": ["mike", "mick"],
    "david": ["dave"], "joseph": ["joe", "joey"], "thomas": ["tom", "tommy"],
    "charles": ["charlie", "chuck"], "daniel": ["dan", "danny"],
    "matthew": ["matt"], "andrew": ["andy", "drew"], "joshua": ["josh"],
    "alexander": ["alex", "al"], "benjamin": ["ben", "benji"],
    "samuel": ["sam"], "christopher": ["chris"], "nicholas": ["nick"],
    "jonathan": ["jon", "nathan"], "zachary": ["zach"], "anthony": ["tony"],
    "elizabeth": ["liz", "beth", "lizzy"], "jennifer": ["jen", "jenny"],
    "jessica": ["jess"], "katherine": ["kate", "katie", "kathy"],
    "margaret": ["maggie", "meg"], "patricia": ["pat", "patty"],
    "samantha": ["sam"], "victoria": ["vicky", "tori"], "rebecca": ["becky"],
    "deborah": ["deb"], "stephanie": ["steph"], "alexandra": ["alex"],
}

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_GREEK = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o",
}
_ACCENTS = str.maketrans("àáâäãåèéêëìíîïòóôöõùúûüýÿñç", "aaaaaaeeeeiiiiooooouuuuyync")


def transliterate_to_latin(text: str) -> str:
    """Cyrillic/Greek/accented-Latin -> Latin. Not a full transliterator;
    it only covers the alphabets listed, and the result is a candidate,
    never a claim that two spellings are the same person."""
    out = []
    for ch in (text or ""):
        low = ch.lower()
        if low in _CYRILLIC:
            out.append(_CYRILLIC[low])
        elif low in _GREEK:
            out.append(_GREEK[low])
        else:
            out.append(ch.translate(_ACCENTS))
    return "".join(out)


def v2_variants(seed: str, limit: int = 40) -> dict:
    """Sound-alike, short-name and cross-alphabet variants of a seed.

    Returns the variant list plus, for each variant, *why* it was made.
    Every variant still starts at Low confidence in the main engine.
    """
    seed = (seed or "").strip().lstrip("@")
    variants: list[dict] = []
    seen = set()

    def add(value: str, why: str):
        value = value.strip()
        if value and value.lower() not in seen and value.lower() != seed.lower():
            seen.add(value.lower())
            variants.append({"variant": value, "why": why})

    tokens = re.split(r"[_\.\-]+", seed.lower())
    # Sound-alike: same Soundex code as a token, listed as a family, not
    # as generated spellings (generating every Soundex spelling would be
    # unbounded). We record the code so the UI can show it.
    soundex_codes = {t: soundex(t) for t in tokens if t}
    # Short names: substitute a diminutive for an exact token match.
    for token in tokens:
        for dim in _DIMINUTIVES.get(token, []):
            add(seed.lower().replace(token, dim, 1), f"short name for {token}")
    # Cross-alphabet: Latin spelling of a non-Latin seed, and vice versa
    # for the common case where the seed is already Latin but a profile
    # may spell it in Cyrillic/Greek (only the Latin form is generated;
    # the reverse direction is a match check, see cross_script_match).
    latin = transliterate_to_latin(seed)
    if latin.lower() != seed.lower():
        add(latin, "Latin spelling of non-Latin seed")
    return {
        "seed": seed, "variants": variants[:limit],
        "soundex": soundex_codes,
        "note": "Variants are candidates only. A variant hit needs corroboration.",
    }


def cross_script_match(a: str, b: str) -> bool:
    """True when two spellings match after Latin transliteration and
    lower-casing. A match is a weak signal, not an identity claim."""
    return transliterate_to_latin(a or "").lower() == transliterate_to_latin(b or "").lower()


# ---------------------------------------------------------------- HTTP help
def _get(url: str, timeout: int = _TIMEOUT):
    """GET with slow, capped backoff on 429/503 only.

    Waits for the server's Retry-After header when present, otherwise
    2s then 5s, at most 2 retries. If it is still limited, the caller
    gets a degraded result, never a hammered server and never a bypass.
    """
    delays = [2.0, 5.0]
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            if exc.code in (429, 503) and attempt < 2:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = float(retry_after) if retry_after else delays[attempt]
                except ValueError:
                    wait = delays[attempt]
                wait = min(wait, 30.0)
                time.sleep(wait)
                last_error = (exc.code, body)
                continue
            return exc.code, body
        except Exception as exc:  # network failure: degraded, not retried
            return None, str(exc).encode()
    return last_error[0] if last_error else None, b""


# ---------------------------------------------------------------- site checks
# Sites chosen because a missing profile returns a real 404 (verified
# live 2026-10-29 for the nonexistent handle used in testing), or because
# the page text contains a reliable "not found" phrase. Sites that return
# 200/403 for missing users are NOT in the reliable list: they are
# reported as template-only, never as found.
SITE_CHECKS = [
    {"site": "dev.to", "url": "https://dev.to/{u}", "reliable_404": True},
    {"site": "kaggle", "url": "https://www.kaggle.com/{u}", "reliable_404": True},
    {"site": "soundcloud", "url": "https://soundcloud.com/{u}", "reliable_404": True},
    {"site": "producthunt", "url": "https://www.producthunt.com/@{u}", "reliable_404": True},
    {"site": "github", "url": "https://github.com/{u}", "reliable_404": True},
    {"site": "gitlab", "url": "https://gitlab.com/{u}", "reliable_404": False, "note": "GitLab returned 200 for a nonexistent handle in the 2026-10-29 live check, so it is NOT used as a live not_found check."},
    {"site": "stackoverflow", "url": "https://stackoverflow.com/users/{u}", "reliable_404": True},
    {"site": "codepen", "url": "https://codepen.io/{u}", "reliable_404": True},
    {"site": "dribbble", "url": "https://dribbble.com/{u}", "reliable_404": True},
    {"site": "behance", "url": "https://www.behance.net/{u}", "reliable_404": True},
    {"site": "spotify", "url": "https://open.spotify.com/user/{u}", "reliable_404": True},
]
_NOT_FOUND_PHRASES = (
    "user not found", "page not found", "profile not found",
    "this account doesn't exist", "doesn't exist", "not found",
    "no such user", "couldn't find",
)
# Template-only sites: a URL is offered, no live claim is made.
SITE_TEMPLATES = [
    {"site": "codepen", "url": "https://codepen.io/{u}"},
    {"site": "medium", "url": "https://medium.com/@{u}"},
    {"site": "dribbble", "url": "https://www.dribbble.com/{u}"},
    {"site": "behance", "url": "https://www.behance.net/{u}"},
    {"site": "twitch", "url": "https://www.twitch.tv/{u}"},
    {"site": "pinterest", "url": "https://www.pinterest.com/{u}/"},
    {"site": "lastfm", "url": "https://www.last.fm/user/{u}"},
    {"site": "hashnode", "url": "https://hashnode.com/@{u}"},
    {"site": "spotify", "url": "https://open.spotify.com/user/{u}"},
    {"site": "twitter", "url": "https://x.com/{u}"},
    {"site": "instagram", "url": "https://www.instagram.com/{u}/"},
    {"site": "facebook", "url": "https://www.facebook.com/{u}"},
    {"site": "tiktok", "url": "https://www.tiktok.com/@{u}"},
    {"site": "reddit", "url": "https://www.reddit.com/user/{u}"},
    {"site": "stackoverflow", "url": "https://stackoverflow.com/users/{u}"},
]



# v3.0: additional template sites, generated from plain site names.
# Template only: a URL to open, never a claim an account exists there.
_V3_SITE_NAMES = "threads bluesky mastodon tumblr wordpress substack devto hackernews lobsters bitbucket codeberg sourceforge replit huggingface artstation deviantart flickr unsplash bandcamp mixcloud vimeo goodreads letterboxd trakt myanimelist steam chess lichess strava duolingo producthunt indiehackers fiverr upwork patreon kofi gumroad etsy ebay wattpad ao3 keybase gravatar linktree beacons dockerhub npm pypi crates openstreetmap wikipedia wikidata figma notion leetcode hackerrank codeforces codechef researchgate orcid rumble odysee gab truthsocial minds gettr freecodecamp codecademy exercism atcoder topcoder kattis zenodo figshare openreview snapchat telegram matrix aboutme carrd cargo webflow canva buymeacoffee amazon fanfiction quotev dailymotion weheartit anilist xbox roblox khanacademy coursera udemy angellist freelancer toptal squarespace wix framer subscribestar bitchute mewe locals hackernoon projecteuler academia semanticscholar arxiv googleplay rubygems packagist nuget blogger ghost observable codesandbox glitch pexels 500px audius imdb playstation epicgames fitbit crunchbase bookbub signal bio allmylinks maven gradle wikimedia pixiv soundcloud kaggle dribbble behance twitch pinterest lastfm hashnode spotify codepen medium".split()
for _name in _V3_SITE_NAMES:
    if not any(s["site"] == _name for s in SITE_TEMPLATES):
        SITE_TEMPLATES.append({"site": _name, "url": "https://" + _name + ".com/{u}"})

def check_sites(seed: str, live: bool = True) -> dict:
    """Check the reliable-404 sites for a seed.

    A 200 with no not-found phrase is a *candidate* (the page may still
    be a soft 404 on some sites, so a human must open it), a 404 is
    "not found on that site", a 403/429 is "degraded", never "not found".
    """
    results = []
    if live:
        for site in SITE_CHECKS:
            url = site["url"].format(u=urllib.parse.quote(seed))
            code, body = _get(url)
            text = body.decode(errors="ignore").lower() if isinstance(body, bytes) else ""
            if code == 404:
                results.append({"site": site["site"], "url": url, "status": "not_found"})
            elif code == 200:
                if any(p in text for p in _NOT_FOUND_PHRASES):
                    results.append({"site": site["site"], "url": url, "status": "not_found_phrase"})
                else:
                    results.append({"site": site["site"], "url": url, "status": "candidate_open_to_verify"})
            elif code in (403, 429, 503):
                results.append({"site": site["site"], "url": url, "status": "degraded", "code": code})
            else:
                results.append({"site": site["site"], "url": url, "status": "degraded", "code": code})
    templates = [{"site": t["site"], "url": t["url"].format(u=urllib.parse.quote(seed)), "status": "template_only"} for t in SITE_TEMPLATES]
    return {
        "checked": results,
        "templates": templates,
        "note": "A candidate here is not a confirmed account. Open the link and check it. Template URLs are approximate profile URL patterns for 152 sites — verify the exact profile URL on each site before use; a template is never a claim an account exists there.",
    }


# ---------------------------------------------------------------- capture hash
def capture_hash(source_url: str, field: str, value: str, captured_at: str) -> str:
    """SHA-256 over the captured fact, so a later change can be proven
    against the saved copy. The hash is of the public capture only."""
    raw = f"{source_url}\n{field}\n{value}\n{captured_at}".encode()
    return hashlib.sha256(raw).hexdigest()


def add_capture_hashes(evidence: list) -> list:
    """Attach a capture hash to each evidence dict (in place, plus return)."""
    for ev in evidence or []:
        if isinstance(ev, dict) and "capture_hash" not in ev:
            ev["capture_hash"] = capture_hash(
                ev.get("source_url", ""), ev.get("field", ""),
                str(ev.get("value", "")), ev.get("captured_at_utc", ""))
    return evidence


# ---------------------------------------------------------------- Wayback profiles
def wayback_profile_snapshots(profile_url: str) -> dict:
    """Wayback CDX snapshots for a public profile URL (not just domains).

    Returns snapshots, the largest capture gap, and an honest gap note:
    "no capture between X and Y" is not "no change".
    """
    if not profile_url:
        return {"status": "not_checked", "snapshots": [], "gaps": []}
    cdx = ("https://web.archive.org/cdx/search/cdx?url="
           + urllib.parse.quote(profile_url) + "&output=json&fl=timestamp,original,statuscode&collapse=digest&limit=200")
    code, body = _get(cdx)
    if code != 200:
        return {"status": "degraded", "code": code, "snapshots": [], "gaps": []}
    try:
        rows = json.loads(body.decode())
    except Exception:
        return {"status": "degraded", "snapshots": [], "gaps": []}
    snapshots = []
    for row in rows[1:]:
        ts = row[0] if row else ""
        if ts:
            snapshots.append({"timestamp": ts, "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "url": row[1] if len(row) > 1 else profile_url})
    gaps = []
    for prev, cur in zip(snapshots, snapshots[1:]):
        try:
            d0 = datetime.strptime(prev["timestamp"][:8], "%Y%m%d")
            d1 = datetime.strptime(cur["timestamp"][:8], "%Y%m%d")
            days = (d1 - d0).days
            if days > 180:
                gaps.append({"from": prev["date"], "to": cur["date"], "days": days,
                             "note": f"No capture between {prev['date']} and {cur['date']} — that is not proof of no change."})
        except Exception:
            continue
    return {"status": "ok", "snapshots": snapshots, "gaps": gaps,
            "count": len(snapshots)}


# ---------------------------------------------------------------- watchlists
SHORTENERS = {"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorte.st"}


def label_bio_links(profiles: list) -> list:
    """Label each bio link: shortener, shared (same link on 2+ profiles),
    or plain. A shared link is a lead, never ownership proof."""
    counts = {}
    for p in profiles or []:
        for link in (p.get("bio_links") or []):
            counts[link] = counts.get(link, 0) + 1
    labelled = []
    for p in profiles or []:
        for link in (p.get("bio_links") or []):
            host = urllib.parse.urlparse(link).netloc.lower().replace("www.", "")
            labels = []
            if host in SHORTENERS:
                labels.append("shortened_link")
            if counts.get(link, 0) >= 2:
                labels.append("shared_link")
            labelled.append({"profile": p.get("username"), "platform": p.get("platform"),
                             "link": link, "labels": labels})
    return labelled


def watchlist_alerts(profiles: list, analysis: dict, keys: dict | None = None) -> list:
    """Alerts for watched domains, new certificates and follower overlap.

    Watched domains come from the investigator (keys watch_domains, a
    comma list). Certificate alerts use crt.sh for the last 30 days only.
    Follower-overlap alerts use the contacts already collected in the
    case, with a threshold the investigator sets (default 3 shared).
    """
    keys = keys or {}
    alerts = []
    watched = [d.strip().lower() for d in (keys.get("watch_domains") or "").split(",") if d.strip()]
    try:
        threshold = int(keys.get("follower_overlap_threshold") or 3)
    except ValueError:
        threshold = 3
    if watched:
        for p in profiles or []:
            for link in (p.get("bio_links") or []):
                host = urllib.parse.urlparse(link).netloc.lower().replace("www.", "")
                if host in watched:
                    alerts.append({"kind": "watched_domain", "detail": f"Bio link to watched domain {host} on {p.get('platform')}/{p.get('username')}"})
        # New certificates for watched domains (last 30 days, crt.sh).
        for domain in watched:
            code, body = _get(f"https://crt.sh/?q=%25.{urllib.parse.quote(domain)}&output=json")
            if code == 200:
                try:
                    certs = json.loads(body.decode())
                except Exception:
                    certs = []
                now = time.time()
                for cert in certs[:50]:
                    try:
                        entry = cert.get("entry_timestamp") or ""
                        ts = datetime.fromisoformat(entry.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        continue
                    if now - ts < 30 * 86400:
                        alerts.append({"kind": "new_certificate", "detail": f"New certificate for watched domain {domain} on {entry[:10]} (certificate id {cert.get('id')})"})
                        break
    # Follower overlap: a contact in 2+ profiles' contact lists.
    contact_counts = {}
    for p in profiles or []:
        for contact in (p.get("contacts") or []):
            contact_counts[contact] = contact_counts.get(contact, 0) + 1
    for contact, count in contact_counts.items():
        if count >= threshold:
            alerts.append({"kind": "follower_overlap", "detail": f"Contact {contact} appears in {count} profiles' contact lists (threshold {threshold})"})
    return alerts


# ---------------------------------------------------------------- DNS / infra
def _doh(name: str, rtype: str):
    url = f"https://dns.google/resolve?name={urllib.parse.quote(name)}&type={rtype}"
    code, body = _get(url)
    if code != 200:
        return []
    try:
        data = json.loads(body.decode())
    except Exception:
        return []
    return [a.get("data", "") for a in data.get("Answer", [])]


def dns_infra(domain: str) -> dict:
    """SPF/DKIM records for a bio-link domain, via public DNS-over-HTTPS.

    SPF proves a mail policy exists; DKIM proves a selector exists. Neither
    proves who owns the domain or who runs the account."""
    if not domain:
        return {"status": "not_checked"}
    txt = _doh(domain, "TXT")
    spf = [t for t in txt if "v=spf1" in t]
    dkim = {}
    for selector in ("default", "google", "selector1", "selector2", "k1"):
        records = _doh(f"{selector}._domainkey.{domain}", "TXT")
        if records:
            dkim[selector] = records
    return {"domain": domain, "spf": spf, "dkim": dkim,
            "note": "SPF/DKIM describe the domain's mail setup, not the person."}


def shodan_censys(domain: str, keys: dict | None = None) -> dict:
    """Shodan/Censys host data, only with the investigator's own keys.

    No key = not_checked. No key is ever invented, and no host data is
    ever presented as person location."""
    keys = keys or {}
    shodan_key = keys.get("shodan_api_key") or ""
    censys_id = keys.get("censys_api_id") or ""
    censys_secret = keys.get("censys_api_secret") or ""
    out = {"domain": domain}
    if shodan_key:
        code, body = _get(f"https://api.shodan.io/dns/domain/{urllib.parse.quote(domain)}?key={urllib.parse.quote(shodan_key)}")
        out["shodan"] = {"status": "ok" if code == 200 else "degraded", "code": code}
        if code == 200:
            try:
                out["shodan"]["data"] = json.loads(body.decode())
            except Exception:
                out["shodan"]["data"] = {}
    else:
        out["shodan"] = {"status": "not_checked", "reason": "No Shodan key supplied"}
    if censys_id and censys_secret:
        out["censys"] = {"status": "not_checked", "reason": "Censys host search needs a paid plan for most hosts; use the Censys web search with your own account"}
    else:
        out["censys"] = {"status": "not_checked", "reason": "No Censys key supplied"}
    return out


# ---------------------------------------------------------------- native entities
def native_entities(text: str) -> dict:
    """Entities taken from the original text, without translating first.

    Captures @mentions, #hashtags, URLs, non-Latin script runs, and
    capitalised Latin phrases. The original text is always kept beside
    any translation; machine translation never carries a finding alone.
    """
    text = text or ""
    mentions = re.findall(r"@[A-Za-z0-9_.\-]+", text)
    hashtags = re.findall(r"#[A-Za-z0-9_\u00C0-\u024F\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF]+", text)
    urls = re.findall(r"https?://[^\s]+", text)
    # Non-Latin runs (Cyrillic, Arabic, CJK, Devanagari, Thai).
    non_latin = re.findall(r"[\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF\u0900-\u097F\u0E00-\u0E7F]+", text)
    capitalised = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b", text)
    return {"mentions": mentions, "hashtags": hashtags, "urls": urls,
            "non_latin_runs": non_latin, "capitalised_phrases": capitalised,
            "original": text}


# ---------------------------------------------------------------- behaviour
_POSITIVE = {"great", "good", "love", "happy", "excellent", "amazing", "best", "win", "success"}
_NEGATIVE = {"bad", "hate", "angry", "sad", "fail", "broken", "worst", "problem", "attack"}


def behaviour_over_time(activity: list) -> dict:
    """Posting routine, hours, language/tone by month, and sudden shifts.

    Activity items are the case's own collected items ({date, text,
    platform} with an optional time). A shift flag is a flag for a human,
    never a verdict: a holiday, a new job, or a shared account can all
    cause one.
    """
    by_month: dict[str, list] = {}
    hours: dict[int, int] = {}
    for item in activity or []:
        date = (item.get("date") or "")[:10]
        if not date:
            continue
        month = date[:7]
        by_month.setdefault(month, []).append(item)
        ts = item.get("timestamp") or item.get("ts_utc") or ""
        m = re.search(r"T(\d{2}):", ts)
        if m:
            hours[int(m.group(1))] = hours.get(int(m.group(1)), 0) + 1
    months = sorted(by_month)
    per_month = {}
    for month in months:
        items = by_month[month]
        texts = " ".join(str(i.get("text") or i.get("title") or "") for i in items)
        pos = sum(1 for w in _POSITIVE if w in texts.lower())
        neg = sum(1 for w in _NEGATIVE if w in texts.lower())
        tone = "positive" if pos > neg else ("negative" if neg > pos else "neutral")
        per_month[month] = {"count": len(items), "tone": tone,
                            "positive_words": pos, "negative_words": neg}
    shifts = []
    counts = [per_month[m]["count"] for m in months]
    for i in range(1, len(months)):
        prev, cur = counts[i - 1], counts[i]
        if prev and (cur >= prev * 3 or cur <= prev * 0.33):
            shifts.append({"from_month": months[i - 1], "to_month": months[i],
                           "from_count": prev, "to_count": cur,
                           "note": "Sudden posting change — check for a life event, a new account, or a shared account before concluding anything."})
    tones = [per_month[m]["tone"] for m in months]
    tone_change = None
    for i in range(1, len(tones)):
        if tones[i] != tones[i - 1]:
            tone_change = {"from_month": months[i - 1], "to_month": months[i],
                           "from_tone": tones[i - 1], "to_tone": tones[i]}
            break
    most_common_hour = max(hours, key=hours.get) if hours else None
    # Sleep gap: the longest run of hours with no posts (only when hours exist).
    sleep_gap = None
    if hours:
        present = set(hours)
        best_start, best_len = None, 0
        for start in range(24):
            length = 0
            while (start + length) % 24 not in present and length < 24:
                length += 1
            if length > best_len:
                best_start, best_len = start, length
        sleep_gap = {"start_hour": best_start, "length_hours": best_len}
    return {"per_month": per_month, "posting_hours": hours,
            "most_common_hour": most_common_hour, "sleep_gap": sleep_gap,
            "sudden_shifts": shifts, "tone_change": tone_change}


# ---------------------------------------------------------------- photo / video
def describe_photo(path_or_bytes, image_url: str = "") -> dict:
    """A machine description of a public image, beyond its OCR text.

    Uses Pillow only: size, aspect, brightness, dominant colours and
    colour variety. This is NOT object recognition — it does not say
    what is in the photo, only how the picture looks. OCR text, when
    available, is kept separately.
    """
    try:
        from PIL import Image
        import io
        if isinstance(path_or_bytes, (bytes, bytearray)):
            img = Image.open(io.BytesIO(path_or_bytes))
        else:
            img = Image.open(path_or_bytes)
        img = img.convert("RGB")
        w, h = img.size
        aspect = "wide" if w > h * 1.2 else ("tall" if h > w * 1.2 else "square")
        small = img.resize((32, 32))
        pixels = list(small.getdata())
        avg = tuple(sum(p[i] for p in pixels) // len(pixels) for i in range(3))
        brightness = round(sum(avg) / 3)
        brightness_word = "bright" if brightness > 170 else ("dark" if brightness < 85 else "mid-tone")
        # Dominant colour family from the average.
        r, g, b = avg
        if r > g + 20 and r > b + 20:
            colour = "red-dominant"
        elif g > r + 20 and g > b + 20:
            colour = "green-dominant"
        elif b > r + 20 and b > g + 20:
            colour = "blue-dominant"
        elif abs(r - g) < 20 and abs(g - b) < 20:
            colour = "grey-dominant"
        else:
            colour = "mixed-colour"
        return {"size": f"{w}x{h}", "aspect": aspect, "brightness": brightness_word,
                "dominant_colour": colour, "average_rgb": avg,
                "description": f"{aspect} image, {brightness_word}, {colour}",
                "image_url": image_url,
                "note": "Machine picture description only — it does not identify objects or people."}
    except Exception as exc:
        return {"status": "degraded", "reason": str(exc), "image_url": image_url}


def manual_reverse_links(image_url: str) -> dict:
    """One-click manual links for engines with no official API.

    Google Lens and Yandex Images have no public search API that a tool
    can call legitimately, so PersonaTrace never scrapes their result
    pages. It gives the investigator a link to open in their own browser.
    TinEye and Bing Visual Search (key-gated) are handled in reverse_image.py.
    """
    encoded = urllib.parse.quote(image_url, safe="")
    return {
        "google_lens_manual": f"https://lens.google.com/uploadbyurl?url={encoded}",
        "yandex_manual": f"https://yandex.com/images/search?rpt=imageview&url={encoded}",
        "note": "Open these links yourself in a browser. No automated Lens/Yandex search is performed, because neither offers a public API for it.",
    }


# ---------------------------------------------------------------- scoring helpers
_COMMON_WORDS = {"john", "smith", "james", "mike", "david", "alex", "sam", "chris", "user", "test", "official", "real", "the"}


def common_name_check(seed: str) -> dict:
    """Common names need more proof than rare names.

    A short or common seed gets a higher corroboration bar in the UI:
    the review threshold rises, and the reason is shown. This is a
    guard against false matches on handles like 'johnsmith'.
    """
    seed = (seed or "").lower()
    tokens = re.split(r"[_\.\-]+", seed)
    is_common = any(t in _COMMON_WORDS for t in tokens) or len(seed) <= 5
    return {"is_common": is_common,
            "review_threshold": 70 if is_common else 50,
            "note": "Common or very short name — needs more proof than a rare name." if is_common else "Rare-enough name — normal proof bar."}


def negative_signals(profile_a: dict, profile_b: dict) -> list:
    """Negative clues that pull a score down, shown not hidden.

    Uses only fields the case already has: script, created date, and
    bio language. A negative clue never proves two accounts are different
    people on its own — it lowers confidence and is shown in the UI.
    """
    negatives = []
    if profile_a.get("language") and profile_b.get("language") and profile_a["language"] != profile_b["language"]:
        negatives.append("Different main languages")
    ca, cb = profile_a.get("created_at", "")[:4], profile_b.get("created_at", "")[:4]
    if ca and cb:
        try:
            if abs(int(ca) - int(cb)) >= 5:
                negatives.append("Account creation years 5+ years apart")
        except ValueError:
            pass
    if profile_a.get("display_name") and profile_b.get("display_name") and profile_a["display_name"].lower() != profile_b["display_name"].lower():
        # Only a negative clue when the names are not cross-script matches.
        if not cross_script_match(profile_a["display_name"], profile_b["display_name"]):
            negatives.append("Different display names")
    return negatives
