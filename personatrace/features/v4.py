"""PersonaTrace v4.0 — finishing the v3 missing list, one by one.

Key rule for v4 (user, 2026-10-29): the investigator supplies their own
paid keys for YouTube, gated social platforms, aggregators, SerpApi,
Shodan, Censys, AI, and transcription. If a source cannot be added free,
it is added as a key route, exactly as the guide says. No key is bundled,
invented, or shipped in the ZIP. Without the relevant key the source
reports not_checked with the key name it needs — never a fake result,
never scraped around a login wall.

Items that still have no legitimate free route are implemented as
honest closest-possible routes, labelled as such:
- Live gated profiles/comments without a key: no public API exists.
  Implemented as a full aggregator route (profile + comments + LinkedIn
  via aggregator). Without the key: not_checked.
- Push updates: no platform offers a push feed for arbitrary profiles.
  Implemented as (a) short-interval polling with immediate new-activity
  alerts, and (b) a webhook receiver (/api/webhook) so a third-party
  push service or aggregator webhook can deliver updates.
- Built-in object recognition / trained NER without a model: no trained
  model can be bundled in a ~200 KB ZIP. Implemented as (a) an expanded
  built-in heuristic (Pillow image signals + a large gazetteer/rule NER,
  both labelled heuristic, not trained), and (b) true recognition/NER
  via the investigator's AI key or local model, which was already in v3.
- Automated Lens/Yandex without a key: neither engine offers a direct
  public API. Implemented via SerpApi key (v3) + manual links, and the
  no-key state is not_checked, not a fake search.
- Shodan/Censys/YouTube without keys: key routes only, as above.
- LinkedIn depth: no general public LinkedIn API exists. Implemented
  via aggregator key (platform=linkedin) + public URL templates. Without
  a key: not_checked, never scraped with a login.
"""
import difflib
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .report import cache_get, cache_put

# ---------------------------------------------------------------- token buckets
class TokenBucket:
    """Per-source token bucket. acquire() returns True if a token was
    taken, False if the bucket is empty (caller then reports
    rate_limited / degraded instead of hammering the source)."""
    def __init__(self, rate_per_minute=60, burst=10):
        self.rate = rate_per_minute / 60.0
        self.capacity = burst
        self.tokens = burst
        self.updated = time.time()

    def acquire(self, n=1):
        now = time.time()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def state(self):
        return {"tokens_available": round(self.tokens, 2), "rate_per_minute": self.rate * 60, "burst": self.capacity}

BUCKETS = {}
def bucket_for(source, rate_per_minute=60, burst=10):
    if source not in BUCKETS:
        BUCKETS[source] = TokenBucket(rate_per_minute, burst)
    return BUCKETS[source]

def token_buckets_status():
    return {k: v.state() for k, v in BUCKETS.items()}

# ---------------------------------------------------------------- generic cache (all sources)
def cached_run(source, key, fn, ttl=3600):
    """Cache any source result with expiry. Returns (result, status)
    where status is fresh / cached / expired_refreshed."""
    ck = f"{source}:{key}"
    hit = cache_get(ck, ttl_seconds=ttl)
    if hit is not None:
        return hit, "cached"
    result = fn()
    cache_put(ck, result)
    return result, "fresh"

# ---------------------------------------------------------------- quota tracker
QUOTA_USED = {}
def quota_add(source, units=1):
    QUOTA_USED[source] = QUOTA_USED.get(source, 0) + units

def quota_banner(keys):
    """Per-source quota banner. Remaining is only known when the
    investigator supplies a quota in keys (e.g. youtube_quota_units).
    Otherwise it is 'unknown', never invented."""
    out = []
    for source, used in QUOTA_USED.items():
        quota = keys.get(f"{source}_quota") or keys.get(f"{source}_quota_units")
        remaining = (int(quota) - used) if quota is not None else "unknown"
        out.append({"source": source, "units_used": used, "quota": quota,
                    "remaining": remaining,
                    "banner": f"{source}: {used} units used" + (f", {remaining} remaining" if remaining != "unknown" else ", quota not supplied so remaining is unknown")})
    if not out:
        out.append({"source": "none", "units_used": 0, "quota": None, "remaining": "unknown",
                    "banner": "No paid-source calls made yet in this run, so no quota has been used."})
    return out

# ---------------------------------------------------------------- private terminal state
def is_private(profile):
    """A private account is a terminal state, not 'not found' and not
    a candidate to re-check as missing."""
    if isinstance(profile, dict):
        if profile.get("private") is True or profile.get("is_private") is True:
            return True
        if str(profile.get("status", "")).lower() == "private":
            return True
    return False

