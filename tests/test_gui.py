"""GUI dashboard tests — stdlib only, localhost server only.

Written with unittest so they run under both ``python -m unittest``
and pytest (pytest is not installed in this environment, so the
verified runner is unittest).
"""

import json
import unittest
import urllib.error
import urllib.request

from personatrace.gui.server import run_gui

SECRET = "sk-test-secret-that-must-never-appear"


def _request(port, path, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get_content_type(), \
                resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get_content_type(), \
            err.read().decode("utf-8")


class GuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = run_gui(port=0)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_serves_index(self):
        status, ctype, body = _request(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn('id="graph"', body)
        self.assertIn('id="profile-panel"', body)
        self.assertIn('id="evidence-panel"', body)
        self.assertIn('id="timeline-slider"', body)
        self.assertIn('id="alerts-panel"', body)
        self.assertIn("bridge", body)

    def test_serves_static_assets(self):
        for path in ("/app.js", "/styles.css"):
            status, _, _ = _request(self.port, path)
            self.assertEqual(status, 200, path)

    def test_investigation_demo_labelled(self):
        status, _, body = _request(self.port, "/api/investigation")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["demo"])
        self.assertEqual(data["label"], "demo")
        self.assertEqual(data["seed"], "demo_user_01")
        self.assertGreaterEqual(len(data["profiles"]), 6)
        platforms = {p["platform"] for p in data["profiles"]}
        self.assertGreaterEqual(len(platforms), 4)
        self.assertGreaterEqual(len(data["edges"]), 8)
        self.assertTrue(all(p["username"].startswith("demo_")
                            for p in data["profiles"]))
        self.assertTrue(any(p.get("bridge") for p in data["profiles"]))

    def test_settings_adapter_statuses(self):
        status, _, body = _request(self.port, "/api/settings")
        self.assertEqual(status, 200)
        data = json.loads(body)
        by_name = {a["name"]: a for a in data["adapters"]}
        self.assertEqual(by_name["github"]["status"], "active")
        # Gated adapters start not_checked on a fresh server.
        self.assertEqual(by_name["x"]["status"], "not_checked")
        self.assertIn("Settings", by_name["x"]["message"])

    def test_post_key_never_echoes_value(self):
        # Uses "reddit", not "x": tests share one server and
        # test_settings_adapter_statuses expects "x" still not_checked.
        status, _, body = _request(
            self.port, "/api/settings/keys", method="POST",
            payload={"name": "reddit", "key": SECRET})
        self.assertEqual(status, 200)
        self.assertNotIn(SECRET, body)
        data = json.loads(body)
        self.assertEqual(data["name"], "reddit")
        self.assertEqual(data["stored"], "name_only")
        # The stored name now shows the adapter as active, still
        # without the value appearing anywhere.
        _, _, settings_body = _request(self.port, "/api/settings")
        self.assertNotIn(SECRET, settings_body)
        by_name = {a["name"]: a
                   for a in json.loads(settings_body)["adapters"]}
        self.assertEqual(by_name["reddit"]["status"], "active")

    def test_post_key_requires_fields(self):
        status, _, _ = _request(self.port, "/api/settings/keys",
                                method="POST", payload={"name": "x"})
        self.assertEqual(status, 400)

    def test_timeline_and_alerts(self):
        _, _, timeline_body = _request(self.port, "/api/timeline")
        self.assertGreaterEqual(
            len(json.loads(timeline_body)["timeline"]), 1)
        _, _, alerts_body = _request(self.port, "/api/alerts")
        self.assertGreaterEqual(len(json.loads(alerts_body)["alerts"]), 1)

    def test_export_json_single_case(self):
        status, _, body = _request(self.port, "/api/export?fmt=json")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["case_id"], "demo-case-01")
        self.assertIn("profiles", data)
        self.assertIn("evidence", data)
        self.assertIn("audit", data)
        self.assertTrue(data["demo"])
        self.assertTrue(all("source_url" in e for e in data["evidence"]))

    def test_export_html_lists_provenance(self):
        status, ctype, body = _request(self.port, "/api/export?fmt=html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("Captured (UTC)", body)
        self.assertIn("demo_user_01", body)

    def test_export_bad_format(self):
        status, _, _ = _request(self.port, "/api/export?fmt=xml")
        self.assertEqual(status, 400)

    def test_unknown_route_404(self):
        status, _, _ = _request(self.port, "/api/nope")
        self.assertEqual(status, 404)

    def test_cost_endpoint_is_real(self):
        status, _, body = _request(self.port, "/api/cost")
        self.assertEqual(status, 200)
        rows = json.loads(body)["cost_before_run"]
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["github"]["cost_units"], 0)
        self.assertEqual(by_name["youtube"]["status"], "not_checked")

    def test_live_search_endpoint_never_echoes_keys(self):
        import os
        from unittest import mock

        secret = "sk-live-test-secret-never-echo"
        with mock.patch.dict(os.environ, {"PERSONATRACE_DEMO": "1"}, clear=False):
            status, _, body = _request(
                self.port, "/api/search", method="POST",
                payload={"seed": "demo_user_01", "keys": {"youtube_api_key": secret}})
        self.assertEqual(status, 200)
        self.assertNotIn(secret, body)
        data = json.loads(body)
        self.assertEqual(data["investigation"]["seed"], "demo_user_01")
        self.assertIn("sources", data)
        self.assertIn("cost_before_run", data)

    def test_compare_endpoint(self):
        status, _, body = _request(
            self.port, "/api/compare", method="POST",
            payload={
                "a": {"platform": "github", "username": "a_user", "bio": "A"},
                "b": {"platform": "bluesky", "username": "b_user", "bio": "B"},
            })
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["a"]["username"], "a_user")
        self.assertEqual(data["b"]["username"], "b_user")
        self.assertIn("username", data["fields"])


if __name__ == "__main__":
    unittest.main()
