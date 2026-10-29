"""Integration tests: engine + storage + export + GUI demo data (fictional only)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PERSONATRACE_DEMO"] = "1"
import unittest
from personatrace.core.engine import run_investigation, cluster_discovered_profiles
from personatrace.adapters.registry import ADAPTERS, available_adapters
from personatrace.storage.db import save_investigation, load_investigation
from personatrace.features.export import export_case


class IntegrationTest(unittest.TestCase):
    def test_engine_demo_run_clusters_and_roundtrips(self):
        inv = run_investigation("demo_user_01", list(ADAPTERS.values()), {})
        self.assertGreaterEqual(len(inv.profiles), 5)
        # Gated adapters must be not_checked without keys, never "not found"
        statuses = available_adapters({})
        for gated in ("x", "instagram", "reddit", "tiktok"):
            self.assertEqual(statuses[gated], "not_checked")
        cluster_discovered_profiles(inv)
        self.assertGreaterEqual(len(inv.edges), 1)
        self.assertTrue(any(e.kind == "same_username" for e in inv.edges))
        self.assertTrue(any(pm["status"] == "pending" for pm in inv.possible_matches))
        # No profile is auto-confirmed by clustering alone
        self.assertFalse(any(p.status == "confirmed" for p in inv.profiles))
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "personatrace.db")
            save_investigation(db, inv)
            loaded = load_investigation(db)
            self.assertEqual(len(loaded.profiles), len(inv.profiles))
            self.assertEqual(len(loaded.edges), len(inv.edges))
            self.assertGreaterEqual(len(loaded.possible_matches), 1)
            self.assertTrue(all(len(e.evidence) >= 0 for e in loaded.edges))
            out = export_case(loaded, os.path.join(d, "export"), fmt="json")
            self.assertTrue(os.path.exists(out))

    def test_demo_fixtures_roundtrip_with_edge_evidence(self):
        from demo.fixtures import demo_investigation
        inv = demo_investigation()
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "personatrace.db")
            save_investigation(db, inv)
            loaded = load_investigation(db)
            self.assertEqual(len(loaded.profiles), len(inv.profiles))
            self.assertEqual(len(loaded.edges), len(inv.edges))
            self.assertEqual(len(loaded.possible_matches), len(inv.possible_matches))
            # Edge evidence must survive (integration fix)
            self.assertTrue(any(len(e.evidence) > 0 for e in loaded.edges))
            self.assertTrue(all(p.confidence >= 0 for p in loaded.profiles))


if __name__ == "__main__":
    unittest.main()
