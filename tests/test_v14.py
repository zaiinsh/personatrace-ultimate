"""v1.4 tests: comments, mentions, news, monitor changes, CSV, comparison, analyst."""

import tempfile
import unittest

from personatrace.core.engine import Investigation
from personatrace.features.analyst import add_note, default_checklist
from personatrace.features.compare_cases import compare_cases
from personatrace.features.export import export_case
from personatrace.features.social import build_timeline, hashtags_and_topics
from personatrace.monitor import compare_investigations


def _inv(seed="octocat"):
    inv = Investigation(case_id="case-v14", seed=seed, seed_type="username")
    inv.profiles = []
    inv.edges = []
    inv.possible_matches = []
    inv.alerts = []
    inv.audit = []
    return inv


class TestSocialPure(unittest.TestCase):
    def test_hashtags_and_timeline(self):
        activity = {"github:octocat": [{"text": "Hello #opensource world", "created_at": "2024-01-02T00:00:00Z", "source_url": ""}]}
        info = hashtags_and_topics(activity, [])
        self.assertIn("opensource", info["hashtags"])
        timeline = build_timeline(activity, [])
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["kind"], "activity")

    def test_comments_demo_mode(self):
        from personatrace.features.social import fetch_comments

        out = fetch_comments(_inv(), {}, live=False)
        self.assertEqual(out["comments"], [])


class TestMonitorChanges(unittest.TestCase):
    def test_follower_name_and_activity_changes(self):
        old = {"case_id": "a", "profiles": [{"platform": "github", "username": "octocat", "display_name": "Old", "follower_count": 10, "following_count": 5}],
               "edges": [], "analysis": {"activity": {"github:octocat": [{"text": "old post"}]}}}
        new = {"case_id": "b", "profiles": [{"platform": "github", "username": "octocat", "display_name": "New", "follower_count": 12, "following_count": 5}],
               "edges": [], "analysis": {"activity": {"github:octocat": [{"text": "new post"}]}}}
        report = compare_investigations(old, new)
        # Same activity on both runs must NOT appear as disappeared.
        same = compare_investigations(old, old)
        self.assertEqual(same["disappeared_activity"], [])
        self.assertEqual(same["new_activity"], [])
        self.assertEqual(report["follower_changes"]["github:octocat"]["delta"], 2)
        self.assertEqual(len(report["name_changes"]), 1)
        self.assertIn("new post", report["new_activity"])
        self.assertIn("old post", report["disappeared_activity"])
        self.assertTrue(report["monitor_alerts"])


class TestCsvComparisonAnalyst(unittest.TestCase):
    def test_csv_export_and_comparison_and_notes(self):
        inv = _inv()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_case(inv, tmp, fmt="csv")
            self.assertTrue(path.endswith("case.csv"))
            with open(path, encoding="utf-8") as fh:
                self.assertIn("platform,username,field", fh.readline())
        inv.checklist = default_checklist()
        self.assertEqual(len(inv.checklist), 6)
        note = add_note(inv, "Check this manually.")
        self.assertEqual(note["text"], "Check this manually.")
        self.assertEqual(len(inv.notes), 1)
        a, b = _inv("octocat"), _inv("pg")
        a.analysis = {"bio_domains": {"github:octocat": ["example.com"]}, "contacts": {"github:octocat": ["shared"]}, "hashtags": {"x": 1}}
        b.analysis = {"bio_domains": {"github:pg": ["example.com"]}, "contacts": {"github:pg": ["shared"]}, "hashtags": {"x": 1}}
        comp = compare_cases(a, b)
        self.assertIn("example.com", comp["shared_bio_domains"])
        self.assertIn("shared", comp["shared_contacts"])
        self.assertIn("human review", comp["note"].lower())


if __name__ == "__main__":
    unittest.main()