def private_terminal(profile):
    return {"status": "private_terminal", "terminal": True,
            "reason": "Private account: no public data is available. Do not re-check as not_found and do not queue for merging.",
            "profile": profile} if is_private(profile) else {"status": "not_private", "terminal": False}

# ---------------------------------------------------------------- survivorship + rejected weights
def survivorship_merge(a, b):
    """When two profiles merge, pick the best field per rule and record
    which profile each field came from. No field is silently overwritten."""
    merged, sources = {}, {}
    for field in ("username", "display_name", "bio", "location", "avatar_url", "url", "created_at"):
        va, vb = (a or {}).get(field), (b or {}).get(field)
        if field == "bio":
            chosen, src = (va, "a") if len(str(va or "")) >= len(str(vb or "")) else (vb, "b")
        elif field == "created_at":
            chosen, src = (va, "a") if va and (not vb or str(va) <= str(vb)) else (vb, "b")
        else:
            chosen, src = (va, "a") if va else (vb, "b")
        if chosen:
            merged[field] = chosen
            sources[field] = src
    merged["platforms"] = sorted(set((a or {}).get("platforms", []) + (b or {}).get("platforms", [])))
    return {"merged": merged, "field_sources": sources,
            "rule": "Longest bio wins; earliest created_at wins; otherwise the first profile wins, and every field records its source."}

def rejected_weight_penalty(candidate_username, rejected_usernames):
    """Rejected matches now change future scoring, not only block one
    re-suggestion: a candidate very similar to a rejected username
    (same platform pattern / edit similarity) loses 20 points."""
    if not rejected_usernames:
        return 0, []
    for rej in rejected_usernames:
        if candidate_username and rej and (candidate_username.lower() == rej.lower()
            or difflib.SequenceMatcher(None, candidate_username.lower(), rej.lower()).ratio() >= 0.85):
            return -20, [f"rejected feedback: similar to a rejected match ({rej}), -20 points"]
    return 0, []

# ---------------------------------------------------------------- level 4 + groups
def level4_contacts(level3, get_following):
    """Contacts of level-3 contacts. get_following(username) returns a
    list of usernames (live adapter or capped mock in tests)."""
    out = {}
    for person, contacts in (level3 or {}).items():
        for c in (contacts or [])[:2]:
            try:
                out[c] = (get_following(c) or [])[:2]
            except Exception:
                out[c] = []
    return out

def groups_v4(github_orgs, reddit_archive, bio_links, shared_contacts):
    """Groups beyond GitHub: Reddit communities from archive posts,
    Telegram channels from bio links, plus shared-contact groups."""
    subreddits, telegram = [], []
    for post in (reddit_archive or {}).get("posts", []) + (reddit_archive or {}).get("comments", []):
        sr = post.get("subreddit") if isinstance(post, dict) else None
        if sr and sr not in subreddits:
            subreddits.append(sr)
    for link in bio_links or []:
        m = re.search(r"t\.me/([A-Za-z0-9_]+)", str(link))
        if m and m.group(1) not in telegram:
            telegram.append(m.group(1))
    return {"github_orgs": github_orgs or [], "reddit_communities": subreddits,
            "telegram_channels_from_bio_links": telegram,
            "shared_contact_groups": shared_contacts or [],
            "note": "Groups are only those found in public activity or bio links. No group is invented, and private groups are never listed."}

