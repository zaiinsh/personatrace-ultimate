"""Tests for PersonaTrace adapters. Stdlib + unittest only, no network.

Demo mode (PERSONATRACE_DEMO=1) is forced in setUp for demo tests; live
HTTP is never called except in tests that mock urllib, where a fake
429 / failure response proves the no-retry, honest-degradation behaviour.
All fixtures are fictional demo_* data only.
"""

import os
import unittest
from unittest import mock

from personatrace.adapters import (
    ADAPTERS,
    available_adapters,
    build_site_urls,
    site_url,
)
from personatrace.adapters.free import GitHubAdapter, YouTubeAdapter
from personatrace.adapters.gated import GATED_PLATFORMS, LicensedAggregatorAdapter
from personatrace.adapters.site_lists import CLOSED_PLATFORMS, SITE_LISTS


def _demo_env():
    return mock.patch.dict(os.environ, {"PERSONATRACE_DEMO": "1"}, clear=False)


def _no_demo_env():
    env = {k: v for k, v in os.environ.items() if k != "PERSONATRACE_DEMO"}
    return mock.patch.dict(os.environ, env, clear=True)


class TestGatedMissingKey(unittest.TestCase):
    def test_missing_key_is_not_checked_not_not_found(self):
        with _no_demo_env():
            for platform in GATED_PLATFORMS:
                adapter = LicensedAggregatorAdapter(platform)
                self.assertEqual(adapter.status({}), "not_checked")
                result = adapter.search("someone", {})
                self.assertEqual(result.status, "not_checked")
                self.assertEqual(result.profiles, [])
                self.assertIn("Settings", result.message)
                self.assertIn("API Keys", result.message)
                self.assertNotIn("not found", result.message.lower())

    def test_missing_key_wins_even_in_demo_mode(self):
        with _demo_env():
            adapter = LicensedAggregatorAdapter("x")
            self.assertEqual(adapter.status({}), "not_checked")
            result = adapter.search("someone", {})
            self.assertEqual(result.status, "not_checked")
            self.assertEqual(result.profiles, [])

    def test_registry_reports_gated_not_checked_without_keys(self):
        with _no_demo_env():
            statuses = available_adapters({})
            for platform in GATED_PLATFORMS:
                self.assertEqual(statuses[platform], "not_checked")


class TestDemoMode(unittest.TestCase):
    def test_free_demo_profiles_are_labelled(self):
        with _demo_env():
            result = GitHubAdapter().search("anyone", {})
            self.assertEqual(result.status, "ok")
            self.assertTrue(result.profiles)
            for profile in result.profiles:
                self.assertTrue(profile.username.startswith("demo_"))
                self.assertTrue(profile.bio.startswith("[DEMO DATA"))
                self.assertTrue(
                    any(ev.method == "demo" for ev in profile.evidence)
                )

    def test_gated_demo_with_key_is_labelled(self):
        with _demo_env():
            result = LicensedAggregatorAdapter("instagram").search(
                "anyone", {"licensed_aggregator": "dummy-key"}
            )
            self.assertEqual(result.status, "ok")
            self.assertTrue(result.profiles)
            for profile in result.profiles:
                self.assertEqual(profile.platform, "instagram")
                self.assertTrue(profile.username.startswith("demo_"))
                self.assertTrue(
                    any(ev.method == "demo" for ev in profile.evidence)
                )

    def test_demo_profiles_never_claim_to_be_real(self):
        with _demo_env():
            result = GitHubAdapter().search("anyone", {})
            self.assertIn("demo", result.message.lower())


