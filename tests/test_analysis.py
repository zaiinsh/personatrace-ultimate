"""Wired analysis + monitor + budget tests. No network: demo mode on,
and live fetches are skipped there, so these tests stay offline."""

import os
import unittest
from unittest import mock

os.environ["PERSONATRACE_DEMO"] = "1"

from personatrace.core.engine import run_investigation
from personatrace.features.analysis import run_analysis
from personatrace.monitor import compare_investigations


class AnalysisTest(unittest.TestCase):
    def test_analysis_runs_on_demo_case_without_network(self):
        inv = run_investigation("demo_user_01", adapters=[], keys={})
        # Engine with empty adapters still runs analysis (offline in demo).
        self.assertTrue(hasattr(inv, "analysis"))
        a = inv.analysis
        self.assertIn("languages", a)
        self.assertIn("snapshots", a)
        self.assertIn("coordinated", a)
        self.assertIn("behaviour_summary", a)
        self.assertFalse(a["live"])

    def test_analysis_on_demo_profiles(self):
        from demo.fixtures import demo_investigation

        inv = demo_investigation()
        a = run_analysis(inv, keys={})
        self.assertGreaterEqual(len(a["snapshots"]), 5)
        self.assertEqual(a["coordinated"]["verdict"], "pattern, not proof")

    def test_monitor_detects_changes(self):
        old = {"case_id": "old", "profiles": [
            {"platform": "github", "username": "a", "bio": "hello", "display_name": "",
             "bio_links": [], "follower_count": 1, "following_count": 0,
             "created_at": "", "status": "candidate"}],
            "edges": []}
        new = {"case_id": "new", "profiles": [
            {"platform": "github", "username": "a", "bio": "hello world", "display_name": "",
             "bio_links": [], "follower_count": 1, "following_count": 0,
             "created_at": "", "status": "candidate"},
            {"platform": "bluesky", "username": "b", "bio": "", "display_name": "",
             "bio_links": [], "follower_count": 0, "following_count": 0,
             "created_at": "", "status": "candidate"}],
            "edges": [{"from_id": "github:a", "to_id": "bluesky:b", "kind": "same_username"}]}
        report = compare_investigations(old, new)
        self.assertEqual(report["profiles_added"], ["bluesky:b"])
        self.assertIn("github:a", report["profiles_changed"])
        self.assertEqual(len(report["new_edges"]), 1)
        self.assertIn("may be deleted", report["note"])

    def test_budget_skips_youtube(self):
        from personatrace.adapters.free import YouTubeAdapter

        with mock.patch.dict(os.environ, {}, clear=False):
            # Remove demo flag for this check only via engine path:
            # a fake youtube adapter is skipped by budget regardless.
            class FakeYouTube:
                name = "youtube"
                platform = "youtube"

                def search(self, seed, keys):
                    raise AssertionError("budget should have skipped this")

            inv = run_investigation(
                "someone", adapters=[FakeYouTube()], keys={},
                max_cost_units=50, analyse=False)
            actions = [a["action"] for a in inv.audit]
            self.assertIn("adapter_skipped_budget", actions)


if __name__ == "__main__":
    unittest.main()