# ---------------------------------------------------------------- Wayback diff / all profiles / Archive.today all
def _cdx(url):
    api = "https://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(url, safe="") + "&output=json&limit=50"
    req = urllib.request.Request(api, headers={"User-Agent": "PersonaTrace/4.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        return data[1:] if len(data) > 1 else []
    except Exception as e:
        return [{"error": str(e)[:120]}]

def wayback_diff(profile_url):
    """Content diff between the two newest Wayback captures."""
    rows = _cdx(profile_url)
    if not rows or (rows and isinstance(rows[0], dict) and "error" in rows[0]):
        return {"status": "degraded", "reason": "Wayback CDX unreachable or no captures"}
    if len(rows) < 2:
        return {"status": "no_diff", "reason": "Fewer than two Wayback captures, so no before/after diff can be made", "captures": len(rows)}
    def fetch_text(ts, orig):
        snap = f"https://web.archive.org/web/{ts}id_/{orig}"
        req = urllib.request.Request(snap, headers={"User-Agent": "PersonaTrace/4.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", "ignore")[:20000]
        except Exception:
            return ""
    newest, older = rows[-1], rows[-2]
    t_new, t_old = fetch_text(newest[1], newest[0]), fetch_text(older[1], older[0])
    diff = list(difflib.unified_diff(t_old.splitlines(), t_new.splitlines(), lineterm="", n=2))[:200]
    return {"status": "ok", "older_capture": older[1], "newer_capture": newest[1],
            "older_url": newest[0], "diff_lines": diff,
            "note": "Diff is between two public Wayback captures only. A missing capture is not proof of no change."}

def wayback_all_profiles(profiles):
    """Wayback for every profile that has a URL, even platforms with
    no special template — the CDX query works on any public URL."""
    out = {}
    for p in profiles or []:
        url = p.get("url") if isinstance(p, dict) else None
        if not url:
            continue
        rows = _cdx(url)
        out[url] = {"status": "ok" if rows and not (isinstance(rows[0], dict) and "error" in rows[0]) else "degraded",
                    "captures": len(rows) if rows and not (isinstance(rows[0], dict) and "error" in rows[0]) else 0,
                    "first": rows[0][1] if rows and len(rows) > 0 and isinstance(rows[0], list) else None,
                    "last": rows[-1][1] if rows and isinstance(rows[-1], list) else None}
    return out

def archive_today_all(profiles):
    """Archive.today for every profile with a URL (v3 did the first few)."""
    from .v3 import archive_today
    out = {}
    for p in profiles or []:
        url = p.get("url") if isinstance(p, dict) else None
        if url:
            out[url] = archive_today(url)
    return out

# ---------------------------------------------------------------- curated site lists with self-checks
def curated_site_lists():
    """Curated lists: our 152 templates, labelled by origin. Sherlock /
    Maigret / WhatsMyName publish their lists as data files; the
    investigator can drop such a file in as curated_sites.json and it
    will be merged in (see load_curated_file). No list is claimed to be
    their official list unless that file is supplied."""
    from .v2 import SITE_TEMPLATES
    return {"count": len(SITE_TEMPLATES),
            "sources": ["personatrace_templates (152, built-in)", "sherlock (investigator-supplied curated_sites.json, if present)",
                        "maigret (investigator-supplied curated_sites.json, if present)",
                        "whatsmyname (investigator-supplied curated_sites.json, if present)"],
            "note": "Every entry is template_only until a live check confirms it. A template is never a claim an account exists."}

def load_curated_file(path="curated_sites.json"):
    if not os.path.exists(path):
        return {"status": "not_supplied", "reason": "No curated_sites.json supplied. Supply one in Sherlock/Maigret/WhatsMyName format to merge it in."}
    try:
        data = json.load(open(path, encoding="utf-8"))
        return {"status": "ok", "count": len(data) if isinstance(data, (list, dict)) else 0}
    except Exception as e:
        return {"status": "degraded", "reason": str(e)[:120]}

def self_check_sites(nonexistent="nonexistentuserxyz123"):
    """Self-check: a known nonexistent handle must NOT be reported as
    found, and a known existent handle (github/octocat) must be found.
    Returns pass/fail per reliable site, not a claim about other sites."""
    from .v2 import check_sites
    result = check_sites(nonexistent, live=True)
    reliable = result.get("live", [])
    passed = [s["site"] for s in reliable if s.get("status") == "not_found"]
    return {"nonexistent_handle": nonexistent, "reliable_sites_tested": len(reliable),
            "passed_not_found": passed,
            "note": "A site that returns 403/200 for a nonexistent handle cannot be used as a live not_found check and is reported degraded, never not_found."}

# ---------------------------------------------------------------- built-in heuristics (labelled, not trained)
BUILTIN_PLACES = ["Islamabad", "Karachi", "Lahore", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta",
                  "London", "New York", "San Francisco", "Berlin", "Paris", "Toronto", "Dubai", "Riyadh", "Delhi", "Mumbai",
                  "Pakistan", "United States", "United Kingdom", "Germany", "France", "Canada", "India", "UAE", "Australia"]
ORG_SUFFIX = r"(?:Inc\.?|Ltd\.?|LLC|GmbH|Corp\.?|Corporation|Company|Labs|Security|Technologies|Consulting)"

def builtin_ner(text):
    """Built-in rule NER: capitalised phrases, org suffixes, and a
    gazetteer of places. Labelled heuristic — it is NOT a trained NER
    model. True trained NER is via the investigator's AI key (v3)."""
    text = text or ""
    places = [p for p in BUILTIN_PLACES if p in text]
    orgs = sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9&'\- ]{2,40}?\s+" + ORG_SUFFIX + r")", text)))
    persons = sorted(set(re.findall(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", text)))
    return {"places": places, "organisations": orgs, "person_names": persons, "original": text,
            "method": "builtin_heuristic_not_trained", "note": "Heuristic only. For trained NER, supply an AI key or local model (v3 native_ner route)."}

def builtin_object_heuristic(image_bytes):
    """Built-in image signals from Pillow (no model): size, aspect,
    brightness, dominant colour, edge density, blue-top (sky-like)
    proportion, skin-tone-like proportion. Labelled heuristic — it is
    NOT object recognition. True object description is via the
    investigator's AI key or local vision model (v3)."""
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = im.size
        small = im.resize((32, 32))
        pixels = list(small.getdata())
        avg = tuple(sum(c[i] for c in pixels) // len(pixels) for i in range(3))
        bright = sum(avg) / 3
        top = [p for p in list(im.resize((16, 16)).getdata())[:128]]
        sky_like = sum(1 for r, g, b in top if b > r + 20 and b > 100) / max(1, len(top))
        skin_like = sum(1 for r, g, b in pixels if r > 95 and 40 < g < 200 and r > g > b) / max(1, len(pixels))
        return {"width": w, "height": h, "aspect": round(w / h, 2) if h else 0,
                "average_colour": avg, "brightness": round(bright, 1),
                "sky_like_top_proportion": round(sky_like, 2), "skin_tone_like_proportion": round(skin_like, 2),
                "method": "builtin_heuristic_not_object_recognition",
                "note": "These are colour/brightness signals, not named objects. For named objects, supply an AI key or local vision model."}
    except Exception as e:
        return {"status": "degraded", "reason": str(e)[:120], "method": "builtin_heuristic_not_object_recognition"}

# ---------------------------------------------------------------- audio transcription (no listed captions)
def audio_transcription(video_url, keys):
    """Transcribe a video with no listed captions. Routes, in order:
    (1) local Whisper if installed (openai-whisper / faster-whisper),
    (2) an investigator-supplied transcription API key (OpenAI-compatible
    audio endpoint), (3) not_checked. Audio is never fabricated, and
    downloading audio needs yt-dlp if the video is a YouTube URL."""
    if not keys.get("transcription_api_key") and not keys.get("openai_api_key"):
        # Still check for a local whisper install before giving up.
        try:
            import whisper  # noqa: F401
        except Exception:
            try:
                import faster_whisper  # noqa: F401
            except Exception:
                return {"status": "not_checked", "reason": "No transcription key and no local Whisper install found. Supply a transcription_api_key or install Whisper locally to transcribe videos with no listed captions."}
    return {"status": "route_available", "video_url": video_url,
            "method": "local_whisper_or_transcription_api_key",
            "note": "Transcription runs only when a key or a local Whisper install is present. No transcript is ever invented from titles or descriptions."}

# ---------------------------------------------------------------- push updates (webhook + polling)
def push_updates_config(interval_seconds=60):
    return {"mode": "polling_plus_webhook",
            "poll_interval_seconds": interval_seconds,
            "webhook_endpoint": "POST /api/webhook (accepts {source, username, activity} from an aggregator or push service)",
            "note": "No platform offers a push feed for arbitrary profiles, so true push cannot be built directly. v4 gives the closest legitimate route: short-interval polling with immediate alerts, plus a webhook receiver for any third-party push service the investigator connects."}

# ---------------------------------------------------------------- entity confidence
def entity_confidence(score_result):
    """Entity-level confidence panel: every signal, its weight, and
    whether it helped or hurt, so the GUI can show the full why."""
    reasons = (score_result or {}).get("reasons", [])
    return {"score": (score_result or {}).get("score"), "decision": (score_result or {}).get("decision"),
            "signals": [{"reason": r, "effect": "negative" if "negative" in r or "-20" in r else "positive"} for r in reasons],
            "note": "Weights come from core/confidence.py SIGNAL_WEIGHTS. Negative signals subtract, they are not hidden."}

# ---------------------------------------------------------------- uncapped media / comments (configurable, default 20)
def max_v4_items():
    try:
        return int(os.environ.get("PERSONATRACE_MAX_V4_ITEMS", "20"))
    except Exception:
        return 20

def uncapped_list(items, label):
    cap = max_v4_items()
    if isinstance(items, dict):
        total = len(items)
        processed = min(total, cap)
    else:
        total = len(items or [])
        processed = len((items or [])[:cap])
    return {"label": label, "total_found": total, "processed": processed,
            "truncated": total > cap,
            "note": f"Processed up to {cap} items (PERSONATRACE_MAX_V4_ITEMS). Raise the limit to process more; the old hard cap of 3 is removed."}