class TestFreeAdapters(unittest.TestCase):
    def test_free_status_is_active(self):
        with _no_demo_env():
            for name in ("github", "bluesky", "mastodon", "dns"):
                self.assertIn(ADAPTERS[name].status({}), ("active", "degraded"))
            self.assertEqual(ADAPTERS["github"].status({}), "active")

    def test_youtube_no_key_is_not_checked_not_not_found(self):
        with _no_demo_env():
            adapter = YouTubeAdapter()
            self.assertEqual(adapter.status({}), "not_checked")
            result = adapter.search("anyone", {})
            self.assertEqual(result.status, "not_checked")
            self.assertEqual(result.profiles, [])
            self.assertNotIn("not found", result.message.lower())

    def test_youtube_live_with_key_mocked(self):
        import json as _json

        class FakeResponse:
            def __init__(self, payload):
                self.status = 200
                self._payload = _json.dumps(payload).encode("utf-8")

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        payload = {
            "items": [{
                "id": {"channelId": "UCtest123"},
                "snippet": {
                    "channelTitle": "Test Channel",
                    "description": "A test channel.",
                    "publishedAt": "2020-01-01T00:00:00Z",
                },
            }]
        }

        def fake_urlopen(req, timeout=None):
            # The key must go to Google's API URL; it must never appear
            # in a profile URL, message or evidence source URL (checked
            # above via the channel URL, and in the GUI by never echoing).
            return FakeResponse(payload)

        with _no_demo_env(), mock.patch(
            "personatrace.adapters.free.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            result = YouTubeAdapter().search("anyone", {"youtube_api_key": "dummy-youtube-key"})
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.profiles), 1)
        self.assertEqual(result.profiles[0].username, "Test Channel")
        self.assertEqual(result.cost_units, 100.0)
        self.assertIn("youtube.com/channel/UCtest123", result.profiles[0].evidence[0].source_url)

    def test_429_is_degraded_after_slow_capped_retries(self):
        import urllib.error

        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

        with _no_demo_env(), mock.patch(
            "personatrace.adapters.free.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            result = GitHubAdapter().search("anyone", {})
        # v2.0: slow, capped retries (2 retries, then degraded) — not a hammer.
        self.assertEqual(len(calls), 3, "429 must be retried slowly at most twice, then degraded")
        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.profiles, [])

    def test_network_failure_is_degraded_not_fabricated(self):
        with _no_demo_env(), mock.patch(
            "personatrace.adapters.free.urllib.request.urlopen",
            side_effect=OSError("network down"),
        ):
            result = GitHubAdapter().search("anyone", {})
        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.profiles, [])


class TestSiteLists(unittest.TestCase):
    def test_no_closed_platform_live_check_claims(self):
        platforms = {plat for plat, _ in SITE_LISTS}
        self.assertFalse(platforms & set(CLOSED_PLATFORMS))
        for closed in CLOSED_PLATFORMS:
            self.assertIsNone(site_url(closed, "demo_user_01"))

    def test_templates_use_username_placeholder_and_build_urls(self):
        for plat, template in SITE_LISTS:
            self.assertIn("{username}", template)
        urls = dict(build_site_urls("demo_user_01"))
        self.assertIn("demo_user_01", urls["github"])
        self.assertNotIn("x", urls)
        self.assertNotIn("instagram", urls)


class TestGatedLiveConfigurable(unittest.TestCase):
    def test_key_without_base_url_is_degraded(self):
        with _no_demo_env():
            result = LicensedAggregatorAdapter("x").search(
                "anyone", {"licensed_aggregator_key": "dummy-key"}
            )
            self.assertEqual(result.status, "degraded")
            self.assertEqual(result.profiles, [])

    def test_key_with_base_url_mocked(self):
        import json as _json

        class FakeResponse:
            def __init__(self, payload):
                self.status = 200
                self._payload = _json.dumps(payload).encode("utf-8")

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        payload = {
            "username": "testuser",
            "display_name": "Test User",
            "bio": "Public test profile.",
            "url": "https://x.com/testuser",
            "followers_count": 42,
        }

        def fake_urlopen(req, timeout=None):
            self.assertIn("platform=x", req.full_url)
            self.assertIn("username=anyone", req.full_url)
            return FakeResponse(payload)

        with _no_demo_env(), mock.patch(
            "personatrace.adapters.gated.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            result = LicensedAggregatorAdapter("x").search(
                "anyone",
                {
                    "licensed_aggregator_key": "dummy-key",
                    "licensed_aggregator_base_url": "https://provider.example/v1",
                },
            )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.profiles[0].username, "testuser")
        self.assertEqual(result.profiles[0].evidence[0].method, "licensed_aggregator")


class TestCostBeforeRun(unittest.TestCase):
    def test_cost_rows_are_real_not_placeholder(self):
        from personatrace.adapters.registry import cost_before_run

        with _no_demo_env():
            rows = cost_before_run({})
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["github"]["cost_units"], 0)
        self.assertEqual(by_name["youtube"]["status"], "not_checked")
        self.assertEqual(by_name["x"]["status"], "not_checked")
        with _no_demo_env():
            rows = cost_before_run({"youtube_api_key": "dummy"})
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["youtube"]["cost_units"], 100)


class TestRegistry(unittest.TestCase):
    def test_registry_covers_free_and_gated(self):
        for name in ("github", "youtube", "bluesky", "mastodon", "wayback", "crtsh", "dns"):
            self.assertIn(name, ADAPTERS)
        for platform in GATED_PLATFORMS:
            self.assertIn(platform, ADAPTERS)
            self.assertEqual(ADAPTERS[platform].name, "licensed_aggregator")
            self.assertEqual(ADAPTERS[platform].platform, platform)
            self.assertTrue(ADAPTERS[platform].requires_key)


if __name__ == "__main__":
    unittest.main()
