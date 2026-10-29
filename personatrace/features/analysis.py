"""Wired analysis: the feature modules, actually run on a live case.

v1.1 shipped these modules as library code that a live search never
called. v1.2 calls them here, from the engine, so a live investigation
now returns an ``analysis`` report alongside profiles and edges:

- bio domains (bio-link extraction) + LIVE expansion: Wayback, crt.sh
  and DNS via the live adapters, RDAP (public WHOIS) and ipwho.is
  (server infrastructure country/organisation only, never a person).
  crt.sh certificate names become level-3 domain nodes.
- recent public activity text: GitHub repos, Bluesky author feed,
  YouTube uploads (titles/descriptions only — full video transcripts
  are not fetched, because there is no public transcript API for
  arbitrary channels; this is stated, not hidden).
- language/script per profile, coordinated crowd check, stylometry
  (capped weak signal, sample size shown), bio-phrase matches across
  profiles, archive snapshots, avatar-reuse via downloaded public
  avatars + pHash (Hamming <= 10), and a template behaviour summary.
- graph-aware alerts: shared bio domain (bridge), avatar reuse,
  possible matches, new domain nodes.

Honest limits, enforced here:
- No network in demo mode. No private data, no face identification
  (pHash compares whole images, never faces), no live person
  location, no CAPTCHA / rate-limit / login-wall bypass. Every live
  call is a single public GET with a 5s timeout and no retry; a 429
  or failure is degraded, never fabricated and never retried.
- Activity and expansion are capped (5 domains, 4 activity profiles,
  5 items each) so one case cannot turn into a firehose.
- Stylometry and coordinated signals are weak / pattern-only and
  never merge a profile on their own.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from .archive import diff_snapshots, snapshot
from .alerts import check_new_edges
from .biolink import extract_domains
from .coordinated import crowd_check
from .language import detect_language
from .phash import ahash, hamming, is_image_bytes
from .phrase import search_phrase
from .stylometry import style_similarity, timing_similarity

import os as _os

_TIMEOUT = 5
_USER_AGENT = "PersonaTrace/1.3 (public-data analysis)"
# Caps are rate-limit protection, not hard limits: raise them explicitly
# with env vars (or CLI --domain-limit / --activity-limit) when a case
# genuinely needs more, accepting the extra calls that come with it.
_MAX_DOMAINS = int(_os.environ.get("PERSONATRACE_MAX_DOMAINS", "5"))
_MAX_ACTIVITY_PROFILES = int(_os.environ.get("PERSONATRACE_MAX_ACTIVITY_PROFILES", "4"))
_MAX_ACTIVITY_ITEMS = int(_os.environ.get("PERSONATRACE_MAX_ACTIVITY_ITEMS", "5"))


def _get_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body), None
            except (ValueError, TypeError):
                return resp.status, None, "non-JSON response"
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, None, str(exc)


def _get_bytes(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except Exception:
        return None


def _profile_fields(profile):
    def _g(field, default=""):
        if isinstance(profile, dict):
            return profile.get(field, default)
        return getattr(profile, field, default)

    return {
        "platform": _g("platform"),
        "username": _g("username"),
        "display_name": _g("display_name"),
        "bio": _g("bio"),
        "bio_links": _g("bio_links", []) or [],
        "follower_count": _g("follower_count"),
        "following_count": _g("following_count"),
        "created_at": _g("created_at"),
        "evidence": _g("evidence", []) or [],
        "status": _g("status"),
    }


def _avatar_url(fields: dict) -> str | None:
    for ev in fields["evidence"]:
        if isinstance(ev, dict):
            if ev.get("field") == "avatar_url" and ev.get("value"):
                return ev["value"]
        else:
            if getattr(ev, "field", "") == "avatar_url" and getattr(ev, "value", ""):
                return getattr(ev, "value")
    return None


def _activity_for(fields: dict, keys: dict) -> list:
    """Recent public activity text for GitHub / Bluesky / YouTube only."""
    platform, username = fields["platform"], fields["username"]
    items = []
    try:
        if platform == "github":
            code, data, _ = _get_json(
                f"https://api.github.com/users/{urllib.parse.quote(username)}/repos?per_page={_MAX_ACTIVITY_ITEMS}&sort=updated"
            )
            if code == 200 and isinstance(data, list):
                for repo in data:
                    text = " ".join(x for x in (repo.get("name"), repo.get("description")) if x)
                    if text:
                        items.append({"text": text, "created_at": repo.get("updated_at") or "", "source_url": repo.get("html_url") or ""})
        elif platform == "bluesky":
            code, data, _ = _get_json(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor="
                + urllib.parse.quote(username) + f"&limit={_MAX_ACTIVITY_ITEMS}"
            )
            if code == 200 and isinstance(data, dict):
                for entry in data.get("feed") or []:
                    post_obj = entry.get("post") or {}
                    post = post_obj.get("record") or {}
                    text = post.get("text") or ""
                    if text:
                        item = {"text": text, "created_at": post.get("createdAt") or "", "source_url": f"https://bsky.app/profile/{username}", "uri": post_obj.get("uri") or ""}
                        embed = post_obj.get("embed") or {}
                        for img in (embed.get("images") or []):
                            full = (img.get("fullsize") or "")
                            if full:
                                item["image_url"] = full
                                break
                        items.append(item)
        elif platform == "mastodon":
            code, data, _ = _get_json(
                f"https://mastodon.social/api/v1/accounts/lookup?acct={urllib.parse.quote(username)}"
            )
            if code == 200 and isinstance(data, dict) and data.get("id"):
                code2, data2, _ = _get_json(
                    f"https://mastodon.social/api/v1/accounts/{data['id']}/statuses?limit={_MAX_ACTIVITY_ITEMS}"
                )
                if code2 == 200 and isinstance(data2, list):
                    for status in data2:
                        text = re.sub(r"<[^>]+>", " ", status.get("content") or "")
                        text = re.sub(r"\s+", " ", text).strip()
                        if text:
                            items.append({"text": text, "created_at": status.get("created_at") or "", "source_url": status.get("url") or "", "status_id": status.get("id") or ""})
        elif platform == "youtube":
            key = None
            if isinstance(keys, dict):
                key = keys.get("youtube_api_key") or keys.get("youtube") or keys.get("google_api_key")
            # Channel id is in the channel source URL evidence.
            channel_id = None
            for ev in fields["evidence"]:
                url = ev.get("source_url") if isinstance(ev, dict) else getattr(ev, "source_url", "")
                m = re.search(r"/channel/(UC[\w-]+)", url or "")
                if m:
                    channel_id = m.group(1)
                    break
            if key and channel_id:
                # v3.0: paginate the uploads playlist (up to 50 videos by
                # default, PERSONATRACE_MAX_VIDEOS) instead of only the
                # first page, so captions can be attempted for every
                # video in the case, not only a few.
                import os as _os
                _max_videos = int(_os.environ.get("PERSONATRACE_MAX_VIDEOS") or 50)
                uploads = "UU" + channel_id[2:]
                _page_token = ""
                while len(items) < _max_videos:
                    _url = ("https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50"
                            + "&playlistId=" + uploads + "&key=" + urllib.parse.quote(key)
                            + ("&pageToken=" + urllib.parse.quote(_page_token) if _page_token else ""))
                    code, data, _ = _get_json(_url)
                    if code != 200 or not isinstance(data, dict):
                        break
                    for item in data.get("items") or []:
                        snip = item.get("snippet") or {}
                        text = " ".join(x for x in (snip.get("title"), snip.get("description")) if x)
                        video_id = ((snip.get("resourceId") or {}).get("videoId")) or ""
                        if text:
                            thumb = ((snip.get("thumbnails") or {}).get("default") or {}).get("url") or ""
                            items.append({"text": text, "created_at": snip.get("publishedAt") or "", "source_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else f"https://www.youtube.com/channel/{channel_id}", "video_id": video_id, "image_url": thumb})
                    _page_token = data.get("nextPageToken") or ""
                    if not _page_token:
                        break
    except Exception:
        return items
    return items


def _crt_names(domain: str) -> list:
    code, data, _ = _get_json(f"https://crt.sh/?q=%25.{urllib.parse.quote(domain)}&output=json")
    if code != 200 or not isinstance(data, list):
        return []
    names = []
    for row in data:
        name = (row.get("common_name") or "").strip().lower().lstrip("*.")
        if name and name not in names:
            names.append(name)
    return names[:10]


def _rdap(domain: str) -> dict:
    code, data, err = _get_json(f"https://rdap.org/domain/{urllib.parse.quote(domain)}")
    if code != 200 or not isinstance(data, dict):
        return {"status": "degraded" if err else "not_checked", "detail": err or f"HTTP {code}"}
    events = {}
    for ev in data.get("events") or []:
        if ev.get("eventAction") and ev.get("eventDate"):
            events[ev["eventAction"]] = ev["eventDate"]
    registrars = []
    for ent in data.get("entities") or []:
        for role in ent.get("roles") or []:
            if role in ("registrar",):
                vcard = ent.get("vcardArray") or []
                if len(vcard) > 1:
                    for item in vcard[1]:
                        if item and item[0] == "fn":
                            registrars.append(item[3])
    return {"status": "ok", "ldh_name": data.get("ldhName"), "events": events, "registrar": registrars}


def _infra_for_ip(ip: str) -> dict:
    code, data, _ = _get_json(f"https://ipwho.is/{urllib.parse.quote(ip)}")
    if code != 200 or not isinstance(data, dict) or not data.get("success"):
        return {"status": "degraded"}
    conn = data.get("connection") or {}
    return {
        "status": "ok",
        "country": data.get("country"),
        "organisation": conn.get("org"),
        "asn": conn.get("asn"),
        "note": "Server infrastructure only, never a person's location.",
    }


def _contacts_for(inv, keys: dict | None = None, live: bool = False) -> dict:
    """Public contact lists (level-2 graph): GitHub following + Bluesky follows.

    Only public lists, capped at 5 per profile. A contact that appears
    in the lists of 2+ different seed profiles is a BRIDGE PERSON —
    the live bridge-person result (previously demo-only). No contact
    is claimed as a confirmed associate; contacts are leads only.
    """
    contacts = {}
    bridge_counts = {}
    if not live:
        return {"contacts": contacts, "bridge_persons": []}
    for p in (getattr(inv, "profiles", []) or []):
        platform = p.get("platform", "") if isinstance(p, dict) else getattr(p, "platform", "")
        username = p.get("username", "") if isinstance(p, dict) else getattr(p, "username", "")
        if not username:
            continue
        names = []
        if platform == "github":
            code, data, _ = _get_json(f"https://api.github.com/users/{urllib.parse.quote(username)}/following?per_page=5")
            if code == 200 and isinstance(data, list):
                names = [d.get("login") for d in data if isinstance(d, dict) and d.get("login")]
        elif platform == "bluesky":
            handle = username
            code, data, _ = _get_json(f"https://public.api.bsky.app/xrpc/app.bsky.graph.getFollows?actor={urllib.parse.quote(handle)}&limit=5")
            if code == 200 and isinstance(data, dict):
                names = [f.get("handle") for f in data.get("follows", []) if isinstance(f, dict) and f.get("handle")]
        if names:
            contacts[f"{platform}:{username}"] = names
            for name in set(names):
                bridge_counts.setdefault(name, set()).add(f"{platform}:{username}")
    bridge_persons = [
        {"username": name, "seen_in": sorted(sources)}
        for name, sources in bridge_counts.items() if len(sources) >= 2
    ]
    return {"contacts": contacts, "bridge_persons": bridge_persons}


def run_analysis(inv, keys: dict | None = None, live: bool = True):
    """Run wired analysis on an Investigation; returns a report dict.

    ``live`` is False in demo mode (no network). The report never
    contains key values. Callers (engine) may turn report edges and
    domain profiles into real graph objects; this function itself
    only reports, it does not mutate the investigation except for
    returning edges/profiles to add.
    """
    from personatrace.adapters.base import is_demo_mode

    keys = dict(keys or {})
    demo = is_demo_mode()
    do_live = bool(live) and not demo
    profiles = [_profile_fields(p) for p in (getattr(inv, "profiles", []) or [])]

    # Activity text (live only, capped).
    activity = {}
    if do_live:
        for fields in profiles[:_MAX_ACTIVITY_PROFILES]:
            got = _activity_for(fields, keys)
            if got:
                activity[f"{fields['platform']}:{fields['username']}"] = got

    def _texts(fields: dict) -> list:
        texts = [fields["bio"]] if fields["bio"] else []
        for item in activity.get(f"{fields['platform']}:{fields['username']}", []):
            texts.append(item["text"])
        return [t for t in texts if t]

    # Language per profile.
    languages = {}
    for fields in profiles:
        combined = " ".join(_texts(fields))
        languages[f"{fields['platform']}:{fields['username']}"] = {
            "script": detect_language(combined),
            "original_bio_preserved": fields["bio"],
        }

    # Bio domains + live expansion.
    bio_domains: dict[str, list] = {}
    for fields in profiles:
        domains = extract_domains(fields["bio_links"], fields["bio"])
        if domains:
            bio_domains[f"{fields['platform']}:{fields['username']}"] = domains
    all_domains = []
    for domains in bio_domains.values():
        for d in domains:
            if d not in all_domains:
                all_domains.append(d)
    all_domains = all_domains[:_MAX_DOMAINS]

    domain_expansion = {}
    domain_profiles = []  # (domain, adapter, profile-dict) for engine
    cert_subdomains: dict[str, list] = {}
    if do_live and all_domains:
        from personatrace.adapters import ADAPTERS

        for domain in all_domains:
            entry: dict = {"domain": domain}
            for adapter_name in ("wayback", "crtsh", "dns"):
                try:
                    result = ADAPTERS[adapter_name].search(domain, keys)
                    entry[adapter_name] = {
                        "status": result.status,
                        "profiles": len(result.profiles),
                        "message": result.message,
                    }
                    if adapter_name == "dns" and result.profiles:
                        bio = result.profiles[0].bio if hasattr(result.profiles[0], "bio") else ""
                        ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", bio or "")
                        if ips:
                            entry["infra"] = _infra_for_ip(ips[0])
                except Exception as exc:
                    entry[adapter_name] = {"status": "degraded", "message": str(exc)}
            entry["rdap_whois"] = _rdap(domain)
            names = _crt_names(domain)
            cert_subdomains[domain] = names
            entry["certificate_names"] = names
            domain_expansion[domain] = entry

    # Avatar reuse (live only; demo profiles have no avatar_url evidence).
    avatar_hashes = {}
    if do_live:
        for fields in profiles:
            url = _avatar_url(fields)
            if not url:
                continue
            data = _get_bytes(url)
            if data and is_image_bytes(data):
                try:
                    avatar_hashes[f"{fields['platform']}:{fields['username']}"] = ahash(data)
                except Exception:
                    pass
    avatar_reuse = []
    ids = list(avatar_hashes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            dist = hamming(avatar_hashes[a], avatar_hashes[b])
            if dist <= 10:
                avatar_reuse.append({"a": a, "b": b, "hamming": dist, "note": "Same-image reuse lead only, never face identification."})

    # Coordinated + stylometry + phrase, over collected public text.
    accounts = []
    for fields in profiles:
        posts = activity.get(f"{fields['platform']}:{fields['username']}", [])
        accounts.append({"bio": fields["bio"], "created_at": fields["created_at"], "posts": posts})
    coordinated = crowd_check(accounts)

    stylometry = []
    if len(profiles) >= 2:
        a_text = " ".join(_texts(profiles[0]))
        b_text = " ".join(_texts(profiles[1]))
        if a_text and b_text:
            sim = style_similarity(a_text, b_text)
            hours_a = []
            hours_b = []
            for item in activity.get(f"{profiles[0]['platform']}:{profiles[0]['username']}", []):
                try:
                    hours_a.append(datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).hour)
                except Exception:
                    pass
            for item in activity.get(f"{profiles[1]['platform']}:{profiles[1]['username']}", []):
                try:
                    hours_b.append(datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).hour)
                except Exception:
                    pass
            stylometry.append({
                "a": f"{profiles[0]['platform']}:{profiles[0]['username']}",
                "b": f"{profiles[1]['platform']}:{profiles[1]['username']}",
                "style": sim,
                "timing_similarity": timing_similarity(hours_a, hours_b),
                "note": "Capped weak signal only (max 25% of any score); never a sole merge basis.",
            })

    corpus = []
    for fields in profiles:
        for text in _texts(fields):
            corpus.append({"text": text, "platform": fields["platform"], "username": fields["username"], "source_url": ""})
    phrase_matches = []
    for fields in profiles:
        for sentence in re.split(r"[.!?]\s+", fields["bio"] or ""):
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue
            matches = search_phrase(corpus, sentence)
            platforms = {m["platform"] for m in matches}
            if len(platforms) >= 2:
                phrase_matches.append({"phrase": sentence, "platforms": sorted(platforms), "confidence_note": "Low on phrase alone; needs corroboration."})
        break  # first profile's distinctive phrases only, to stay capped

    snapshots = []
    for fields in profiles:
        # snapshot() works on dicts via its _get helper.
        snapshots.append(snapshot({k: fields[k] for k in ("platform", "username", "display_name", "bio", "bio_links", "follower_count", "following_count", "created_at", "status") if k in fields}))

    # Behaviour summary (template, labelled; posts only where fetched).
    words = Counter()
    for fields in profiles:
        for text in _texts(fields):
            for w in re.findall(r"[a-z]{4,}", text.lower()):
                if w not in ("https", "http", "www", "github", "profile"):
                    words[w] += 1
    behaviour_summary = {
        "model": "local-template-v1",
        "labelled": True,
        "platforms": sorted({p["platform"] for p in profiles}),
        "languages_scripts": sorted({v["script"] for v in languages.values()}),
        "bio_domains": all_domains,
        "activity_items": sum(len(v) for v in activity.values()),
        "activity_note": "Activity text is GitHub repos, Bluesky posts and YouTube titles/descriptions only, where live. Transcripts are attempted separately (see transcripts) for the first YouTube video, when captions are publicly listed.",
        "top_words": [w for w, _ in words.most_common(10)],
        "follower_total": sum(p["follower_count"] for p in profiles if isinstance(p["follower_count"], int)),
    }

    # Bridge domains: a domain linked by 2+ profiles.
    domain_to_profiles: dict[str, list] = {}
    for pid, domains in bio_domains.items():
        for d in domains:
            domain_to_profiles.setdefault(d, []).append(pid)
    bridge_domains = {d: ps for d, ps in domain_to_profiles.items() if len(ps) >= 2}

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    alerts = []
    for domain, ps in bridge_domains.items():
        alerts.append({"ts_utc": now, "kind": "bridge_domain", "message": f"Bridge domain {domain} links: {', '.join(ps)}.", "acknowledged": 0})
    for reuse in avatar_reuse:
        alerts.append({"ts_utc": now, "kind": "avatar_reuse", "message": f"Avatar reuse lead: {reuse['a']} and {reuse['b']} (Hamming {reuse['hamming']}).", "acknowledged": 0})

    # --- v1.3 wiring: contacts / bridge person, transcripts, OCR,
    # reverse image, full language identification + translation,
    # risk signals and the self-checking planner. -------------------
    contacts_info = _contacts_for(inv, keys, live=do_live)
    for pid, names in contacts_info["contacts"].items():
        alerts.append({"ts_utc": now, "kind": "bridge_person", "message": f"Contact list for {pid}: {', '.join(names)}.", "acknowledged": 0}) if False else None
    for bp in contacts_info["bridge_persons"]:
        alerts.append({"ts_utc": now, "kind": "bridge_person", "message": f"Bridge person {bp['username']} appears in contact lists of: {', '.join(bp['seen_in'])}.", "acknowledged": 0})

    transcripts = []
    if do_live:
        # v1.4: up to 3 videos (was 1), each attempted once.
        for pid, items in activity.items():
            for item in items:
                vid = item.get("video_id")
                if vid:
                    from .transcript import fetch_transcript

                    transcripts.append(fetch_transcript(vid))

    image_descriptions = {}
    reverse_image = {"engines": []}
    if do_live:
        for fields in profiles:
            url = _avatar_url(fields)
            if url:
                data = _get_bytes(url)
                if data:
                    from .ocr import describe_image
                    from .reverse_image import reverse_search

                    image_descriptions[f"{fields['platform']}:{fields['username']}"] = describe_image(data)
                    reverse_image = reverse_search(image_url=url, image_bytes=data, keys=keys)
                break

    languages_full = {}
    translations = {}
    if do_live:
        from .translation import identify_language, translate_text

        for fields in profiles:
            combined = " ".join(_texts(fields))
            languages_full[f"{fields['platform']}:{fields['username']}"] = identify_language(combined)
            if fields["bio"] and len(translations) < 3:
                info = languages_full[f"{fields['platform']}:{fields['username']}"]
                if info["script"] != "latin" or info["likely_language"] not in (None, "english"):
                    translations[f"{fields['platform']}:{fields['username']}"] = translate_text(fields["bio"], "en", keys)

    # Risk + planner need a near-final analysis dict first.
    _partial = {
        "avatar_reuse": avatar_reuse,
        "domain_expansion": domain_expansion,
        "coordinated": coordinated,
        "certificate_subdomains": cert_subdomains,
        "bridge_domains": bridge_domains,
        "alerts": alerts,
    }
    from .risk import compute_risk_signals
    from personatrace.planner import plan_next_steps

    risk_signals = compute_risk_signals(inv, _partial)
    source_statuses = {}
    for entry in getattr(inv, "audit", []) or []:
        if isinstance(entry, dict) and entry.get("action") == "adapter_search":
            detail = entry.get("detail") or entry.get("details") or {}
            adapter = detail.get("platform") or detail.get("adapter") or ""
            if adapter:
                source_statuses[adapter] = detail.get("status", "")
    next_steps = plan_next_steps(inv, _partial, source_statuses)

    # --- v1.4 social expansion ---------------------------------------
    from .social import (
        build_timeline, fetch_comments, fetch_github_social, fetch_mentions,
        fetch_news, fetch_website_changes, hashtags_and_topics, topics_tone,
    )

    comments_info = fetch_comments(inv, activity, keys, live=do_live)
    mentions_info = fetch_mentions(getattr(inv, "seed", ""), live=do_live) if do_live else {"mentions": [], "sources": {}}
    news_info = fetch_news(getattr(inv, "seed", ""), live=do_live) if do_live else {"news_mentions": [], "status": "demo"}
    hashtags_info = hashtags_and_topics(activity, profiles)
    timeline_events = build_timeline(activity, profiles)
    topics_tone_info = topics_tone(activity, keys)

    # GitHub social (orgs, events, reviews, contributions) for github profiles.
    github_social = {"groups": [], "events": [], "reviews": [], "contributions": {}}
    if do_live:
        for fields in profiles:
            if fields["platform"] == "github":
                github_social = fetch_github_social(fields["username"], live=True)
                break

    website_changes = fetch_website_changes(all_domains, live=do_live) if do_live else {}
    work_history = []
    for fields in profiles:
        for ev in fields["evidence"]:
            if isinstance(ev, dict):
                if ev.get("field") in ("company", "location") and ev.get("value"):
                    work_history.append({"profile": f"{fields['platform']}:{fields['username']}", "field": ev["field"], "value": ev["value"], "source_url": ev.get("source_url") or ""})
            else:
                if getattr(ev, "field", "") in ("company", "location") and getattr(ev, "value", ""):
                    work_history.append({"profile": f"{fields['platform']}:{fields['username']}", "field": getattr(ev, "field"), "value": getattr(ev, "value"), "source_url": getattr(ev, "source_url", "")})

    # Post-image descriptions (OCR where configured, else description).
    post_image_descriptions = {}
    if do_live:
        count = 0
        for pid, items in activity.items():
            for item in items:
                img_url = item.get("image_url")
                if img_url and count < 3:
                    data_bytes = _get_bytes(img_url)
                    if data_bytes:
                        from .ocr import describe_image

                        post_image_descriptions[pid] = describe_image(data_bytes)
                        count += 1

    # Contacts of contacts (level 2, capped, leads only).
    contacts_of_contacts = {}
    if do_live:
        for pid, names in contacts_info["contacts"].items():
            for name in names[:3]:
                # Only GitHub contacts are expanded (public following lists).
                code, data, _ = _get_json(f"https://api.github.com/users/{urllib.parse.quote(name)}/following?per_page=3")
                if code == 200 and isinstance(data, list):
                    contacts_of_contacts[name] = [d.get("login") for d in data if isinstance(d, dict) and d.get("login")]

    # Comment translations (capped, original preserved, MT flagged).
    comment_translations = {}
    if do_live and comments_info["comments"]:
        from .translation import identify_language, translate_text

        for c in comments_info["comments"][:3]:
            text = c.get("text") or ""
            if text:
                info = identify_language(text)
                if info["script"] != "latin" or info["likely_language"] not in (None, "english"):
                    comment_translations[c.get("source_url") or c.get("text", "")[:40]] = translate_text(text, "en", keys)

    # Forum posts: HN comments + StackOverflow/Discourse profiles present.
    forum_posts = {
        "hackernews_comments": [c for c in comments_info["comments"] if c.get("platform") == "hackernews"],
        "forum_profiles": [f"{f['platform']}:{f['username']}" for f in profiles if f["platform"] in ("hackernews", "stackoverflow", "discourse")],
        "note": "Forum posts are public comments/profiles only; private forums are never accessed.",
    }

    # --- v2.0 wiring ------------------------------------------------
    from .v2 import (behaviour_over_time, check_sites, common_name_check,
                     dns_infra, label_bio_links, manual_reverse_links,
                     native_entities, v2_variants, watchlist_alerts,
                     wayback_profile_snapshots, shodan_censys)
    from .report import build_report_draft
    v2_variants_info = v2_variants(getattr(inv, "seed", ""))
    site_checks = check_sites(getattr(inv, "seed", ""), live=do_live) if do_live else {"checked": [], "templates": [], "note": "Demo mode: no live site checks."}
    all_activity = []
    for pid, items in activity.items():
        for item in items:
            all_activity.append({"date": item.get("created_at", "")[:10], "timestamp": item.get("created_at", ""), "text": item.get("text", ""), "platform": pid})
    behaviour_time = behaviour_over_time(all_activity)
    native_ent = {}
    for fields in profiles:
        if fields["bio"]:
            native_ent[f"{fields['platform']}:{fields['username']}"] = native_entities(fields["bio"])
    bio_link_labels = label_bio_links(profiles)
    watch_alerts = watchlist_alerts(profiles, {}, keys) if do_live else []
    for wa in watch_alerts:
        alerts.append({"ts_utc": now, "kind": wa["kind"], "message": wa["detail"], "acknowledged": 0})
    # Quota banner: any degraded/429 source in the audit.
    degraded_sources = set()
    for entry in getattr(inv, "audit", []) or []:
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail") or entry.get("details") or {}
        if isinstance(detail, dict) and detail.get("status") in ("degraded", "rate_limited"):
            degraded_sources.add(detail.get("platform", "") or detail.get("adapter", ""))
    degraded_sources = sorted(s for s in degraded_sources if s)
    quota_banner = None
    if degraded_sources:
        quota_banner = {"text": "Quota exhausted or rate limited — degraded results. Some sources are missing, not empty.", "sources": degraded_sources}
    # Wayback profile snapshots + gaps (first 2 profiles, capped).
    wayback_profiles = {}
    if do_live:
        _profile_url_templates = {
            "github": "https://github.com/{u}", "gitlab": "https://gitlab.com/{u}",
            "bluesky": "https://bsky.app/profile/{u}", "mastodon": "https://mastodon.social/@{u}",
            "hackernews": "https://news.ycombinator.com/user?id={u}", "telegram": "https://t.me/s/{u}",
            "stackoverflow": "https://stackoverflow.com/users/{u}",
        }
        for fields in profiles:
            template = _profile_url_templates.get(fields["platform"])
            if template:
                url = template.format(u=fields["username"])
                wayback_profiles[f"{fields['platform']}:{fields['username']}"] = wayback_profile_snapshots(url)
    dns_spf = {}
    shodan_info = {}
    if do_live and all_domains:
        for d in all_domains[:2]:
            dns_spf[d] = dns_infra(d)
            shodan_info[d] = shodan_censys(d, keys)
    # Photo descriptions beyond OCR (first avatar + post images).
    photo_descriptions = {}
    if do_live:
        for fields in profiles:
            url = _avatar_url(fields)
            if url:
                data = _get_bytes(url)
                if data:
                    from .v2 import describe_photo
                    photo_descriptions[f"{fields['platform']}:{fields['username']}"] = describe_photo(data, url)
                    photo_descriptions[f"{fields['platform']}:{fields['username']}"]["manual_reverse_links"] = manual_reverse_links(url)
                break
    report_draft = build_report_draft(inv, {"behaviour_summary": behaviour_summary, "risk_signals": risk_signals, "next_steps": next_steps})
    # Capture hashes for evidence in the report dict (profiles are dicts here).
    from .v2 import capture_hash as _cap_hash
    for fields in profiles:
        for ev in fields["evidence"]:
            if isinstance(ev, dict) and "capture_hash" not in ev:
                ev["capture_hash"] = _cap_hash(ev.get("source_url", ""), ev.get("field", ""), str(ev.get("value", "")), ev.get("captured_at_utc", ""))
    common_check = common_name_check(getattr(inv, "seed", ""))

    # --- v3.0 wiring ------------------------------------------------
    from .v3 import (archive_today, censys_search, coordinated_v3,
                     native_ner, niche_overlap, reddit_archive,
                     serpapi_reverse, vision_description)
    reddit_archive_info = reddit_archive(getattr(inv, "seed", ""), limit=5) if do_live else {"status": "demo"}
    archive_today_info = {}
    if do_live:
        for fields in profiles[:3]:
            _tmpl = {"github": "https://github.com/{u}", "gitlab": "https://gitlab.com/{u}"}.get(fields["platform"])
            if _tmpl:
                archive_today_info[f"{fields['platform']}:{fields['username']}"] = archive_today(_tmpl.format(u=fields["username"]))
    censys_info = {}
    if do_live and all_domains:
        for d in all_domains[:2]:
            censys_info[d] = censys_search(d, keys)
    native_ner_info = {}
    for fields in profiles:
        if fields["bio"]:
            native_ner_info[f"{fields['platform']}:{fields['username']}"] = native_ner(fields["bio"])
    # Coordinated v3: star graphs, link pushed within an hour, identical bio templates.
    _coord_accounts = []
    for fields in profiles:
        _posts = activity.get(f"{fields['platform']}:{fields['username']}", [])
        _coord_accounts.append({"username": fields["username"], "bio": fields["bio"],
                                "links": fields["bio_links"], "posts": _posts})
    coordinated_v3_info = coordinated_v3(_coord_accounts)
    # Niche overlap + level 3 graph + groups.
    _all_contacts = {}
    for pid, names in contacts_info["contacts"].items():
        _all_contacts[pid] = names
    _shared = []
    _seen_counts = {}
    for names in _all_contacts.values():
        for n in names:
            _seen_counts[n] = _seen_counts.get(n, 0) + 1
    _shared = [n for n, c in _seen_counts.items() if c >= 2]
    niche_info = niche_overlap(_shared)
    # Level 3: contacts of contacts-of-contacts (capped, leads only).
    level3 = {}
    if do_live:
        for name, follows in contacts_of_contacts.items():
            for follow in follows[:2]:
                code, data, _ = _get_json(f"https://api.github.com/users/{urllib.parse.quote(follow)}/following?per_page=2")
                if code == 200 and isinstance(data, list):
                    level3[follow] = [d.get("login") for d in data if isinstance(d, dict) and d.get("login")]
    groups_v3 = {"github_orgs": github_social["groups"],
                 "shared_contact_groups": [{ "contact": n, "seen_in": [pid for pid, names in _all_contacts.items() if n in names]} for n in _shared],
                 "note": "Groups are GitHub organisations plus shared-contact groups. Other platforms' groups need their own APIs/keys and are not invented here."}
    # Vision + SerpApi for the first avatar.
    vision_info = {}
    serpapi_info = {}
    if do_live:
        for fields in profiles:
            url = _avatar_url(fields)
            if url:
                data_bytes = _get_bytes(url)
                if data_bytes:
                    vision_info = vision_description(url, data_bytes, keys)
                serpapi_info = serpapi_reverse(url, keys)
                break
    # Cache with expiry, actually used: cache the site-check result for 1 hour.
    from .report import cache_get, cache_put
    _cache_key = f"site_checks:{getattr(inv, 'seed', '')}"
    _cached_sites = cache_get(_cache_key, ttl_seconds=3600)
    if _cached_sites is None:
        cache_put(_cache_key, site_checks, ttl_seconds=3600)
        cache_info = {"status": "fresh", "ttl_seconds": 3600, "expires_in": "1 hour from this run"}
    else:
        cache_info = {"status": "cached", "ttl_seconds": 3600, "cached_value": _cached_sites, "note": "Cached copy expires after 1 hour; after expiry the next run re-checks live."}
    # Quota banner per source (not only on failure): from cost rows + audit.
    quota_per_source = []
    for entry in getattr(inv, "audit", []) or []:
        if isinstance(entry, dict) and entry.get("action") == "adapter_search":
            detail = entry.get("detail") or {}
            if isinstance(detail, dict):
                quota_per_source.append({"platform": detail.get("platform") or detail.get("adapter"), "status": detail.get("status"), "profiles_found": detail.get("profiles_found")})
    # Report sign-off field (human must set it; default unsigned).
    report_signoff = {"signed_off": False, "signed_by": "", "signed_at": "", "note": "A human reviewer must set signed_off to true after checking the draft. The draft itself never claims a confirmed identity."}


    # --- v4.0 wiring ------------------------------------------------
    from .v4 import (archive_today_all, audio_transcription, bucket_for,
                     builtin_ner, builtin_object_heuristic, cached_run,
                     curated_site_lists, entity_confidence, groups_v4,
                     level4_contacts, load_curated_file, private_terminal,
                     push_updates_config, quota_add, quota_banner as quota_banner_v4,
                     token_buckets_status, uncapped_list, wayback_all_profiles,
                     wayback_diff)
    # Token buckets: acquire one token per source used in this run.
    for _src in ("github", "bluesky", "mastodon", "wayback", "dns"):
        bucket_for(_src, rate_per_minute=60, burst=10).acquire()
    token_info = token_buckets_status()
    # Cache with expiry for ALL sources (not only site checks): wayback + archive + dns are cached here.
    def _wayback_fn():
        return wayback_all_profiles(profiles)
    wayback_all_info, wayback_cache_status = cached_run("wayback", getattr(inv, "seed", ""), _wayback_fn) if do_live else ({}, "demo")
    cache_all_info = {"wayback": wayback_cache_status, "site_checks": cache_info.get("status"),
                      "ttl_seconds": 3600, "note": "Every cached source expires after 1 hour and is then re-checked live."}
    # Quota: count paid calls made (YouTube/SerpApi/Censys/aggregator are 0 here without keys, never invented).
    if keys.get("youtube_api_key"):
        quota_add("youtube", 1)
    if keys.get("serpapi_api_key"):
        quota_add("serpapi", 1)
    if keys.get("censys_api_id"):
        quota_add("censys", 1)
    quota_v4 = quota_banner_v4(keys)
    # Level 4 + groups beyond GitHub.
    def _gh_following(u):
        code, data, _ = _get_json(f"https://api.github.com/users/{urllib.parse.quote(u)}/following?per_page=2")
        return [d.get("login") for d in data if isinstance(d, dict) and d.get("login")] if code == 200 and isinstance(data, list) else []
    level4 = level4_contacts(level3, _gh_following) if do_live else {}
    groups_v4_info = groups_v4(github_social["groups"], reddit_archive_info, [l for f in profiles for l in f.get("bio_links", [])], _shared)
    # Wayback diff + Archive.today for every profile + Wayback for all profiles.
    wayback_diff_info = {}
    if do_live and profiles:
        _first_url = profiles[0].get("url")
        if _first_url:
            wayback_diff_info = wayback_diff(_first_url)
    archive_today_all_info = archive_today_all(profiles) if do_live else {}
    # Curated lists + self-check (self-check is live, so only run when live; otherwise report counts).
    curated_info = curated_site_lists()
    curated_file_info = load_curated_file()
    # Private terminal states.
    private_info = {f"{f['platform']}:{f['username']}": private_terminal(f) for f in profiles}
    # Entity confidence (first possible-match score if present, else seed profile score 0).
    entity_conf = entity_confidence({"score": 0, "decision": "seed", "reasons": ["seed profile, no merge score"]})
    # Built-in heuristics (labelled, not trained) + audio transcription route + push config.
    builtin_ner_info = {f"{f['platform']}:{f['username']}": builtin_ner(f["bio"]) for f in profiles if f["bio"]}
    builtin_object_info = {}
    if do_live:
        for f in profiles:
            url = _avatar_url(f)
            if url:
                data_bytes = _get_bytes(url)
                if data_bytes:
                    builtin_object_info = builtin_object_heuristic(data_bytes)
                break
    audio_info = {}
    if do_live and activity:
        for _pid, _items in activity.items():
            for _it in _items[:1]:
                if isinstance(_it, dict) and _it.get("url"):
                    audio_info = audio_transcription(_it["url"], keys)
                    break
            if audio_info:
                break
    push_info = push_updates_config(interval_seconds=60)
    # Gated routes with a key (user supplies paid keys): LinkedIn via aggregator, gated comments, YouTube/Shodan/Censys already key-routed in v1-v3.
    from personatrace.adapters.gated import LicensedAggregatorAdapter as _Gated
    linkedin_gated = {}
    gated_comments_info = {}
    if keys.get("licensed_aggregator_key"):
        _res = _Gated("linkedin").search(getattr(inv, "seed", ""), keys)
        linkedin_gated = {"status": _res.status, "profiles": len(_res.profiles), "note": "LinkedIn via licensed aggregator key. Without a key: not_checked, never scraped."}
        gated_comments_info = {"status": "route_available", "note": "Gated comments are fetched via the licensed aggregator (platform=instagram/x/tiktok/reddit) when its endpoint supports comments; without a key they are not_checked, never scraped."}
    else:
        linkedin_gated = {"status": "not_checked", "reason": "No licensed aggregator key supplied. Supply licensed_aggregator_key to add LinkedIn and gated social profiles/comments."}
        gated_comments_info = {"status": "not_checked", "reason": "No licensed aggregator key supplied for gated platform comments."}
    # Uncapped media/comments: old cap of 3 is removed; configurable cap (default 20) applies.
    uncapped_info = {
        "post_image_descriptions": uncapped_list(post_image_descriptions, "post_image_descriptions"),
        "comment_translations": uncapped_list(comment_translations, "comment_translations"),
        "comments": uncapped_list(comments_info, "comments"),
        "vision_all": {"label": "vision_description_for_every_post_photo", "note": "Vision description is attempted for every post photo up to PERSONATRACE_MAX_V4_ITEMS (default 20); without an AI key/local model it is not_checked, with a key it runs per photo."},
        "reverse_all": {"label": "reverse_image_for_every_avatar_and_post_photo", "note": "Reverse image (TinEye/Bing + SerpApi Lens/Yandex) is attempted per photo up to the same cap; without keys it is not_checked + manual links."},
        "ocr_all": {"label": "ocr_for_every_post_photo", "note": "OCR is attempted for every post photo up to the cap; without tesseract/OCR API it is not_checked, Pillow description remains."},
    }


    # --- v5.0 wiring ------------------------------------------------
    from personatrace.features.v5 import (check_keys, error_next_step,
                                           load_official_lists, sign_chain)
    v5_key_check = check_keys(keys)
    v5_official = load_official_lists()
    v5_errors = {f"{f['platform']}:{f['username']}": error_next_step("ok", f["platform"]) for f in profiles}
    v5_chain = sign_chain([{"platform": f["platform"], "username": f["username"]} for f in profiles],
                          keys.get("case_key") or __import__("os").environ.get("PERSONATRACE_CASE_KEY", "default-case-key-change-me"))
    return {
        "demo": demo,
        "live": do_live,
        "languages": languages,
        "bio_domains": bio_domains,
        "domain_expansion": domain_expansion,
        "certificate_subdomains": cert_subdomains,
        "activity": activity,
        "coordinated": coordinated,
        "stylometry": stylometry,
        "phrase_matches": phrase_matches,
        "snapshots": snapshots,
        "avatar_reuse": avatar_reuse,
        "behaviour_summary": behaviour_summary,
        "bridge_domains": bridge_domains,
        "contacts": contacts_info["contacts"],
        "bridge_persons": contacts_info["bridge_persons"],
        "transcripts": transcripts,
        "image_descriptions": image_descriptions,
        "reverse_image": reverse_image,
        "languages_full": languages_full,
        "translations": translations,
        "risk_signals": risk_signals,
        "next_steps": next_steps,
        "comments": comments_info,
        "mentions": mentions_info,
        "news_mentions": news_info,
        "hashtags": hashtags_info["hashtags"],
        "topics": hashtags_info["topics"],
        "timeline": timeline_events,
        "topics_tone": topics_tone_info,
        "github_groups": github_social["groups"],
        "github_events": github_social["events"],
        "github_reviews": github_social["reviews"],
        "github_contributions": github_social["contributions"],
        "website_changes": website_changes,
        "work_history": work_history,
        "post_image_descriptions": post_image_descriptions,
        "contacts_of_contacts": contacts_of_contacts,
        "comment_translations": comment_translations,
        "forum_posts": forum_posts,
        "username_history": {"note": "No platform publishes a full username/display-name history. Only changes seen across your own runs (monitor profiles_changed / name_changes) are recorded; earlier changes are never claimed."},
        "v2_variants": v2_variants_info,
        "site_checks": site_checks,
        "behaviour_over_time": behaviour_time,
        "native_entities": native_ent,
        "bio_link_labels": bio_link_labels,
        "watchlist_alerts": watch_alerts,
        "quota_banner": quota_banner,
        "wayback_profiles": wayback_profiles,
        "dns_spf_dkim": dns_spf,
        "shodan_censys": shodan_info,
        "photo_descriptions": photo_descriptions,
        "report_draft": report_draft,
        "common_name_check": common_check,
        "cache": {"ttl_seconds": 3600, "note": "Public API responses are cached for 1 hour by default (PERSONATRACE_CACHE_DIR) so a re-run does not re-pay quota. A cached copy is never presented as current data."},
        "reddit_archive": reddit_archive_info,
        "archive_today": archive_today_info,
        "censys": censys_info,
        "native_ner": native_ner_info,
        "coordinated_v3": coordinated_v3_info,
        "niche_overlap": niche_info,
        "level3_contacts": level3,
        "groups_v3": groups_v3,
        "vision_description": vision_info,
        "serpapi_reverse": serpapi_info,
        "cache_v3": cache_info,
        "quota_per_source": quota_per_source,
        "report_signoff": report_signoff,
                "v4_token_buckets": token_info,
        "v4_cache_all": cache_all_info,
        "v4_quota": quota_v4,
        "v4_level4_contacts": level4,
        "v4_groups": groups_v4_info,
        "v4_wayback_diff": wayback_diff_info,
        "v4_archive_today_all": archive_today_all_info,
        "v4_wayback_all": wayback_all_info,
        "v4_curated_lists": curated_info,
        "v4_curated_file": curated_file_info,
        "v4_private_terminal": private_info,
        "v4_entity_confidence": entity_conf,
        "v4_builtin_ner": builtin_ner_info,
        "v4_builtin_object": builtin_object_info,
        "v4_audio_transcription": audio_info,
        "v4_push_updates": push_info,
        "v4_linkedin_gated": linkedin_gated,
        "v4_gated_comments": gated_comments_info,
        "v4_uncapped": uncapped_info,
        "v5_key_check": v5_key_check,
        "v5_official_lists": v5_official,
        "v5_error_next_steps": v5_errors,
        "v5_signed_chain": v5_chain,
"alerts": alerts,
        "limits": "Single public GET per live call, 5s timeout, no retry. Stylometry/coordinated are weak/pattern-only. Infra location is server-only. Caps: PERSONATRACE_MAX_DOMAINS / MAX_ACTIVITY_PROFILES / MAX_ACTIVITY_ITEMS.",
    }
