"""Final-version public-web adapters (v6.0.0-final).

These wrap features/v6.py collectors. They are single-threaded, one
request per search, no retry on 429/401/403, stop on login wall/CAPTCHA.
A blocked result is status 'degraded' in adapter terms with a message
that names the v6 status (blocked/gated_paid/gated_login) — never a
fake profile. A not_checked gated route is still the licensed aggregator
adapter; these web adapters are the free fallback tried after it.
"""
from __future__ import annotations
from .base import AdapterResult, BaseAdapter, Evidence, Profile, is_demo_mode
from .mock_data import utcnow_iso
from personatrace.features.v6 import (
    instagram_public_web, tiktok_public_web, x_public_web, record_collector,
)

def _profile_from_v6(platform, seed, result):
    fields = result.get("fields") or {}
    def val(name):
        f = fields.get(name) or {}
        return f.get("value") if isinstance(f, dict) else None
    evidence = []
    url = result.get("url") or f"https://{platform}.com/{seed}"
    evidence.append(Evidence(source_url=url, captured_at_utc=utcnow_iso(), method="public_web",
                             platform=platform, field="username", value=str(val("username") or seed), confidence=85))
    bio = val("bio") or ""
    return Profile(platform=platform, username=str(val("username") or seed),
                   display_name=str(val("display_name") or ""), bio=str(bio or ""),
                   bio_links=[val("external_url")] if val("external_url") else [],
                   follower_count=val("follower_count"), following_count=val("following_count"),
                   created_at="", evidence=evidence, status="candidate")

class _WebAdapter(BaseAdapter):
    requires_key = False
    free_tier = True
    demo_capable = False
    def status(self, keys):
        return "active"
    def _run(self, seed, fn):
        if is_demo_mode():
            return AdapterResult(profiles=[], status="not_checked",
                message=f"{self.platform}: demo mode — public-web adapters are disabled in demo mode to avoid mixing demo and live data.")
        result = fn(seed, pace_seconds=0)
        status = result.get("status")
        if status == "found":
            return AdapterResult(profiles=[_profile_from_v6(self.platform, seed, result)], status="ok",
                message=f"{self.platform}: public profile header found via public web (v6). {result.get('note','')}")
        if status == "private":
            return AdapterResult(profiles=[], status="ok",
                message=f"{self.platform}: account exists but is private — header only, no private content attempted. {result.get('note','')}")
        if status == "not_found":
            return AdapterResult(profiles=[], status="ok",
                message=f"{self.platform}: no public profile found via public web for '{seed}'.")
        # blocked / not_checked -> degraded in adapter terms, message keeps v6 status
        return AdapterResult(profiles=[], status="degraded",
            message=f"{self.platform}: v6 status={status} — {result.get('note','')}")

class InstagramWebAdapter(_WebAdapter):
    name = "instagram_web"; platform = "instagram_web"
    def search(self, seed, keys):
        return self._run(seed, instagram_public_web)

class TikTokWebAdapter(_WebAdapter):
    name = "tiktok_web"; platform = "tiktok_web"
    def search(self, seed, keys):
        return self._run(seed, tiktok_public_web)

class XWebAdapter(_WebAdapter):
    name = "x_web"; platform = "x_web"
    def search(self, seed, keys):
        return self._run(seed, x_public_web)

FINAL_ADAPTERS = {
    "instagram_web": InstagramWebAdapter(),
    "tiktok_web": TikTokWebAdapter(),
    "x_web": XWebAdapter(),
}
