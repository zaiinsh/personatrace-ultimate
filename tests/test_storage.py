"""Tests for PersonaTrace SQLite storage. Stdlib + unittest only, no network.

Round-trip test uses fictional demo_* data only.
"""

import os
import sqlite3
import tempfile
import unittest

from personatrace.adapters.base import Edge, Evidence, Investigation, Profile
from personatrace.storage.db import (
    add_alert,
    init_db,
    load_investigation,
    log_audit,
    save_investigation,
)

CONTRACT_TABLES = {
    "cases",
    "profiles",
    "edges",
    "evidence",
    "timeline",
    "audit",
    "alerts",
}


def _sample_investigation():
    ev = Evidence(
        source_url="https://github.com/demo_user_01",
        captured_at_utc="2026-01-01T00:00:00+00:00",
        method="demo",
        platform="github",
        field="username",
        value="demo_user_01",
        confidence=0,
    )
    profile = Profile(
        platform="github",
        username="demo_user_01",
        display_name="Demo User",
        bio="[DEMO DATA] fictional",
        status="candidate",
        evidence=[ev],
    )
    profile2 = Profile(
        platform="x",
        username="demo_user_01",
        display_name="Demo User",
        status="candidate",
        evidence=[],
    )
    return Investigation(
        case_id="case-demo-01",
        seed="demo_user_01",
        seed_type="username",
        profiles=[profile, profile2],
        edges=[
            Edge(
                from_id="github:demo_user_01",
                to_id="x:demo_user_01",
                kind="same_username",
                confidence=40,
                band="Low",
                evidence=[],
            )
        ],
        timeline=[
            {
                "ts_utc": "2026-01-02T00:00:00+00:00",
                "kind": "profile_found",
                "description": "demo github profile recorded",
            }
        ],
        audit=[
            {
                "ts_utc": "2026-01-02T00:00:00+00:00",
                "actor": "investigator",
                "action": "case_created",
                "detail": "demo case",
            }
        ],
        alerts=[
            {
                "ts_utc": "2026-01-03T00:00:00+00:00",
                "kind": "new_edge",
                "message": "demo edge added",
                "acknowledged": False,
            }
        ],
    )


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "case", "personatrace.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_db_creates_contract_tables(self):
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertTrue(CONTRACT_TABLES <= tables)

    def test_round_trip_preserves_all_sections(self):
        inv = _sample_investigation()
        save_investigation(self.db_path, inv)
        loaded = load_investigation(self.db_path)

        self.assertEqual(loaded.case_id, "case-demo-01")
        self.assertEqual(loaded.seed, "demo_user_01")
        self.assertEqual(loaded.seed_type, "username")

        self.assertEqual(len(loaded.profiles), 2)
        gh = [p for p in loaded.profiles if p.platform == "github"][0]
        self.assertEqual(gh.username, "demo_user_01")
        self.assertEqual(gh.display_name, "Demo User")
        self.assertEqual(gh.bio, "[DEMO DATA] fictional")
        self.assertEqual(gh.status, "candidate")
        self.assertEqual(len(gh.evidence), 1)
        self.assertEqual(gh.evidence[0].source_url, "https://github.com/demo_user_01")
        self.assertEqual(gh.evidence[0].method, "demo")
        self.assertEqual(gh.evidence[0].field, "username")
        self.assertEqual(gh.evidence[0].value, "demo_user_01")
        self.assertEqual(gh.evidence[0].confidence, 0)

        self.assertEqual(len(loaded.edges), 1)
        edge = loaded.edges[0]
        self.assertEqual(edge.from_id, "github:demo_user_01")
        self.assertEqual(edge.to_id, "x:demo_user_01")
        self.assertEqual(edge.kind, "same_username")
        self.assertEqual(edge.confidence, 40)
        self.assertEqual(edge.band, "Low")

        self.assertEqual(len(loaded.timeline), 1)
        self.assertEqual(loaded.timeline[0]["kind"], "profile_found")
        self.assertEqual(
            loaded.timeline[0]["description"], "demo github profile recorded"
        )

        self.assertEqual(len(loaded.audit), 1)
        self.assertEqual(loaded.audit[0]["actor"], "investigator")
        self.assertEqual(loaded.audit[0]["action"], "case_created")

        self.assertEqual(len(loaded.alerts), 1)
        self.assertEqual(loaded.alerts[0]["kind"], "new_edge")
        self.assertEqual(loaded.alerts[0]["message"], "demo edge added")
        self.assertFalse(loaded.alerts[0]["acknowledged"])

    def test_save_is_idempotent(self):
        inv = _sample_investigation()
        save_investigation(self.db_path, inv)
        save_investigation(self.db_path, inv)
        loaded = load_investigation(self.db_path)
        self.assertEqual(len(loaded.profiles), 2)
        self.assertEqual(len(loaded.edges), 1)

    def test_log_audit_and_add_alert_work(self):
        init_db(self.db_path)
        log_audit(self.db_path, "case-demo-01", "investigator", "exported", "demo export")
        add_alert(self.db_path, "case-demo-01", "new_profile", "demo profile appeared")
        loaded = load_investigation(self.db_path, "case-demo-01")
        self.assertEqual(len(loaded.audit), 1)
        self.assertEqual(loaded.audit[0]["action"], "exported")
        self.assertEqual(loaded.audit[0]["detail"], "demo export")
        self.assertEqual(len(loaded.alerts), 1)
        self.assertEqual(loaded.alerts[0]["kind"], "new_profile")
        self.assertFalse(loaded.alerts[0]["acknowledged"])

        # Appending again accumulates, it does not overwrite.
        log_audit(self.db_path, "case-demo-01", "investigator", "reviewed", "ok")
        loaded = load_investigation(self.db_path, "case-demo-01")
        self.assertEqual(len(loaded.audit), 2)


if __name__ == "__main__":
    unittest.main()
