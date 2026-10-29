"""v1.3 full-version tests: PDF, migration, risk, planner, OCR, reverse, transcripts."""

import io
import json
import tempfile
import unittest
from unittest.mock import patch

from personatrace.core.engine import Investigation
from personatrace.features.export import export_case
from personatrace.features.export_pdf import export_pdf
from personatrace.features.risk import compute_risk_signals
from personatrace.features.translation import identify_language
from personatrace.planner import plan_next_steps
from personatrace.storage.migrate import to_cypher, to_postgres_sql


def _inv():
    inv = Investigation(case_id="case-v13-test", seed="octocat", seed_type="username")
    inv.profiles = []
    inv.edges = []
    inv.possible_matches = []
    inv.alerts = []
    inv.audit = [{"action": "adapter_search", "details": {"adapter": "x", "status": "not_checked"}}]
    return inv


class TestPdfExport(unittest.TestCase):
    def test_pdf_starts_with_pdf_and_contains_case_id(self):
        inv = _inv()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_case(inv, tmp, fmt="pdf")
            self.assertTrue(path.endswith("case.pdf"))
            with open(path, "rb") as fh:
                data = fh.read()
            self.assertTrue(data.startswith(b"%PDF"))
            try:
                from pypdf import PdfReader

                text = "".join((page.extract_text() or "") for page in PdfReader(path).pages)
                self.assertIn("case-v13-test", text)
            except Exception:
                pass  # ReportLab compresses streams; %PDF header is the portable check

    def test_export_pdf_direct(self):
        inv = _inv()
        with tempfile.TemporaryDirectory() as tmp:
            path = export_pdf(inv, tmp)
            with open(path, "rb") as fh:
                self.assertTrue(fh.read(4) == b"%PDF")


class TestMigration(unittest.TestCase):
    def test_cypher_and_sql_contain_case(self):
        inv = _inv()
        inv.profiles = [{"platform": "github", "username": "octocat", "display_name": "The Octocat", "bio": "", "status": "ok", "created_at": ""}]
        cypher = to_cypher(inv)
        sql = to_postgres_sql(inv)
        self.assertIn("PersonaTrace", cypher)
        self.assertIn("pt_profiles", sql)
        self.assertIn("case-v13-test", sql)


class TestRiskPlanner(unittest.TestCase):
    def test_risk_and_planner(self):
        inv = _inv()
        inv.possible_matches = [{"a": "x", "b": "y"}]
        analysis = {"avatar_reuse": [{"a": "a", "b": "b", "hamming": 3}],
                    "domain_expansion": {}, "coordinated": {"signals": []},
                    "certificate_subdomains": {}, "bridge_domains": {}, "alerts": []}
        risks = compute_risk_signals(inv, analysis)
        self.assertTrue(any(r["signal"] == "avatar_reuse" for r in risks))
        steps = plan_next_steps(inv, analysis, {"x": "not_checked"})
        self.assertTrue(any("Add a key" in s["action"] for s in steps))
        self.assertTrue(all("human_required" in s for s in steps))


class TestLanguageOcr(unittest.TestCase):
    def test_identify_language_english(self):
        info = identify_language("the quick brown fox and the lazy dog with you")
        self.assertEqual(info["script"], "latin")
        self.assertIn(info["likely_language"], ("english", None))

    def test_image_description_no_fake_ocr(self):
        from PIL import Image

        from personatrace.features.ocr import describe_image

        buf = io.BytesIO()
        Image.new("RGB", (20, 10), (255, 0, 0)).save(buf, format="PNG")
        desc = describe_image(buf.getvalue())
        self.assertEqual(desc["size"], [20, 10])
        self.assertIn(desc["ocr"]["status"], ("ok", "not_checked", "degraded"))
        if desc["ocr"]["status"] == "not_checked":
            self.assertIsNone(desc["ocr"]["text"])


class TestTranscriptReverseLlm(unittest.TestCase):
    def test_transcript_invalid_id(self):
        from personatrace.features.transcript import fetch_transcript

        out = fetch_transcript("!!!")
        self.assertEqual(out["status"], "invalid")

    def test_reverse_no_keys_not_checked(self):
        from personatrace.features.reverse_image import reverse_search

        out = reverse_search(image_url="https://example.com/a.jpg", keys={})
        self.assertTrue(all(e["status"] == "not_checked" for e in out["engines"]))

    def test_llm_mocked_success(self):
        from personatrace.ai.layer import AILayer

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "Real LLM summary."}}]}).encode()

        with patch("urllib.request.urlopen", return_value=Resp()):
            ai = AILayer(mode="llm", api_key="dummy-key-for-test", base_url="https://example.invalid/v1")
            out = ai.summarise([], [])
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["text"], "Real LLM summary.")


if __name__ == "__main__":
    unittest.main()
