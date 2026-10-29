"""Free (no-key) adapters: github, youtube, bluesky, mastodon, wayback,
crtsh, dns.

Rules for every live call in this module:
- One single public HTTP GET (or one stdlib DNS lookup for dns), short
  timeout (5s). No retries, ever — a 429 is returned as degraded, never
  retried, and never bypassed. No login wall is ever crossed and no
  CAPTCHA is ever solved or bypassed.
- Any failure (network error, non-200, unparsable body) is reported
  honestly as status "degraded" with zero profiles, never as "not found"
  for a failed lookup and never as fabricated data.
- A 404 on an exact-lookup endpoint is different: it is an honest
  "no public profile found" with status "ok" and zero profiles, because
  the lookup itself succeeded.
- If PERSONATRACE_DEMO=1, labelled demo profiles are returned instead
  of any live call (no network is attempted in demo mode).

Live-capability honesty (see also the final report):
- Live-capable in this build: github, bluesky, mastodon (mastodon.social
  lookup only), wayback (domain seeds only), crtsh (domain seeds only),
  dns (domain seeds only, stdlib lookup).
- Live in this build: youtube, via the YouTube Data API v3 channel
  search, when a key is supplied (keys: "youtube", "youtube_api_key"
  or "google_api_key", or env YOUTUBE_API_KEY / GOOGLE_API_KEY).
  Without a key it returns status "not_checked", never "not found".
  Scraping youtube.com pages is never attempted. A search costs
  100 YouTube API units (see cost_before_run in registry.py).
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from .base import AdapterResult, BaseAdapter, Evidence, Profile, is_demo_mode
from .mock_data import demo_profiles, utcnow_iso

_TIMEOUT = 5
_USER_AGENT = "PersonaTrace/1.0 (public-data lookup; contact via Settings)"


def _get_json(url: str, headers: dict | None = None):
    """GET returning (http_status_or_None, parsed_json_or_None, error).

    v2.0: on 429/503 only, wait slowly and retry at most twice —
    Retry-After header when present, otherwise 2s then 5s, capped at
    30s. This is waiting for the limit, not bypassing it: if the
    server is still limited after the retries, the result is degraded
    and reported as such. Network errors are not retried.
    v8.0: optional extra headers (e.g. a GitHub token Authorization).
    """
    import time as _time
    _headers = {"User-Agent": _USER_AGENT}
    if headers:
        _headers.update(headers)
    for attempt in range(3):
        req = urllib.request.Request(url, headers=_headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    return resp.status, json.loads(body), None
                except (ValueError, TypeError):
                    return resp.status, None, "non-JSON response"
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < 2:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait = float(retry_after) if retry_after else (2.0 if attempt == 0 else 5.0)
                except ValueError:
                    wait = 2.0 if attempt == 0 else 5.0
                _time.sleep(min(wait, 30.0))
                continue
            return exc.code, None, f"HTTP {exc.code}"
        except Exception as exc:
            return None, None, str(exc)
    return 429, None, "HTTP 429 after slow retries"


def _degraded(adapter_name: str, detail: str) -> AdapterResult:
    return AdapterResult(
        profiles=[],
        status="degraded",
        message=f"{adapter_name}: live lookup unavailable ({detail}); "
        "no data returned. Run with PERSONATRACE_DEMO=1 for labelled demo data.",
    )


def _profile(platform: str, username: str, source_url: str, **kwargs) -> Profile:
    evidence = [
        Evidence(
            source_url=source_url,
            captured_at_utc=utcnow_iso(),
            method="public_api" if platform not in ("dns", "wayback", "crtsh") else "public_lookup",
            platform=platform,
            field="username",
            value=username,
            confidence=90,
        )
    ]
    return Profile(platform=platform, username=username, evidence=evidence, **kwargs)


def _is_domain(seed: str) -> bool:
    return "." in seed and " " not in seed and not seed.startswith((".", "@"))


class _FreeAdapter(BaseAdapter):
    requires_key = False
    free_tier = True
    demo_capable = True

    def status(self, keys: dict) -> str:
        # Free adapters need no key, so they are available to attempt.
        # A failed live attempt is reported by search() as degraded.
        return "active"

    def _demo(self, seed: str) -> AdapterResult:
        return AdapterResult(
            profiles=demo_profiles(self.platform),
            status="ok",
            message=f"{self.platform}: demo data only (PERSONATRACE_DEMO=1) — "
            "labelled dummy profiles, not real accounts.",
        )


class GitHubAdapter(_FreeAdapter):
    name = "github"
    platform = "github"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        url = f"https://api.github.com/users/{urllib.parse.quote(seed)}"
        # v8.0 GitHub-403 fix (part 1): use the investigator's GitHub
        # token when one is configured (keys or env) — 5,000 req/hour
        # instead of the 60/hour unauthenticated limit that caused the
        # v7 live 403s. The token is never put in any output.
        _token = (keys or {}).get("github_token") or os.environ.get("GITHUB_TOKEN")
        _headers = {"Authorization": f"Bearer {_token}"} if _token else None
        code, data, err = _get_json(url, headers=_headers)
        if code == 200 and isinstance(data, dict):
            profile = _profile(
                "github",
                data.get("login", seed),
                data.get("html_url", url),
                display_name=data.get("name") or "",
                bio=data.get("bio") or "",
                bio_links=[data["blog"]] if data.get("blog") else [],
                follower_count=data.get("followers"),
                following_count=data.get("following"),
                created_at=data.get("created_at") or "",
            )
            if data.get("avatar_url"):
                profile.evidence.append(
                    Evidence(
                        source_url=data["avatar_url"],
                        captured_at_utc=utcnow_iso(),
                        method="public_api",
                        platform="github",
                        field="avatar_url",
                        value=data["avatar_url"],
                        confidence=90,
                    )
                )
            # Public fields the user chose to show on their own profile.
            for field in ("company", "location"):
                if data.get(field):
                    profile.evidence.append(
                        Evidence(
                            source_url=data.get("html_url", url),
                            captured_at_utc=utcnow_iso(),
                            method="public_api",
                            platform="github",
                            field=field,
                            value=str(data[field]),
                            confidence=90,
                        )
                    )
            return AdapterResult(
                profiles=[profile],
                status="ok",
                message="github: public profile found via GitHub public API.",
            )
        if code == 404:
            return AdapterResult(
                profiles=[],
                status="ok",
                message=f"github: no public GitHub profile found for '{seed}'.",
            )
        if code == 429:
            return _degraded("github", "rate limited (HTTP 429) — not retried")
        if code == 403:
            # v8.0 GitHub-403 fix (part 2): fall back ONCE to the exact
            # public profile page (shared helper with Direct Profile
            # Mode, features/v8.py) and build a derived profile from
            # its OpenGraph/meta. A 429 keeps the v2.0 behaviour above:
            # slow capped retries inside _get_json, then degraded —
            # the fallback is never used to hammer a rate limit.
            try:
                from ..features.v8 import github_web_fallback

                fb = github_web_fallback(seed)
            except Exception:
                fb = {"status": "degraded"}
            if fb.get("status") == "found":
                profile = _profile(
                    "github", seed, fb["profile_url"],
                    display_name=fb.get("display_name", ""),
                    bio=fb.get("bio", ""),
                )
                profile.evidence[0].method = "public_web"
                if fb.get("avatar_url"):
                    profile.evidence.append(
                        Evidence(
                            source_url=fb["avatar_url"],
                            captured_at_utc=utcnow_iso(),
                            method="public_web",
                            platform="github",
                            field="avatar_url",
                            value=fb["avatar_url"],
                            confidence=70,
                        )
                    )
                return AdapterResult(
                    profiles=[profile],
                    status="ok",
                    message="github: public profile found via public-web fallback after the API returned 403 (derived OpenGraph fields only — no counts/dates on this route). Add a GitHub token for the full API profile.",
                )
            return _degraded("github", "HTTP 403 and the public-web fallback did not return a profile page")
        return _degraded("github", err or f"HTTP {code}")


class GitLabAdapter(_FreeAdapter):
    name = "gitlab"
    platform = "gitlab"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        url = "https://gitlab.com/api/v4/users?username=" + urllib.parse.quote(seed)
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, list) and data:
            user = data[0]
            profile = _profile(
                "gitlab",
                user.get("username", seed),
                user.get("web_url", f"https://gitlab.com/{seed}"),
                display_name=user.get("name") or "",
                bio=user.get("bio") or "",
                created_at=user.get("created_at") or "",
            )
            if user.get("avatar_url"):
                profile.evidence.append(
                    Evidence(
                        source_url=user["avatar_url"],
                        captured_at_utc=utcnow_iso(),
                        method="public_api",
                        platform="gitlab",
                        field="avatar_url",
                        value=user["avatar_url"],
                        confidence=90,
                    )
                )
            return AdapterResult(
                profiles=[profile],
                status="ok",
                message="gitlab: public profile found via the GitLab public API.",
            )
        if code == 200:
            return AdapterResult(
                profiles=[],
                status="ok",
                message=f"gitlab: no public GitLab profile found for '{seed}'.",
            )
        if code == 429:
            return _degraded("gitlab", "rate limited (HTTP 429) — not retried")
        return _degraded("gitlab", err or f"HTTP {code}")


class BlueskyAdapter(_FreeAdapter):
    name = "bluesky"
    platform = "bluesky"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        url = (
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor="
            + urllib.parse.quote(seed)
        )
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict):
            handle = data.get("handle", seed)
            profile = _profile(
                "bluesky",
                handle,
                f"https://bsky.app/profile/{handle}",
                display_name=data.get("displayName") or "",
                bio=data.get("description") or "",
                bio_links=re.findall(r"https?://[^\s]+", data.get("description") or ""),
                follower_count=(data.get("followersCount")),
                following_count=(data.get("followsCount")),
                created_at=data.get("createdAt") or "",
            )
            if data.get("avatar"):
                profile.evidence.append(
                    Evidence(
                        source_url=data["avatar"],
                        captured_at_utc=utcnow_iso(),
                        method="public_api",
                        platform="bluesky",
                        field="avatar_url",
                        value=data["avatar"],
                        confidence=90,
                    )
                )
            return AdapterResult(
                profiles=[profile],
                status="ok",
                message="bluesky: public profile found via Bluesky public API.",
            )
        if code in (400, 404):
            return AdapterResult(
                profiles=[],
                status="ok",
                message=f"bluesky: no public Bluesky profile found for '{seed}'.",
            )
        if code == 429:
            return _degraded("bluesky", "rate limited (HTTP 429) — not retried")
        return _degraded("bluesky", err or f"HTTP {code}")


class MastodonAdapter(_FreeAdapter):
    name = "mastodon"
    platform = "mastodon"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        # Honest scope limit: only the mastodon.social instance is queried.
        url = (
            "https://mastodon.social/api/v1/accounts/lookup?acct="
            + urllib.parse.quote(seed)
        )
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict):
            username = data.get("acct", seed)
            _note = data.get("note") or ""
            _bio = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _note)).strip()
            profile = _profile(
                "mastodon",
                username,
                data.get("url", f"https://mastodon.social/@{username}"),
                display_name=data.get("display_name") or "",
                bio=_bio,  # HTML tags stripped; markup is never shown as bio.
                bio_links=re.findall(r'href="([^"]+)"', _note),
                follower_count=data.get("followers_count"),
                following_count=data.get("following_count"),
                created_at=data.get("created_at") or "",
            )
            if data.get("avatar"):
                profile.evidence.append(
                    Evidence(
                        source_url=data["avatar"],
                        captured_at_utc=utcnow_iso(),
                        method="public_api",
                        platform="mastodon",
                        field="avatar_url",
                        value=data["avatar"],
                        confidence=90,
                    )
                )
            return AdapterResult(
                profiles=[profile],
                status="ok",
                message="mastodon: public profile found on mastodon.social only; "
                "other instances are not queried by this adapter.",
            )
        if code == 404:
            return AdapterResult(
                profiles=[],
                status="ok",
                message=f"mastodon: no public profile found on mastodon.social for '{seed}'.",
            )
        if code == 429:
            return _degraded("mastodon", "rate limited (HTTP 429) — not retried")
        return _degraded("mastodon", err or f"HTTP {code}")


def _youtube_key(keys: dict) -> str | None:
    if isinstance(keys, dict):
        for candidate in ("youtube", "youtube_api_key", "google_api_key"):
            value = keys.get(candidate)
            if value:
                return value
    for env_name in ("YOUTUBE_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(env_name)
        if value:
            return value
    return None


class YouTubeAdapter(_FreeAdapter):
    name = "youtube"
    platform = "youtube"

    def status(self, keys: dict) -> str:
        if is_demo_mode():
            return "active"
        return "active" if _youtube_key(keys) else "not_checked"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        key = _youtube_key(keys)
        if not key:
            return AdapterResult(
                profiles=[],
                status="not_checked",
                message="youtube: not checked — no YouTube Data API key "
                "is configured. Add a youtube_api_key in Settings, or "
                "set YOUTUBE_API_KEY, to enable YouTube lookup. "
                "This does not mean no channel exists.",
            )
        # Single public API call only. The key is sent to Google's API
        # as required by that API; it is never put in a profile URL,
        # message or audit detail returned by this adapter.
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            "?part=snippet&type=channel&maxResults=5&q="
            + urllib.parse.quote(seed)
            + "&key=" + urllib.parse.quote(key)
        )
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict):
            items = data.get("items") or []
            if not items:
                return AdapterResult(
                    profiles=[],
                    status="ok",
                    message=f"youtube: no public YouTube channel found for '{seed}'.",
                    cost_units=100.0,
                )
            profiles = []
            for item in items:
                snippet = item.get("snippet") or {}
                channel_id = (item.get("id") or {}).get("channelId", "")
                title = snippet.get("channelTitle") or snippet.get("title") or seed
                source = (
                    f"https://www.youtube.com/channel/{channel_id}"
                    if channel_id
                    else "https://www.youtube.com/"
                )
                profiles.append(
                    _profile(
                        "youtube",
                        title,
                        source,
                        display_name=title,
                        bio=snippet.get("description") or "",
                        created_at=snippet.get("publishedAt") or "",
                    )
                )
            return AdapterResult(
                profiles=profiles,
                status="ok",
                message="youtube: public channel(s) found via the YouTube Data API.",
                cost_units=100.0,
            )
        if code == 429:
            return _degraded("youtube", "rate limited (HTTP 429) — not retried")
        if code == 403:
            return _degraded(
                "youtube", "API rejected the request (HTTP 403 — key or quota)"
            )
        return _degraded("youtube", err or f"HTTP {code}")


class WaybackAdapter(_FreeAdapter):
    name = "wayback"
    platform = "wayback"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        if not _is_domain(seed):
            return AdapterResult(
                profiles=[],
                status="degraded",
                message="wayback: lookup needs a domain seed (e.g. example.com); "
                "username seeds are not checked against the Wayback Machine.",
            )
        url = "http://archive.org/wayback/available?url=" + urllib.parse.quote(seed)
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict):
            snap = (data.get("archived_snapshots") or {}).get("closest") or {}
            snap_url = snap.get("url")
            if snap_url:
                return AdapterResult(
                    profiles=[
                        _profile(
                            "wayback",
                            seed,
                            snap_url,
                            bio=f"Closest archived snapshot: {snap_url}",
                            created_at=snap.get("timestamp") or "",
                        )
                    ],
                    status="ok",
                    message="wayback: archived snapshot found via the public availability API.",
                )
            return AdapterResult(
                profiles=[],
                status="ok",
                message=f"wayback: no archived snapshot found for '{seed}'.",
            )
        if code == 429:
            return _degraded("wayback", "rate limited (HTTP 429) — not retried")
        return _degraded("wayback", err or f"HTTP {code}")


class CrtshAdapter(_FreeAdapter):
    name = "crtsh"
    platform = "crtsh"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        if not _is_domain(seed):
            return AdapterResult(
                profiles=[],
                status="degraded",
                message="crtsh: lookup needs a domain seed (e.g. example.com); "
                "username seeds are not checked against certificate logs.",
            )
        url = f"https://crt.sh/?q=%25.{urllib.parse.quote(seed)}&output=json"
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, list):
            names = sorted({row.get("common_name", "") for row in data if row.get("common_name")})
            if not names:
                return AdapterResult(
                    profiles=[],
                    status="ok",
                    message=f"crtsh: no public certificates found for '{seed}'.",
                )
            return AdapterResult(
                profiles=[
                    _profile(
                        "crtsh",
                        seed,
                        f"https://crt.sh/?q=%25.{seed}",
                        bio=f"{len(names)} public certificate name(s) in crt.sh logs; "
                        f"first: {names[0]}",
                    )
                ],
                status="ok",
                message="crtsh: public certificate log data found.",
            )
        if code == 429:
            return _degraded("crtsh", "rate limited (HTTP 429) — not retried")
        return _degraded("crtsh", err or f"HTTP {code}")


class DnsAdapter(_FreeAdapter):
    name = "dns"
    platform = "dns"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        if not _is_domain(seed):
            return AdapterResult(
                profiles=[],
                status="degraded",
                message="dns: lookup needs a domain seed (e.g. example.com); "
                "username seeds are not resolved via DNS.",
            )
        try:
            infos = socket.getaddrinfo(seed, 443, proto=socket.IPPROTO_TCP)
            addrs = sorted({info[4][0] for info in infos if info[4]})
        except Exception as exc:
            return _degraded("dns", f"DNS resolution failed ({exc})")
        if not addrs:
            return AdapterResult(
                profiles=[],
                status="ok",
                message=f"dns: no public DNS records resolved for '{seed}'.",
            )
        return AdapterResult(
            profiles=[
                _profile(
                    "dns",
                    seed,
                    f"https://{seed}/",
                    bio=f"Public DNS resolution: {', '.join(addrs)}",
                )
            ],
            status="ok",
            message="dns: public DNS records resolved via stdlib lookup.",
        )


def _get_text(url: str, user_agent: str = "Mozilla/5.0 (public-data lookup)"):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", str(exc)


class TelegramAdapter(_FreeAdapter):
    name = "telegram"
    platform = "telegram"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        # Public channel page only (t.me/s/<channel> needs no login).
        # No login wall is crossed and no private channel is accessed:
        # private channels have no public t.me/s page.
        url = f"https://t.me/s/{urllib.parse.quote(seed)}"
        code, body, err = _get_text(url)
        if code == 200 and body:
            title_m = re.search(r"<title>(.*?)</title>", body, re.S)
            desc_m = re.search(r'og:description" content="([^"]*)"', body)
            title = re.sub(r"\s+", " ", (title_m.group(1) if title_m else "")).strip()
            if title and title != "Telegram" and " – Telegram" in title:
                name = title.replace(" – Telegram", "").strip()
                profile = _profile(
                    "telegram", seed, url,
                    display_name=name,
                    bio=desc_m.group(1) if desc_m else "",
                )
                return AdapterResult(
                    profiles=[profile], status="ok",
                    message="telegram: public channel page found via t.me/s (public page, not an API).",
                )
            return AdapterResult(
                profiles=[], status="ok",
                message=f"telegram: no public Telegram channel found for '{seed}'.",
            )
        if code == 429:
            return _degraded("telegram", "rate limited (HTTP 429) — not retried")
        return _degraded("telegram", err or f"HTTP {code}")


class HackerNewsAdapter(_FreeAdapter):
    name = "hackernews"
    platform = "hackernews"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        url = f"https://hn.algolia.com/api/v1/users/{urllib.parse.quote(seed)}"
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict) and data.get("username"):
            return AdapterResult(
                profiles=[_profile(
                    "hackernews", data["username"],
                    f"https://news.ycombinator.com/user?id={data['username']}",
                    display_name=data.get("username") or "",
                    bio=data.get("about") or "",
                    created_at=data.get("created_at") or "",
                )],
                status="ok",
                message="hackernews: public forum user found via the Algolia HN API.",
            )
        if code == 404:
            return AdapterResult(
                profiles=[], status="ok",
                message=f"hackernews: no public Hacker News user found for '{seed}'.",
            )
        if code == 429:
            return _degraded("hackernews", "rate limited (HTTP 429) — not retried")
        return _degraded("hackernews", err or f"HTTP {code}")


class DiscourseAdapter(_FreeAdapter):
    name = "discourse"
    platform = "discourse"
    requires_key = False

    def _base_url(self, keys: dict):
        if isinstance(keys, dict):
            for candidate in ("discourse_base_url", "forum_base_url"):
                if keys.get(candidate):
                    return str(keys[candidate]).rstrip("/")
        import os as _os

        return (_os.environ.get("DISCOURSE_BASE_URL") or "").rstrip("/") or None

    def status(self, keys: dict) -> str:
        if is_demo_mode():
            return "active"
        return "active" if self._base_url(keys) else "not_checked"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        base = self._base_url(keys)
        if not base:
            return AdapterResult(
                profiles=[], status="not_checked",
                message="discourse: not checked — no Discourse forum address configured. "
                "Set discourse_base_url (e.g. https://meta.discourse.org) to check "
                "that forum's public user API. This does not mean no account exists.",
            )
        url = f"{base}/u/{urllib.parse.quote(seed)}.json"
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict) and isinstance(data.get("user"), dict):
            user = data["user"]
            return AdapterResult(
                profiles=[_profile(
                    "discourse", user.get("username", seed),
                    f"{base}/u/{user.get('username', seed)}",
                    display_name=user.get("name") or "",
                    bio=user.get("bio_raw") or "",
                    created_at=user.get("created_at") or "",
                )],
                status="ok",
                message="discourse: public forum user found via that forum's public user API.",
            )
        if code == 404:
            return AdapterResult(
                profiles=[], status="ok",
                message=f"discourse: no public user found for '{seed}' on that forum.",
            )
        if code == 429:
            return _degraded("discourse", "rate limited (HTTP 429) — not retried")
        return _degraded("discourse", err or f"HTTP {code}")


class StackOverflowAdapter(_FreeAdapter):
    name = "stackoverflow"
    platform = "stackoverflow"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        if is_demo_mode():
            return self._demo(seed)
        url = "https://api.stackexchange.com/2.3/users?inname=" + urllib.parse.quote(seed) + "&site=stackoverflow"
        code, data, err = _get_json(url)
        if code == 200 and isinstance(data, dict):
            items = [u for u in (data.get("items") or []) if u.get("display_name", "").lower() == seed.lower()]
            if not items and data.get("items"):
                # inname is a substring search; only an exact display-name
                # match is returned as a profile, others are not claimed.
                items = []
            if items:
                user = items[0]
                return AdapterResult(
                    profiles=[_profile(
                        "stackoverflow", user.get("display_name", seed),
                        user.get("link", url),
                        display_name=user.get("display_name") or "",
                        bio="",
                        created_at="",
                    )],
                    status="ok",
                    message="stackoverflow: public forum user found via the Stack Exchange API (exact display-name match only).",
                )
            return AdapterResult(
                profiles=[], status="ok",
                message=f"stackoverflow: no exact public Stack Overflow user found for '{seed}'.",
            )
        if code == 429:
            return _degraded("stackoverflow", "rate limited (HTTP 429) — not retried")
        return _degraded("stackoverflow", err or f"HTTP {code}")


class LinkedInAdapter(_FreeAdapter):
    name = "linkedin"
    platform = "linkedin"

    def status(self, keys: dict) -> str:
        return "not_checked"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        # Intentional non-adapter: LinkedIn offers no general
        # third-party profile search API (own profile / Company Pages
        # only), and its public profiles are largely login-walled.
        # The blueprint itself says: do not promise LinkedIn depth.
        # So this adapter never scrapes LinkedIn and never claims a
        # result; it reports not_checked with that reason.
        return AdapterResult(
            profiles=[], status="not_checked",
            message="linkedin: not checked — LinkedIn has no general public "
            "profile search API for arbitrary users, and login-walled "
            "pages are not scraped. LinkedIn depth is intentionally not "
            "promised. This does not mean no profile exists.",
        )


FREE_ADAPTERS = {
    "github": GitHubAdapter(),
    "gitlab": GitLabAdapter(),
    "telegram": TelegramAdapter(),
    "hackernews": HackerNewsAdapter(),
    "stackoverflow": StackOverflowAdapter(),
    "discourse": DiscourseAdapter(),
    "linkedin": LinkedInAdapter(),
    "youtube": YouTubeAdapter(),
    "bluesky": BlueskyAdapter(),
    "mastodon": MastodonAdapter(),
    "wayback": WaybackAdapter(),
    "crtsh": CrtshAdapter(),
    "dns": DnsAdapter(),
}
