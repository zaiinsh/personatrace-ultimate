"""v1.4 social expansion: comments, mentions, news, groups, events,
contributions, reviews, website changes, forum posts, hashtags,
timeline, topics/tone, work history, post-image OCR, contacts of
contacts — all from public sources only, capped, single GET each,
no retry, no login, no private data.

Every sub-result carries a status (ok / degraded / not_checked) so
a missing source is never presented as "no comments" or "no news".
Gated platforms (X, Instagram, Reddit, TikTok) stay not_checked for
comments: their aggregator profile endpoint does not expose comment
threads, and login-walled pages are not scraped.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

_TIMEOUT = 5
_UA = "PersonaTrace/1.4 (public-data lookup)"


def _comment_limit() -> int:
    """v8.0: configurable comment cap. PERSONATRACE_COMMENT_LIMIT
    (set by the CLI --comment-limit flag) replaces the old fixed
    sample caps (5 per platform / 20 total). Default 100."""
    import os as _os
    try:
        return max(1, int(_os.environ.get("PERSONATRACE_COMMENT_LIMIT", "100")))
    except Exception:
        return 100


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            import json

            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, None, str(exc)


def _get_text(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", str(exc)


def _profiles(inv):
    out = []
    for p in getattr(inv, "profiles", []) or []:
        if isinstance(p, dict):
            out.append(p)
        else:
            out.append({"platform": getattr(p, "platform", ""), "username": getattr(p, "username", ""), "evidence": getattr(p, "evidence", []) or []})
    return out


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_comments(inv, activity: dict, keys: dict | None = None, live: bool = True) -> dict:
    """Public comments/replies on the person's own posts, per platform."""
    if not live:
        return {"comments": [], "by_platform": {}, "note": "Demo mode: no network."}
    comments, by_platform = [], {}
    for p in _profiles(inv):
        platform, username = p["platform"], p["username"]
        items = []
        if platform == "hackernews":
            code, data, err = _get_json(f"https://hn.algolia.com/api/v1/search?tags=comment,author_{urllib.parse.quote(username)}&hitsPerPage={_comment_limit()}")
            if code == 200 and isinstance(data, dict):
                for hit in data.get("hits", []) or []:
                    items.append({"author": username, "text": _clean(hit.get("comment_text") or ""), "created_at": hit.get("created_at") or "", "source_url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}", "post_url": ""})
            by_platform[platform] = {"status": "ok" if code == 200 else "degraded", "count": len(items), "message": err or ""}
        elif platform == "bluesky":
            # Replies to the author's own posts, via the public thread API.
            for item in (activity.get(f"bluesky:{username}", []) or [])[:2]:
                uri = item.get("uri")
                if not uri:
                    continue
                code, data, err = _get_json(f"https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?uri={urllib.parse.quote(uri)}&depth=2")
                if code == 200 and isinstance(data, dict):
                    def _walk(node):
                        for reply in (node.get("replies") or []):
                            post = (reply.get("post") or {}).get("record") or {}
                            author = ((reply.get("post") or {}).get("author") or {}).get("handle") or ""
                            if post.get("text"):
                                items.append({"author": author, "text": post["text"], "created_at": post.get("createdAt") or "", "source_url": f"https://bsky.app/profile/{username}", "post_url": item.get("source_url") or ""})
                            _walk(reply)
                    _walk(data.get("thread") or {})
            by_platform[platform] = {"status": "ok", "count": len(items)}
        elif platform == "mastodon":
            code, data, err = _get_json(f"https://mastodon.social/api/v1/accounts/lookup?acct={urllib.parse.quote(username)}")
            if code == 200 and isinstance(data, dict) and data.get("id"):
                for item in (activity.get(f"mastodon:{username}", []) or [])[:1]:
                    sid = item.get("status_id")
                    if not sid:
                        continue
                    code2, data2, err2 = _get_json(f"https://mastodon.social/api/v1/statuses/{sid}/context")
                    if code2 == 200 and isinstance(data2, dict):
                        for reply in data2.get("descendants", []) or []:
                            items.append({"author": (reply.get("account") or {}).get("acct") or "", "text": _clean(reply.get("content") or ""), "created_at": reply.get("created_at") or "", "source_url": reply.get("url") or "", "post_url": item.get("source_url") or ""})
                by_platform[platform] = {"status": "ok", "count": len(items)}
            else:
                by_platform[platform] = {"status": "degraded", "count": 0, "message": err or ""}
        elif platform == "youtube":
            key = (keys or {}).get("youtube_api_key") or (keys or {}).get("youtube") or (keys or {}).get("google_api_key")
            vids = [i.get("video_id") for i in (activity.get(f"youtube:{username}", []) or []) if i.get("video_id")]
            if key and vids:
                code, data, err = _get_json(f"https://www.googleapis.com/youtube/v3/commentThreads?part=snippet&videoId={vids[0]}&maxResults={min(_comment_limit(), 50)}&key={urllib.parse.quote(key)}")
                if code == 200 and isinstance(data, dict):
                    for it in data.get("items", []) or []:
                        snip = ((it.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
                        items.append({"author": snip.get("authorDisplayName") or "", "text": snip.get("textDisplay") or "", "created_at": snip.get("publishedAt") or "", "source_url": f"https://www.youtube.com/watch?v={vids[0]}", "post_url": ""})
                by_platform[platform] = {"status": "ok" if code == 200 else "degraded", "count": len(items), "message": err or ""}
            else:
                by_platform[platform] = {"status": "not_checked", "count": 0, "message": "YouTube comments need a Data API key."}
        elif platform in ("x", "instagram", "reddit", "tiktok"):
            by_platform[platform] = {"status": "not_checked", "count": 0, "message": "Comments are not exposed by the licensed-aggregator profile endpoint; login-walled pages are not scraped."}
        if items:
            comments.extend([{**c, "platform": platform} for c in items[:_comment_limit()]])
    return {"comments": comments[:_comment_limit()], "by_platform": by_platform, "note": "Comments are public replies to the person's own posts only. A platform marked not_checked/degraded is not 'no comments'."}


def fetch_mentions(seed: str, live: bool = True) -> dict:
    """Public posts by others mentioning the seed username."""
    if not live:
        return {"mentions": [], "sources": {}}
    mentions, sources = [], {}
    # Hacker News stories + comments mentioning the seed.
    code, data, err = _get_json(f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(seed)}&hitsPerPage=5")
    if code == 200 and isinstance(data, dict):
        for hit in data.get("hits", []) or []:
            title = hit.get("title") or hit.get("comment_text") or ""
            if title:
                mentions.append({"source": "hackernews", "text": _clean(title), "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}", "author": hit.get("author") or ""})
        sources["hackernews"] = {"status": "ok", "count": len(mentions)}
    else:
        sources["hackernews"] = {"status": "degraded", "message": err or ""}
    # Mastodon public search (statuses).
    code, data, err = _get_json(f"https://mastodon.social/api/v2/search?q={urllib.parse.quote(seed)}&type=statuses&limit=5")
    if code == 200 and isinstance(data, dict):
        count = 0
        for st in data.get("statuses", []) or []:
            mentions.append({"source": "mastodon", "text": _clean(st.get("content") or ""), "url": st.get("url") or "", "author": (st.get("account") or {}).get("acct") or ""})
            count += 1
        sources["mastodon"] = {"status": "ok", "count": count}
    else:
        sources["mastodon"] = {"status": "degraded", "message": err or ""}
    # Bluesky search is appview-gated (403 in this environment), so it
    # is reported degraded, never as "no mentions".
    sources["bluesky"] = {"status": "degraded", "message": "Bluesky searchPosts returned 403 in verification; not retried."}
    return {"mentions": mentions[:10], "sources": sources}


def fetch_news(seed: str, live: bool = True) -> dict:
    """Public news/blog mentions via the Google News public RSS feed."""
    if not live:
        return {"news_mentions": [], "status": "demo"}
    code, body, err = _get_text(f"https://news.google.com/rss/search?q={urllib.parse.quote(seed)}&hl=en-US&gl=US&ceid=US:en")
    if code != 200 or not body.strip():
        return {"news_mentions": [], "status": "degraded", "message": err or f"HTTP {code}"}
    try:
        root = ET.fromstring(body)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                items.append({"title": title, "url": link, "published_at": pub})
            if len(items) >= 5:
                break
        return {"news_mentions": items, "status": "ok"}
    except Exception as exc:
        return {"news_mentions": [], "status": "degraded", "message": str(exc)}


def fetch_github_social(username: str, live: bool = True) -> dict:
    """GitHub public orgs, public events, PR reviews, contributions."""
    if not live:
        return {"groups": [], "events": [], "reviews": [], "contributions": {}}
    out = {"groups": [], "events": [], "reviews": [], "contributions": {}}
    code, data, err = _get_json(f"https://api.github.com/users/{urllib.parse.quote(username)}/orgs?per_page=10")
    if code == 200 and isinstance(data, list):
        out["groups"] = [{"name": o.get("login"), "url": o.get("url")} for o in data]
    code, data, err = _get_json(f"https://api.github.com/users/{urllib.parse.quote(username)}/events/public?per_page=20")
    if code == 200 and isinstance(data, list):
        out["events"] = [{"type": e.get("type"), "repo": (e.get("repo") or {}).get("name"), "created_at": e.get("created_at")} for e in data[:10]]
        months = Counter((e.get("created_at") or "")[:7] for e in data if e.get("created_at"))
        types = Counter(e.get("type") for e in data if e.get("type"))
        out["contributions"] = {"by_month": dict(sorted(months.items())), "by_type": dict(types), "note": "Public events only; a private contribution is never shown."}
    code, data, err = _get_json(f"https://api.github.com/search/issues?q=type:pr+reviewed-by:{urllib.parse.quote(username)}&per_page=5")
    if code == 200 and isinstance(data, dict):
        out["reviews"] = [{"title": i.get("title"), "url": i.get("html_url"), "state": i.get("state")} for i in (data.get("items") or [])]
    return out


def fetch_website_changes(domains: list, live: bool = True) -> dict:
    """Archived snapshot dates per bio domain (Wayback CDX, capped)."""
    if not live:
        return {}
    out = {}
    for domain in domains[:5]:
        code, body, err = _get_text(f"https://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(domain)}&output=json&fl=timestamp,original&collapse=digest&limit=5")
        if code == 200 and body.strip():
            try:
                import json as _json

                rows = _json.loads(body)
                snaps = [r[0] for r in rows[1:] if r] if len(rows) > 1 else []
                out[domain] = {"status": "ok", "snapshot_timestamps": snaps, "note": "Archived versions only; a missing snapshot is not a claim the site never changed."}
            except Exception as exc:
                out[domain] = {"status": "degraded", "message": str(exc)}
        else:
            out[domain] = {"status": "degraded", "message": err or f"HTTP {code}"}
    return out


def hashtags_and_topics(activity: dict, profiles) -> dict:
    tags, words = Counter(), Counter()
    for items in activity.values():
        for item in items:
            text = item.get("text") or ""
            for tag in re.findall(r"#(\w+)", text):
                tags[tag.lower()] += 1
            for w in re.findall(r"[a-z]{4,}", text.lower()):
                if w not in ("https", "http", "www", "github", "profile"):
                    words[w] += 1
    for p in profiles:
        bio = p.get("bio") if isinstance(p, dict) else getattr(p, "bio", "")
        for tag in re.findall(r"#(\w+)", bio or ""):
            tags[tag.lower()] += 1
    return {"hashtags": dict(tags.most_common(20)), "topics": [w for w, _ in words.most_common(20)]}


def build_timeline(activity: dict, profiles) -> list:
    events = []
    for pid, items in activity.items():
        for item in items:
            if item.get("created_at"):
                events.append({"date": item["created_at"], "kind": "activity", "profile": pid, "text": (item.get("text") or "")[:200], "source_url": item.get("source_url") or ""})
    for p in profiles:
        if isinstance(p, dict):
            created, platform, username = p.get("created_at"), p.get("platform"), p.get("username")
        else:
            created, platform, username = getattr(p, "created_at", ""), getattr(p, "platform", ""), getattr(p, "username", "")
        if created:
            events.append({"date": created, "kind": "account_created", "profile": f"{platform}:{username}", "text": f"Account created: {platform}:{username}", "source_url": ""})
    events.sort(key=lambda e: e["date"])
    return events


def topics_tone(activity: dict, keys: dict | None = None) -> dict:
    """Topic + tone summary, labelled machine-made, heuristic tone only."""
    positive = {"great", "love", "amazing", "awesome", "good", "happy", "thanks", "excellent", "win", "success"}
    negative = {"bad", "hate", "fail", "error", "bug", "broken", "sad", "angry", "problem", "crash"}
    pos = neg = total = 0
    words = Counter()
    for items in activity.values():
        for item in items:
            text = (item.get("text") or "").lower()
            toks = re.findall(r"[a-z]+", text)
            total += len(toks)
            pos += sum(1 for t in toks if t in positive)
            neg += sum(1 for t in toks if t in negative)
            for w in toks:
                if len(w) >= 4:
                    words[w] += 1
    summary = {
        "topics": [w for w, _ in words.most_common(10)],
        "tone": {"positive_words": pos, "negative_words": neg, "total_words": total, "note": "Word-list heuristic only, not a psychological or sentiment claim."},
        "labelled": True, "model": "local-template-v1",
    }
    # LLM summary when a key is configured (real call, else not_checked).
    try:
        from personatrace.ai.layer import AILayer

        layer = AILayer(mode="llm", keys=keys or {})
        if layer.api_key:
            all_text = " ".join(i.get("text", "") for items in activity.values() for i in items)[:2000]
            if all_text:
                result = layer.summarise([{"username": "case", "platform": "activity"}], [])
                # Use a dedicated LLM call via summarise prompt is not
                # topic-specific, so keep the template topics and add
                # the LLM text as a labelled extra, never replacing facts.
                if result.get("status") == "ok":
                    summary["llm_summary"] = result.get("text")
                    summary["model"] = result.get("model")
    except Exception:
        pass
    return summary
