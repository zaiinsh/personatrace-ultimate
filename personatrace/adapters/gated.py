"""Gated adapter: one licensed-aggregator adapter covering x, instagram,
reddit and tiktok.

CONTRACT behaviour, applied in this exact precedence order in search():
1. Missing key -> status "not_checked", ZERO profiles, and a message that
   prompts the investigator to add a key in Settings > API Keys. It is
   NEVER reported as "not found" — absence of a key is not absence of an
   account. This rule wins even in demo mode.
2. Key present + PERSONATRACE_DEMO=1 -> labelled demo profiles
   (usernames ``demo_*``, bios ``[DEMO DATA...``, evidence
   ``method="demo"``). Demo data is never presented as real.
3. Key present + aggregator address configured + not demo mode ->
   one single live call to that aggregator's profile endpoint:
   GET {base_url}/v1/profile?platform={platform}&username={seed}
   with an Authorization: Bearer header. The aggregator is expected
   to return a JSON object for one public profile (username/handle,
   display_name, bio/description, url, follower/following counts).
   Any other shape, a 429, or a network failure returns "degraded"
   with zero profiles — never fabricated data, never a retry.
4. Key present but no aggregator address configured -> "degraded",
   zero profiles, with a plain message saying the address is missing.
   Steps 1 and 2 must not change.

Key lookup: ``keys`` is a dict of name -> key value. Any of these names
counts for a platform instance: the platform name itself (e.g. "x"),
"licensed_aggregator", "licensed_aggregator_key",
"licensed_aggregator:<platform>" or
"licensed_aggregator_<platform>", or env PERSONATRACE_AGGREGATOR_KEY.
Empty values do not count.
Address lookup: keys "licensed_aggregator_base_url" /
"licensed_aggregator_url", or env PERSONATRACE_AGGREGATOR_BASE_URL.
The address is a provider URL, not a secret, and is never echoed with
a key. Example (format only, not a provider endorsement):
https://provider.example/v1

No scraping, no login-wall bypass, no CAPTCHA bypass, no private data:
this adapter only ever talks to a licensed aggregator (when configured)
or returns the states above.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .base import AdapterResult, BaseAdapter, Evidence, Profile, is_demo_mode
from .mock_data import demo_profiles, utcnow_iso

_TIMEOUT = 5
_USER_AGENT = "PersonaTrace/1.1 (licensed-aggregator lookup)"

GATED_PLATFORMS = ("x", "instagram", "reddit", "tiktok")


def _find_key(platform: str, keys: dict) -> str | None:
    if isinstance(keys, dict):
        for candidate in (
            platform,
            "licensed_aggregator",
            "licensed_aggregator_key",
            f"licensed_aggregator:{platform}",
            f"licensed_aggregator_{platform}",
        ):
            value = keys.get(candidate)
            if value:
                return value
    value = os.environ.get("PERSONATRACE_AGGREGATOR_KEY")
    if value:
        return value
    return None


def _find_base_url(keys: dict) -> str | None:
    if isinstance(keys, dict):
        for candidate in ("licensed_aggregator_base_url", "licensed_aggregator_url"):
            value = keys.get(candidate)
            if value:
                return str(value).rstrip("/")
    value = os.environ.get("PERSONATRACE_AGGREGATOR_BASE_URL")
    if value:
        return value.rstrip("/")
    return None


def _get_json(url: str, key: str):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Authorization": f"Bearer {key}"},
    )
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


def _profile_from_aggregator(platform: str, seed: str, data: dict) -> Profile | None:
    if not isinstance(data, dict):
        return None
    username = (
        data.get("username") or data.get("handle") or data.get("name") or seed
    )
    if not username:
        return None
    source = (
        data.get("url") or data.get("profile_url") or data.get("source_url") or ""
    )
    evidence = [
        Evidence(
            source_url=source,
            captured_at_utc=utcnow_iso(),
            method="licensed_aggregator",
            platform=platform,
            field="username",
            value=str(username),
            confidence=90,
        )
    ]
    followers = data.get("followers") or data.get("followers_count")
    following = data.get("following") or data.get("follows_count") or data.get("following_count")
    return Profile(
        platform=platform,
        username=str(username),
        display_name=str(data.get("display_name") or data.get("displayName") or ""),
        bio=str(data.get("bio") or data.get("description") or ""),
        follower_count=followers,
        following_count=following,
        created_at=str(data.get("created_at") or ""),
        evidence=evidence,
    )


class LicensedAggregatorAdapter(BaseAdapter):
    """One adapter class; the ``platform`` field varies per instance."""

    name = "licensed_aggregator"
    requires_key = True
    free_tier = False
    demo_capable = True

    def __init__(self, platform: str):
        if platform not in GATED_PLATFORMS:
            raise ValueError(f"licensed aggregator does not cover platform: {platform!r}")
        self.platform = platform

    def status(self, keys: dict) -> str:
        if not _find_key(self.platform, keys):
            return "not_checked"
        if is_demo_mode():
            return "active"
        return "active" if _find_base_url(keys) else "degraded"

    def search(self, seed: str, keys: dict) -> AdapterResult:
        key = _find_key(self.platform, keys)
        if not key:
            return AdapterResult(
                profiles=[],
                status="not_checked",
                message=(
                    f"{self.platform}: not checked — no licensed aggregator key "
                    "is configured. Add a key in Settings > API Keys to enable "
                    f"{self.platform} lookup. This does not mean no account exists."
                ),
            )
        if is_demo_mode():
            return AdapterResult(
                profiles=demo_profiles(self.platform),
                status="ok",
                message=(
                    f"{self.platform}: demo data only (PERSONATRACE_DEMO=1) — "
                    "labelled dummy profiles, not real accounts."
                ),
            )
        base_url = _find_base_url(keys)
        if not base_url:
            return AdapterResult(
                profiles=[],
                status="degraded",
                message=(
                    f"{self.platform}: live lookup unavailable — a licensed "
                    "aggregator key is present but no aggregator address is "
                    "configured. Set licensed_aggregator_base_url (or env "
                    "PERSONATRACE_AGGREGATOR_BASE_URL) to your provider's "
                    "profile endpoint base, then run again. No live call "
                    "was attempted and no data was returned."
                ),
            )
        url = (
            f"{base_url}/v1/profile?platform={urllib.parse.quote(self.platform)}"
            f"&username={urllib.parse.quote(seed)}"
        )
        code, data, err = _get_json(url, key)
        if code == 200 and isinstance(data, dict):
            candidate = data
            if isinstance(data.get("profiles"), list) and data["profiles"]:
                candidate = data["profiles"][0]
            elif isinstance(data.get("profile"), dict):
                candidate = data["profile"]
            profile = _profile_from_aggregator(self.platform, seed, candidate)
            if profile is None:
                return AdapterResult(
                    profiles=[],
                    status="degraded",
                    message=(
                        f"{self.platform}: aggregator returned an unrecognised "
                        "response shape; no data was used."
                    ),
                )
            return AdapterResult(
                profiles=[profile],
                status="ok",
                message=(
                    f"{self.platform}: public profile found via the "
                    "licensed aggregator."
                ),
            )
        if code == 404:
            return AdapterResult(
                profiles=[],
                status="ok",
                message=(
                    f"{self.platform}: no public profile found for '{seed}' "
                    "via the licensed aggregator."
                ),
            )
        if code == 429:
            return AdapterResult(
                profiles=[],
                status="degraded",
                message=(
                    f"{self.platform}: aggregator rate limited (HTTP 429) — "
                    "not retried, no data returned."
                ),
            )
        return AdapterResult(
            profiles=[],
            status="degraded",
            message=(
                f"{self.platform}: live lookup unavailable "
                f"({err or f'HTTP {code}'}); no data returned."
            ),
        )


GATED_ADAPTERS = {platform: LicensedAggregatorAdapter(platform) for platform in GATED_PLATFORMS}
