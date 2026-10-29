"""Tests for personatrace.ai.layer (stdlib + unittest only, no network).

Run with pytest if available, else: python3 -m unittest discover -s tests -t .
"""

import unittest

from personatrace.ai.layer import AILayer
from demo.fixtures import demo_investigation


class TestAILocal(unittest.TestCase):
    def test_local_mode_works_with_no_key_and_labels_model(self):
        ai = AILayer(mode="local")
        inv = demo_investigation()
        out = ai.summarise(inv.profiles, inv.edges)
        self.assertEqual(out["model"], "local-template-v1")
        self.assertTrue(out["labelled"])
        self.assertIsNone(out["accepted"])
        self.assertIsNone(out["rejected"])
        self.assertIn("profile_count", out["inputs_summary"])
        self.assertIn("demo_user_01", out["text"])

    def test_local_translate_preserves_original(self):
        ai = AILayer(mode="local")
        out = ai.translate("مرحبا بالعالم", "en")
        self.assertEqual(out["original_text"], "مرحبا بالعالم")
        self.assertIsNone(out["translated_text"])
        self.assertEqual(out["model"], "local-template-v1")

    def test_local_draft_report(self):
        ai = AILayer(mode="local")
        out = ai.draft_report(demo_investigation())
        self.assertEqual(out["model"], "local-template-v1")
        self.assertIsNone(out["accepted"])
        self.assertIsNone(out["rejected"])
        self.assertEqual(out["inputs_summary"]["case_id"], "demo-case-01")


class TestAILlmNoKey(unittest.TestCase):
    def test_llm_without_key_returns_not_checked_never_fake(self):
        ai = AILayer(mode="llm", api_key=None)
        inv = demo_investigation()
        for out in (ai.summarise(inv.profiles, inv.edges),
                    ai.translate("hello", "fr"),
                    ai.draft_report(inv)):
            self.assertEqual(out["status"], "not_checked")
            self.assertIsNone(out["text"])
            self.assertIsNone(out["accepted"])
            self.assertIsNone(out["rejected"])
            self.assertIn("API Keys", out["message"])

    def test_llm_with_key_attempts_real_call_never_fabricates(self):
        ai = AILayer(mode="llm", api_key="dummy-key-for-test")
        out = ai.summarise([], [])
        self.assertIn(out["status"], ("ok", "degraded"))
        if out["status"] == "degraded":
            self.assertIsNone(out["text"])

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            AILayer(mode="mystery")


if __name__ == "__main__":
    unittest.main()
